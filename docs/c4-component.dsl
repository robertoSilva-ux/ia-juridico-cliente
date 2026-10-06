workspace {
    model {
        advogado = person "Advogado / Usuário" "Pessoa física que acessa a plataforma via navegador"
        administrador = person "Administrador" "Usuário com role admin — gerencia usuários, documentos globais e configurações"

        legaliz = softwareSystem "Legaliz.ai" "Assistente jurídico com RAG — 100% offline e local" {

            webapp = container "Streamlit UI" "Interface web — Chat, Gerenciar Docs, Admin, Auditoria" "Python + Streamlit" {
                chatUI = component "Chat Jurídico UI" "Interface de chat com histórico de mensagens, fontes citadas e expardor de fontes" "Streamlit chat"
                docMgmtUI = component "Gerenciar Documentos UI" "Upload de PDFs, lista de documentos, exclusão, toggle escopo privado/global" "Streamlit file_uploader"
                adminPanel = component "Painel Admin UI" "Configurações do sistema, gestão de usuários, documentos globais, auditoria, seleção de modelo" "Streamlit tabs"
                authUI = component "Auth UI" "Forms de login/logout com streamlit-authenticator" "streamlit-authenticator"
            }

            agent = container "Agent RAG" "Pipeline de recuperação e geração de respostas jurídicas" "Python + LangChain" {
                retrieve = component "Retrieve" "Busca semântica vetorial no pgvector — query embedding +similarity threshold + TOP_K" "Python"
                hyde = component "HyDE" "Hypothetical Document Embeddings — gera doc hipotético via LLM, busca complementar, fusão RRF" "Python + LLM"
                rerank = component "MMR Rerank" "Maximal Marginal Relevance — re-ranking para reduzir redundância entre documentos recuperados" "Python"
                factCheck = component "Fact-check" "Verificação pós-geração — checagem de citações [n] e groundedness semântica por sentença" "Python"
                regimeBoost = component "Regime Boost" "Boost de relevância para documentos do regime jurídico (previdenciário/trabalhista)" "Python"
                buildContext = component "Build Context" "Monta o prompt com contexto recuperado + pergunta do advogado" "Python"
                generate = component "Generate" "Gera resposta final via LLM com chat history e contexto construído" "Python + LLM"
            }

            ingest = container "Ingest Pipeline" "Processamento de PDFs → chunks → embeddings → armazenamento no banco" "Python" {
                pdfExtract = component "PDF Extract" "PyPDFLoader — carrega páginas do PDF" "Python + PyPDFLoader"
                normalize = component "Normalize Whitespace" "Normalização de ruído de PDF (hifenização, NBSP, espaços duplicados)" "Python + regex"
                splitLegal = component "Legal Split" "Chunking que preserva dispositivos jurídicos — não quebra Art. N entre chunks" "Python + RecursiveCharacterTextSplitter"
                dedup = component "Dedup" "Filtra chunks cujo conteúdo já existe no banco para o mesmo arquivo" "Python + SQL"
                embedBatch = component "Embed Batch" "Gera embeddings em lote via Ollama (nomic-embed-text)" "Python + Ollama"
                store = component "Store" "Insere chunks no PostgreSQL com metadados jurídicos e vetor de embedding" "Python + psycopg2/pgvector"
            }

            legalParser = container "Legal Parser" "Extração de metadados jurídicos do conteúdo dos chunks" "Python" {
                parse = component "Parse" "Extrai artigo, parágrafo, inciso, tipo_doc, numero_doc, ano_doc do texto do chunk" "Python + regex"
                enrich = component "Enrich Metadata" "Enriquece metadados do chunk com título, fonte, contexto extraído do nome do arquivo" "Python"
                buildTitle = component "Build Title" "Constrói título legível a partir do nome do arquivo PDF" "Python"
            }

            auth = container "Auth Module" "Autenticação e gestão de usuários" "Python + streamlit-authenticator" {
                login = component "Login" "Formulário de autenticação com email/senha" "streamlit-authenticator"
                logout = component "Logout" "Encerra sessão do usuário" "streamlit-authenticator"
                userMgmt = component "User Management" "CRUD de usuários — criação, reset de senha, limite de usuários" "Python"
            }

            audit = container "Audit Module" "Registro e exportação de perguntas do chat" "Python" {
                log = component "Log Question" "Registra cada pergunta do chat com usuário, email, resposta e fontes utilizadas" "Python + PostgreSQL"
                export = component "Export CSV" "Gera CSV paginado dos registros de auditoria com filtros por usuário e data" "Python + csv"
            }

            embeddings = container "Embeddings Wrapper" "Wrapper de embeddings com prefixos assimétricos para nomic-embed-text" "Python + Ollama" {
                embedDoc = component "Embed Document" "Vetoriza documentos/chunks aplicando prefixo search_document:" "Python + Ollama"
                embedQuery = component "Embed Query" "Vetoriza consultas aplicando prefixo search_query:" "Python + Ollama"
            }

            ranking = container "Ranking Engine" "Fusão de rankings e re-ranking" "Python" {
                rrf = component "RRF Fusion" "Reciprocal Rank Fusion — funde rankings de query original + HyDE" "Python"
                mmr = component "MMR Re-rank" "Maximal Marginal Relevance para reduzir redundância no TOP-K final" "Python"
            }

            postgres = container "PostgreSQL + pgvector" "Banco de dados vetorial — documentos, embeddings, usuários, logs" "ankane/pgvector (Docker)"
            ollama = container "Ollama Server" "Modelos LLM locais — llama3.2:3b, gemma4, nomic-embed-text" "Ollama (Docker)"
            gpu = container "GPU NVIDIA" "Aceleração CUDA — 3-5x speedup vs CPU" "NVIDIA GPU"
        }
        
        advogado -> webapp "Acessa via navegador HTTPS"
        administrador -> webapp "Acessa via navegador HTTPS"
        webapp -> auth "Autentica login/logout"
        webapp -> agent "Envia pergunta, recebe resposta"
        webapp -> ingest "Aciona upload de PDF"
        webapp -> audit "Consulta logs de auditoria"

        // Relações do Agent com contêineres externos mantidas
        agent -> ollama "Embeddings + LLM inference"
        agent -> postgres "Busca semântica vetorial + armazenamento"
        agent -> embeddings "Gera embeddings para busca"
        agent -> ranking "Fusão RRF dos rankings"
        
        // CORREÇÃO: Pipeline interno do Agent RAG ligado entre os componentes
        buildContext -> retrieve "Inicia busca semântica"
        retrieve -> hyde "Gera documento hipotético para busca complementar"
        retrieve -> rerank "Executa re-ranking MMR nos resultados"
        rerank -> regimeBoost "Aplica boost de regime jurídico"
        regimeBoost -> buildContext "Retorna contexto ordenado"
        buildContext -> generate "Gera resposta final com LLM"
        generate -> factCheck "Verifica groundedness da resposta"

        ingest -> ollama "Gera embeddings dos chunks"
        ingest -> postgres "Armazena chunks indexados"
        ingest -> legalParser "Extrai metadados jurídicos"

        legalParser -> postgres "Persiste metadados dos documentos"

        auth -> postgres "Consulta/armazena credenciais de usuários"
        audit -> postgres "Persiste logs de auditoria"

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
        component agent {
            include *
            autolayout lr
        }
        component ingest {
            include *
            autolayout lr
        }
        theme default
    }
}