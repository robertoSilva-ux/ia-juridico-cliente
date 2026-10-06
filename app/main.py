import os
import tempfile

import streamlit as st
import streamlit_authenticator as stauth
from langchain_core.messages import AIMessage, HumanMessage

import ollama_utils
from agent import get_response, set_llm_model
from audit import count_audit_logs, get_audit_logs, get_unique_users_from_audit
from auth import (
    add_user,
    get_all_users_for_auth,
    get_system_setting,
    get_user_count,
    set_system_setting,
    update_password,
)
from config import OLLAMA_BASE_URL
from embeddings import NomicOllamaEmbeddings
from gpu_check import check_gpu, format_gpu_status
from ingest import process_pdf, store_in_postgres
from manage import delete_document, list_documents, update_document_scope

# Configuração da página deve ser a primeira chamada Streamlit
st.set_page_config(page_title="Assistente Jurídico - Legaliz.ai", layout="wide")

# Forçar o atributo lang do HTML para pt-br de forma persistente
# MutationObserver reage INSTANTANEAMENTE a qualquer mudança no atributo lang,
# resolvendo o bug do corretor ortográfico sublinhar texto em português.
st.components.v1.html(
    """
    <script>
        (function() {
            var LANG = 'pt-br';
            function fixLang() {
                var targets = [window.document.documentElement, window.parent.document.documentElement];
                targets.forEach(function(target) {
                    if (target && target.lang !== LANG) {
                        target.lang = LANG;
                        target.setAttribute('lang', LANG);
                    }
                });
            }
            // Aplica imediatamente
            fixLang();
            // Cria um MutationObserver que monitora o atributo 'lang'
            // e corrige no momento exato em que o Streamlit tentar resetar
            var observer = new MutationObserver(function(mutations) {
                mutations.forEach(function(m) {
                    if (m.attributeName === 'lang' && m.target.lang !== LANG) {
                        m.target.lang = LANG;
                        m.target.setAttribute('lang', LANG);
                    }
                });
            });
            var targets = [window.document.documentElement, window.parent.document.documentElement];
            targets.forEach(function(target) {
                if (target) {
                    observer.observe(target, { attributes: true, attributeFilter: ['lang'] });
                }
            });
            // Observer também o body para capturar se o Streamlit recriar o documento
            var bodyTargets = [window.document.body, window.parent.document.body];
            bodyTargets.forEach(function(body) {
                if (body) {
                    var bodyObserver = new MutationObserver(function() {
                        fixLang();
                    });
                    bodyObserver.observe(body, { childList: true, subtree: true });
                }
            });
        })();
    </script>
    """,
    height=0,
)

# --- AUTENTICAÇÃO ---
credentials = get_all_users_for_auth()

authenticator = stauth.Authenticate(
    credentials,
    "legal_ai_cookie",
    "legal_ai_key",
    cookie_expiry_days=30
)

# Renderizar formulário de login
authenticator.login()

if st.session_state["authentication_status"] is False:
    st.error('Email/senha incorretos')
elif st.session_state["authentication_status"] is None:
    st.warning('Por favor, insira seu email e senha')
