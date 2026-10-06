workspace {
    model {
        advogado = person "Advogado / Usuário" "Pessoa física que acessa a plataforma via navegador"
        administrador = person "Administrador" "Usuário com role admin — gerencia usuários, documentos globais e configurações"

        legaliz = softwareSystem "Legaliz.ai" "Assistente jurídico com RAG — 100% offline e local" {
            webapp = container "Streamlit UI" "Interface web — Chat Jurídico, Gerenciar Documentos, Painel Admin, Auditoria" "Python + Streamlit"
            agent = container "Agent RAG" "Pipeline de recuperação e geração — Retrieval, HyDE, MMR Rerank, Fact-check, Citations" "Python + LangChain"
            auth = container "Auth Module" "streamlit-authenticator com roles admin/user — login, logout, gestão de sessão" "Python + streamlit-authenticator"
            ingest = container "Ingest Pipeline" "PDF → chunks → embeddings → PostgreSQL — processamento e indexação de documentos" "Python"
            legalParser = container "Legal Parser" "Extração de metadados jurídicos — artigo, parágrafo, inciso, tipo_doc, numero_doc" "Python"
            ranking = container "Ranking Engine" "MMR re-ranking, HyDE, RRF fusion, regime boost" "Python"
            factcheck = container "Fact-check" "Verificação de groundedness pós-geração — citações e sentenças apoiadas" "Python"
            embeddings = container "Embeddings" "Wrapper de embeddings com prefixos assimétricos para Ollama" "Python + nomic-embed-text"
            postgres = container "PostgreSQL + pgvector" "Banco de dados vetorial — documentos, embeddings, usuários, logs de auditoria" "ankane/pgvector (Docker)"
            ollama = container "Ollama Server" "Servidor de modelos LLM locais e embeddings — llama3.2:3b, gemma4, nomic-embed-text" "Ollama (Docker)"
            gpu = container "GPU NVIDIA" "Aceleração CUDA para inferência de LLM e embeddings — 3-5x speedup vs CPU" "NVIDIA GPU"
        }
        advogado -> webapp "Acessa via navegador HTTPS"
        administrador -> webapp "Acessa via navegador HTTPS"
        webapp -> auth "Autentica login/logout"
        webapp -> agent "Envia pergunta, recebe resposta"
        agent -> ollama "Embeddings + LLM inference"
        agent -> postgres "Busca semântica vetorial + armazenamento"
        agent -> embeddings "Gera embeddings para busca"
        agent -> ranking "Re-ranking MMR e fusão RRF"
        agent -> factcheck "Verifica groundedness da resposta"
        ingest -> ollama "Gera embeddings dos chunks"
        ingest -> postgres "Armazena chunks indexados"
        ingest -> legalParser "Extrai metadados jurídicos dos chunks"
        legalParser -> postgres "Persiste metadados dos documentos"
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
