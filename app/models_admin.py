"""Tela administrativa para gerenciar os modelos de IA do Ollama.

Renderizada dentro da aba "Modelos de IA" do Painel Admin (main.py).
Cobre o CRUD sobre a coleção de modelos instalados no servidor Ollama:
  - Listar/status (nome, tamanho, família, parâmetros, quantização, carga)
  - Baixar novo (pull) com barra de progresso
  - Atualizar tag para a versão mais recente (re-pull)
  - Carregar (warmup) e descarregar (unload) para controlar memória/GPU
  - Remover (delete) um modelo instalado
"""
import streamlit as st

import ollama_utils as ou


def _render_running(models_installed, running_details):
    """Painel resumo: memória/VRAM em uso pelos modelos carregados."""
    with st.expander("🧠 Modelos carregados em memória (VRAM/RAM)", expanded=False):
        if not running_details:
            st.info("Nenhum modelo carregado no momento. Use 'Carregar' em um modelo para aquecê-lo.")
            return
        for rm in running_details:
            nome = rm["name"]
            vram = ou.human_size(rm.get("size_vram"))
            total = ou.human_size(rm.get("size"))
            inst = next((m for m in models_installed if m["name"] == nome), None)
            fam = inst["family"] if inst else "—"
            st.markdown(
                f"- **{nome}** "
                f"`{vram}` VRAM / `{total}` RAM — família `{fam}`"
            )
        st.caption("Um modelo descarregado libera memória/VRAM para outros.")


def _render_installed_table(models_installed, installed_names, running_names):
    """Tabela + ações por modelo instalado."""
    st.write("### Modelos Instalados")
    if not models_installed:
        st.info("Nenhum modelo instalado no Ollama ainda.")
        return

    # Cabeçalho
    cols = st.columns([3, 1, 1.3, 1.2, 1.2, 2.6])
    for c, h in zip(cols, ["Modelo", "Tamanho", "Família", "Parâmetros", "Quant.", "Ações"], strict=True):
        c.markdown(f"**{h}**")

    for m in models_installed:
        nome = m.get("name") or "?"
        is_running = nome in running_names
        col1, col2, col3, col4, col5, col6 = st.columns([3, 1, 1.3, 1.2, 1.2, 2.6])

        with col1:
            estado = "🟢" if is_running else "⚪"
            st.markdown(f"{estado} `{nome}`")
        with col2:
            st.write(ou.human_size(m.get("size")))
        with col3:
            st.write(m.get("family") or "—")
        with col4:
            st.write(m.get("parameter_size") or "—")
        with col5:
            st.write(m.get("quantization_level") or "—")
        with col6:
            # Ações em mini-colunas para não estourar largura
            a1, a2, a3 = st.columns(3)
            key = f"m_{nome}"
            if is_running:
                if a1.button("⏹", key=f"stop_{key}", help="Descarregar da memória"):
                    ok, msg = ou.stop_model(nome)
                    st.success(msg) if ok else st.error(msg)
                    st.rerun()
            else:
                if a1.button("▶️", key=f"load_{key}", help="Carregar na memória (warmup)"):
                    ok, msg = ou.warmup_model(nome)
                    st.success(msg) if ok else st.error(msg)
                    st.rerun()
            if a2.button("🔄", key=f"pull_{key}", help="Atualizar para a versão mais recente da tag"):
                _run_pull(nome, is_update=True)
            if a3.button("🗑️", key=f"del_{key}", help="Remover modelo"):
                st.session_state[f"confirm_del_{key}"] = True

            # Confirmação de remoção via form
            if st.session_state.get(f"confirm_del_{key}", False):
                with st.form(f"form_del_{key}"):
                    st.warning(f"Remover **{nome}**? Esta ação não pode ser desfeita.")
                    c1, c2 = st.columns(2)
                    confirm = c1.form_submit_button("⚠️ Confirmar remoção")
                    cancel = c2.form_submit_button("Cancelar")
                    if confirm:
                        ok, msg = ou.delete_model(nome)
                        if ok:
                            st.success(f"Modelo '{nome}' removido.")
                        else:
                            st.error(msg)
                        st.session_state.pop(f"confirm_del_{key}", None)
                        st.rerun()
                    if cancel:
                        st.session_state.pop(f"confirm_del_{key}", None)
                        st.rerun()


def _run_pull(model_name, is_update=False):
    """Executa pull (download/atualização) com barra de progresso."""
    label = f"Atualizando `{model_name}`..." if is_update else f"Baixando `{model_name}`..."
    with st.status(label, expanded=True) as status:
        bar = st.progress(0.0)
        txt = st.empty()

        def _cb(pct, msg_state):
            if pct is not None:
                bar.progress(min(pct, 1.0))
            txt.caption(msg_state or "")

        ok, msg = ou.pull_model_blocking(model_name, progress_cb=_cb)
        bar.progress(1.0)
        if is_update and ok:
            status.update(label=f"✅ `{model_name}` atualizado!", state="complete", expanded=False)
        elif ok:
            status.update(label=f"✅ `{model_name}` baixado!", state="complete", expanded=False)
        else:
            status.update(label=f"❌ Falha ao baixar `{model_name}`", state="error", expanded=True)
        if not ok:
            st.error(msg)
    st.success(msg) if ok else None
    if ok:
        st.rerun()


def render():
    """Ponto de entrada da aba 'Modelos de IA' do Painel Admin."""
    st.header("🤖 Gerenciar Modelos de IA (Ollama)")

    if not ou.is_ollama_connected():
        st.error("🔴 Ollama não está respondendo. Verifique se o serviço está no ar.")
        st.caption("Use `docker compose logs ollama` para diagnosticar.")
        return

    models_installed = ou.list_models(detailed=True)
    installed_names = {m["name"] for m in models_installed}
    running_names = set(ou.get_running_models())
    running_details = ou.get_running_details()

    # Ação rápida + download de novo modelo
    with st.expander("➕ Baixar Novo Modelo", expanded=False):
        st.caption("Ex.: `llama3.1:8b`, `mistral`, `phi3:mini`, `nomic-embed-text`.")
        new_model = st.text_input("Nome do modelo (tag) no Ollama Hub", placeholder="ex.: llama3.1:8b", key="new_model_input")
        baixar = st.button("⬇️ Baixar Modelo")
        if baixar:
            if not new_model.strip():
                st.error("Informe o nome do modelo.")
            else:
                _run_pull(new_model.strip().lower())

    _render_running(models_installed, running_details)
    st.divider()
    _render_installed_table(models_installed, installed_names, running_names)
    st.caption("🟢 = modelo carregado em memória · ⚪ = apenas instalado (não carregado).")
