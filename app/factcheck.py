"""Fact-check e groundedness pós-geração.

Extraído de agent.py na refatoração (2026-09-25). Mantém a API pública original.
Funções: _split_sentences, _extract_citations, _load_dispositivos_base,
invalidate_dispositivos_cache, _check_semantic_grounding, _canonicalizar_numeros,
_normalize_dispositivo, _has_factual_claim, _factual_claim_grounded,
_classify_sentence_grounded, _classificar_sentenca, _unidades_factuais,
_unidades_ausentes, _parece_recusa, _is_boilerplate, _fact_check_answer.

Veredito da resposta (campo `veredito` do retorno): `fundamentada` · `parcial` ·
`recusou` · `sem_lastro`. Quem decide o que a interface exibe é o `agent`, a
partir dele — o fact-check só mede.
"""
import logging
import re
from typing import Any

from config import (
    FACT_CHECK_CACHE_MAX_CHARS,
    FACT_CHECK_CACHE_MAX_ROWS,
    FACT_CHECK_ENABLED,
)

from database import get_db_connection

logger = logging.getLogger(__name__)

# FACT-CHECK / GROUNDEDNESS (verificação pós-geração)
# =========================================================

def _split_sentences(text: str) -> list[str]:
    """Divide a resposta em sentenças, preservando o texto real.

    Quebra por . ! ? seguidos de espaço/fim, mas evita quebrar abreviações
    comuns em textos jurídicos (art., inc., §, etc.).
    """
    if not text:
        return []
    # Protege abreviações curtas (art., inc., par., al., etc.) da quebra
    protected = re.sub(r'\b((?:art|inc|par|al|n|p)\.)', lambda m: m.group(1).replace('.', 'ABBR'), text)
    sentences = re.split(r'(?<=[.!?])\s+', protected)
    out = []
    for s in sentences:
        s = s.replace('ABBR', '.').strip()
        if s:
            out.append(s)
    return out


def _extract_citations(sentence: str) -> list[int]:
    """Extrai os números de citação citados em uma sentença.

    Aceita as duas grafias que chegam na prática: `[3]` e `[DOC 3]` — a segunda é
    a que o system prompt MANDA usar ("cite … no formato [DOC n]"). Reconhecer só
    `[n]` reprovava como "sem fonte" toda resposta corretamente citada, o que
    disparava reescrita e terminava em recusa de uma resposta boa (defeito medido
    em 2026-10-16: 4 de 5 perguntas legítimas recusadas por esse motivo).
    """
    return [int(n) for n in re.findall(r"\[\s*(?:DOC\s*)?(\d+)\s*\]", sentence, re.IGNORECASE)]


# Cache POR DONO dos dispositivos (art. N / §N / inciso X) que existem no escopo
# alcançável por aquele usuário. Duas razões, ambas medidas:
#  - comparar contra só os docs recuperados gerava falso positivo (dispositivo válido que
#    simplesmente não foi recuperado naquela pergunta);
#  - comparar contra a BASE INTEIRA — como era — validava dispositivo de OUTRO cliente e
#    carregava o corpus todo na memória de um container de 512 MB (P1-1).
# O escopo agora é o mesmo da recuperação: `scope='global' OR owner_id = <dono>`; sem dono
# (lote/legado, ou eval) vale `scope='global' OR owner_id IS NULL`.
_DISPOSITIVOS_BASE_CACHE: dict = {}


