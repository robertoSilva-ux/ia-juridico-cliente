"""
Parser de documentos jurídicos — extrai metadados estruturados de chunks de texto.

Exemplos:
  "Art. 54. A aposentadoria..." → artigo=54, tipo_doc extraído do file_name
  "§ 1º O segurado..." → paragrafo=1
  "I - Contribuir..." → inciso=I
"""

import logging
import re

logger = logging.getLogger(__name__)

# =========================================================
# PARSER DE REFERÊNCIAS NO CONTEÚDO
# =========================================================

def extract_article_num(text: str) -> int | None:
    """Extrai número do artigo do texto do chunk.

    Reconhece: Art. 54, Art. 7º, Artigo 5°, ART. 12, art 3
    E artigos com separador de milhar: Art. 1.238, Art. 1.242, ART 1.261

    O separador de milhar é crítico: o Código Civil (L10406) tem artigos
    acima de 1.000 escritos como "Art. 1.238". Sem tratar o ponto, o regex
    casava só o primeiro dígito e armazenava artigo=1 — foram 1.029 chunks
    corrompidos na base antes desta correção (2026-09-21).
    """
    patterns = [
        r'(?:^|\n)\s*Art\.?\s*(\d{1,3}(?:\.\d{3})+|\d+)[º°]?',   # Art. 1.238, Art. 54, Art. 7º
        r'(?:^|\n)\s*Artigo\s+(\d{1,3}(?:\.\d{3})+|\d+)[º°]?',      # Artigo 5°, Artigo 1.238
        r'(?:^|\n)\s*ART\.?\s*(\d{1,3}(?:\.\d{3})+|\d+)[º°]?',    # ART. 1.238, ART. 54
        r'(?:^|\n)\s*ART\s+(\d{1,3}(?:\.\d{3})+|\d+)[º°]?',        # ART 7, ART 1.261
    ]
    for pattern in patterns:
        m = re.search(pattern, text)
        if m:
            # Normaliza o separador de milhar: "1.238" -> 1238
            return int(m.group(1).replace('.', ''))
    return None


def extract_paragraph(text: str) -> str | None:
    """Extrai parágrafo do texto do chunk.

    Reconhece: § 1º, §1º, § 2°, Parágrafo único, § único
    """
    # § 1º, § 2°, etc.
    m = re.search(r'§\s*(\d+)[º°]?', text)
    if m:
        return m.group(1)

    # Parágrafo único
    if re.search(r'Parágrafo\s+único', text, re.IGNORECASE):
        return 'único'

    return None


def extract_inciso(text: str) -> str | None:
    """Extrai inciso do texto do chunk.

    Reconhece: I -, II -, a), b), Inciso I, etc.
    """
    # Inciso I, Inciso II, etc.
    m = re.search(r'Inciso\s+([IVXLCDM]+)', text, re.IGNORECASE)
    if m:
        return m.group(1)

    # I - (romano no início de linha)
    m = re.search(r'(?:^|\n)\s*([IVXLCDM]+)\s+[-–—]', text)
    if m:
        val = m.group(1)
        if val in ('I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X',
                   'XI', 'XII', 'XIII', 'XIV', 'XV', 'XVI', 'XVII', 'XVIII', 'XIX', 'XX'):
            return val

    # a), b), c) etc.
    m = re.search(r'(?:^|\n)\s*([a-z])\)', text)
    if m:
        return m.group(1)

    return None


# =========================================================
# PARSER DE NOME DE ARQUIVO
# =========================================================

