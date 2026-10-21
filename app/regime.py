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
        # Sem distância (busca por dispositivo/keyword) o `or 0.0` mantém esses
        # resultados à frente — comportamento preservado de propósito nesta fase:
        # mudar a ORDEM da recuperação não é o que esta correção faz.
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

#: Normalização de ordinais escritos por extenso ("segundo o art. 9º" -> "2 o art. 9º").
#: Vive fora de `_parse_article_reference` porque a detecção de NORMA (P2-32) usa a
#: mesma normalização — duas cópias divergiriam na primeira correção.
_ORDINAIS = (
    (r'\b(primeiro|primeira)\b', '1'),
    (r'\b(segundo|segunda)\b', '2'),
    (r'\b(terceiro|terceira)\b', '3'),
    (r'\b(quarto|quarta)\b', '4'),
    (r'\b(quinto|quinta)\b', '5'),
    (r'\b(sexto|sexta)\b', '6'),
    (r'\b(setimo|setima|sétimo|sétima)\b', '7'),
    (r'\b(oitavo|oitava)\b', '8'),
    (r'\b(nono|nona)\b', '9'),
    (r'\b(décimo|decimo|décima|decima)\b', '10'),
)

#: Tipo de norma, como a pergunta escreve -> valor de `tipo_doc` na base.
_TIPO_DOC_MAP = {
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
    'lei complementar': 'lei_complementar',
    'lei-complementar': 'lei_complementar',
    'lcp': 'lei_complementar',
}

#: "decreto 3048", "lei 8.080", "cf/88", "da CF"… Ordem importa: os padrões com
#: tipo sem número vêm antes para não perder "da constituição" para o genérico, e
#: "lei complementar N" antes de "lei N" (senão o número da complementar se perde).
_DOC_PATTERNS = [
    r'(?:do|da|de|pela|na)\s+(cf)\b',
    r'(?:do|da|de|pela|na)\s+(constituição|constituicao)\b',
    r'(cf|ec|mp)\s*[-/]?\s*(\d{2,4})',
    r'(lei[-\s]*complementar|lcp)\s+n?[º°]?\s*(\d{1,5}(?:\.\d{3})*)',
    r'(decreto[-\s]*lei|decreto|lei|constituição|constituicao|ec|portaria|in|mp|tema|súmula|sumula|emenda)\s+(\d{1,5}(?:\.\d{3})*(?:[-/]\d{2,4})?)',
    r'(decreto|lei|constituição|constituicao|ec|portaria|in|mp|tema|súmula|sumula|emenda)\s+n?[º°]?\s*(\d{1,5}(?:\.\d{3})*)',
    # A Constituição é a única norma que a pergunta nomeia sem preposição nem
    # número ("o que diz a Constituição sobre saúde?"). Vem por último para não
    # roubar "cf/88" dos padrões com número.
    r'\b(constituição|constituicao|cf)\b',
]


def _normalizar_ordinais(query: str) -> str:
    """Minúsculas + ordinais por extenso trocados por algarismo."""
    norm_query = (query or '').lower()
    for padrao, digito in _ORDINAIS:
        norm_query = re.sub(padrao, digito, norm_query)
    return norm_query


def _extrair_norma(norm_query: str) -> tuple[str | None, str | None]:
    """Extrai (tipo_doc, numero_doc) de uma query JÁ normalizada por `_normalizar_ordinais`.

    Sem número também serve: "segundo a Constituição" dá ("constituicao", None) — e
    é justamente o caso em que só o tipo identifica a norma.
    """
    for pattern in _DOC_PATTERNS:
        m = re.search(pattern, norm_query)
        if m:
            raw_type = m.group(1)
            tipo_doc = _TIPO_DOC_MAP.get(raw_type, raw_type)
            numero_doc = None
            if m.lastindex and m.lastindex >= 2 and m.group(2):
                g2 = m.group(2)
                numero_doc = g2.split('-')[0].split('/')[0].replace('.', '')
            return tipo_doc, numero_doc

    # Fallback: padrão Lnnnn (ex: L14126, l14126 = Lei 14.126)
    m = re.search(r'\bl(\d{4,})(?:consol)?\b', norm_query)
    if m:
        return 'lei', m.group(1)
    return None, None


def _parse_norm_reference(query: str) -> tuple[str, str | None] | None:
    """Qual NORMA a pergunta nomeia — sem exigir que ela cite um artigo.

    É o que falta em `_parse_article_reference` para o escopo da recuperação
    (P2-32): "O que a Lei 8.080 diz sobre consórcios?" não tem artigo e mesmo
    assim diz de que norma está falando. Devolve (tipo_doc, numero_doc) ou None
    quando a pergunta não nomeia norma nenhuma ("aposentadoria rural").
    """
    tipo_doc, numero_doc = _extrair_norma(_normalizar_ordinais(query))
    if not tipo_doc:
        return None
    return tipo_doc, numero_doc


def _parse_article_reference(query: str) -> tuple[str, str | None, str | None, str | None] | None:
    """Extrai referência jurídica completa da query.

    Retorna (numero_artigo, tipo_doc_opcional, numero_doc_opcional, paragrafo_opcional)
    ou None.

    ATENÇÃO à ordem: é (número do ARTIGO, tipo da norma, número da norma,
    parágrafo). Os exemplos abaixo estavam escritos com tipo e número trocados
    desde a refatoração de 2026-09-25 — quem lesse a docstring e desempacotasse
    como ela dizia lia `tipo_doc` onde havia `numero_doc` (corrigido em P2-32,
    com `TestParseArticleReferenceCompat` travando o contrato de verdade).

    Exemplos:
      "artigo 54 do decreto 3048" -> ("54", "decreto", "3048", None)
      "art. 5o da constituição" -> ("5", "constituicao", None, None)
      "art 5 da cf" -> ("5", "constituicao", None, None)
      "art. 7 § 2 do decreto 3048" -> ("7", "decreto", "3048", "2")
      "o que diz o artigo 6" -> ("6", None, None, None)
      "células tronco" -> None
    """
    norm_query = _normalizar_ordinais(query)

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

    tipo_doc, numero_doc = _extrair_norma(norm_query)
    return (article_num, tipo_doc, numero_doc, paragraph)


def _metadata_search(query: str, user_id: int | None = None,
                      conn_factory=get_db_connection) -> list[dict[str, Any]]:
    """Busca determinística por metadados estruturados (artigo + tipo_doc + numero_doc).

    Se o parser identificou artigo e tipo de documento, faz busca exata nas colunas.
    Isso garante que consultas como "art. 54 do decreto 3048" encontrem o chunk
    certo sem depender de embeddings.

    `distance` volta NULL e `origem` = 'dispositivo': aqui NÃO houve comparação
    vetorial, e devolver 0.0 (o que a interface lia como "100% de similaridade")
    era invenção — o chamador decide o que mostrar a partir de `origem`.
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
            NULL::float AS distance,
            'dispositivo' AS origem,
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
            NULL::float AS distance,
            'keyword' AS origem,
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


