workspace {
    model {
        advogado = person "Advogado / Usuário" "Pessoa física que acessa o platforma via navegador para fazer perguntas jurídicas"
        administrador = person "Administrador" "Usuário com perfil administrador — gerencia usuários, documentos globais e configurações do sistema"

        legaliz = softwareSystem "Legaliz.ai" "Assistente jurídico com RAG — 100% offline e local" {
            webapp = container "Streamlit UI" "Interface web em Streamlit — Chat Jurídico, Gerenciar Documentos, Painel Admin, Auditoria" "Python + Streamlit"
            agent = container "Agent RAG" "Pipeline de recuperação e geração de respostas — Retrieval, HyDE, MMR Rerank, Fact-check, Citations" "Python (langchain, ollama, pgvector)"
            auth = container "Autenticação" "streamlit-authenticator com roles admin/user — login, logout, gestão de sessão" "Python + streamlit-authenticator"
            
            // Contêineres movidos para dentro do softwareSystem
            postgres = container "PostgreSQL + pgvector" "Banco de dados vetorial para documentos, embeddings, usuários e logs de auditoria" "ankane/pgvector (Docker)"
            ollama = container "Ollama Server" "Servidor de modelos LLM locais e embeddings — llama3.2:3b, gemma4, nomic-embed-text" "Ollama (Docker)"
            gpu = container "GPU NVIDIA" "Aceleração CUDA para inferência de LLM e embeddings — 3-5x speedup vs CPU" "NVIDIA GPU"
        }

        // Relacionamentos
        advogado -> webapp "Acessa via navegador HTTPS"
        administrador -> webapp "Acessa via navegador HTTPS"
        webapp -> auth "Autentica login/logout"
        webapp -> agent "Envia pergunta, recebe resposta"
        agent -> ollama "Embeddings + LLM inference"
        agent -> postgres "Busca semântica vetorial + armazenamento"
        ollama -> gpu "Inferência no GPU"
    }

    views {
        systemContext legaliz {
            include *
            autolayout lr
        }
        container legaliz {
            include *
            autolayout lr
        }
        theme default
    }
}