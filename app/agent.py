import logging
import os
from typing import Any

import psycopg2
from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama import ChatOllama
from psycopg2.extras import RealDictCursor

from config import (
    EMBEDDING_MODEL,
    HYDE_ENABLED,
    HYDE_QUERY_WEIGHT,
    LLM_MODEL,
    LLM_NUM_CTX,
    OLLAMA_BASE_URL,
    RERANK_ENABLED,
    RERANK_TOP_K_MULTIPLIER,
    SIMILARITY_THRESHOLD,
    TEMPERATURE,
    TOP_K,
)
from database import get_db_connection
from embeddings import NomicOllamaEmbeddings
from factcheck import (  # noqa: F401  (re-export da API pública)
    _BOILERPLATE_PATTERNS,
    _DISPOSITIVO_PATTERN,
    _EXTENSO_MAP,
    _EXTENSO_PATTERN,
    _FACTUAL_NUM_PATTERN,
    _canonicalizar_numeros,
    _check_semantic_grounding,
    _classify_sentence_grounded,
    _extract_citations,
    _fact_check_answer,
    _factual_claim_grounded,
    _has_factual_claim,
    _is_boilerplate,
    _load_dispositivos_base,
    _normalize_dispositivo,
    _split_sentences,
    invalidate_dispositivos_cache,
)
from ranking import (  # noqa: F401  (re-export da API pública)
    _TIPO_LABEL,
    _cosine_sim,
    _fuse_rrf,
    _mmr_rerank,
    _source_label,
    _to_vector,
    build_context,
)

# Re-export de módulos extraídos na refatoração (2026-09-25).
# As funções continuam importáveis de `agent` para não quebrar a API pública.
from regime import (  # noqa: F401  (re-export da API pública)
    _apply_regime_boost,
    _infer_regime_profile,
    _keyword_search,
    _merge_unique_docs,
    _metadata_search,
    _parse_article_reference,
)

# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


# =========================================================
# SINGLETONS
# =========================================================

logger.info("Inicializando embeddings...")
EMBEDDINGS = NomicOllamaEmbeddings(model=EMBEDDING_MODEL, base_url=OLLAMA_BASE_URL)
LLM = None
CHAIN = None

def _ollama_kwargs() -> dict:
    """Kwargs comuns ao ChatOllama; num_ctx só vai quando configurado (>0),
    para não sobrescrever o default do Modelfile nos testes A/B."""
    kwargs = {"model": LLM_MODEL, "base_url": OLLAMA_BASE_URL, "temperature": TEMPERATURE}
    if LLM_NUM_CTX > 0:
        kwargs["num_ctx"] = LLM_NUM_CTX
    return kwargs


def ensure_llm():
    global LLM, CHAIN, LLM_MODEL
    if LLM is not None:
        return True
    model = LLM_MODEL or os.getenv("LLM_MODEL")
    if not model:
        return False
    LLM = ChatOllama(**_ollama_kwargs())
    CHAIN = PROMPT | LLM
    logger.info(f"Modelo LLM inicializado: {model} (num_ctx={LLM_NUM_CTX or 'default'})")
    return True

def set_llm_model(model_name: str, provider: str = "Ollama", api_key: str = None, base_url: str = None):
    global LLM, CHAIN, LLM_MODEL
    # Apenas modelos locais (Ollama) são suportados.
    LLM_MODEL = model_name
    LLM = ChatOllama(**_ollama_kwargs())
    CHAIN = PROMPT | LLM
    logger.info(f"Modelo LLM atualizado para: [{provider}] {model_name}")


# =========================================================
# PROMPTS
# =========================================================

def _load_md_dir(dirname: str) -> str:
    """Concatena, em ordem alfabética, todos os .md de uma pasta (ou "")."""
    folder = os.path.join(os.path.dirname(__file__), dirname)
    parts = []
    if os.path.isdir(folder):
        for filename in sorted(os.listdir(folder)):
            if filename.endswith(".md"):
                with open(os.path.join(folder, filename), encoding="utf-8") as f:
                    content = f.read().strip()
                    if content:
                        parts.append(content)
    return "\n\n".join(parts)


def load_prompts() -> str:
    """Monta o SYSTEM prompt (persona + regras de conduta).

    Só a pasta `prompts/` entra aqui: são instruções de papel, nunca o
    contexto recuperado. O contexto e a pergunta do advogado vão na mensagem
    human (ver USER_PROMPT), para o modelo não confundir as DIRETRIZES do
    system com conteúdo a responder (eco/instruction leakage).
    """
    return _load_md_dir("prompts")


SYSTEM_PROMPT = load_prompts()

