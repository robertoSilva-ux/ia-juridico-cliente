"""Busca e boost por regime jurídico + referência de artigo.

Extraído de agent.py na refatoração (2026-09-25). Mantém a API pública original.
Funções: _infer_regime_profile, _apply_regime_boost, _merge_unique_docs,
_parse_article_reference, _metadata_search, _keyword_search.
"""
import logging
import re
from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor

from database import get_db_connection

logger = logging.getLogger(__name__)


def _infer_regime_profile(query: str) -> dict[str, Any]:
    """Infere sinais conservadores de regime para desempatar a busca semântica.

    O boost só atua quando a pergunta contém um marcador claro. Sem marcador,
    a busca permanece puramente semântica para não impor um regime arbitrário.
    """
    normalized = re.sub(r"[^a-z0-9à-ÿ]+", " ", (query or "").lower())
    preferred = []
    excluded = []

    if re.search(r"\b(lc|lcp|lei complementar)\s*142\b", normalized):
        preferred.append(("lei_complementar", "142"))
    rgps_markers = (
        r"\brgps\b|regime geral|inss|sal[aá]rio fam[ií]lia|dependente|"
        r"segurado|pensão por morte|aposentadoria por tempo de contribui"
    )
    if re.search(rgps_markers, normalized, re.IGNORECASE):
        preferred.extend([("decreto", "3048"), ("lei", "8213")])
        excluded.extend([("emenda", ""), ("constituicao", "")])

    return {"preferred": preferred, "excluded": excluded}


