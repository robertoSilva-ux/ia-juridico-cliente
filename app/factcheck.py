"""Fact-check e groundedness pós-geração.

Extraído de agent.py na refatoração (2026-09-25). Mantém a API pública original.
Funções: _split_sentences, _extract_citations, _load_dispositivos_base,
invalidate_dispositivos_cache, _check_semantic_grounding, _canonicalizar_numeros,
_normalize_dispositivo, _has_factual_claim, _factual_claim_grounded,
_classify_sentence_grounded, _is_boilerplate, _fact_check_answer.
"""
import logging
import re
from typing import Any

from config import FACT_CHECK_ENABLED
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
    """Extrai os números de citação [n] citados em uma sentença."""
    return [int(n) for n in re.findall(r'\[(\d+)\]', sentence)]


# Cache, carregado 1x, dos dispositivos (art. N / §N / inciso X) que EXISTEM na
# base inteira. Comparar contra só os docs recuperados gerava falso positivo:
# um dispositivo válido pode simplesmente não ter sido recuperado naquela
# pergunta. O cache é preenchido sob demanda e limpo quando a base muda.
_DISPOSITIVOS_BASE_CACHE: set | None = None


def _load_dispositivos_base() -> set:
    """Carrega (e memoiza) os dispositivos normalizados de toda a base.

    Retorna um set de chaves normalizadas (ex.: 'art42', 'par3'). Em caso de
    falha de BD, retorna set vazio — degrada para 'não valida', evitando
    marcar tudo como alucinação quando a base está inacessível.
    """
    global _DISPOSITIVOS_BASE_CACHE
    if _DISPOSITIVOS_BASE_CACHE is not None:
        return _DISPOSITIVOS_BASE_CACHE
    encontrados = set()
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT content FROM documents WHERE content IS NOT NULL")
                for (content,) in cur:
                    for disp in _DISPOSITIVO_PATTERN.findall(content or ''):
                        encontrados.add(_normalize_dispositivo(disp))
    except Exception as e:
        logger.warning(f"Falha ao carregar dispositivos da base (validação desativada): {e}")
        return set()
    _DISPOSITIVOS_BASE_CACHE = encontrados
    logger.info(f"Cache de dispositivos da base: {len(encontrados)} entradas")
    return encontrados


def invalidate_dispositivos_cache() -> None:
    """Invalida o cache de dispositivos (chamar após reindexar/ingerir docs)."""
    global _DISPOSITIVOS_BASE_CACHE
    _DISPOSITIVOS_BASE_CACHE = None


def _check_semantic_grounding(sentence: str, context_text: str) -> tuple[str, str]:
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
    # chunk da base -> fundamento inventado. Compara contra a base inteira (não
    # só os docs recuperados), para não punir dispositivo válido só não-recuperado.
    dispositivos_base = _load_dispositivos_base()
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
    """True se a sentença contém afirmação factual verificável (número ou dispositivo)."""
    return bool(_FACTUAL_NUM_PATTERN.search(sentence) or _DISPOSITIVO_PATTERN.search(sentence))


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


def _classify_sentence_grounded(sentence: str, valid_refs: set, context_text: str = '') -> str:
    """Classifica uma sentença como suportada (determinístico, sem LLM).

    Detecta citações fabricadas/inválidas E afirmações factuais desancoradas:
    uma sentença com número de prazo/requisito ou dispositivo que NÃO aparece no
    contexto recuperado, e sem citação [n], recebe 'partial' (antes passava como
    'supported', deixando a alucinação "limpa" escapar). Se o fato aparece no
    contexto, permanece 'supported' (só faltou a tag — não é alucinação).
    """
    stripped = sentence.strip()
    if not stripped:
        return 'supported'
    low = stripped.lower()

    # Lista de fontes final e títulos — não são afirmações de conteúdo
    if low.startswith('fontes:') or low.startswith('fonte:') or low.startswith('#'):
        return 'supported'
    # Transições/negações/introduções curtas sem conteúdo factual
    if len(stripped) < 40 and not _extract_citations(stripped):
        return 'supported'

    citations = _extract_citations(stripped)
    if not citations:
        # Frase explicativa sem [n]: síntese fluida é OK. Mas se afirma fato
        # concreto (prazo/requisito/dispositivo) que NÃO está no contexto, é
        # afirmação desancorada.
        if _has_factual_claim(stripped) and context_text and not _factual_claim_grounded(stripped, context_text):
            return 'partial'
        return 'supported'

    invalid = [c for c in citations if c not in valid_refs]
    if not invalid:
        return 'supported'
    if len(invalid) == len(citations):
        return 'no_support'
    return 'partial'


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


def _fact_check_answer(answer: str, retrieved_docs: list[dict[str, Any]]) -> dict[str, Any]:
    """Verifica de forma estruturada se a resposta está apoiada nos docs recuperados.

    Núcleo determinístico (sem chamada LLM extra): divide em sentenças e verifica
    as citações [n] contra os DOCs disponíveis. Detecta citações fabricadas
    (alucinação estrutural) e afirmações sem fonte. O resultado é exposto para a
    UI exibir um aviso e, se FACT_CHECK_LLM_ENABLED, sentenças 'no_support' são
    sinalizadas para reescrita/remoção.

    Retorno:
      {
        'enabled': bool,
        'total_sentences': int,
        'supported': int,
        'partial': int,
        'no_support': int,
        'flagged_sentences': [{'n': N, 'text': str, 'status': str, 'invalid_citations': [int]}],
        'all_grounded': bool
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
    }
    if not FACT_CHECK_ENABLED:
        return result

    # Rótulos [n] válidos = índices 1..N dos docs recuperados (o build_context
    # rotula [DOC 1], [DOC 2]... com esses mesmos índices).
    valid_refs = set(range(1, len(retrieved_docs) + 1))
    # Texto concatenado dos docs p/ checagem de lastro semântico (groundedness)
    context_text = ' '.join((d.get('content') or '') for d in retrieved_docs)

    sentences = _split_sentences(answer)
    result['total_sentences'] = len(sentences)

    for n, sent in enumerate(sentences, start=1):
        status = _classify_sentence_grounded(sent, valid_refs, context_text)
        reason = ''
        # Só checa groundedness semântico em sentenças com conteúdo factual ou
        # citação — frases curtas de cortesia ("A pergunta é interessante!") não
        # são afirmações e gerariam falso positivo de cobertura_baixa.
        stripped_sent = sent.strip()
        is_boilerplate = _is_boilerplate(stripped_sent)
        if not is_boilerplate:
            # A checagem estrutural ([n]) sozinha não pega vazamento de
            # conhecimento interno (ex.: transcrever doutrina que não está nos
            # docs). Aplica o groundedness semântico para reforçar/ajustar.
            sem_status, sem_reason = _check_semantic_grounding(sent, context_text)
            if sem_status == 'no_support' and status in ('supported', 'partial'):
                status = 'no_support'
                reason = sem_reason
            elif sem_status == 'weak' and status == 'supported':
                status = 'partial'
                reason = sem_reason

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

    return result