def _load_dispositivos_base(user_id: int | None = None) -> frozenset:
    """Dispositivos normalizados que existem no escopo do usuário (memoizado por dono).

    Os limites (`FACT_CHECK_CACHE_MAX_ROWS`/`_CHARS`) existem porque a varredura sem teto
    era o caminho do OOM; ao atingi-los a validação continua com o que coube e o log avisa.
    Em caso de falha de BD devolve conjunto vazio — degrada para "não valida", evitando
    marcar tudo como alucinação quando a base está inacessível.
    """
    if user_id in _DISPOSITIVOS_BASE_CACHE:
        return _DISPOSITIVOS_BASE_CACHE[user_id]
    if user_id is None:
        escopo, params = "(scope = 'global' OR owner_id IS NULL)", ()
    else:
        escopo, params = "(scope = 'global' OR owner_id = %s)", (user_id,)

    encontrados: set[str] = set()
    caracteres = 0
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT content FROM documents "
                    f"WHERE content IS NOT NULL AND {escopo} LIMIT %s",
                    params + (FACT_CHECK_CACHE_MAX_ROWS,),
                )
                for (content,) in cur:
                    encontrados.update(
                        _normalize_dispositivo(disp)
                        for disp in _DISPOSITIVO_PATTERN.findall(content or '')
                    )
                    caracteres += len(content or "")
                    if caracteres >= FACT_CHECK_CACHE_MAX_CHARS:
                        logger.warning(
                            "Cache de dispositivos (dono=%s): teto de %s caracteres atingido — "
                            "validação segue com os fragmentos lidos",
                            user_id, FACT_CHECK_CACHE_MAX_CHARS,
                        )
                        break
    except Exception as e:
        logger.warning(f"Falha ao carregar dispositivos da base (validação desativada): {e}")
        return frozenset()
    _DISPOSITIVOS_BASE_CACHE[user_id] = frozenset(encontrados)
    logger.info("Cache de dispositivos (dono=%s): %s entradas, %s caracteres lidos",
                user_id, len(encontrados), caracteres)
    return _DISPOSITIVOS_BASE_CACHE[user_id]


def invalidate_dispositivos_cache() -> None:
    """Invalida o cache de dispositivos — chamado pela ingestão, que muda a base."""
    _DISPOSITIVOS_BASE_CACHE.clear()


def _check_semantic_grounding(sentence: str, context_text: str,
                              user_id: int | None = None) -> tuple[str, str]:
    """Verifica o lastro da sentença no contexto recuperado (groundedness).

    Retorna (status, razão):
      - ('no_support', 'autor_sem_lastro'): a sentença cita autor/obra (padrão
        "SOBRENOME, ano" ou "SOBRENOME (ano)") que NÃO aparece em nenhum chunk
        recuperado — forte indício de vazamento de conhecimento pré-treinado do
        modelo (regra "NUNCA use seu conhecimento interno" do prompt).
      - ('weak', 'cobertura_baixa'): pouca sobreposição lexical com o contexto
        (groundedness fraco, sem ser conclusivo).
      - ('supported', ''): as unidades significativas da sentença encontram
        correspondência no contexto.

    ``user_id`` delimita o escopo do índice de dispositivos (P1-1): o dispositivo
    citado é conferido contra o que existe no escopo DAQUELE usuário.
    """
    if not context_text or not sentence.strip():
        return 'no_support', 'sem_contexto'

    # 1. Citação de autor/obra sem lastro -> conhecimento pré-treinado (vazamento)
    autor = re.search(r'\b([A-ZÀ-Ú][A-ZÀ-Ú\u00c0-\u00da]{1,25}),\s?\d{4}', sentence)
    if autor:
        sobrenome = autor.group(1)
        if sobrenome.lower() not in context_text.lower():
            return 'no_support', 'autor_sem_lastro'

    # 1b. Dispositivo (art. N, §N, inciso X) citado que NÃO existe em NENHUM
    # fragmento do ESCOPO DO DONO -> fundamento inventado. Compara contra o escopo
    # (não só contra os docs recuperados), para não punir dispositivo válido que
    # simplesmente não foi recuperado naquela pergunta — e nunca contra outro cliente.
    dispositivos_base = _load_dispositivos_base(user_id)
    if dispositivos_base:
        for disp in _DISPOSITIVO_PATTERN.findall(sentence):
            norm = _normalize_dispositivo(disp)
            if norm and norm not in dispositivos_base:
                return 'no_support', 'dispositivo_sem_lastro'

    # 2. Cobertura de termos significativos no contexto
    tokens = re.findall(r'[a-zà-ú]{4,}', sentence.lower())
    # Remove termos muito genéricos que poluem a medida
    generic = {'contrato', 'parte', 'forma', 'valor', 'caso', 'dever', 'direito', 'pagar', 'coisa', 'sobre', 'está', 'para', 'como', 'esta', 'pode'}
    sig = [t for t in tokens if t not in generic]
    if len(sig) < 3:
        return 'supported', ''
    ctx_low = context_text.lower()
    present = sum(1 for t in set(sig) if t in ctx_low)
    ratio = present / len(set(sig))
    if ratio < 0.15:
        return 'weak', 'cobertura_baixa'
    return 'supported', ''


