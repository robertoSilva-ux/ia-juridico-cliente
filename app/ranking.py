"""Ranking, re-ranking (MMR/RRF) e formatação de contexto.

Extraído de agent.py na refatoração (2026-09-25). Contém apenas funções puras
(sem dependência de banco/LLM global): _fuse_rrf, _to_vector, _cosine_sim,
_mmr_rerank, _mesma_norma, _limitar_por_documento, _source_label, build_context e
a constante _TIPO_LABEL.
"""
import ast
import logging
import math
from collections import Counter
from typing import Any

from config import MAX_CONTEXT_CHARS, RERANK_LAMBDA_MULT, TOP_K
from legal_parser import parse_file_name

logger = logging.getLogger(__name__)

def _fuse_rrf(rankings: list[list[dict[str, Any]]], limit: int = TOP_K, k: int = 60,
              weights: list[float] | None = None) -> list[dict[str, Any]]:
    """Reciprocal Rank Fusion — combina rankings de múltiplas buscas num só.

    Kimothi (A Simple Guide to RAG): ensemble/hybrid search funde resultados de
    múltiplas estratégias p/ evitar que uma só dite o resultado. O RRF soma
    w/(k + posição) por doc (w = peso do ranking, default 1.0); docs presentes
    em várias buscas sobem na fusão. `weights` permite dar mais importância a
    um ranking (ex.: a query original pesa mais que o HyDE p/ evitar drift).
    """
    scores: dict[Any, float] = {}
    order: dict[Any, int] = {}
    for rank_num, rank in enumerate(rankings):
        w = weights[rank_num] if weights and rank_num < len(weights) else 1.0
        for pos, doc in enumerate(rank, start=1):
            did = doc.get('id')
            if did not in scores:
                scores[did] = 0.0
                order[did] = doc
            scores[did] += w / (k + pos)

    # Ordena por score RRF decrescente; preserva o doc (mantém distance p/ exibição)
    merged = sorted(order.items(), key=lambda kv: scores[kv[0]], reverse=True)[:limit]
    return [doc for _, doc in merged]


# =========================================================
# RE-RANKING POR MMR (Maximal Marginal Relevance)
# =========================================================

def _to_vector(emb) -> list[float] | None:
    """Converte embedding (lista ou string pgvector '[0.1,0.2,...]') em lista float."""
    if emb is None:
        return None
    if isinstance(emb, str):
        emb = ast.literal_eval(emb)
    try:
        return [float(x) for x in emb]
    except (TypeError, ValueError):
        return None


def _cosine_sim(vec_a, vec_b) -> float:
    """Similaridade de cosseno entre dois vetores (1 - cosine_distance)."""
    a = _to_vector(vec_a)
    b = _to_vector(vec_b)
    if a is None or b is None or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _mmr_rerank(query_embedding: list, docs: list[dict[str, Any]], limit: int = TOP_K,
                lambda_mult: float = RERANK_LAMBDA_MULT) -> list[dict[str, Any]]:
    """Re-ranqueia docs por MMR (Maximal Marginal Relevance) usando a query embedding.

    Seleção iterativa: cada passo escolhe o doc que maximiza
        lambda * rel(query, doc) - (1 - lambda) * max(sim(doc, já_selecionados))
    reduzindo redundância entre os documentos que vão ao contexto (ex.: notas de
    rodapé da doutrina que duplicam conteúdo). Referência: Kimothi "A Simple Guide
    to RAG" e Auffarth "RAG The Seminal Papers".
    """
    if not docs or limit <= 0:
        return docs[:limit] if limit else []

    query_vec = _to_vector(query_embedding)
    if query_vec is None:
        return docs[:limit]

    # Similaridade de cada doc com a query
    selected = []
    remaining = list(docs)

    # Pré-computa sim com a query para todos
    rel = []
    for d in remaining:
        emb = d.get('embedding')
        if emb is not None:
            rel.append(_cosine_sim(query_vec, emb))
        elif d.get('distance') is not None:
            # pgvector <=> é cosine distance: similaridade = 1 - distance
            rel.append(1.0 - float(d['distance']))
        else:
            rel.append(0.0)

    while len(selected) < min(limit, len(remaining)):
        best_idx = -1
        best_score = -float('inf')
        for i, d in enumerate(remaining):
            # Relevância com a query
            score = lambda_mult * rel[i] + float(d.get('regime_score', 0.0))
            # Penalização por redundância com os já selecionados (se houver)
            if selected:
                sims = [_cosine_sim(s.get('embedding'), d.get('embedding'))
                        for s in selected
                        if s.get('embedding') is not None and d.get('embedding') is not None]
                if sims:
                    score -= (1 - lambda_mult) * max(sims)
            if score > best_score:
                best_score = score
                best_idx = i
        chosen = remaining.pop(best_idx)
        chosen['mmr_score'] = round(best_score, 4)
        selected.append(chosen)
        rel.pop(best_idx)

    logger.info(f"MMR re-ranking: {len(docs)} candidatos -> {len(selected)} selecionados (lambda={lambda_mult})")
    return selected


# =========================================================
# TETO POR DOCUMENTO (dominância de documento na recuperação)
# =========================================================

def _mesma_norma(doc: dict[str, Any], norma: tuple[str, str | None] | None) -> bool:
    """O documento é o da norma que a pergunta nomeou?

    A identidade vem do METADADO (`tipo_doc`/`numero_doc`), como no resto do
    ranking — nunca do nome do arquivo lido pelo modelo.
    """
    if not norma:
        return False
    tipo_doc, numero_doc = norma
    if numero_doc:
        return str(doc.get('numero_doc') or '') == str(numero_doc)
    return bool(tipo_doc) and doc.get('tipo_doc') == tipo_doc