# Bloco da mensagem human: contexto recuperado + pergunta. Mantido em
# `prompts_user/` para separar claramente o que é instrução (system) do que é
# conteúdo do usuário (human). Se o arquivo sumir, cai no padrão inline.
USER_PROMPT = _load_md_dir("prompts_user") or (
    "## CONTEXTO RECUPERADO DA BASE JURÍDICA\n\n{context}\n\n---\n\n"
    "**PERGUNTA DO ADVOGADO:**\n\n{input}"
)

PROMPT = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    ("placeholder", "{chat_history}"),
    ("human", USER_PROMPT)
])

# CHAIN is initialized lazily via ensure_llm() or set_llm_model()


# =========================================================
# BOOST DE REGIME JURÍDICO
# =========================================================


def retrieve_context(query: str, user_id: int | None = None, limit: int = TOP_K,
                     embeddings=EMBEDDINGS, conn_factory=get_db_connection) -> list[dict[str, Any]]:
    """
    Recupera contexto usando fluxo determinístico + híbrido:

    1. Se a pergunta menciona artigo específico:
       a. Tenta busca por metadados estruturados (artigo, tipo_doc, numero_doc)
       b. Se não achou, tenta busca por palavra-chave (regex no conteúdo)
       c. Junta com resultados semânticos
    2. Se não menciona, faz só busca semântica pura
    """

    parsed = _parse_article_reference(query)

    if parsed:
        article_num, tipo_doc, numero_doc, paragraph = parsed
        logger.info(f"Query jurídica detectada: artigo={article_num}, tipo={tipo_doc}, num={numero_doc}, para={paragraph}")

        # 1a. Busca determinística por metadados
        metadata_rows = _metadata_search(query, user_id=user_id)

        if metadata_rows:
            logger.info(f"✅ Busca por metadados encontrou {len(metadata_rows)} resultados!")
            # Retorna direto — não precisa de embedding
            return metadata_rows[:limit]

        # 1b. Fallback para busca por palavra-chave
        keyword_rows = _keyword_search(query, user_id=user_id)

        if keyword_rows:
            logger.info(f"✅ Busca por palavra-chave encontrou {len(keyword_rows)} resultados!")
            # Se achou keyword, faz merge com semântico
            query_embedding = embeddings.embed_query(query)
            semantic_rows = _semantic_search(query_embedding, user_id, limit)

            seen_ids = set()
            merged = []
            for doc in keyword_rows:
                seen_ids.add(doc["id"])
                merged.append(doc)
            for doc in semantic_rows:
                if doc["id"] not in seen_ids:
                    merged.append(doc)

            logger.info(f"Total após merge híbrido: {len(merged)} (keyword={len(keyword_rows)}, semântico={len(semantic_rows)})")
            return merged[:limit]

        # 1c. Não achou por estrutura nem keyword, cai no semântico
        logger.info("Nenhum resultado por metadados ou keyword, caindo no semântico...")

        # 2. Busca semântica pura
    query_embedding = embeddings.embed_query(query)
    if HYDE_ENABLED:
        hyde_rows = _semantic_hyde(query, query_embedding, user_id, limit)
        if hyde_rows is not None:
            return hyde_rows
    # Falls through: HyDE desativado ou sem LLM -> busca semântica comum (+ MMR)
    return _semantic_with_rerank(query_embedding, user_id, limit, query=query)


def _semantic_hyde(query: str, query_embedding: list, user_id: int | None = None,
                   limit: int = TOP_K, embeddings=EMBEDDINGS, llm=LLM,
                   conn_factory=get_db_connection) -> list[dict[str, Any]] | None:
    """Busca semântica com fusão HyDE + query original (RRF) e re-ranking MMR.

    Pipeline (Kimothi, HyDE + ensemble):
      1. Gera documento hipotético (âncora jurídica) via LLM.
      2. Recupera candidatos usando o embedding da query E o do doc hipotético.
      3. Funde os dois rankings por Reciprocal Rank Fusion (evita overexpansion).
      4. Re-ranqueia com MMR (reduz redundância).

    Retorna None quando HyDE não aplicar (LLM indisponível/falhou), sinalizando
    ao chamador que deve cair na busca semântica comum.
    """
    hypo = _generate_hypothetical_doc(query, llm=llm)
    if hypo is None:
        return None

    # Etapa larga p/ cada ranking, para o re-ranking ter candidatos
    search_limit = max(limit, limit * RERANK_TOP_K_MULTIPLIER) if RERANK_ENABLED else limit
    include_emb = RERANK_ENABLED

    try:
        hypo_embedding = embeddings.embed_document(hypo)
    except Exception as e:
        logger.warning(f"HyDE: falha ao embedar doc hipotético, caindo para busca comum: {e}")
        return None

    rows_query = _semantic_search(query_embedding, user_id, search_limit, include_embedding=include_emb, conn_factory=conn_factory)
    rows_hyde = _semantic_search(hypo_embedding, user_id, search_limit, include_embedding=include_emb, conn_factory=conn_factory)
    logger.info(f"HyDE: query={len(rows_query)} docs, hyde={len(rows_hyde)} docs -> fusão RRF (peso query={HYDE_QUERY_WEIGHT})")

    fused = _fuse_rrf([rows_query, rows_hyde], limit=limit if not RERANK_ENABLED else search_limit,
                      weights=[HYDE_QUERY_WEIGHT, 1.0])
    # _regime_search desativado (2026-09-21): promovia chunks por `id ASC` e
    # deslocava o resultado semântico correto para fora do TOP_K. Ver bloco de
    # comentário na definição da função.
    # regime_rows = _regime_search(query, user_id, limit=limit, include_embedding=include_emb)
    # fused = _merge_unique_docs(fused, regime_rows)

    # Re-ranking MMR no conjunto fundido (usa o embedding da query como referência)
    fused = _apply_regime_boost(query, fused)
    if RERANK_ENABLED and fused:
        fused = _mmr_rerank(query_embedding, fused, limit=limit)
        for doc in fused:
            doc.pop('embedding', None)
    return fused


