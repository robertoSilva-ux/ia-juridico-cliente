"""Retorno de ações da interface, e o componente de indexação de PDF.

Mora fora do `main.py` por dois motivos:

1. **`st.success(...)` seguido de `st.rerun()` é invisível.** O rerun descarta a
   renderização da execução atual, então a mensagem some no mesmo instante em que
   aparece — era o que fazia a indexação parecer silenciosa: a única evidência de
   sucesso era a linha nova na tabela de documentos. `flash()` guarda a mensagem
   no `session_state` e `render_flash()` a mostra na execução seguinte, uma vez.
2. **`main.py` é um script com efeitos no import** (executa o Streamlit), então
   nada dele é importável por teste. Este módulo é.

Traz também a montagem da RESPOSTA do chat (`montar_resposta`), pela mesma razão:
o veredito de lastro e a recusa honesta são comportamento de produto e precisam ser
testáveis fora do runtime do Streamlit.
"""
from __future__ import annotations

import os
import tempfile

import streamlit as st
from config import EMBEDDING_MODEL, OLLAMA_BASE_URL
from embeddings import NomicOllamaEmbeddings
from ingest import ingest_document

_PENDENTE = "_flash_pendente"

#: Como o veredito do fact-check aparece para o advogado. O que NÃO pode é a
#: resposta com lastro não verificado chegar à tela sem aviso: era o estado até
#: aqui — o `agent` calculava o veredito e o `main.py` o descartava.
_RESUMO_VEREDITO = {
    'ok': "✅ Lastro verificado: {frases} frase(s) conferida(s) contra os trechos recuperados.",
    'parcial': ("⚠️ Lastro com ressalva em {sinalizadas} de {frases} frase(s): {motivo}. "
                "Confira o trecho citado antes de usar."),
    'recusada': None,
    'erro': None,
}

#: O motivo vem em código (`sem_fonte`, `ano_nao_consta`…) porque é ele que o log e
#: os testes usam. O advogado precisa da frase: o código vai entre parênteses.
_MOTIVO_RESSALVA = {
    'sem_fonte': "a resposta não cita o trecho de onde vem cada dado, então não deu para conferir",
    'lastro_fora_do_citado': "o dado afirmado não está no trecho que a resposta cita",
    'ano_nao_consta': "o material recuperado não registra o ano da norma citada",
    'cobertura_baixa': "pouca sobreposição entre o texto da resposta e os trechos recuperados",
    'citacao_parcial': "parte das citações não corresponde a um trecho recuperado",
    'afirmacao_desancorada': "há afirmação concreta que não aparece nos trechos recuperados",
}

_ORIGEM_SEM_SIMILARIDADE = {
    'dispositivo': "busca por dispositivo (similaridade não calculada)",
    'keyword': "busca por palavra-chave (similaridade não calculada)",
}


def _linhas_de_fontes(sources) -> list[str]:
    """Uma linha por fonte: rótulo, origem e se a resposta a citou.

    A similaridade só aparece quando FOI medida. Resultado de busca por
    dispositivo/keyword não tem distância, e a interface antiga calculava
    `1 - 0.0` e escrevia "100,00%" — número inventado num produto jurídico.
    """
    linhas = []
    for fonte in sources or []:
        ref = fonte.get('ref')
        rotulo = fonte.get('source_label') or fonte.get('file_name') or "Documento s/ nome"
        prefixo = f"[{ref}] " if ref else ""
        distancia = fonte.get('distance')
        origem = fonte.get('origem') or 'semantico'
        if distancia is None:
            medida = _ORIGEM_SEM_SIMILARIDADE.get(origem, "similaridade não calculada")
        else:
            medida = f"similaridade {1 - float(distancia):.0%}"
        marca = "citada na resposta" if fonte.get('citada') else "recuperada, não citada"
        # R-24: o trecho pode vir do PREÂMBULO do documento (capa, apresentação, lista das
        # leis que alteraram a norma, comentário). Sem dizer isso, a interface apresentaria
        # comentário de apostila como se fosse texto de lei.
        papel = " · trecho de comentário, não é dispositivo" \
            if (fonte.get('tipo_trecho') or 'dispositivo') == 'preambulo' else ""
        linhas.append(f"**{prefixo}{rotulo}** — {medida} · {marca}{papel}")
    return linhas