def _limitar_por_documento(docs: list[dict[str, Any]], limite_por_documento: int,
                           norma: tuple[str, str | None] | None = None) -> list[dict[str, Any]]:
    """Teto de trechos de um MESMO ARQUIVO antes do MMR (P2-32).

    Motivo medido: numa base em que um documento tem 80 % dos fragmentos, é o
    tamanho relativo dele que decide quem aparece no contexto — o primeiro
    estágio semântico devolve quase só trechos desse documento, e a resposta da
    norma perguntada fica de fora. O teto espalha o contexto por arquivo.

    Três decisões que não são de gosto:

    - **não descarta nada**: quem passa do teto vai para o FIM da lista, e o
      corte de MAX_CONTEXT_CHARS é que decide se sobra espaço. Descartar
      fragmento de dispositivo já foi defeito caro neste projeto.
    - **o arquivo da norma pedida fica isento**: se a pergunta é sobre a Lei
      8.080 e a resposta está em cinco artigos dela, limitar a 4 seria trocar
      dominância por recall perdido.
    - `limite_por_documento <= 0` desliga (permite A/B medido por config).
    """
    if limite_por_documento <= 0 or not docs:
        return docs

    escolhidos: list[dict[str, Any]] = []
    adiados: list[dict[str, Any]] = []
    contagem: Counter = Counter()
    for doc in docs:
        arquivo = doc.get('file_name')
        if _mesma_norma(doc, norma) or contagem[arquivo] < limite_por_documento:
            escolhidos.append(doc)
            contagem[arquivo] += 1
        else:
            adiados.append(doc)

    if adiados:
        logger.info(f"Teto por documento: {len(adiados)} trechos rebaixados para o fim "
                    f"(limite={limite_por_documento} por arquivo)")
    return escolhidos + adiados


# =========================================================
# FORMATAÇÃO DE CONTEXTO
# =========================================================

# Rótulos legíveis por tipo de documento (usados na referência bibliográfica)
_TIPO_LABEL = {
    'decreto': 'Decreto',
    'lei': 'Lei',
    'constituicao': 'Constituição',
    'cf': 'Constituição',
    'emenda': 'Emenda Constitucional',
    'ec': 'Emenda Constitucional',
    'portaria': 'Portaria',
    'instrucao': 'Instrução Normativa',
    'in': 'Instrução Normativa',
    'medida_provisoria': 'Medida Provisória',
    'mp': 'Medida Provisória',
    'jurisprudencia': 'Tema',
    'sumula': 'Súmula',
}


def _source_label(doc: dict[str, Any]) -> str:
    """Monta a referência bibliográfica legível de um documento.

    Ex.: 'Decreto 3048, art. 54', 'Lei 8213/1991', ou cai no file_name quando
    não há metadados jurídicos estruturados.

    Quando o registro não traz `tipo_doc`/`numero_doc` (bases ingeridas antes de o
    parser entender o formato do nome), a identidade é lida do NOME DO ARQUIVO.
    Sem isso o rótulo cai no nome cru — e foi de "LEI-8080-ESQUEMATIZADA1.pdf" que
    um modelo extraiu "8080" para escrever "Lei nº 8080/2011" (docs/EVOLUCAO.md,
    bloco 5).
    """
    nome = doc.get('file_name') or 'Documento sem nome'
    tipo_doc = doc.get('tipo_doc')
    numero_doc = doc.get('numero_doc')
    ano_doc = doc.get('ano_doc')
    artigo = doc.get('artigo')
    source_title = doc.get('source_title')

    if not (tipo_doc and numero_doc):
        meta = parse_file_name(nome)
        if meta.get('tipo') and meta.get('numero'):
            tipo_doc, numero_doc = meta['tipo'], meta['numero']
            ano_doc = ano_doc or meta.get('ano')

    if tipo_doc and numero_doc:
        tipo = _TIPO_LABEL.get(tipo_doc, tipo_doc.capitalize())
        ref = f"{tipo} {numero_doc}"
        if ano_doc:
            ref = f"{ref}/{ano_doc}"
    else:
        ref = source_title or nome
    if artigo:
        ref = f"{ref}, art. {artigo}"
    return ref


def build_context(documents: list[dict[str, Any]]) -> str:
    """Formata os documentos recuperados para o contexto do modelo.

    Cada documento recebe um rótulo numerado [DOC 1], [DOC 2]... para que o
    modelo possa citá-lo de forma inequívoca no corpo da resposta e na lista
    de referências final. O índice dessa numeração é o MESMO usado em
    `get_response` para montar a lista de fontes exibida na interface,
    garantindo que "[1]" no texto corresponda ao arquivo listado.
    """
    if not documents:
        return "Nenhum documento relevante encontrado."

    formatted_docs = []
    for index, doc in enumerate(documents, start=1):
        nome = doc.get('file_name', 'Sem nome')
        ref = _source_label(doc)
        formatted_doc = (
            f"[DOC {index}] — {ref}\n"
            f"Arquivo: {nome}\n"
            f"Conteúdo: {doc.get('content')}"
        )
        formatted_docs.append(formatted_doc)

    return "\n\n".join(formatted_docs)[:MAX_CONTEXT_CHARS]