def parse_file_name(file_name: str) -> dict[str, str | None]:
    """Extrai tipo, número e ano do nome do arquivo.

    Exemplos:
      "Decreto 3.048-99.pdf" → {"tipo": "decreto", "numero": "3048", "ano": "1999"}
      "Lei 8.213-91.pdf"    → {"tipo": "lei", "numero": "8213", "ano": "1991"}
      "CF-88.pdf"           → {"tipo": "constituicao", "numero": None, "ano": "1988"}
      "Lei 14.133-2021.pdf" → {"tipo": "lei", "numero": "14133", "ano": "2021"}
      "Tema 1102 STF.pdf"   → {"tipo": "jurisprudencia", "numero": None, "ano": None}
    """
    result = {"tipo": None, "numero": None, "ano": None}
    if not file_name:
        return result

    name = file_name.replace('.pdf', '').replace('.PDF', '').strip()

    # Mapeamento de tipos de documento
    tipo_map = {
        'decreto': 'decreto',
        'lei complementar': 'lei_complementar',
        'lcp': 'lei_complementar',
        'lc': 'lei_complementar',
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
        'projeto': 'projeto_lei',
    }

    # Extrai tipo (primeira palavra reconhecida)
    name_lower = name.lower()
    for key, value in tipo_map.items():
        if name_lower.startswith(key):
            result['tipo'] = value
            break

    # Formato Planalto para leis complementares: Lcp 142, LC 142.
    if not result['tipo']:
        m = re.match(r'LC[Pp]?\\s*(\\d+)', name, re.IGNORECASE)
        if m:
            result['tipo'] = 'lei_complementar'
            result['numero'] = m.group(1)

    # Se não achou por prefixo, tenta regex para "Decreto 3.048", "Lei 8.213" etc.
    if not result['tipo']:
        m = re.match(r'(Decreto|Lei|Constituição|CF|EC|Portaria|IN|MP|Tema|Súmula)\s', name, re.IGNORECASE)
        if m:
            result['tipo'] = tipo_map.get(m.group(1).lower(), m.group(1).lower())

    # Tenta padrão "Lnnnnn" ou "Lnnnn" (ex: L14126 = Lei 14.126, L9263 = Lei 9.263, L8213consol = Lei 8.213) — padrão Planalto
    if not result['tipo']:
        # Pega tudo que é L seguido de dígitos (aceita sufixos como "consol")
        m = re.match(r'^L(\d{4,})([a-z]|$)', name, re.IGNORECASE)
        if m:
            result['tipo'] = 'lei'
            result['numero'] = m.group(1)

    # Tenta padrão "PLnnnn" (Projeto de Lei)
    if not result['tipo']:
        m = re.match(r'^PL(\d+)\b', name, re.IGNORECASE)
        if m:
            result['tipo'] = 'projeto_lei'
            result['numero'] = m.group(1)

    # Extrai número (ex: "3.048" -> "3048", "14.133" -> "14133")
    # Pega o primeiro número que aparece depois de um espaço (não no ano)
    if not result['numero'] and result['tipo'] == 'lei_complementar':
        m = re.search(r'\b(?:lcp?|lc|lei\s+complementar)\s*(\d+)\b', name, re.IGNORECASE)
        if m:
            result['numero'] = m.group(1)
    if not result['numero']:
        m = re.search(r'(?:^|\s)(\d{1,2}(?:\.\d{3})+)(?:\s|-)', name)
        if m:
            result['numero'] = m.group(1).replace('.', '')
        else:
            # Tenta número simples
            m = re.search(r'(?:^|\s)(\d{3,4})(?:\s|-)', name)
            if m:
                result['numero'] = m.group(1)

    # Extrai ano (formato -99, -1999, /99, /1999, (1988))
    m = re.search(r'[-/](\d{2,4})\)?$', name)
    if m:
        year_str = m.group(1)
        if len(year_str) == 2:
            year_str = '19' + year_str if int(year_str) > 50 else '20' + year_str
        result['ano'] = year_str
    else:
        m = re.search(r'\((\d{4})\)', name)
        if m:
            result['ano'] = m.group(1)

    return result


# =========================================================
# PARSER COMPLETO DE CHUNK
# =========================================================

def parse_chunk(content: str, file_name: str) -> dict:
    """Extrai todos os metadados jurídicos de um chunk.

    Retorna dict com: artigo, paragrafo, inciso, tipo_doc, numero_doc, ano_doc
    """
    result = {
        'artigo': extract_article_num(content),
        'paragrafo': extract_paragraph(content),
        'inciso': extract_inciso(content),
    }

    file_meta = parse_file_name(file_name)
    result['tipo_doc'] = file_meta['tipo']
    result['numero_doc'] = file_meta['numero']
    result['ano_doc'] = file_meta['ano']

    return result


def enrich_chunk_metadata(chunk_content: str, file_name: str, existing_metadata: dict) -> dict:
    """Enriquece metadados existentes com info jurídica extraída."""
    legal = parse_chunk(chunk_content, file_name)
    enriched = dict(existing_metadata or {})
    enriched.update(legal)
    return enriched


def build_title(meta):
    tipo = (meta.get('tipo') or '').strip()
    numero = (meta.get('numero') or '').strip()
    ano = (meta.get('ano') or '').strip()
    if not tipo and not numero:
        return ''
    tipo_label = {
        'lei': 'Lei',
        'lei_complementar': 'Lei Complementar',
        'decreto': 'Decreto',
        'constituicao': 'Constituição',
        'emenda': 'Emenda Constitucional',
        'portaria': 'Portaria',
        'instrucao': 'Instrução Normativa',
        'medida_provisoria': 'Medida Provisória',
        'jurisprudencia': 'Jurisprudência',
        'sumula': 'Súmula',
        'projeto_lei': 'Projeto de Lei',
    }.get(tipo, tipo.capitalize())
    titulo = tipo_label
    if numero:
        try:
            n = int(numero)
        except ValueError:
            n = None
        if n is not None and len(numero) > 3:
            num_fmt = f'{n:,}'.replace(',', '.')
        else:
            num_fmt = numero
        titulo = titulo + ' ' + num_fmt
    if ano:
        titulo = titulo + '/' + ano[-2:]
    return titulo