def _semantic_with_rerank(query_embedding: list, user_id: int | None = None, limit: int = TOP_K,
                          query: str = "", conn_factory=get_db_connection) -> list[dict[str, Any]]:
    """Busca semântica + re-ranking por MMR (2 estágios).

    Quando RERANK_ENABLED, recupera um top-k mais largo na 1ª etapa e
    re-ranqueia por MMR para reduzir redundância. Desativável via config.
    """
    semantic_limit = limit
    if RERANK_ENABLED:
        semantic_limit = max(limit, limit * RERANK_TOP_K_MULTIPLIER)
        logger.info(f"Re-ranking MMR ativo: buscando {semantic_limit} candidatos (mult={RERANK_TOP_K_MULTIPLIER})")

    rows = _semantic_search(query_embedding, user_id, semantic_limit, include_embedding=RERANK_ENABLED, conn_factory=conn_factory)
    # _regime_search desativado (2026-09-21) — ver bloco na definição da função.
    # regime_rows = _regime_search(query, user_id, limit=limit, include_embedding=RERANK_ENABLED)
    # rows = _merge_unique_docs(rows, regime_rows)
    rows = _apply_regime_boost(query, rows)

    if RERANK_ENABLED and rows:
        rows = _mmr_rerank(query_embedding, rows, limit=limit)
        # Remove a chave 'embedding' (pesada) do que vai ao prompt/contexto
        for doc in rows:
            doc.pop('embedding', None)
    return rows


def _semantic_search(query_embedding: list, user_id: int | None = None, limit: int = TOP_K,
                     include_embedding: bool = False, conn_factory=get_db_connection) -> list[dict[str, Any]]:
    """Busca semântica pura por similaridade de vetores.

    include_embedding: se True, inclui o vetor 'embedding' em cada doc
    (necessário para re-ranking MMR; mantido off por padrão para não
    sobrecarregar o contexto desnecessariamente).
    """
    emb_col = "\n                embedding," if include_embedding else ""
    if user_id is not None:
        sql = f"""
            SELECT
                id,
                file_name,
                content,
                scope,
                embedding <=> %s::vector AS distance,{emb_col}
                artigo,
                tipo_doc,
                numero_doc,
                source_id
            FROM documents
            WHERE embedding <=> %s::vector < %s
              AND (scope = 'global' OR owner_id = %s)
            ORDER BY distance ASC
            LIMIT %s
        """
        params = (query_embedding, query_embedding, SIMILARITY_THRESHOLD, user_id, limit)
    else:
        sql = f"""
            SELECT
                id,
                file_name,
                content,
                scope,
                embedding <=> %s::vector AS distance,{emb_col}
                artigo,
                tipo_doc,
                numero_doc,
                source_id
            FROM documents
            WHERE embedding <=> %s::vector < %s
            ORDER BY distance ASC
            LIMIT %s
        """
        params = (query_embedding, query_embedding, SIMILARITY_THRESHOLD, limit)

    try:
        with conn_factory() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
                logger.info(f"Documentos recuperados (semântico): {len(rows)}")
                return rows
    except psycopg2.Error:
        logger.exception("Erro de banco de dados na busca semântica")
        return []
    except Exception:
        logger.exception("Erro inesperado na busca semântica")
        return []


# =========================================================
# HYDE (Hypothetical Document Embeddings) — query transformation
# =========================================================