# Padrões de afirmação factual: números de prazo/requisito ("25 anos", "180 dias")
# e citação de dispositivo (art. N, §N, inciso X). Sentença com isso MAS sem
# citação [n] é afirmação desancorada — vira 'partial' (não confiável).
_FACTUAL_NUM_PATTERN = re.compile(r"\b(\d{1,4}\s*(?:anos?|dias?|meses?|%))\b", re.IGNORECASE)
_DISPOSITIVO_PATTERN = re.compile(
    r"\b(art(?:igo)?\.?\s*\d+|§\s*\d+|inciso\s+[IVXLCDM]+)", re.IGNORECASE
)

# --- Identidade da NORMA (lei/decreto/EC/MP) --------------------------------
# O fact-check cobria quantidade-com-unidade ("180 dias") e dispositivo
# ("art. 25"), mas não a IDENTIDADE da norma. Caso medido em 2026-10-16: o modelo
# escreveu "A Lei nº 8080/2011 regula o SUS" — o número vinha do NOME DO ARQUIVO
# (que aparece no cabeçalho de cada [DOC] do contexto) e o ano de um trecho de
# OUTRA lei ("(Incluído pela Lei nº 12.401, de 2011)"). Como cada pedaço existia
# em algum lugar do contexto, os checks por token aprovavam: `all_grounded: True`
# numa resposta errada (a Lei 8.080 é de 19/09/1990).
# Regra aqui é de PAR: número e ano precisam aparecer juntos no CONTEÚDO de um
# mesmo documento. Nome de arquivo nunca sustenta citação — se a identificação da
# norma só existe no nome do arquivo, o dado não está lastreado.
_TIPO_NORMA = (r"(?:lei(?:\s+complementar)?|decreto(?:-lei)?|emenda\s+constitucional|"
               r"ec|medida\s+provisória|mp)")
_NORMA_PATTERN = re.compile(
    rf"\b{_TIPO_NORMA}\s*n?[º°.]*\s*(\d[\d.]{{1,11}})(?:\s*[/\-]\s*(\d{{2,4}}))?",
    re.IGNORECASE,
)
# "Lei nº 8.080, de 19 de setembro de 1990" — ano na data por extenso
_NORMA_DATA_PATTERN = re.compile(
    rf"\b{_TIPO_NORMA}\s*n?[º°.]*\s*(\d[\d.]{{1,11}})[^.;]{{0,80}}?\bde\s+(\d{{4}})\b",
    re.IGNORECASE,
)


def _norm_numero(bruto: str) -> str:
    """'8.080' -> '8080' (a base grafa com ponto, o modelo costuma escrever sem)."""
    return re.sub(r"\D", "", bruto or "")


def _norm_ano(bruto: str | None) -> str | None:
    """'91' -> '1991', '19' -> '2019', '1990' -> '1990'.

    A convenção de dois dígitos é a do direito brasileiro (Lei 8.213/91); o corte
    em 30 separa as séries 19xx das 20xx sem ambiguidade nos casos reais.
    """
    if not bruto:
        return None
    numero = int(bruto)
    if len(bruto) <= 2:
        return str(1900 + numero if numero >= 30 else 2000 + numero)
    return str(numero)


def _normas_citadas(texto: str) -> list[tuple[str, str | None]]:
    """Citações de norma no texto: lista de (número normalizado, ano|None)."""
    achados: dict[str, str | None] = {}
    for m in _NORMA_PATTERN.finditer(texto or ""):
        numero = _norm_numero(m.group(1))
        achados[numero] = _norm_ano(m.group(2)) or achados.get(numero)
    for m in _NORMA_DATA_PATTERN.finditer(texto or ""):
        numero = _norm_numero(m.group(1))
        achados[numero] = achados.get(numero) or _norm_ano(m.group(2))
    return list(achados.items())


