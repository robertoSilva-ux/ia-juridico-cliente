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
    # (A regex tinha a barra dobrada — `\\\\s` dentro de raw string casa barra invertida
    # literal — e o ramo NUNCA disparava; o prefixo do tipo_map cobria o caso por acaso.)
    if not result['tipo']:
        m = re.match(r'LC[Pp]?\s*(\d+)', name, re.IGNORECASE)
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
        # Separadores reais de nome de arquivo: espaço, "-", "_" e o início do
        # nome; e o número pode TERMINAR o nome ("LEI 8080", "LEI-8080-ESQ1").
        # Os padrões antigos exigiam espaço dos dois lados, então
        # "LEI-8080-ESQUEMATIZADA1.pdf" e "LEI 8080.pdf" ficavam com numero=None —
        # e o rótulo degenerava para "Lei", deixando o modelo ler "8080" do
        # próprio nome do arquivo e escrever "Lei nº 8080/2011" (ver factcheck).
        m = re.search(r'(?:^|[\s\-_])(\d{1,3}(?:\.\d{3})+)(?=[\s\-_.]|$)', name)
        if m:
            result['numero'] = m.group(1).replace('.', '')
        else:
            # Número simples
            m = re.search(r'(?:^|[\s\-_])(\d{3,5})(?=[\s\-_.]|$)', name)
            if m:
                result['numero'] = m.group(1)

    # Extrai ano (formato -99, -1999, /99, /1999, _1991, (1988))
    m = re.search(r'[-/_](\d{2,4})\)?$', name)
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
# IDENTIDADE DA NORMA NO DOCUMENTO (R-9)
# =========================================================

# Cabeçalho do texto oficial (Planalto): "LEI Nº 8.080, DE 19 DE SETEMBRO DE 1990",
# "DECRETO Nº 3.048, DE 6 DE MAIO DE 1999", "EMENDA CONSTITUCIONAL Nº 103, DE 12 DE
# NOVEMBRO DE 2019", "LEI COMPLEMENTAR Nº 142, DE 8 DE MAIO DE 2013". O par número+ano
# vem JUNTO aqui — que é exatamente o que faltava na apostila, onde o número está em um
# fragmento e o ano em outro (docs/PLANO_REFINAMENTO_RAG.md, P2-30).
_TIPOS_NORMA = {
    'lei complementar': 'lei_complementar',
    'lei': 'lei',
    'decreto-lei': 'decreto',
    'decreto': 'decreto',
    'emenda constitucional': 'emenda',
    'medida provisória': 'medida_provisoria',
    'medida provisoria': 'medida_provisoria',
}
_NORMA_CAUDA = (r"\s*,?\s*(?:de\s+)?(?:\d{1,2}\s*[º°o]?\s+de\s+[a-zçãéíóúâêô]+\s+de\s+)?"
                # Ano de dois dígitos só depois de "/" (convenção "Lei 8.213/91"): o
                # hífen é ambíguo — "MP nº 2.164-41" é a 41ª reedição, não o ano 1941,
                # e o corte em 30 transformaria isso num ano errado em todo o documento.
                r"([/-]?\s*\d{4}|/\s*\d{2}(?=[\s.,;)]|$))")