def montar_resposta(result: dict) -> list[dict]:
    """Blocos da resposta do chat, a partir do retorno de `agent.get_response`.

    Devolve blocos em vez de desenhar: é o que permite testar (e revisar) o
    comportamento de exibição sem o runtime do Streamlit. `status` decide a forma:

    - `ok`        → a resposta + confirmação do lastro conferido
    - `parcial`   → a resposta + aviso de ressalva (o veredito não é silencioso)
    - `recusada`  → a recusa canônica em destaque, com os trechos recuperados
    - `erro`      → a mensagem de falha

    A recusa NÃO é apresentada como resposta: era exatamente o defeito medido
    (não-resposta exibida com 15 fontes e selo verde).
    """
    status = (result or {}).get('status', 'ok')
    texto = (result or {}).get('answer') or ''
    fact = (result or {}).get('fact_check') or {}
    fontes = (result or {}).get('sources') or []
    blocos: list[dict] = []

    if status == 'erro':
        blocos.append({'tipo': 'error', 'texto': texto})
    elif status == 'recusada':
        blocos.append({'tipo': 'warning', 'texto': texto})
    else:
        blocos.append({'tipo': 'markdown', 'texto': texto})
        if status == 'parcial':
            motivo = result.get('motivo') or 'parcial'
            blocos.append({'tipo': 'warning', 'texto': _RESUMO_VEREDITO['parcial'].format(
                sinalizadas=fact.get('no_support', 0) + fact.get('partial', 0),
                frases=fact.get('total_sentences', 0),
                motivo=f"{_MOTIVO_RESSALVA.get(motivo, motivo)} ({motivo})",
            )})
        elif fact.get('enabled', True):
            blocos.append({'tipo': 'caption', 'texto': _RESUMO_VEREDITO['ok'].format(
                frases=fact.get('total_sentences', 0))})

    if fontes:
        titulo = ("📚 Fontes recuperadas (nenhuma sustenta a resposta)"
                  if status == 'recusada' else "📚 Fontes Citadas")
        blocos.append({'tipo': 'expander', 'titulo': titulo, 'linhas': _linhas_de_fontes(fontes)})
    return blocos


def render_resposta(result: dict) -> None:
    """Desenha os blocos de `montar_resposta` na página."""
    for bloco in montar_resposta(result):
        tipo = str(bloco.get('tipo', 'markdown'))
        if tipo == 'expander':
            with st.expander(bloco.get('titulo', 'Fontes')):
                for linha in bloco.get('linhas', []):
                    st.write(linha)
            continue
        desenhar = getattr(st, tipo, None)
        if not callable(desenhar):            # tipo desconhecido não pode sumir com o texto
            desenhar = st.markdown
        desenhar(bloco.get('texto', ''))



def flash(mensagem: str, tipo: str = "success") -> None:
    """Registra a mensagem para aparecer na PRÓXIMA execução.

    Chame imediatamente antes de `st.rerun()`; `tipo` é o nome do aviso do
    Streamlit (`success`, `error`, `warning`, `info`).
    """
    st.session_state[_PENDENTE] = {"mensagem": mensagem, "tipo": tipo}


def render_flash() -> None:
    """Exibe (uma única vez) a mensagem registrada por `flash()`.

    Chamar já autenticado, antes do roteamento de páginas: assim a confirmação
    de uma ação aparece em qualquer página, e não só naquela que a disparou.
    """
    pendente = st.session_state.pop(_PENDENTE, None)
    if not pendente:
        return

    tipo = str(pendente.get("tipo", "info"))
    aviso = getattr(st, tipo, None)
    if not callable(aviso):               # tipo desconhecido não pode engolir a mensagem
        aviso = st.info
    aviso(pendente.get("mensagem", ""))


def render_indexacao_pdf(uploaded_file, *, user_id, scope):
    """Indexa UM PDF com progresso em duas fases e devolve `(mensagem, tipo)`.

    Devolve em vez de exibir para o chamador poder usar `flash()` + `st.rerun()`
    sem perder o retorno. O número de fragmentos vem de `ingest_document`, que
    reporta o que foi realmente gravado — a interface não afirma sucesso por
    conta própria.
    """
    nome = uploaded_file.name
    embeddings = NomicOllamaEmbeddings(model=EMBEDDING_MODEL, base_url=OLLAMA_BASE_URL)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
        tmp_file.write(uploaded_file.getbuffer())
        caminho = tmp_file.name

    try:
        with st.status(f"Indexando `{nome}`...", expanded=True) as statuso:
            barra = st.progress(0.0)
            detalhe = st.empty()

            def _progresso(fracao: float) -> None:
                fracao = min(max(fracao, 0.0), 1.0)
                barra.progress(fracao)
                if fracao < 0.5:
                    fase = "extraindo e fragmentando o PDF"
                else:
                    fase = "gerando embeddings e gravando"
                detalhe.caption(f"{fase} — {int(fracao * 100)}%")

            try:
                indexados = ingest_document(
                    caminho,
                    embeddings,
                    nome,
                    owner_id=user_id,
                    scope=scope,
                    progress_cb=_progresso,
                )
            except Exception as e:                      # noqa: BLE001 — a UI mostra o erro, não morre
                statuso.update(label=f"❌ Falha ao indexar `{nome}`", state="error")
                return f"Falha ao indexar '{nome}': {e}", "error"

            if not indexados:
                # Dois casos chegam aqui com o mesmo número: PDF sem texto
                # extraível (escaneado) e dedup (tudo já estava na base). Nenhum
                # dos dois é sucesso, e a versão anterior dizia "indexado com
                # sucesso" para ambos (P1-6).
                statuso.update(
                    label=f"⚠️ Nada novo de `{nome}`", state="complete", expanded=False
                )
                return (
                    f"'{nome}': nada foi indexado — ou o PDF não tem texto extraível "
                    f"(digitalizado/escaneado) ou os fragmentos já estavam na base.",
                    "warning",
                )

            statuso.update(
                label=f"✅ `{nome}` — {indexados} fragmento(s) indexado(s)",
                state="complete",
                expanded=False,
            )
            return f"'{nome}' indexado: {indexados} fragmento(s) no escopo {scope}.", "success"
    finally:
        if os.path.exists(caminho):
            os.remove(caminho)