elif st.session_state["authentication_status"]:
    # Usuário autenticado
    username = st.session_state["username"]
    user_data = credentials['usernames'][username]
    user_role = user_data['role']
    user_id = user_data['id']  # ID do usuário logado

    # Barra lateral de navegação e logout
    st.sidebar.title(f"Olá, {user_data['name']}")

    nav_options = ["Chat Jurídico", "Gerenciar Documentos"]
    if user_role == 'admin':
        nav_options.append("Painel Admin")

    page = st.sidebar.radio("Ir para:", nav_options)

    st.sidebar.divider()
    st.sidebar.markdown("### ⚙️ Modelo de IA")

    ollama_ok = ollama_utils.is_ollama_connected()
    ollama_models = ollama_utils.get_available_models()

    if not ollama_ok:
        st.sidebar.error("🔴 Ollama não está respondendo")
        st.sidebar.caption("Verifique se o serviço Ollama está rodando no servidor.")
    else:
        if not ollama_models:
            st.sidebar.warning("📦 Nenhum modelo de IA encontrado")
            if st.sidebar.button("⬇️ Baixar Llama 3.2 3B (recomendado)"):
                with st.sidebar.status("Baixando modelo...") as status:
                    progress_bar = st.sidebar.progress(0)
                    for update in ollama_utils.pull_model("llama3.2:3b"):
                        if "completed" in update:
                            pct = update["completed"] / update.get("total", 1)
                            progress_bar.progress(min(pct, 1.0))
                        elif "error" in update:
                            st.sidebar.error(f"Erro: {update['error']}")
                            break
                        elif "status" in update and update["status"] in ["success", "downloading"]:
                            pass  # continua
                    progress_bar.progress(1.0)
                    status.update(label="✅ Modelo baixado!", state="complete")
                    st.rerun()
        else:
            available_models = ["[Ollama] " + m for m in ollama_models]

            if "selected_model" not in st.session_state or not st.session_state.selected_model:
                st.session_state.selected_model = available_models[0] if available_models else ""
                # Ativar o modelo padrão na primeira vez
                if st.session_state.selected_model:
                    model_name = st.session_state.selected_model.replace("[Ollama] ", "")
                    ollama_utils.warmup_model(model_name)
                    set_llm_model(model_name, provider="Ollama")

            index_model = 0
            if st.session_state.selected_model in available_models:
                index_model = available_models.index(st.session_state.selected_model)
            elif available_models:
                st.session_state.selected_model = available_models[0]

            selected = st.sidebar.selectbox("Selecione o modelo:", available_models, index=index_model)

            if selected and selected != st.session_state.selected_model:
                model_name = selected.replace("[Ollama] ", "")
                running_models = ollama_utils.get_running_models()
                for rm in running_models:
                    if rm != model_name:
                        ollama_utils.stop_model(rm)
                ollama_utils.warmup_model(model_name)
                set_llm_model(model_name, provider="Ollama")

                st.session_state.selected_model = selected

    st.sidebar.divider()
    col_logout = st.sidebar.columns(2)
    with col_logout[0]:
        if st.button("🆕 Novo Chat", use_container_width=True):
            st.session_state.messages = []
            st.rerun()
    with col_logout[1]:
        authenticator.logout('Sair', 'sidebar')

    if page == "Chat Jurídico":
        st.title("⚖️ Assistente Jurídico Local")

        if "messages" not in st.session_state:
            st.session_state.messages = []

        # Interface de Chat
        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

        if prompt := st.chat_input("Como posso ajudar com sua questão jurídica?"):
            st.session_state.messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)

            with st.chat_message("assistant"):
                with st.spinner("Pensando..."):
                    chat_history = []
                    for m in st.session_state.messages[:-1]:
                        if m["role"] == "user":
                            content = m["content"]
                            chat_history.append(HumanMessage(content=content))
                        else:
                            content = m["content"]
                            chat_history.append(AIMessage(content=content))

                    # Passa o user_id e user_email para isolar documentos e auditar
                    result = get_response(prompt, chat_history, user_id=user_id, user_email=username)
                    answer = result["answer"]
                    sources = result["sources"]

                    st.markdown(answer)

                    if sources:
                        with st.expander("📚 Fontes Citadas"):
                            st.caption("As citações [n] no texto correspondem às fontes abaixo:")
                            for source in sources:
                                nome = source.get('file_name') or "Documento s/ nome"
                                ref = source.get('source_label') or nome
                                ref_num = source.get('ref')
                                prefix = f"[{ref_num}] " if ref_num else ""
                                st.write(f"- **{prefix}{ref}** (Similaridade: {1 - source['distance']:.2%})")

                    st.session_state.messages.append({"role": "assistant", "content": answer})

    elif page == "Gerenciar Documentos":
        st.title("📂 Gerenciamento de Documentos")

        with st.expander("➕ Adicionar Novo Documento", expanded=False):
            uploaded_file = st.file_uploader("Escolha um arquivo PDF", type="pdf")
            if uploaded_file:
                st.info("🔒 Documentos enviados são privados por padrão (visíveis apenas para você).")
                if st.button("Processar e Indexar"):
                    progress_bar = st.progress(0)
                    status_text = st.empty()

                    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
                        tmp_file.write(uploaded_file.getbuffer())
                        tmp_path = tmp_file.name

                    try:
                        status_text.text("Lendo e fragmentando PDF...")
                        chunks = process_pdf(tmp_path)
                        embeddings = NomicOllamaEmbeddings(
                            model="nomic-embed-text",
                            base_url=OLLAMA_BASE_URL
                        )

                        # Passa owner_id e scope='private' por padrão
                        for percent_complete in store_in_postgres(chunks, embeddings, uploaded_file.name, owner_id=user_id, scope='private'):
                            progress_bar.progress(percent_complete)
                            status_text.text(f"Processando: {int(percent_complete * 100)}%")

                        st.success(f"Documento '{uploaded_file.name}' indexado com sucesso!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Erro ao processar: {e}")
                    finally:
                        if os.path.exists(tmp_path):
                            os.remove(tmp_path)

        st.divider()
        st.write("### Base de Conhecimento Atual")

        # Lista documentos filtrados pelo user_id
        is_admin = (user_role == 'admin')
        docs = list_documents(user_id=user_id, is_admin=is_admin)

        if not docs:
            st.info("Nenhum documento encontrado na base de dados.")
        else:
            for file_name, uploaded_at, chunks, scope in docs:
                display_name = file_name if file_name != 'SEM_NOME' else "Documentos Legados (Sem Nome)"
                scope_icon = "🌐 Global" if scope == 'global' else "🔒 Privado"
                with st.expander(f"{scope_icon} — {display_name}"):
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        if uploaded_at:
                            st.write(f"**Data de inclusão:** {uploaded_at.strftime('%d/%m/%Y %H:%M')}")
                        else:
                            st.write("**Data de inclusão:** Indisponível")
                        st.write(f"**Fragmentos (chunks):** {chunks}")
                    with col2:
                        if st.button("Excluir", key=f"del_{file_name}"):
                            delete_document(file_name, user_id=user_id, is_admin=is_admin)
                            st.success("Removido!")
                            st.rerun()

    elif page == "Painel Admin" and user_role == 'admin':
        st.title("⚙️ Painel Administrativo")

        tab1, tab2, tab3, tab4, tab5 = st.tabs(["Configurações do Sistema", "Gestão de Usuários", "Documentos Globais", "Auditoria", "Modelos de IA"])

        with tab1:
            st.header("Configurações Gerais")

            # Indicador de GPU
            with st.expander("🎮 Status da GPU", expanded=True):
                gpu_status = check_gpu()
                st.markdown(format_gpu_status(gpu_status))
                st.caption("A GPU acelera o Ollama em 3-5x comparado à CPU.")

            st.divider()
            max_users = get_system_setting('max_users')
            new_max = st.number_input("Limite máximo de usuários", min_value=1, value=int(max_users) if max_users else 10)
            if st.button("Salvar Configurações"):
                set_system_setting('max_users', new_max)
                st.success("Configurações atualizadas!")

        with tab2:
            st.header("Gestão de Contas")

            # Criar novo usuário
            with st.expander("➕ Criar Novo Usuário"):
                with st.form("new_user_form"):
                    new_email = st.text_input("Email")
                    new_name = st.text_input("Nome Completo")
                    new_pass = st.text_input("Senha", type="password")
                    new_role = st.selectbox("Papel", ["user", "admin"])

                    if st.form_submit_button("Cadastrar"):
                        current_count = get_user_count()
                        limit = int(get_system_setting('max_users') or 10)

                        if current_count >= limit:
                            st.error(f"Limite de usuários atingido ({limit}).")
                        else:
                            success, msg = add_user(new_email, new_name, new_pass, new_role)
                            if success:
                                st.success(msg)
                                st.rerun()
                            else:
                                st.error(msg)

            st.divider()
            # Listar usuários e resetar senha
            st.write("### Usuários Cadastrados")
            all_creds = get_all_users_for_auth()
            for u_mail, u_info in all_creds['usernames'].items():
                col_u, col_a = st.columns([3, 1])
                with col_u:
                    st.write(f"**{u_info['name']}** ({u_mail}) - Cargo: `{u_info['role']}`")
                with col_a:
                    if st.button("Resetar Senha", key=f"reset_{u_mail}"):
                        st.session_state[f"resetting_{u_mail}"] = True

                if st.session_state.get(f"resetting_{u_mail}"):
                    with st.form(f"form_reset_{u_mail}"):
                        new_pwd = st.text_input("Nova Senha", type="password")
                        if st.form_submit_button("Confirmar Alteração"):
                            update_password(u_mail, new_pwd)
                            st.success(f"Senha de {u_mail} alterada!")
                            del st.session_state[f"resetting_{u_mail}"]
                            st.rerun()

        with tab3:
            st.header("🌐 Gerenciar Documentos Globais")
            st.write("Documentos globais ficam visíveis para **todos os usuários** (leis, jurisprudência, etc).")

            # Upload de documento global
            with st.expander("➕ Adicionar Documento Global", expanded=False):
                uploaded_file = st.file_uploader("Escolha um arquivo PDF", type="pdf", key="global_upload")
                if uploaded_file:
                    if st.button("Processar como Global", key="btn_global"):
                        progress_bar = st.progress(0)
                        status_text = st.empty()

                        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
                            tmp_file.write(uploaded_file.getbuffer())
                            tmp_path = tmp_file.name

                        try:
                            status_text.text("Lendo e fragmentando PDF...")
                            chunks = process_pdf(tmp_path)
                            embeddings = NomicOllamaEmbeddings(
                                model="nomic-embed-text",
                                base_url=os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")
                            )

                            for percent_complete in store_in_postgres(chunks, embeddings, uploaded_file.name, owner_id=user_id, scope='global'):
                                progress_bar.progress(percent_complete)
                                status_text.text(f"Processando: {int(percent_complete * 100)}%")

                            st.success(f"Documento global '{uploaded_file.name}' indexado com sucesso!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Erro ao processar: {e}")
                        finally:
                            if os.path.exists(tmp_path):
                                os.remove(tmp_path)

            st.divider()
            # Listar todos os documentos (admin vê tudo)
            st.write("### Todos os Documentos")
            all_docs = list_documents(user_id=user_id, is_admin=True)
            if not all_docs:
                st.info("Nenhum documento cadastrado.")
            else:
                for file_name, uploaded_at, chunks, scope in all_docs:
                    display_name = file_name if file_name != 'SEM_NOME' else "Documentos Legados (Sem Nome)"
                    scope_icon = "🌐 Global" if scope == 'global' else "🔒 Privado"
                    with st.expander(f"{scope_icon} — {display_name}"):
                        col1, col2, col3 = st.columns([3, 1, 1])
                        with col1:
                            if uploaded_at:
                                st.write(f"**Data de inclusão:** {uploaded_at.strftime('%d/%m/%Y %H:%M')}")
                            st.write(f"**Fragmentos (chunks):** {chunks}")
                            st.write(f"**Escopo:** {scope}")
                        with col2:
                            if scope == 'private':
                                if st.button("🌐 Tornar Global", key=f"global_{file_name}"):
                                    update_document_scope(file_name, 'global', user_id)
                                    st.rerun()
                            else:
                                if st.button("🔒 Tornar Privado", key=f"private_{file_name}"):
                                    update_document_scope(file_name, 'private', user_id)
                                    st.rerun()
                        with col3:
                            if st.button("Excluir", key=f"del_admin_{file_name}"):
                                delete_document(file_name, is_admin=True)
                                st.success("Removido!")
                                st.rerun()

        with tab4:
            st.header("📋 Auditoria de Perguntas")
            st.write("Registro de todas as perguntas feitas pelos usuários no chat jurídico.")

            # Filtros
            col_f1, col_f2, col_f3 = st.columns([2, 2, 1])

            with col_f1:
                audit_users = get_unique_users_from_audit()
                filter_user = st.selectbox(
                    "Filtrar por usuário",
                    ["Todos"] + audit_users,
                    key="audit_filter_user"
                )

            with col_f2:
                filter_date_from = st.date_input("Data inicial", value=None, key="audit_date_from")
                filter_date_to = st.date_input("Data final", value=None, key="audit_date_to")

            with col_f3:
                st.write("")
                st.write("")
                if st.button("🔄 Limpar Filtros", key="audit_clear"):
                    st.rerun()

            # Paginação
            ITEMS_PER_PAGE = 20
            if "audit_page" not in st.session_state:
                st.session_state.audit_page = 0

            # Montar params de filtro
            email_param = filter_user if filter_user and filter_user != "Todos" else None
            date_from_param = str(filter_date_from) if filter_date_from else None
            date_to_param = str(filter_date_to) if filter_date_to else None
            if date_to_param:
                date_to_param += " 23:59:59"

            total_logs = count_audit_logs(
                user_email=email_param,
                date_from=date_from_param,
                date_to=date_to_param
            )

            total_pages = max(1, (total_logs + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
            current_page = st.session_state.audit_page

            # Navegação de páginas
            col_p1, col_p2, col_p3, col_p4 = st.columns([1, 2, 2, 1])
            with col_p1:
                if st.button("◀ Anterior", disabled=(current_page == 0)):
                    st.session_state.audit_page = max(0, current_page - 1)
                    st.rerun()
            with col_p2:
                st.write(f"Página **{current_page + 1}** de **{total_pages}** ({total_logs} registros)")
            with col_p3:
                if st.button("📥 Exportar CSV"):
                    logs = get_audit_logs(
                        user_email=email_param,
                        date_from=date_from_param,
                        date_to=date_to_param,
                        limit=total_logs,
                        offset=0
                    )
                    if logs:
                        import csv
                        import io
                        output = io.StringIO()
                        writer = csv.writer(output)
                        writer.writerow(["ID", "Usuário", "Email", "Pergunta", "Resumo", "Fontes", "Data"])
                        for row in logs:
                            writer.writerow([
                                row["id"],
                                row.get("user_name", ""),
                                row["user_email"],
                                row["question"],
                                row["response_summary"],
                                ", ".join(row["sources_used"]) if row.get("sources_used") else "",
                                row["created_at"].strftime("%d/%m/%Y %H:%M") if row.get("created_at") else ""
                            ])
                        st.download_button(
                            label="📥 Baixar CSV",
                            data=output.getvalue(),
                            file_name="auditoria_legalizai.csv",
                            mime="text/csv"
                        )
                    else:
                        st.info("Nenhum registro para exportar.")
            with col_p4:
                if st.button("Próximo ▶", disabled=(current_page >= total_pages - 1)):
                    st.session_state.audit_page = min(total_pages - 1, current_page + 1)
                    st.rerun()

            # Tabela de registros
            offset = current_page * ITEMS_PER_PAGE
            logs = get_audit_logs(
                user_email=email_param,
                date_from=date_from_param,
                date_to=date_to_param,
                limit=ITEMS_PER_PAGE,
                offset=offset
            )

            if not logs:
                st.info("Nenhum registro de auditoria encontrado.")
            else:
                for log in logs:
                    with st.expander(f"🗣️ {log['question'][:80]}... — {log['user_email']} — {log['created_at'].strftime('%d/%m/%Y %H:%M') if log.get('created_at') else ''}"):
                        st.markdown(f"**👤 Usuário:** {log.get('user_name', log['user_email'])} ({log['user_email']})")
                        st.markdown(f"**❓ Pergunta:** {log['question']}")
                        st.markdown(f"**💬 Resposta:** {log['response_summary']}")
                        if log.get('sources_used'):
                            st.markdown(f"**📚 Fontes utilizadas:** {', '.join(log['sources_used'])}")
                        st.caption(f"🕐 {log['created_at'].strftime('%d/%m/%Y %H:%M:%S') if log.get('created_at') else ''}")

        with tab5:
            import models_admin
            models_admin.render()