def _identidade_do_documento(doc: dict[str, Any]) -> list[tuple[str, str | None]]:
    """(número, ano) da norma que o documento É, segundo os metadados do registro.

    Diferente do conteúdo: aqui é o rótulo que o próprio pipeline fornece ao modelo
    ("Arquivo X é a Lei Y"). Citar essa identidade não é invenção — inventar é
    juntar o número de um documento com o ano lido em OUTRO.
    """
    numero = _norm_numero(str(doc.get("numero_doc") or ""))
    if numero:
        return [(numero, _norm_ano(str(doc.get("ano_doc") or "") or None))]

    nome = doc.get("file_name") or ""
    if not nome:
        return []
    try:
        from legal_parser import parse_file_name
        meta = parse_file_name(nome)
    except Exception as e:      # parser fora do ar não pode derrubar o fact-check
        logger.warning(f"Falha ao ler a identidade do arquivo {nome!r}: {e}")
        return []
    if meta.get("numero"):
        return [(_norm_numero(meta["numero"] or ""), _norm_ano(meta.get("ano")))]
    return []


def _index_normas_contexto(retrieved_docs: list[dict[str, Any]]) -> tuple[set, set]:
    """(números, pares número+ano) sustentados pelo contexto recuperado.

    Junta duas origens legítimas: o CONTEÚDO dos documentos (o par número+ano
    escrito no texto) e a IDENTIDADE de cada documento (metadado/nome do arquivo).
    O nome do arquivo não sustenta uma citação por si — mas sustenta a identidade
    daquele documento, que é o que o contexto apresenta ao modelo.
    """
    numeros: set[str] = set()
    pares: set[tuple[str, str | None]] = set()
    for doc in retrieved_docs or []:
        for numero, ano in _normas_citadas(doc.get("content") or ""):
            numeros.add(numero)
            if ano:
                pares.add((numero, ano))
        for numero, ano in _identidade_do_documento(doc):
            numeros.add(numero)
            if ano:
                pares.add((numero, ano))
    return numeros, pares


def _norma_grounding(sentence: str, numeros_ctx: set, pares_ctx: set) -> tuple[str | None, str]:
    """Status/razão das normas citadas na sentença (None = nada a apontar).

    Severidade em três níveis, do pior para o mais brando:
      - número que não existe em lugar nenhum do contexto -> 'no_support'
        ('norma_sem_lastro'): número de lei inventado.
      - número existe, mas o contexto registra OUTRO ano para ele ->
        'no_support' ('ano_incompativel'): o modelo juntou duas normas.
      - número existe, mas nenhum ano consta do contexto -> 'partial'
        ('ano_nao_consta'): não é possível verificar o ano (não há contradição).
    """
    citadas = _normas_citadas(sentence)
    if not citadas:
        return None, ''
    numeros_com_ano = {numero for numero, _ in pares_ctx}
    for numero, ano in citadas:
        if not ano:
            if numero not in numeros_ctx:
                return 'no_support', 'norma_sem_lastro'
            continue
        if (numero, ano) in pares_ctx:
            continue
        if numero not in numeros_ctx:
            return 'no_support', 'norma_sem_lastro'
        if numero not in numeros_com_ano:
            return 'partial', 'ano_nao_consta'
        return 'no_support', 'ano_incompativel'
    return None, ''


