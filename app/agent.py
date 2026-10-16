import logging
import os
import re
from typing import Any

import psycopg2
from config import (
    EMBEDDING_MODEL,
    FACT_CHECK_LLM_ENABLED,
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
from embeddings import NomicOllamaEmbeddings
from factcheck import (  # noqa: F401  (re-export da API pública)
    _BOILERPLATE_PATTERNS,
    _DISPOSITIVO_PATTERN,
    _EXTENSO_MAP,
    _EXTENSO_PATTERN,
    _FACTUAL_NUM_PATTERN,
    _canonicalizar_numeros,
    _check_semantic_grounding,
    _classificar_sentenca,
    _classify_sentence_grounded,
    _extract_citations,
    _fact_check_answer,
    _factual_claim_grounded,
    _has_factual_claim,
    _is_boilerplate,
    _load_dispositivos_base,
    _normalize_dispositivo,
    _parece_recusa,
    _split_sentences,
    _unidades_ausentes,
    _unidades_factuais,
    _veredito_da_resposta,
    invalidate_dispositivos_cache,
)
from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama import ChatOllama
from psycopg2.extras import RealDictCursor
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

from database import get_db_connection

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
                embedding <=> %s::vector AS distance,
                'semantico' AS origem,{emb_col}
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
                embedding <=> %s::vector AS distance,
                'semantico' AS origem,{emb_col}
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

# ---------------------------------------------------------
# PORTÃO DE SUFICIÊNCIA E RECUSA CANÔNICA
# ---------------------------------------------------------
# O limiar de distância NÃO decide se a base responde. Medido com o
# `nomic-embed-text` (13 perguntas, corpus de dev): perguntas COM resposta na base
# têm top-1 entre 0,15 e 0,27 e perguntas FORA da base entre 0,20 e 0,35 — as
# faixas se sobrepõem, e o `SIMILARITY_THRESHOLD` (0,80) deixa tudo passar.
# Quem decide é perguntar ao modelo se o contexto contém o que a pergunta exige:
# medido no `phi4-mini:3.8b`, 7/7 das perguntas legítimas → SIM, 4/6 fora da base
# → NAO, a 0,5–2,0 s por chamada (docs/PLANO_REFINAMENTO_RAG.md, R-8).
_PROMPT_SUFICIENCIA = (
    "Você é um verificador de suficiência de contexto. Responda em UMA linha, "
    "começando por SIM ou NAO, e nada mais.\n\n"
    "Pergunta do advogado: {query}\n\n"
    "Contexto recuperado da base:\n{context}\n\n"
    "O contexto acima contém, de forma explícita e literal, o dispositivo ou o dado "
    "necessário para responder à pergunta? Responda SIM apenas se o dispositivo/dado "
    "estiver no texto acima (não basta o texto ser do mesmo assunto). Responda NAO se "
    "for preciso conhecimento externo, dedução, ou se o dado não aparecer no texto.\n"
    "Resposta:"
)
_SUFICIENCIA_VEREDITO = re.compile(r"[*#\s]*(SIM|N[ÃA]O)", re.IGNORECASE)


def _contexto_suficiente(query: str, context: str, llm: Any = None) -> bool | None:
    """A base responde a esta pergunta? True/False — ou None se não der para avaliar.

    None (verificação desligada, LLM fora, resposta ambígua) significa **segue o
    fluxo normal**: ausência de veredito não pode virar recusa, senão uma falha de
    infraestrutura passaria a derrubar perguntas legítimas.
    """
    if not FACT_CHECK_LLM_ENABLED:
        return None
    if llm is None:
        llm = LLM
    if llm is None:
        return None
    try:
        resposta = llm.invoke(_PROMPT_SUFICIENCIA.format(query=query, context=context))
    except Exception as e:
        logger.warning(f"Suficiência: falha ao consultar o modelo, seguindo sem o portão: {e}")
        return None
    texto = (resposta.content if hasattr(resposta, "content") else str(resposta)) or ""
    achado = _SUFICIENCIA_VEREDITO.match(texto.strip())
    if not achado:
        logger.warning(f"Suficiência: resposta inesperada {texto[:40]!r} — seguindo sem o portão")
        return None
    return not achado.group(1).upper().startswith("N")


#: Por que a resposta não foi entregue — texto completo, porque ele vai para a
#: interface (o advogado precisa saber o que faltou) e para o log.
_MOTIVO_TEXTO = {
    'sem_recuperacao': "a busca não recuperou nenhum trecho no escopo deste usuário",
    'contexto_insuficiente': ("os trechos recuperados tratam do mesmo tema, mas nenhum "
                              "contém o dispositivo ou o dado que a pergunta exige"),
    'modelo_recusou': ("o modelo declarou que o material recuperado não contém a resposta "
                       "(ele é instruído a não responder fora da base)"),
    'norma_sem_lastro': "a resposta cita número de norma que não existe em nenhum trecho recuperado",
    'ano_incompativel': "a resposta cita uma norma com ano diferente do que o material registra",
    'autor_sem_lastro': "a resposta cita autor/obra que não aparece em nenhum trecho recuperado",
    'dispositivo_sem_lastro': ("a resposta cita dispositivo (artigo/parágrafo/inciso) que não "
                               "existe no material indexado"),
    'citacao_inexistente': "a resposta cita um trecho [n] que não foi recuperado",
    'sem_fonte': "a resposta não cita nenhum trecho, dispositivo, norma ou número verificável",
    'resposta_vazia': "o modelo não devolveu conteúdo",
}

#: Instrução de reescrita (uma única chance). Vai no bloco da PERGUNTA, junto com
#: o contexto — o system prompt continua sendo só diretriz de papel.
_FEEDBACK_REESCRITA = (
    "\n\n[CORREÇÃO OBRIGATÓRIA — a resposta anterior foi descartada pelo verificador]\n"
    "Motivo: {motivo}.\n"
    "Reescreva a resposta obedecendo a estas três regras:\n"
    "1) toda frase que afirme número, prazo, valor, percentual ou dispositivo termina citando "
    "o trecho que a sustenta, no formato [DOC n];\n"
    "2) use apenas o que aparece literalmente nos trechos recuperados — não complete com "
    "conhecimento próprio;\n"
    "3) se os trechos não contiverem o necessário, diga que a base não contém a resposta e pare."
)

#: Segunda chance quando o modelo RECUSA. A redação evita AFIRMAR que o material
#: contém o dado (só o portão de suficiência sabe disso, e ele pode estar desligado):
#: pede para procurar termo por termo e só repetir a recusa se realmente não estiver.
#: Medido com o phi4-mini nas duas perguntas que ele recusa tendo o dado no contexto
#: recuperado: esta redação devolveu a resposta correta em uma delas (a outra exige
#: uma inferência que o modelo de 4B não faz — ver a limitação registrada no plano).
_FEEDBACK_RECUSA = (
    "\n\n[CORREÇÃO OBRIGATÓRIA — sua resposta anterior foi recusada]\n"
    "Procure outra vez, termo por termo, o dispositivo/dado que a pergunta exige dentro dos "
    "trechos acima: ele pode estar em um trecho que trata do tema com outras palavras.\n"
    "1) se encontrar, responda citando [DOC n] e reproduza o dado como ele está escrito no trecho;\n"
    "2) só repita a recusa se, depois de procurar, o dispositivo não estiver em nenhum dos trechos."
)


def _texto_recusa(motivo: str, n_trechos: int) -> str:
    """Mensagem de recusa do SISTEMA — nunca do modelo.

    Formato fixo, para o advogado reconhecer o estado do produto e saber o que
    fazer: quantos trechos foram examinados, por que nenhum serve e como obter a
    resposta (indexar a norma oficial / reformular com o artigo).
    """
    causa = _MOTIVO_TEXTO.get(motivo, "a resposta gerada não pôde ser verificada contra o material recuperado")
    return (
        "**Não encontrei a resposta na base de documentos.**\n\n"
        f"{n_trechos} trecho(s) recuperado(s). Motivo: {causa}.\n\n"
        "Para obter a resposta, indexe o texto oficial da norma que trata do tema "
        "(de preferência a íntegra, do Planalto) ou reformule a pergunta citando o artigo "
        "específico.\n\n"
        "_Nenhuma afirmativa foi produzida fora do material indexado._"
    )


def _montar_sources(retrieved_docs: list[dict[str, Any]], citadas=()) -> list[dict[str, Any]]:
    """Fontes para a interface: similaridade REAL (ou `None`) e origem da busca.

    `distance` só existe quando houve busca vetorial. Na busca por metadados/
    dispositivo não há similaridade nenhuma, e a interface antiga calculava
    `1 - 0.0` e exibia "100,00%" para um resultado que nunca foi comparado.
    """
    citadas = set(citadas or ())
    fontes = []
    for index, doc in enumerate(retrieved_docs or [], start=1):
        distancia = doc.get("distance")
        fontes.append({
            "ref": index,
            "source_label": _source_label(doc),
            "file_name": doc.get("file_name"),
            "artigo": doc.get("artigo"),
            "distance": float(distancia) if distancia is not None else None,
            "origem": doc.get("origem") or "semantico",
            "citada": index in citadas,
        })
    return fontes


def _auditar(user_id, user_email, query: str, resumo: str, retrieved_docs) -> None:
    """Registra a pergunta no `audit_log` sem derrubar o chat se o log falhar."""
    try:
        from audit import log_question
        arquivos = list({doc.get("file_name") for doc in (retrieved_docs or []) if doc.get("file_name")})
        log_question(user_id=user_id, user_email=user_email, question=query,
                     response_summary=resumo, sources=arquivos)
    except Exception as audit_err:
        logger.warning(f"Falha ao registrar auditoria: {audit_err}")


def _gerar(query: str, context: str, chat_history: list[Any], feedback_motivo: str | None = None) -> str:
    """Gera a resposta; com `feedback_motivo`, pede a reescrita citando o defeito."""
    entrada = query
    if feedback_motivo == 'modelo_recusou':
        entrada = query + _FEEDBACK_RECUSA
    elif feedback_motivo:
        entrada = query + _FEEDBACK_REESCRITA.format(
            motivo=_MOTIVO_TEXTO.get(feedback_motivo, feedback_motivo)
        )
    response = CHAIN.invoke({"input": entrada, "context": context, "chat_history": chat_history})
    return response.content


def _recusar(query: str, retrieved_docs, motivo: str, user_id, user_email,
             descartada: str | None = None, suficiente: bool | None = None) -> dict[str, Any]:
    """Recusa canônica — o caminho honesto quando a base não responde.

    As fontes vão junto (com a similaridade real): é com elas que o advogado
    decide se o que falta é o material indexado. O texto descartado nunca vai para
    a tela, mas fica no retorno e no log de auditoria.
    """
    texto = _texto_recusa(motivo, len(retrieved_docs or []))
    logger.info(f"Recusa honesta ({motivo}); trechos={len(retrieved_docs or [])} suficiência={suficiente}")
    resumo = f"[RECUSA: {motivo}] " + (descartada or "")
    _auditar(user_id, user_email, query, resumo, retrieved_docs)
    return {
        "answer": texto,
        "sources": _montar_sources(retrieved_docs),
        "fact_check": {},
        "status": "recusada",
        "motivo": motivo,
        "suficiente": suficiente,
        "descartada": descartada,
    }


def get_response(query: str, chat_history: list[Any] | None = None, user_id: int | None = None, user_email: str | None = None) -> dict[str, Any]:
    """Responde à pergunta do advogado — ou diz honestamente que não encontrou.

    Fluxo (Fase 1 de docs/PLANO_REFINAMENTO_RAG.md):

    1. Recupera os trechos no escopo do usuário. Sem trecho nenhum, a resposta é a
       recusa canônica: não existe caminho em que o modelo receba contexto vazio
       (ou a frase "Nenhum documento relevante encontrado") e improvise.
    2. Pergunta ao modelo se o contexto contém o que a pergunta exige. "NAO" ⇒
       recusa canônica, sem gerar resposta.
    3. Gera a resposta e mede o lastro. Veredito `sem_lastro` (norma/dispositivo
       inexistente, citação fabricada, ou resposta sem nenhuma unidade
       verificável) ⇒ UMA regeneração com o motivo apontado; persistindo, a
       resposta **não é exibida** e vira recusa — o texto descartado fica em
       `descartada` e no log de auditoria.
    4. `fundamentada`/`parcial` ⇒ exibe, com o veredito e as fontes citadas.

    Retorno: `answer` (o que a interface exibe), `sources`, `fact_check`,
    `status` ('ok' | 'parcial' | 'recusada' | 'erro'), `motivo`, `descartada`.
    """
    if chat_history is None:
        chat_history = []

    if not ensure_llm():
        return {"answer": "Nenhum modelo LLM configurado. Selecione um modelo nas configurações.",
                "sources": [], "fact_check": {}, "status": "erro", "motivo": "sem_modelo",
                "descartada": None}

    try:
        retrieved_docs = retrieve_context(query, user_id=user_id)

        if not retrieved_docs:
            return _recusar(query, retrieved_docs, 'sem_recuperacao', user_id, user_email)

        context = build_context(retrieved_docs)

        # Suficiência = o material responde? False recusa; True libera (e depois
        # serve de argumento na segunda chance do modelo); None = não foi possível
        # avaliar, segue o fluxo normal.
        suficiente = _contexto_suficiente(query, context)
        if suficiente is False:
            return _recusar(query, retrieved_docs, 'contexto_insuficiente', user_id, user_email,
                            suficiente=False)

        # Contexto e pergunta vão na mensagem human (USER_PROMPT), não no system.
        resposta = _gerar(query, context, chat_history)
        fact_check = _fact_check_answer(resposta, retrieved_docs, user_id=user_id)
        descartada = None

        if fact_check['veredito'] in ('sem_lastro', 'recusou'):
            # UMA chance de segunda leitura, com o motivo do defeito — e só uma:
            # `sem_lastro` pede reescrita ancorada; `recusou` pede para procurar de
            # novo no material (recusar o que a base responde é tão grave quanto
            # inventar). Persistindo o defeito, a resposta não é exibida.
            descartada = resposta
            motivo_retry = fact_check['motivo'] if fact_check['veredito'] == 'sem_lastro' else 'modelo_recusou'
            logger.info(f"Veredito {fact_check['veredito']} ({motivo_retry}): uma segunda leitura")
            resposta = _gerar(query, context, chat_history, feedback_motivo=motivo_retry)
            fact_check = _fact_check_answer(resposta, retrieved_docs, user_id=user_id)
            if fact_check['veredito'] in ('sem_lastro', 'recusou'):
                return _recusar(query, retrieved_docs,
                                fact_check['motivo'] or 'modelo_recusou',
                                user_id, user_email, descartada=descartada,
                                suficiente=suficiente)

        if fact_check['enabled'] and not fact_check['all_grounded']:
            logger.info(
                f"Fact-check: {fact_check['no_support']} sentenças sem suporte, "
                f"{fact_check['partial']} parciais (de {fact_check['total_sentences']})"
            )

        _auditar(user_id, user_email, query, resposta, retrieved_docs)

        return {
            "answer": resposta,
            "sources": _montar_sources(retrieved_docs, fact_check.get('citadas')),
            "fact_check": fact_check,
            "status": 'parcial' if fact_check['veredito'] == 'parcial' else 'ok',
            "motivo": fact_check['motivo'],
            "suficiente": suficiente,
            "descartada": descartada,
        }

    except (psycopg2.Error, ConnectionError):
        logger.exception("Erro de infraestrutura na geração da resposta")
        return {
            "answer": "Erro de conexão ao processar a consulta. Tente novamente.",
            "sources": [], "fact_check": {}, "status": "erro", "motivo": "conexao",
            "suficiente": None, "descartada": None,
        }
    except Exception:
        logger.exception("Erro inesperado na geração da resposta")
        return {
            "answer": "Erro interno ao processar a consulta.",
            "sources": [], "fact_check": {}, "status": "erro", "motivo": "interno",
            "suficiente": None, "descartada": None,
        }