# O número aceita o sufixo de reedição da MP ("2.164-41"), que é descartado na
# normalização: a identidade da norma é o número, não a reedição.
_NORMA_NUMERO = r"([\d.]{1,12}(?:-\d{1,2})?)"
_CABECALHO_NORMA = re.compile(
    r"\b(lei\s+complementar|lei|decreto-lei|decreto|emenda\s+constitucional|"
    r"medida\s+provis[óo]ria)\s*n\s*[.º°]*\s*" + _NORMA_NUMERO + _NORMA_CAUDA,
    re.IGNORECASE,
)
# Forma SEM "nº" — material didático escreve o título em prosa: "Apresentarei a você neste
# artigo a Lei 8.080, de 19 de setembro de 1990". Medido no PDF real da apostila: sem este
# padrão, a identidade saía da LISTA DE LEIS QUE ALTERAM a 8.080 (pos. 2.113 do texto:
# "Decreto nº 1.651, de 28 de setembro de 1995") — norma citada, não o documento.
_CABECALHO_NORMA_SEM_N = re.compile(
    r"\b(lei\s+complementar|lei|decreto-lei|decreto|emenda\s+constitucional|"
    r"medida\s+provis[óo]ria)\s+" + _NORMA_NUMERO + _NORMA_CAUDA,
    re.IGNORECASE,
)
# Mesmo cabeçalho em CAIXA ALTA — é como o Planalto grafa o título do documento
# ("LEI Nº 8.080, DE..."), enquanto a lei CITADA no corpo vem em caixa mista
# ("(Incluído pela Lei nº 12.401, de 2011)").
_CABECALHO_NORMA_MAIUSCULO = re.compile(
    r"\b(LEI\s+COMPLEMENTAR|LEI|DECRETO-LEI|DECRETO|EMENDA\s+CONSTITUCIONAL|"
    r"MEDIDA\s+PROVIS[ÓO]RIA)\s*N\s*[.º°]*\s*" + _NORMA_NUMERO
    + _NORMA_CAUDA.replace("[a-zçãéíóúâêô]", "[A-ZÇÃÉÍÓÚÂÊÔ]")
)
# Citação, não identidade: "(Incluído pela Lei nº 12.401…", "(Redação dada pela Lei…".
_CITA_CUE = re.compile(
    r"(?:pela|pelo|vide|com\s+a\s+reda[çc][ãa]o|inclu[íi]d[oa]s?|alterad[oa]s?|revogad[oa]s?|"
    r"acrescid[oa]s?|vetad[oa]s?|conforme|segundo|de\s+acordo\s+com|nas?\s+formas?\s+d[ao]|"
    r"previst[oa]s?\s+n[ao]s?|nos\s+termos\s+d[ao])\s*[\w()]*\s*$",
    re.IGNORECASE,
)
_CABECALHO_CONSTITUICAO = re.compile(
    r"constitui[çc][ãa]o(?:\s+da\s+rep[úu]blica\s+federativa\s+do\s+brasil)?[^.\n]{0,40}?(19\d{2})",
    re.IGNORECASE,
)


def _achado_de_cabecalho(match, trecho: str) -> bool:
    """True se a ocorrência NÃO é uma norma citada (citação não é identidade do documento)."""
    antes = trecho[max(0, match.start() - 45):match.start()]
    return not _CITA_CUE.search(antes)


def _norm_ano(bruto: str | None) -> str | None:
    """'1990' -> '1990'; '91' -> '1991'; '05' -> '2005' (corte em 30, como no fact-check).

    A convenção de dois dígitos é a do direito brasileiro ("Lei nº 8.213/91") e é como o
    nome de muitos arquivos do Planalto vem.
    """
    if not bruto:
        return None
    digitos = re.sub(r"\D", "", bruto)
    if not digitos:
        return None
    if len(digitos) <= 2:
        numero = int(digitos)
        return str(1900 + numero if numero >= 30 else 2000 + numero)
    return digitos


def parse_norm_header(texto: str, limite: int = 2000) -> dict[str, str | None]:
    """Identidade da norma a partir do cabeçalho DO TEXTO (primeiros ``limite`` caracteres).

    Três padrões, e a escolha é por POSIÇÃO, não por padrão: a identidade é a norma
    anunciada mais no início do texto. Ordem por padrão erraria — no material didático o
    título da própria lei aparece em prosa ("a Lei 8.080, de 19 de setembro de 1990", sem
    "nº") e a lista de leis que a alteraram vem depois, com "nº": escolher por padrão
    pegaria a norma citada. O que vem de citação é recusado em todos os padrões.

    Devolve `{'tipo', 'numero', 'ano'}` com None no que não achou.

    ``limite`` é curto DE PROPÓSITO. Medido no PDF real da apostila ("LEI-8080-
    ESQUEMATIZADA1", 65 páginas): com 4.000 caracteres a primeira "norma" encontrada é
    `Decreto nº 1.651, de 28 de setembro de 1995` (pos. 2.113) — uma linha da **lista de
    leis que alteraram** a 8.080, ou seja, norma citada virando identidade do documento
    inteiro. Com 2.000 o texto do cabeçalho não tem nenhum "nº" e a identidade vem do
    título em prosa, que é a informação certa. Preço declarado: um documento cujo título
    apareça depois do limite cai para o nome do arquivo (degradação honesta, nunca
    invenção).
    """
    vazio: dict[str, str | None] = {"tipo": None, "numero": None, "ano": None}
    if not texto:
        return vazio
    trecho = texto[:limite]

    candidatos = []
    for padrao, normaliza in ((_CABECALHO_NORMA_MAIUSCULO, True), (_CABECALHO_NORMA, False),
                             (_CABECALHO_NORMA_SEM_N, False)):
        for m in padrao.finditer(trecho):
            if _achado_de_cabecalho(m, trecho):
                candidatos.append((m.start(), m, normaliza))

    if candidatos:
        _, m, normaliza = min(candidatos, key=lambda c: c[0])
        bruto = m.group(1).lower() if normaliza else re.sub(r"\s+", " ", m.group(1).lower())
        return {
            "tipo": _TIPOS_NORMA.get(bruto, bruto),
            # "2.164-41" (MP com reedição) -> "2164": a identidade é o número.
            "numero": re.sub(r"-\d+$", "", m.group(2)).replace(".", ""),
            "ano": _norm_ano(m.group(3)),
        }

    m = _CABECALHO_CONSTITUICAO.search(trecho)
    if m:
        return {"tipo": "constituicao", "numero": None, "ano": m.group(1)}

    return vazio