def _apply_regime_boost(query: str, docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Anota e ordena candidatos por compatibilidade de regime.

    A ordenação é estável e nunca descarta documentos: o contexto continua
    podendo trazer fontes secundárias, apenas depois das fontes do regime alvo.
    """
    profile = _infer_regime_profile(query)
    normalized = (query or "").lower()
    preferred = set(profile["preferred"])
    excluded = set(profile["excluded"])
    if not preferred and not excluded:
        return docs

    boosted = []
    for doc in docs:
        key = (doc.get("tipo_doc"), str(doc.get("numero_doc") or ""))
        file_name = (doc.get("file_name") or "").lower()
        score = 0.0
        if key in preferred:
            # Para salário-família, o decreto regulamentador traz o limite
            # operacional (art. 83); a lei permanece como fonte secundária.
            if key == ("decreto", "3048") and "sal" in normalized:
                score += 0.40
            else:
                score += 0.25
        if ("lei_complementar", "142") in preferred and re.search(r"\blcp?\s*142\b", file_name):
            score += 0.25
        if ("decreto", "3048") in preferred and re.search(r"decreto[^0-9]*3?\.?048", file_name):
            score += 0.25
        if ("lei", "8213") in preferred and re.search(r"(?:lei[^0-9]*8?\.?213|l8213)", file_name):
            score += 0.25
        if key in excluded or (not doc.get("tipo_doc") and "vade_mecum" in file_name):
            score -= 0.10
        copy_doc = dict(doc)
        copy_doc["regime_score"] = score
        boosted.append(copy_doc)

    boosted.sort(key=lambda doc: (
        -float(doc.get("regime_score", 0.0)),
        float(doc.get("distance") or 0.0),
    ))
    return boosted


def _merge_unique_docs(primary: list[dict[str, Any]], extra: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mescla listas preservando a ordem e removendo documentos repetidos."""
    merged = []
    seen = set()
    for doc in list(primary or []) + list(extra or []):
        doc_id = doc.get("id")
        if doc_id in seen:
            continue
        seen.add(doc_id)
        merged.append(doc)
    return merged

def _parse_article_reference(query: str) -> tuple[str, str | None, str | None, str | None] | None:
    """Extrai referência jurídica completa da query.

    Retorna (numero_artigo, nome_lei_opcional, tipo_doc_opcional, paragrafo_opcional) ou None.

    Exemplos:
      "artigo 54 do decreto 3048" -> ("54", "3048", "decreto", None)
      "art. 5o da constituição" -> ("5", "constituicao", "constituicao", None)
      "art 5 da cf" -> ("5", "cf", "constituicao", None)
      "art. 7 § 2 do decreto 3048" -> ("7", "3048", "decreto", "2")
      "o que diz o artigo 6" -> ("6", None, None, None)
      "células tronco" -> None
    """
    # Normaliza a query antes de buscar
    norm_query = query.lower()
    # Troca variantes de ordinal
    norm_query = re.sub(r'\b(primeiro|primeira)\b', '1', norm_query)
    norm_query = re.sub(r'\b(segundo|segunda)\b', '2', norm_query)
    norm_query = re.sub(r'\b(terceiro|terceira)\b', '3', norm_query)
    norm_query = re.sub(r'\b(quarto|quarta)\b', '4', norm_query)
    norm_query = re.sub(r'\b(quinto|quinta)\b', '5', norm_query)
    norm_query = re.sub(r'\b(sexto|sexta)\b', '6', norm_query)
    norm_query = re.sub(r'\b(setimo|setima|sétimo|sétima)\b', '7', norm_query)
    norm_query = re.sub(r'\b(oitavo|oitava)\b', '8', norm_query)
    norm_query = re.sub(r'\b(nono|nona)\b', '9', norm_query)
    norm_query = re.sub(r'\b(décimo|decimo|décima|decima)\b', '10', norm_query)

    # Extrai número do artigo (normalizado)
    patterns = [
        r'artigo\s+(\d+)[ºo°]?',       # artigo 54
        r'art\.\s*(\d+)[ºo°]?',        # art. 54
        r'art\s+(\d+)[ºo°]?',          # art 54 (sem ponto)
        r'art\.?(\d+)[ºo°]?',          # art54 (junto, sem espaço)
    ]

    article_num = None
    for pattern in patterns:
        m = re.search(pattern, norm_query)
        if m:
            article_num = m.group(1)
            break

    if not article_num:
        return None

    # Extrai parágrafo
    paragraph = None
    para_match = re.search(r'§\s*(\d+)[º°]?', norm_query)
    if para_match:
        paragraph = para_match.group(1)
    if re.search(r'parágrafo\s+único', norm_query, re.IGNORECASE):
        paragraph = 'único'

    # Extrai tipo de documento e número
    tipo_doc = None
    numero_doc = None

    # Mapeamento de tipos
    tipo_map = {
        'decreto': 'decreto',
        'lei': 'lei',
        'constituição': 'constituicao',
        'constituicao': 'constituicao',
        'cf': 'constituicao',
        'emenda': 'emenda',
        'ec': 'emenda',
        'portaria': 'portaria',
        'instrução': 'instrucao',
        'in': 'instrucao',
        'medida': 'medida_provisoria',
        'mp': 'medida_provisoria',
        'tema': 'jurisprudencia',
        'súmula': 'sumula',
        'sumula': 'sumula',
    }

    # Procura "decreto 3048", "lei 8213", "cf/88", "da CF" (sem número), etc.
    doc_patterns = [
        # Tipo sem número (ex: "da cf", "da constituição")
        r'(?:do|da|de|pela|na)\s+(cf)\b',
        r'(?:do|da|de|pela|na)\s+(constituição|constituicao)\b',
        # Tipo + número curto (ex: cf/88, mp 123)
        r'(cf|ec|mp)\s*[-/]?\s*(\d{2,4})',
        # Tipo + número (ex: decreto 3048, lei 8213, lei 14126)
        r'(decreto[-\s]*lei|decreto|lei|constituição|constituicao|ec|portaria|in|mp|tema|súmula|sumula|emenda)\s+(\d{1,5}(?:\.\d{3})*(?:[-/]\d{2,4})?)',
        r'(decreto|lei|constituição|constituicao|ec|portaria|in|mp|tema|súmula|sumula|emenda)\s+n?[º°]?\s*(\d{1,5}(?:\.\d{3})*)',
    ]

    for pattern in doc_patterns:
        m = re.search(pattern, norm_query)
        if m:
            raw_type = m.group(1)
            tipo_doc = tipo_map.get(raw_type, raw_type)
            # Tenta extrair número se existir no grupo 2
            if m.lastindex and m.lastindex >= 2 and m.group(2):
                g2 = m.group(2)
                raw_num = g2.split('-')[0].split('/')[0]
                numero_doc = raw_num.replace('.', '')
            break

    # Fallback: padrão Lnnnn (ex: L14126, l14126 = Lei 14.126)
    if tipo_doc is None:
        m = re.search(r'\bl(\d{4,})(?:consol)?\b', norm_query)
        if m:
            tipo_doc = 'lei'
            numero_doc = m.group(1)

    return (article_num, tipo_doc, numero_doc, paragraph)


def _metadata_search(query: str, user_id: int | None = None,
                      conn_factory=get_db_connection) -> list[dict[str, Any]]:
    """Busca determinística por metadados estruturados (artigo + tipo_doc + numero_doc).

    Se o parser identificou artigo e tipo de documento, faz busca exata nas colunas.
    Isso garante que consultas como "art. 54 do decreto 3048" encontrem o chunk
    certo sem depender de embeddings.
    """
    parsed = _parse_article_reference(query)
    if not parsed:
        return []

    article_num, tipo_doc, numero_doc, paragraph = parsed

    if not article_num:
        return []

    logger.info(f"Busca por metadados: artigo={article_num}, tipo={tipo_doc}, numero={numero_doc}, para={paragraph}")

    # Filtro de escopo
    if user_id is not None:
        scope_filter = "AND (scope = 'global' OR owner_id = %s)"
        scope_params = [user_id]
    else:
        scope_filter = ""
        scope_params = []

    # Monta WHERE dinâmico
    conditions = ["artigo = %s"]
    params = [int(article_num)]

    if tipo_doc:
        conditions.append("tipo_doc = %s")
        params.append(tipo_doc)

    if numero_doc:
        conditions.append("numero_doc = %s")
        params.append(numero_doc)

    if paragraph:
        conditions.append("paragrafo = %s")
        params.append(paragraph)

    where_clause = " AND ".join(conditions)

    sql = f"""
        SELECT
            id,
            file_name,
            content,
            scope,
            0.0 AS distance,
            artigo,
            tipo_doc,
            numero_doc,
            source_id
        FROM documents
        WHERE {where_clause}
          {scope_filter}
        ORDER BY id ASC
        LIMIT 5
    """

    params = params + scope_params

    try:
        with conn_factory() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
                logger.info(f"Metadata search: {len(rows)} resultados para artigo {article_num}")
                return rows
    except psycopg2.Error:
        logger.exception("Erro de banco de dados na busca por metadados")
        return []


def _keyword_search(query: str, user_id: int | None = None,
                    conn_factory=get_db_connection) -> list[dict[str, Any]]:
    """Busca por palavra-chave (regex) quando a query menciona artigo específico.

    Usa regex normalizada no conteúdo para encontrar o artigo.
    """
    parsed = _parse_article_reference(query)
    if not parsed:
        return []

    article_num, tipo_doc, numero_doc, paragraph = parsed

    # Monta regex para buscar exatamente o artigo (evita matches parciais como "545" para "54")
    article_pattern = f'Art\\.\\s*{article_num}[\\sº°\\.\\)]'

    logger.info(f"Busca por palavra-chave ativada: artigo={article_num}, tipo={tipo_doc}, num={numero_doc}")

    # Filtro de escopo
    if user_id is not None:
        scope_filter = "AND (scope = 'global' OR owner_id = %s)"
        scope_params = [user_id]
    else:
        scope_filter = ""
        scope_params = []

    # Filtro por tipo/número do documento
    file_filter = ""
    file_params = []
    if tipo_doc and numero_doc:
        file_filter = "AND tipo_doc = %s AND numero_doc = %s"
        file_params = [tipo_doc, numero_doc]
    elif numero_doc:
        file_filter = "AND (numero_doc = %s OR file_name ILIKE %s)"
        file_params = [numero_doc, f'%{numero_doc}%']

    params = [article_pattern] + scope_params + file_params

    sql = f"""
        SELECT
            id,
            file_name,
            content,
            scope,
            0.0 AS distance,
            artigo,
            tipo_doc,
            numero_doc,
            source_id
        FROM documents
        WHERE content ~ %s
          {scope_filter}
          {file_filter}
        ORDER BY file_name ASC, id ASC
        LIMIT 10
    """

    try:
        with conn_factory() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
                logger.info(f"Keyword search: {len(rows)} resultados para artigo {article_num}")
                return rows
    except psycopg2.Error:
        logger.exception("Erro de banco de dados na busca por palavra-chave")
        return []