# Números por extenso — comuns em texto legal ("até quatorze anos") enquanto o
# modelo costuma responder em dígitos ("até 14 anos"). Canonicalizar os dois
# lados antes do fact-check evita falso positivo ortográfico e iguala grafias.
_EXTENSO_MAP = {
    # compostos primeiro (o padrão é montado ordenando por tamanho desc)
    'vinte e um': 21, 'vinte e uma': 21,
    'vinte e dois': 22, 'vinte e duas': 22,
    'cinquenta e cinco': 55, 'cinqüenta e cinco': 55,
    'sessenta e cinco': 65,
    'cento e oitenta': 180,
    'duzentos e quarenta': 240,
    'um': 1, 'uma': 1, 'dois': 2, 'duas': 2, 'três': 3, 'quatro': 4,
    'cinco': 5, 'seis': 6, 'sete': 7, 'oito': 8, 'nove': 9, 'dez': 10,
    'onze': 11, 'doze': 12, 'treze': 13, 'quatorze': 14, 'catorze': 14,
    'quinze': 15, 'dezesseis': 16, 'dezessete': 17,
    'dezoito': 18, 'dezenove': 19, 'dezanove': 19, 'vinte': 20,
    'trinta': 30, 'quarenta': 40, 'cinquenta': 50, 'sessenta': 60,
    'setenta': 70, 'oitenta': 80, 'noventa': 90, 'cem': 100, 'cento': 100,
    'duzentos': 200, 'trezentos': 300, 'quatrocentos': 400,
    'quinhentos': 500, 'seiscentos': 600, 'setecentos': 700,
    'oitocentos': 800, 'novecentos': 900,
}
_EXTENSO_PATTERN = re.compile(
    r"\b(" + "|".join(sorted(_EXTENSO_MAP, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)


def _canonicalizar_numeros(texto: str) -> str:
    """Troca números por extenso por dígitos ('quatorze' -> '14').

    Aplicada igualmente à sentença e ao contexto no fact-check, para que
    'vinte e um anos' (texto da lei) e '21 anos' (resposta do modelo) se
    comparem como o mesmo token canônico.
    """
    return _EXTENSO_PATTERN.sub(lambda m: str(_EXTENSO_MAP[m.group(1).lower()]), texto)


def _normalize_dispositivo(disp: str) -> str:
    """Normaliza um dispositivo para comparação: 'artigo 26' -> 'art26'.

    Iguala as grafias 'art.'/'art'/'artigo' e remove espaços, para não gerar
    falso positivo quando a sentença e o contexto usam formas diferentes.
    """
    s = re.sub(r'\s+', '', disp).lower()
    s = re.sub(r'^art(?:igo)?\.?', 'art', s)
    s = re.sub(r'^§', 'par', s)
    return s


def _has_factual_claim(sentence: str) -> bool:
    """True se a sentença contém afirmação factual verificável (número, dispositivo ou norma)."""
    return bool(_FACTUAL_NUM_PATTERN.search(sentence)
                or _DISPOSITIVO_PATTERN.search(sentence)
                or _NORMA_PATTERN.search(sentence))


def _unidades_factuais(texto: str) -> set:
    """Unidades verificáveis de um texto: números com unidade e dispositivos.

    As duas partes passam pela MESMA normalização (`num:`, `disp:`) para que a
    comparação não dependa da grafia: "artigo 9" e "Art. 9º" viram `disp:art9`.
    """
    canon = _canonicalizar_numeros(texto or "")
    unidades = {f"num:{re.sub(r'[ ]+', '', n).lower()}" for n in _FACTUAL_NUM_PATTERN.findall(canon)}
    unidades |= {f"disp:{_normalize_dispositivo(d)}" for d in _DISPOSITIVO_PATTERN.findall(canon)}
    return unidades


def _unidades_ausentes(sentenca: str, texto: str) -> list[str]:
    """Unidades que a sentença afirma e o texto NÃO contém (ordenadas)."""
    return sorted(_unidades_factuais(sentenca) - _unidades_factuais(texto))


# Recusa honesta: o modelo diz que a base não traz, em vez de responder.
#
# A recusa é uma afirmação SOBRE A BASE, não sobre o direito — então ela é
# procurada na PRIMEIRA frase, e a presença de dispositivo na frase ("…pelo art.
# 55 da Lei 8.080") não a transforma em resposta. Os dois casos medidos em
# 2026-10-16: uma recusa com dispositivo ("A base não contém informações sobre
# quais leis foram revogadas pelo art. 55") era exibida como resposta
# FUNDAMENTADA, e uma resposta concreta com um "não há" de passagem era lida como
# recusa (por isso "não há" sozinho não entra no padrão).
_RECUSA_PATTERN = re.compile(
    r"(n[ãa]o[ ]+(?:se[ ]+)?encontr|"                      # não encontrei/encontrado/encontrar
    r"n[ãa]o[ ]+(?:localizei|localiz|consta|cont[ée]m|traz|especific|informa|est[áa][ ]+indicad|"
    r"foi[ ]+poss[íi]vel|h[áa][ ]+resposta)|"
    r"(?:base|material|trechos?|contexto|documentos?|acervo)[ ]+(?:recuperad[oa]s?[ ]+)?n[ãa]o|"
    r"sem[ ]+lastro|aus[êe]ncia[ ]+de)",
    re.IGNORECASE,
)


def _parece_recusa(texto: str) -> bool:
    """True se a resposta é uma RECUSA, não uma afirmação de conteúdo.

    Recusar é o comportamento desejado quando a base não responde — por isso a
    recusa não é defeito: a interface a canonicaliza. Olhar só a PRIMEIRA frase
    evita o erro inverso (uma resposta concreta que mencione "não há" no meio
    continua sendo resposta), às custas de tratar como recusa a resposta mista que
    começa declarando ausência e depois transcreve um trecho — o `agent` dá a
    segunda chance quando o portão de suficiência diz que o material responde.
    """
    if not texto or not texto.strip():
        return False
    frases = _split_sentences(texto.strip())
    primeira = frases[0] if frases else texto.strip()
    return bool(_RECUSA_PATTERN.search(primeira))


def _factual_claim_grounded(sentence: str, context_text: str) -> bool:
    """True se os fatos da sentença (números/dispositivos) aparecem no contexto.

    Evita falso positivo: uma sentença que diz "carência de 180 dias" SEM tag
    [n] só é desancorada se "180" NÃO aparecer no contexto recuperado. Se
    aparecer, o conteúdo está lastreado (só faltou a citação explícita).
    """
    ctx_norm = re.sub(r'\s+', '', _canonicalizar_numeros(context_text)).lower()
    frase_canon = _canonicalizar_numeros(sentence)
    for num in _FACTUAL_NUM_PATTERN.findall(frase_canon):
        if num and re.sub(r'\s+', '', num).lower() not in ctx_norm:
            return False
    for disp in _DISPOSITIVO_PATTERN.findall(frase_canon):
        if re.sub(r'\s+', '', disp).lower() not in ctx_norm:
            return False
    return True


def _classificar_sentenca(sentence: str, valid_refs: set, context_text: str = '',
                          conteudo_citado: dict | None = None) -> tuple[str, str]:
    """Classifica uma sentença como suportada (determinístico, sem LLM).

    Detecta citações fabricadas/inválidas E afirmações factuais desancoradas:
    uma sentença com número de prazo/requisito ou dispositivo que NÃO aparece no
    contexto recuperado, e sem citação [n], recebe 'partial' (antes passava como
    'supported', deixando a alucinação "limpa" escapar). Se o fato aparece no
    contexto, permanece 'supported' (só faltou a tag — não é alucinação).

    ``conteudo_citado`` ({n: conteúdo do [DOC n]}) muda o critério de "contexto"
    para a sentença COM citação: o dado afirmado tem de estar no fragmento que a
    própria sentença cita — citar [1] e afirmar o dado que está no [3] não
    fundamenta nada, porque o advogado clica em [1] e não encontra. Sem esse
    parâmetro, o critério continua sendo o contexto agregado (compatível com a
    API anterior).
    """
    stripped = sentence.strip()
    if not stripped:
        return 'supported', ''
    low = stripped.lower()

    # Lista de fontes final e títulos — não são afirmações de conteúdo
    if low.startswith('fontes:') or low.startswith('fonte:') or low.startswith('#'):
        return 'supported', ''
    # Transições/negações/introduções curtas sem conteúdo factual
    if len(stripped) < 40 and not _extract_citations(stripped):
        return 'supported', ''

    citations = _extract_citations(stripped)
    if not citations:
        # Frase explicativa sem [n]: síntese fluida é OK. Mas se afirma fato
        # concreto (prazo/requisito/dispositivo) que NÃO está no contexto, é
        # afirmação desancorada.
        if _has_factual_claim(stripped) and context_text and not _factual_claim_grounded(stripped, context_text):
            return 'partial', 'afirmacao_desancorada'
        return 'supported', ''

    invalid = [c for c in citations if c not in valid_refs]
    if invalid:
        if len(invalid) == len(citations):
            return 'no_support', 'citacao_inexistente'
        return 'partial', 'citacao_parcial'

    # Citação válida: o fragmento citado precisa conter o que a sentença afirma.
    if conteudo_citado:
        usados = [conteudo_citado[n] for n in citations if n in conteudo_citado]
        texto_citado = ' '.join(u for u in usados if u)
        if texto_citado and _unidades_ausentes(stripped, texto_citado):
            return 'partial', 'lastro_fora_do_citado'
    return 'supported', ''


def _classify_sentence_grounded(sentence: str, valid_refs: set, context_text: str = '') -> str:
    """Status da sentença (API anterior, sem motivo). Ver `_classificar_sentenca`."""
    return _classificar_sentenca(sentence, valid_refs, context_text)[0]



# Preâmbulos/despedidas de cortesia não são afirmações de conteúdo: não devem
# passar pelo groundedness (gerariam falso positivo de cobertura_baixa).
_BOILERPLATE_PATTERNS = re.compile(
    r'(como assistente|estou aqui para ajudar|espero (que|ter)|sinta-se à vontade|'
    r'a pergunta é (muito )?interessante|excelente pergunta|muito obrigado|'
    r'se (você )?tiver (mais )?alguma d[uú]vida|à disposição|bons estudos|'
    r'posso (ajudar|esclarecer)|vou (ajudar|analisar)|qualquer d[uú]vida)',
    re.IGNORECASE,
)


def _is_boilerplate(sentence: str) -> bool:
    """True se a sentença é cortesia/transição, não uma afirmação de conteúdo."""
    s = sentence.strip()
    if not s:
        return True
    low = s.lower()
    if low.startswith(('fontes:', 'fonte:', '#')):
        return True
    # Frase curta sem citação e sem fato concreto = transição/introdução
    if len(s) < 40 and not _extract_citations(s) and not _has_factual_claim(s):
        return True
    # Cortesia explícita, mesmo em frase longa
    if _BOILERPLATE_PATTERNS.search(s):
        return True
    return False


def _veredito_da_resposta(answer: str, result: dict) -> tuple[str, str]:
    """Veredito da resposta inteira, para o `agent` decidir o que EXIBIR.

    A ordem é a da gravidade do dano em produto jurídico:

    1. `sem_lastro` — alguma sentença cita norma/dispositivo/autor que não existe
       no material. Dano grave: número de lei inventado. Não se exibe.
    2. `recusou` — a resposta é uma recusa ("a base não contém"). É o
       comportamento DESEJADO quando a base não responde: a interface a
       canonicaliza, não a trata como resposta.
    3. `parcial` — resposta com unidades verificáveis mas com ressalva
       (cobertura lexical baixa, ano que o material não registra, citação que não
       é a do dado afirmado) **ou** resposta sem nenhuma unidade verificável
       (`sem_fonte`). `sem_fonte` NÃO bloqueia: medido, uma resposta CORRETA e sem
       citação era descartada, a reescrita desistia e o advogado recebia recusa no
       lugar da resposta que já existia (d2 do mini-quiz). Vira aviso na tela.
    4. `fundamentada` — sem ressalva.
    """
    if not (answer or "").strip():
        return 'sem_lastro', 'resposta_vazia'
    if result['no_support']:
        motivos = [f.get('reason') for f in result['flagged_sentences']
                   if f['status'] == 'no_support' and f.get('reason')]
        return 'sem_lastro', motivos[0] if motivos else 'sem_lastro'
    if _parece_recusa(answer):
        return 'recusou', ''
    if not result['citadas'] and not _unidades_factuais(answer):
        return 'parcial', 'sem_fonte'
    if result['partial']:
        motivos = [f.get('reason') for f in result['flagged_sentences']
                   if f['status'] == 'partial' and f.get('reason')]
        return 'parcial', motivos[0] if motivos else 'parcial'
    return 'fundamentada', ''


def _fact_check_answer(answer: str, retrieved_docs: list[dict[str, Any]],
                       user_id: int | None = None) -> dict[str, Any]:
    """Verifica de forma estruturada se a resposta está apoiada nos docs recuperados.

    Núcleo determinístico (sem chamada LLM extra): divide em sentenças, verifica as
    citações [n] contra os DOCs disponíveis e confere o PAR número+ano das normas
    (ADR-0007). Sentença com citação válida é conferida contra o conteúdo do
    fragmento QUE ELA CITA (`lastro_fora_do_citado`), não contra o contexto
    agregado.

    O retorno traz, além das contagens, o `veredito` da resposta inteira
    (`fundamentada` · `parcial` · `recusou` · `sem_lastro`) e o `motivo` — é com
    isso que o `agent` decide se exibe a resposta, se pede reescrita ou se
    apresenta a recusa canônica. A checagem de suficiência do contexto (se a base
    responde) é feita antes de gerar, em `agent._contexto_suficiente`.

    Retorno:
      {
        'enabled': bool,
        'total_sentences': int,
        'supported': int,
        'partial': int,
        'no_support': int,
        'flagged_sentences': [{'n': N, 'text': str, 'status': str, 'reason': str,
                               'invalid_citations': [int]}],
        'all_grounded': bool,
        'citadas': [int],        # refs [n] que a resposta usa de fato
        'veredito': str,
        'motivo': str
      }
    """
    result = {
        'enabled': FACT_CHECK_ENABLED,
        'total_sentences': 0,
        'supported': 0,
        'partial': 0,
        'no_support': 0,
        'flagged_sentences': [],
        'all_grounded': True,
        'citadas': [],
        'veredito': 'fundamentada',
        'motivo': '',
    }
    if not FACT_CHECK_ENABLED:
        return result

    # Rótulos [n] válidos = índices 1..N dos docs recuperados (o build_context
    # rotula [DOC 1], [DOC 2]... com esses mesmos índices).
    valid_refs = set(range(1, len(retrieved_docs) + 1))
    # Texto concatenado dos docs p/ checagem de lastro semântico (groundedness)
    context_text = ' '.join((d.get('content') or '') for d in retrieved_docs)
    # Conteúdo de CADA fragmento, pelo índice do [DOC n]: é o que permite conferir
    # o lastro no fragmento citado em vez do agregado.
    conteudo_citado = {i: (doc.get('content') or '')
                       for i, doc in enumerate(retrieved_docs or [], start=1)}

    sentences = _split_sentences(answer)
    result['total_sentences'] = len(sentences)

    # Identidade das normas citadas NO CONTEÚDO dos documentos recuperados
    # (pares número+ano). O nome do arquivo não entra: não é lastro.
    numeros_ctx, pares_ctx = _index_normas_contexto(retrieved_docs)

    for n, sent in enumerate(sentences, start=1):
        stripped_sent = sent.strip()
        is_boilerplate = _is_boilerplate(stripped_sent)

        # 1. Norma citada (lei/decreto/EC) tem de casar com o contexto. Roda
        #    antes e, quando aponta erro, prevalece: é o dano mais grave de um
        #    produto jurídico (número/ano de lei trocado).
        status, reason = (None, '')
        if not is_boilerplate:
            status, reason = _norma_grounding(sent, numeros_ctx, pares_ctx)

        # 2. Sem impedimento da checagem de norma, segue a classificação normal.
        if status is None:
            status, reason = _classificar_sentenca(sent, valid_refs, context_text, conteudo_citado)
            if not is_boilerplate:
                # A checagem estrutural ([n]) sozinha não pega vazamento de
                # conhecimento interno (ex.: transcrever doutrina que não está nos
                # docs). Aplica o groundedness semântico para reforçar/ajustar.
                sem_status, sem_reason = _check_semantic_grounding(sent, context_text, user_id)
                if sem_status == 'no_support' and status in ('supported', 'partial'):
                    status, reason = 'no_support', sem_reason
                elif sem_status == 'weak' and status == 'supported':
                    status, reason = 'partial', sem_reason

        if status == 'supported':
            result['supported'] += 1
        elif status == 'partial':
            result['partial'] += 1
            result['all_grounded'] = False
        else:
            result['no_support'] += 1
            result['all_grounded'] = False
        if status != 'supported':
            result['flagged_sentences'].append({
                'n': n,
                'text': sent,
                'status': status,
                'reason': reason,
                'invalid_citations': [c for c in _extract_citations(sent) if c not in valid_refs],
            })

    result['citadas'] = sorted({c for sent in sentences for c in _extract_citations(sent)
                                if c in valid_refs})
    result['veredito'], result['motivo'] = _veredito_da_resposta(answer, result)
    return result