def identidade_do_documento(texto: str, file_name: str | None = None) -> dict[str, str | None]:
    """Identidade da norma para TODO o documento: cabeçalho do texto, nome do arquivo como reserva.

    A identidade vale para todos os fragmentos do arquivo (é do documento, não do
    fragmento) e é o que faz o fact-check deixar de depender do nome do arquivo — na base
    de dev 120 de 122 fragmentos estavam sem `numero_doc`, e a única identidade da 8.080
    era o nome `LEI-8080-ESQUEMATIZADA1.pdf`.

    As duas fontes descrevem o MESMO documento (o cabeçalho dele ou o nome dele), nunca
    outra lei: por isso completar um campo que o cabeçalho não traz com o nome do arquivo
    não recria a composição indevida do ADR-0007.
    """
    cabecalho = parse_norm_header(texto)
    nome: dict[str, str | None] = (parse_file_name(file_name) if file_name
                                   else {"tipo": None, "numero": None, "ano": None})
    return {
        "tipo": cabecalho["tipo"] or nome["tipo"],
        "numero": cabecalho["numero"] or nome["numero"],
        "ano": cabecalho["ano"] or nome["ano"],
    }


def linha_carrega_identidade_de_norma(linha: str) -> bool:
    """True se a linha é (ou começa com) um cabeçalho de norma ou um dispositivo.

    Usado pela limpeza de cabeçalho/rodapé repetido na ingestão (R-10): o texto oficial do
    Planalto repete "LEI Nº 8.080, DE 19 DE SETEMBRO DE 1990" no alto de TODA página, e é
    justamente essa repetição que dá o par número+ano em cada fragmento (P2-30). Removê-la
    como se fosse rodapé destruiria o que torna o corpus oficial melhor que a apostila.
    """
    if not linha:
        return False
    if _CABECALHO_NORMA_MAIUSCULO.search(linha) or _CABECALHO_NORMA.search(linha):
        return True
    return bool(re.match(r"\s*(?:Art|ART|Artigo)\s*\.?\s*\d", linha))


# =========================================================
# PARSER COMPLETO DE CHUNK
# =========================================================

def parse_chunk(content: str, file_name: str, identidade: dict | None = None) -> dict:
    """Extrai todos os metadados jurídicos de um chunk.

    Retorna dict com: artigo, paragrafo, inciso, tipo_doc, numero_doc, ano_doc

    ``identidade`` (de `identidade_do_documento`) substitui o que vinha só do nome do
    arquivo: os três campos de norma são do DOCUMENTO e valem para todo fragmento dele.
    """
    result = {
        'artigo': extract_article_num(content),
        'paragrafo': extract_paragraph(content),
        'inciso': extract_inciso(content),
    }

    base = identidade or parse_file_name(file_name)
    result['tipo_doc'] = base.get('tipo')
    result['numero_doc'] = base.get('numero')
    result['ano_doc'] = base.get('ano')

    return result


def enrich_chunk_metadata(chunk_content: str, file_name: str, existing_metadata: dict,
                          identidade: dict | None = None) -> dict:
    """Enriquece metadados existentes com info jurídica extraída."""
    legal = parse_chunk(chunk_content, file_name, identidade)
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