# Prompt dedicado ao HyDE: gera uma resposta plausível à pergunta SEM acessar a base,
# em linguagem jurídica, sem inventar artigos/refs. Serve apenas como âncora semântica
# (o embedding dela recupera chunks com vocabulário do domínio), e NUNCA é mostrada
# ao usuário nem usada como fonte.
HYDE_PROMPT = (
    "Você é um advogado especializado em Direito Previdenciário e Direito do Trabalho "
    "brasileiro. Redija um parágrafo técnico (2-4 frases) em linguagem jurídica que "
    "responda à pergunta abaixo, usando os institutos próprios desses ramos: benefícios "
    "do INSS (aposentadoria por tempo de contribuição, aposentadoria especial, por "
    "invalidez), carência, período de contribuição, salário-de-contribuição, segurado, "
    "dependência econômica, acidente de trabalho, obrigações do empregador e da "
    "previdência social. "
    "NÃO saia desses ramos (não use direito contratual civil, CDC, Código Civil). "
    "NÃO cite números de artigo nem leis específicas (você não tem acesso à base). "
    "NÃO invente fatos; apenas descreva, em linguagem jurídica natural, o tópico da "
    "resposta."
    "\n\nPergunta: {query}"
    "\n\nResposta hipotética:"
)


def _generate_hypothetical_doc(query: str, llm=None) -> str | None:
    """Gera um documento hipotético (resposta plausível) à query via LLM (HyDE).

    Usa o LLM para produzir um parágrafo em linguagem jurídica que
    sirva de âncora semântica para a busca. Retorna None se o LLM não estiver
    disponível ou falhar (fallback gracioso para busca comum). O documento é
    usado apenas para embedding — nunca entra no contexto/prompt final.
    """
    if llm is None:
        llm = LLM
    if HYDE_ENABLED is False or llm is None:
        return None
    try:
        prompt = HYDE_PROMPT.format(query=query)
        resp = llm.invoke(prompt)
        text = (resp.content if hasattr(resp, 'content') else str(resp)).strip()
        # Garantia mínima: precisa ter algum conteúdo para servir de âncora
        if not text or len(text) < 20:
            return None
        logger.info(f"HyDE: documento hipotético gerado ({len(text)} chars)")
        return text
    except Exception as e:
        logger.warning(f"HyDE: falha ao gerar documento hipotético, usando query pura: {e}")
        return None


# RESPOSTA PRINCIPAL
# =========================================================

def get_response(query: str, chat_history: list[Any] | None = None, user_id: int | None = None, user_email: str | None = None) -> dict[str, Any]:
    if chat_history is None:
        chat_history = []

    if not ensure_llm():
        return {"answer": "Nenhum modelo LLM configurado. Selecione um modelo nas configurações.", "sources": []}

    try:
        retrieved_docs = retrieve_context(query, user_id=user_id)
        context = build_context(retrieved_docs)

        # Contexto e pergunta vão na mensagem human (USER_PROMPT), não no system.
        response = CHAIN.invoke({
            "input": query,
            "context": context,
            "chat_history": chat_history
        })

        # Fact-check pós-geração: verifica se a resposta está grounded nos docs
        fact_check = _fact_check_answer(response.content, retrieved_docs)
        if fact_check['enabled'] and not fact_check['all_grounded']:
            logger.info(
                f"Fact-check: {fact_check['no_support']} sentenças sem suporte, "
                f"{fact_check['partial']} parciais (de {fact_check['total_sentences']})"
            )

        sources = []
        for index, doc in enumerate(retrieved_docs, start=1):
            # `ref` é o rótulo [n] usado pelo modelo na resposta (via build_context),
            # permitindo à UI mostrar "[1] Arquivo X" casado com a citação inline.
            # `artigo` é exposto para o avaliador medir hit por ARTIGO, não só por
            # arquivo: um decreto com centenas de chunks dá source_hit=1/1 mesmo
            # quando o artigo perguntado não veio (ver run_eval.py).
            sources.append({
                "ref": index,
                "source_label": _source_label(doc),
                "file_name": doc.get("file_name"),
                "artigo": doc.get("artigo"),
                "distance": float(doc.get("distance"))
            })

        # Registrar auditoria
        try:
            from audit import log_question
            source_files = list({doc.get("file_name") for doc in retrieved_docs if doc.get("file_name")})
            log_question(
                user_id=user_id,
                user_email=user_email,
                question=query,
                response_summary=response.content,
                sources=source_files
            )
        except Exception as audit_err:
            logger.warning(f"Falha ao registrar auditoria: {audit_err}")

        return {
            "answer": response.content,
            "sources": sources,
            "fact_check": fact_check
        }

    except (psycopg2.Error, ConnectionError):
        logger.exception("Erro de infraestrutura na geração da resposta")
        return {
            "answer": "Erro de conexão ao processar a consulta. Tente novamente.",
            "sources": []
        }
    except Exception:
        logger.exception("Erro inesperado na geração da resposta")
        return {
            "answer": "Erro interno ao processar a consulta.",
            "sources": []
        }
