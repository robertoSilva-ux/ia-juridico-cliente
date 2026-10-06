# C4 Model — System Context Diagram
## Legaliz.ai

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         SYSTEM CONTEXT                                      │
│                     Legaliz.ai v1.0                                         │
└─────────────────────────────────────────────────────────────────────────────┘

                         ┌──────────────────┐
                         │   ADVOGADOS /     │
                         │   USUÁRIOS        │
                         │  (Web Browser)    │
                         └────────┬─────────┘
                                  │ HTTPS (Streamlit UI)
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                    LEGALIZ.AI (System)                              │  │
│  │                                                                      │  │
│  │  ┌─────────────────┐  ┌──────────────────┐  ┌───────────────────┐  │  │
│  │  │  Streamlit UI   │  │  Agent (RAG)     │  │  Auth (streamlit- │  │  │
│  │  │  - Chat Jurídico│  │  - Retrieval     │  │  authenticator)   │  │  │
│  │  │  - Gerenciar    │  │  - HyDE          │  │  - Login/Logout   │  │  │
│  │  │    Documentos   │  │  - MMR Rerank    │  │  - Roles (admin/  │  │  │
│  │  │  - Painel Admin │  │  - Fact-check    │  │    user)          │  │  │
│  │  │  - Auditoria    │  │  - Regime boost  │  │  - User mgmt      │  │  │
│  │  │  - Model config │  │  - Citations     │  │  - Password reset │  │  │
│  │  └────────┬────────┘  └────────┬─────────┘  └───────────────────┘  │  │
│  │           │                    │                                    │  │
│  │           ▼                    ▼                                    │  │
│  │  ┌────────────────────────────────────────────────────────────────┐  │  │
│  │  │                    Application Layer                         │  │  │
│  │  │  - ingest.py (PDF → chunks)  - agent.py (RAG pipeline)      │  │  │
│  │  │  - auth.py (user management)  - audit.py (question logging)  │  │  │
│  │  │  - ranking.py (MMR rerank)    - factcheck.py (groundedness)  │  │  │
│  │  │  - legal_parser.py (artigo/parágrafo extraction)             │  │  │
│  │  │  - regime.py (jurídico regime boost)                         │  │  │
│  │  │  - embeddings.py (nomic-embed-text wrapper)                  │  │  │
│  │  │  - ollama_utils.py (Ollama lifecycle)                        │  │  │
│  │  └────────────────────────────────────────────────────────────────┘  │  │
│  └──────────────────────────────┬───────────────────────────────────────┘  │
│                                 │                                          │
│              ┌──────────────────┼──────────────────┐                       │
│              ▼                  ▼                  ▼                       │
│  ┌─────────────────┐ ┌──────────────────┐ ┌──────────────────────────┐   │
│  │  PostgreSQL +   │ │  Ollama (local)  │ │  GPU (NVIDIA)            │   │
│  │  pgvector       │ │  - LLM models    │ │  - GPU acceleration      │   │
│  │  (vector DB)    │ │  - Embeddings    │ │  - 3-5x speedup vs CPU   │   │
│  │  - Documents    │ │  - nomic-embed-  │ │                          │   │
│  │  - Audit logs   │ │    text          │ │                          │   │
│  │  - Users/roles  │ │  - llama3.2:3b   │ │                          │   │
│  │  - Sources      │ │  - gemma4        │ │                          │   │
│  └─────────────────┘ └──────────────────┘ └──────────────────────────┘   │
│                                                                        │
│  External: None (fully offline/local)                                  │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Atores Externos

| Ator | Descrição |
|------|-----------|
| **Advogados / Usuários** | Pessoas físicas que acessam o sistema via navegador web para fazer perguntas jurídicas e gerenciar documentos |
| **Administrador** | Usuário com role `admin` — gerencia usuários, documentos globais, configurações do sistema e modelos de IA |

### Sistemas Externos

Nenhum. O Legaliz.ai roda **100% offline/local** — sem dependências de APIs externas, provedores de nuvem ou serviços de terceiros.

### Tecnologias Principais

| Componente | Tecnologia |
|------------|-----------|
| Interface | Streamlit (Python) |
| Backend | Python 3.12+ |
| LLM | Ollama (modelos locais: llama3.2:3b, gemma4) |
| Embeddings | nomic-embed-text (via Ollama) |
| Banco de dados | PostgreSQL + pgvector (ankane/pgvector Docker) |
| Vector search | IVFFlat + HNSW (pgvector) |
| Autenticação | streamlit-authenticator |
| Containerização | Docker + docker-compose |
| GPU | NVIDIA (CUDA) — aceleração opcional |

### Fluxo Principal (Pergunta Jurídica)

```
Usuário → Streamlit UI → Agent (RAG)
  → Embedding da query (nomic-embed-text via Ollama)
  → Busca semântica no PostgreSQL/pgvector
  → HyDE (gera doc hipotético via LLM, busca complementar)
  → Fusão RRF + Re-ranking MMR
  → Fact-check pós-geração
  → Resposta com citações [n] → Usuário
```
