# ⚖️ Legaliz.ai - Assistente Jurídico Inteligente (MVP)

![Python](https://img.shields.io/badge/Python-3.11-blue)
![Streamlit](https://img.shields.io/badge/Streamlit-1.28+-red)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-pgvector-4169E1)
![License](https://img.shields.io/badge/License-MIT-green)
![RAG](https://img.shields.io/badge/RAG-LangChain-orange)
![Ollama](https://img.shields.io/badge/LLM-Ollama-000)

O **Legaliz.ai** é um MVP de uma plataforma jurídica que utiliza Inteligência Artificial local para auxiliar advogados na análise de documentos, pesquisa jurisprudencial e redação de peças.

> 🛠️ **Desenvolvimento:** commits vão direto na branch `main`. Pipeline de RAG com técnicas avançadas (ver [Técnicas de RAG](#-técnicas-avançadas-de-rag)). Roadmap de implementação em `docs/TASKS.md`.

---

## 📌 Estado do projeto e documentação

Documentação de trabalho, para quem for retomar ou auditar o produto:

| Documento | O que responde |
|:---|:---|
| **[`docs/EVOLUCAO.md`](docs/EVOLUCAO.md)** | Onde paramos: diário de bordo por bloco de trabalho, o que foi verificado por execução e como retomar (inclusive depois de reiniciar a máquina) |
| [`docs/REVISAO_SEGURANCA.md`](docs/REVISAO_SEGURANCA.md) | Revisão de segurança e isolamento entre clientes: achados com gravidade, evidência e o que já foi corrigido |
| [`docs/BACKLOG.md`](docs/BACKLOG.md) | O que falta, priorizado, com arquivo afetado e critério de aceite |
| [`docs/AMBIENTE_DEV.md`](docs/AMBIENTE_DEV.md) | Como rodar em desenvolvimento (sem Docker) e o checklist de ensaio de paridade antes de release |
| [`docs/adr/`](docs/adr/README.md) | Decisões de arquitetura: contexto, alternativas descartadas e consequências |

**Pendências que dependem do cliente** (detalhe no backlog): **P0-5** — TLS na frente do
Streamlit e fechar a porta do banco publicada no host; **P0-6** — rotacionar as credenciais
que já circularam em texto claro. O restante é evolução incremental.

> ⚠️ **Atualizando uma instalação que já tem dados:** aplicar
> `database/migrate_sources_owner.sql` antes de subir o container novo — ver
> [Desenvolvimento local](#-desenvolvimento-local).

---

## ✨ Funcionalidades

- **🔐 Autenticação Segura:** Sistema de login por email e senha com senhas criptografadas (bcrypt).
- **👥 Controle de Acesso (RBAC):** Diferenciação entre usuários comuns e administradores.
- **💬 Chat Jurídico com Contexto:** Converse com seus documentos. A IA prioriza as informações dos PDFs enviados e cita as fontes.
- **📂 Gerenciamento de Documentos:** Tela para upload e exclusão de documentos indexados.
- **📊 Painel Administrativo:** Gestão de usuários, reset de senhas e configuração de limites do sistema.
- **🔒 Privacidade Total:** Todo o processamento de IA é feito localmente via Ollama.

---

## 🛠️ Stack Tecnológica

| Componente | Tecnologia |
|:---|---:|
| Interface | [Streamlit](https://streamlit.io/) + `streamlit-authenticator` |
| Orquestração de IA | [LangChain](https://www.langchain.com/) |
| Banco de Dados | [PostgreSQL](https://www.postgresql.org/) + [pgvector](https://github.com/pgvector/pgvector) |
| Modelos de IA | [Ollama](https://ollama.com/) (Llama 3 + Nomic Embed) |
| Segurança | `bcrypt` para hash de senhas |
| Infraestrutura | Docker Compose |

---

## 🚀 Instalação e Configuração

### 1. Pré-requisitos

- **Sistema Operacional:** Linux (Ubuntu 22.04+ recomendado) ou Windows com WSL2
- **Memória RAM:** Mínimo de **8GB** (necessário para rodar o modelo Llama 3)
- **Espaço em Disco:** Mínimo de **40GB**
- **GPU (Opcional):** NVIDIA com [Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)

### 2. Configuração de Ambiente

Copie o arquivo de exemplo e edite com suas configurações:

```bash
cp .env.example .env
# Edite .env com suas credenciais, especialmente:
# - POSTGRES_PASSWORD
# - ADMIN_PASSWORD (para criar o admin inicial)
```

**Variáveis de Ambiente disponíveis:**

| Variável | Descrição | Padrão |
|:---|---:|---:|
| `DATABASE_URL` | URL de conexão com PostgreSQL | `postgresql://user:***@db:5432/legal_db` |
| `POSTGRES_USER` | Usuário do PostgreSQL | `user` |
| `POSTGRES_PASSWORD` | Senha do PostgreSQL | — |
| `POSTGRES_DB` | Nome do banco de dados | `legal_db` |
| `DB_POOL_MIN` | Mínimo de conexões no pool | `1` |
| `DB_POOL_MAX` | Máximo de conexões no pool | `10` |
| `OLLAMA_BASE_URL` | URL do serviço Ollama | `http://ollama:11434` |
| `EMBEDDING_MODEL` | Modelo de embeddings | `nomic-embed-text` |
| `LLM_MODEL` | Modelo de linguagem | definido no `.env` (ex.: `phi4-mini:3.8b`) |
| `SIMILARITY_THRESHOLD` | Threshold de similaridade para RAG | `0.80` |
| `TOP_K` | Número de chunks recuperados | `5` |
| `MAX_CONTEXT_CHARS` | Máximo de caracteres no contexto | `12000` |
| `RERANK_ENABLED` | Habilita re-ranking por MMR | `true` |
| `RERANK_TOP_K_MULTIPLIER` | Multiplica `TOP_K` na 1ª etapa do MMR | `3` |
| `RERANK_LAMBDA_MULT` | Trade-off relevância vs redundância (MMR) | `0.7` |
| `HYDE_ENABLED` | Habilita HyDE (query transformation) | `true` |
| `HYDE_TOP_K` | Docs por ranking antes da fusão RRF | `8` |
| `HYDE_QUERY_WEIGHT` | Peso da query original na fusão RRF | `1.4` |
| `FACT_CHECK_ENABLED` | Habilita fact-check pós-geração (lastro da resposta) | `true` |
| `FACT_CHECK_LLM_ENABLED` | Portão de suficiência: 1 chamada curta ao LLM antes de gerar, para decidir se a base responde ("NAO" ⇒ recusa honesta) | `true` |
| `ENCRYPTION_KEY` | Chave de criptografia (**reservada — sem uso no código hoje**, ver P2-18 no backlog) | — |
| `STREAMLIT_SERVER_PORT` | Porta do Streamlit | `8501` |
| `ADMIN_EMAIL` | Email do admin inicial (criado por `init_admin.py`, não pelo schema) | `admin@legaliz.ai` |
| `ADMIN_PASSWORD` | Senha do admin inicial (**obrigatória**; mínimo 8 caracteres) | — |
| `COOKIE_KEY` | Segredo que assina o cookie de sessão (**obrigatória**; ≥32 bytes, própria de cada instalação) | — |

> **⚠️ Segurança:** o sistema **não sobe** sem `COOKIE_KEY` (≥32 bytes, não pública) nem
> com `ADMIN_PASSWORD` ausente/previsível, e o `docker/init.sql` não cria mais usuário
> nenhum. Gere a chave com
> `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`.
> Detalhes em [`docs/REVISAO_SEGURANCA.md`](docs/REVISAO_SEGURANCA.md).

### 3. Instalação via Setup Automatizado

```bash
# Atualize o sistema
sudo apt update && sudo apt upgrade -y

# Instale o Docker (caso não tenha)
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Clone o repositório
git clone https://github.com/seu-usuario/legal-ai-mvp.git
cd legal-ai-mvp

# Configure as variáveis de ambiente
cp .env.example .env
# Edite o .env com suas credenciais

# Execute o setup
chmod +x setup.sh
./setup.sh
```

### 4. Instalação via Makefile

```bash
make setup    # Sobe containers, baixa modelos e cria admin
make logs     # Acompanha os logs
make test     # Executa testes
make down     # Para os containers
make clean    # Remove volumes e limpa
```

### 5. Acesso ao Sistema

- **URL:** [http://localhost:8501](http://localhost:8501)
- **Admin inicial:** criado por `init_admin.py` a partir de `ADMIN_EMAIL`/`ADMIN_PASSWORD`
  do `.env` (o schema do banco não semeia usuário nenhum)
- Se `ADMIN_PASSWORD` não estiver definida (ou for previsível), o `setup.sh` **para** e
  explica o que ajustar — não existe mais senha padrão

---

## 🧠 Arquitetura de Prompts

O Legaliz.ai separa **instruções** (system) de **conteúdo** (human). Persona e regras de conduta ficam no *system prompt*; o contexto recuperado e a pergunta do advogado vão na mensagem *human*. Essa separação evita que o modelo confunda as diretrizes do system com conteúdo a responder (eco/instruction leakage) — um problema real observado com o Llama 3.

### Estrutura

```
app/prompts/              # SYSTEM — papel e regras de conduta
└── system-role.md        # Persona (Clóvis) + regras de ancoragem/veracidade

app/prompts_user/         # HUMAN — conteúdo do usuário
└── context-block.md      # Contexto recuperado ({context}) + pergunta ({input})
```

### Funcionamento

1. Na inicialização, `load_prompts()` em `app/agent.py` lê todos os `.md` de `prompts/` (via helper `_load_md_dir`), em **ordem alfabética**, e concatena com `\n\n` — isso vira o **`SYSTEM_PROMPT`**.
2. O mesmo helper lê `prompts_user/` e monta o **`USER_PROMPT`**, o template da mensagem `human` (contém `{context}` e `{input}`).
3. No `ChatPromptTemplate`: `system` recebe as instruções; `human` recebe o contexto + a pergunta; `{chat_history}` mantém o histórico.
4. Em `get_response()`, o contexto (via `build_context`) e a query são passados no `invoke`, preenchendo o bloco human.

> **Nota:** O contexto recuperado **nunca** entra no system prompt. Se a pasta `prompts_user/` não existir, há um fallback inline com o mesmo formato.

### Vantagens

- **Sem leakage:** Instruções não se confundem com conteúdo; o modelo responde, não ecoa as regras
- **Manutenção simplificada:** Prompts são arquivos Markdown, sem editar código Python
- **Extensível:** Basta adicionar novos `.md` nas pastas para incluir diretrizes ou reformatar o bloco de contexto
- **Versionamento:** Cada prompt tem seu próprio histórico no git

---

## 🧠 Técnicas Avançadas de RAG

O pipeline de recuperação do Legaliz.ai combina **busca determinística + híbrida** com técnicas modernas de RAG, inspiradas nos livros *"A Simple Guide to RAG"* (Abhinav Kimothi) e *"RAG The Seminal Papers"* (Ben Auffarth):

### 1. Busca Determinística (precisão)
Quando a pergunta menciona um artigo/lei específico (ex.: *"art. 54 do Decreto 3048"*), o pipeline busca primeiro por **metadados estruturados** (`artigo`, `tipo_doc`, `numero_doc`) e por **palavra-chave** (regex no conteúdo). Se acha, retorna direto sem depender de embedding — precisão máxima. Só cai na busca semântica se não achar.

### 2. Re-ranking por MMR (Maximal Marginal Relevance)
A busca semântica recupera um top-k **mais largo** (`TOP_K × RERANK_TOP_K_MULTIPLIER`) e re-ranqueia por MMR antes de montar o contexto. O MMR equilibra **relevância** à query com **diversidade** entre os docs — reduzindo redundância (ex.: notas de rodapé da doutrina que duplicam o mesmo trecho). Fator `RERANK_LAMBDA_MULT` controla o trade-off (0.7 = prioriza relevância).

### 3. HyDE (Hypothetical Document Embeddings) + Fusão RRF
Preenche o **vocabulary gap** jurídico: o LLM gera um *documento hipotético* (parágrafo em linguagem jurídica) **sem acessar a base**. O embedding desse documento — com vocabulário do domínio (carência, período de contribuição, salário-de-contribuição...) — recupera chunks parecidos com a *resposta ideal*, casando termos leigos com institutos legais. O resultado é **fundido por Reciprocal Rank Fusion (RRF)** com a busca pela query original, dando **peso `HYDE_QUERY_WEIGHT=1.4`** à query para evitar *drift contextual* (o HyDE complementa, não domina).

> **Nota:** o documento hipotético é embedado como **documento** (prefixo `search_document:`), não como query — ele se parece com o conteúdo indexado, não com a pergunta.

### 4. Recuperação Assimétrica (nomic-embed-text)
O `nomic-embed-text` foi treinado com **prefixos de tarefa** (*asymmetric retrieval*): documentos devem ser vetorizados com `search_document: ` e consultas com `search_query: `. Sem os prefixos o modelo cai para um embedding genérico e a similaridade degrada. O wrapper `app/embeddings.py` (`NomicOllamaEmbeddings`) aplica os prefixos automaticamente antes de chamar o Ollama, mantendo o texto cru armazenado.

> **⚠️ Reindexação obrigatória:** ao ativar/trocar o modelo (ou alterar o esquema de prefixos), toda a base vetorial precisa ser **reindexada** — os vetores antigos ficariam desalinhados com o novo espaço. Use `app/scripts/reindex_embeddings.py`.

### 5. Fact-check / Groundedness (anti-alucinação)
Além da regra de anti-alucinação no prompt, a resposta passa por três barreiras antes de chegar à tela:

1. **Portão de suficiência** (`FACT_CHECK_LLM_ENABLED`): uma chamada curta ao LLM, antes de gerar, perguntando se os trechos recuperados contêm literalmente o dispositivo/dado que a pergunta exige. Resposta "NAO" ⇒ o sistema **não gera resposta** e apresenta a recusa canônica ("Não encontrei a resposta na base…"), com os trechos recuperados ao lado. É o mecanismo da recusa honesta: medido, o limiar de distância **não** separa "a base responde" de "não responde" (top-1 0,15–0,27 dentro da base contra 0,20–0,35 fora, com o `nomic-embed-text`).
2. **Lastro por sentença** (`FACT_CHECK_ENABLED`, determinístico): cada frase com número, prazo, valor ou dispositivo tem de estar apoiada no trecho que **ela cita** — citação `[n]` inexistente, norma com número/ano que o material não registra (ADR-0007) ou dado que está em outro fragmento (`lastro_fora_do_citado`) são reprovados.
3. **Portão de exibição**: veredito `sem_lastro` ⇒ **uma** regeneração com o motivo apontado; persistindo, a resposta **não é exibida** e vira recusa (o texto descartado fica no log de auditoria). Vereditos `parcial` aparecem com aviso de ressalva; `fundamentada` aparece com a confirmação do lastro conferido.

Detalhamento, evidência medida e critérios de aceite: [`docs/PLANO_REFINAMENTO_RAG.md`](docs/PLANO_REFINAMENTO_RAG.md) (Fase 1).

### Fluxo de Retrieval
```
pergunta
  ├─ menciona artigo/lei? ── sim ─▶ busca por metadados ─▶ (acha?) ─▶ retorna
  │                                            └─ não acha ─▶ busca por palavra-chave
  └─ não ─▶ busca semântica
                 └─ HyDE? ─▶ gera doc hipotético (embedado como doc) ─▶ 2 buscas (query + hyde) ─▶ fusão RRF ─▶ MMR
                 └─ não ─▶ busca semântica pura ─▶ MMR

gera resposta (system: persona/regras | human: contexto + pergunta + citações [n])
   └─ fact-check pós-geração (groundedness por sentença)
```

---

## 🔒 Segurança

Revisão completa (com evidências de execução, gravidade e status de cada achado):
**[`docs/REVISAO_SEGURANCA.md`](docs/REVISAO_SEGURANCA.md)**. Plano de ação:
**[`docs/BACKLOG.md`](docs/BACKLOG.md)**.

### Credenciais Externalizadas

Todas as credenciais e configurações sensíveis são lidas de variáveis de ambiente por `app/config.py`. Isso elimina senhas hardcoded no código-fonte.

- `DATABASE_URL`, `OLLAMA_BASE_URL`, `EMBEDDING_MODEL`, `LLM_MODEL` em `config.py`
- Admin inicial criado via `init_admin.py` (o `init.sql` não semeia usuário nenhum)
- `.env.example` fornece o template — o `.env` real está no `.gitignore`
- `COOKIE_KEY` (segredo que assina o cookie de sessão) é **obrigatória** e validada:
  ausente, curta (< 32 bytes) ou com valor conhecido ⇒ a aplicação não inicia

### Isolamento entre Usuários (multi-tenant)

Cada documento tem **dono** (`owner_id`) e escopo (`private`/`global`). Todas as operações
são escopadas por dono — nunca por nome de arquivo:

- a recuperação do chat filtra `scope = 'global' OR owner_id = <usuário>`;
- o dedup da ingestão e a tabela `sources` são únicos por `(file_name, owner_id)`;
- promover para global ou excluir age sobre **um dono por vez** (`owner_id` explícito);
- usuário comum só enxerga e gerencia os próprios documentos (mais os globais).

### Admin na Primeira Execução

O script `init_admin.py` roda após os containers subirem e cria o administrador inicial
com `ADMIN_EMAIL`/`ADMIN_PASSWORD` do `.env`. Ele é idempotente (`ON CONFLICT DO NOTHING`
— rodar de novo não reseta a senha existente) e **falha** com exit code ≠ 0 quando a senha
está ausente, tem menos de 8 caracteres ou é um valor previsível (`admin123`, `admin`,
`password`…). Um banco que ainda tenha a credencial padrão antiga precisa da senha trocada
pelo painel (Gestão de Usuários → Resetar Senha).

---

## 📁 Estrutura do Projeto

```text
├── .env.example              # Template de variáveis de ambiente
├── .gitignore                # Arquivos ignorados pelo git
├── LICENSE.md                # Licença MIT
├── Makefile                  # Comandos automatizados
├── README.md                 # Este arquivo
├── setup.sh                  # Script de setup automatizado
├── docker-compose.yml        # Orquestração Docker com healthchecks
├── app/                      # Código fonte Python
│   ├── main.py               # Interface, navegação e autenticação
│   ├── auth.py               # Lógica de login, hash e permissões
│   ├── agent.py              # Agente RAG com prompts modulares
│   ├── embeddings.py         # Wrapper nomic-embed-text (prefixos assimétricos)
│   ├── config.py             # Configurações centralizadas
│   ├── ingest.py             # Ingestão de documentos
│   ├── manage.py             # Gestão da base de dados
│   ├── ollama_utils.py       # Utilitários Ollama
│   ├── init_admin.py         # Criação de admin inicial
│   ├── providers.py          # Provedores externos de IA
│   ├── prompts/              # SYSTEM: persona + regras de conduta
│   │   └── system-role.md
│   ├── prompts_user/         # HUMAN: contexto + pergunta
│   │   └── context-block.md
│   ├── eval/                 # Avaliador de qualidade do RAG
│   │   ├── run_eval.py       # Roda o questionário e gera relatório JSON
│   │   ├── quiz.json         # Perguntas baseline
│   │   └── relatorios/       # Relatórios gerados (bind-mount, sobrevive a rebuild)
│   ├── scripts/              # Scripts operacionais (rodam no container)
│   │   └── reindex_embeddings.py  # Reindexa a base após mudança de embeddings
│   ├── tests/                # Testes unitários
│   └── requirements.txt      # Dependências Python
├── scripts/                  # Automação de DESENVOLVIMENTO (fora da imagem)
│   ├── db-dev.sh             # banco de dev em podman rootless (start/stop/rm/psql)
│   ├── dev.sh                # app nativa lendo o .env.dev (make dev)
│   ├── smoke_dev.py          # o ambiente está de pé? (RAG ponta a ponta)
│   └── run_tests.sh          # wrapper de compatibilidade -> app/run_tests.sh
├── database/
│   ├── init.sql              # Schema do banco (tabelas + migrações idempotentes)
│   └── migrate_sources_owner.sql  # migração para bases existentes (sources por dono)
├── docs/                     # Documentação complementar
│   ├── EVOLUCAO.md           # diário de bordo: o que foi feito, verificado e o que falta
│   ├── REVISAO_SEGURANCA.md  # achados de segurança/isolamento, com evidência
│   ├── BACKLOG.md            # itens priorizados com critério de aceite
│   ├── AMBIENTE_DEV.md       # ambiente de desenvolvimento + ensaio de paridade
│   ├── adr/                  # decisões de arquitetura (ADR-0001..0005)
│   ├── TESTING.md            # estratégia de testes
│   ├── AGENTS.md             # arquitetura do agente RAG
│   └── ...                   # C4 (dsl/puml/mermaid), planos e schema de teste
└── .github/workflows/
    └── ci.yml                # CI: lint (ruff) · testes · integração · verificação de schema
```

---

## 🧪 Avaliação de Qualidade do RAG

O projeto tem um **avaliador reproduzível** para medir o impacto de mudanças no pipeline, em vez de confiar em impressão subjetiva.

**Como rodar:**

```bash
# Mudou código? Rebuild é obrigatório (sem bind-mount de código)
docker compose build app && docker compose up -d app

# Roda o questionário e grava o relatório (direto no host, via bind-mount)
docker compose exec app python3 eval/run_eval.py --out relatorios/meu_teste.json
```

**Métricas no relatório JSON** (por pergunta):

| Campo | O que mede |
|:---|:---|
| `avg_distance` / `min_distance` | Proximidade vetorial dos chunks recuperados à query |
| `num_sources` | Quantidade de chunks recuperados |
| `source_files` | De quais PDFs vieram as fontes (diversidade) |
| `keyword_recall` | Fração de termos-chave presentes na resposta final |
| `fact_check` | Groundedness da resposta (lastro no contexto) |

> **Dica:** guarde um relatório por versão (`relatorios/antes.json`, `relatorios/depois.json`) e compare campo a campo. Os relatórios ficam em `app/eval/relatorios/`, montado no host — **sobrevivem a rebuilds** do container.

---

## ⚙️ Docker Compose

O arquivo `docker-compose.yml` conta com:

- **Healthchecks** em todos os serviços (`db`, `ollama`, `app`)
- **Dependências condicionais** (`depends_on: condition: service_healthy`)
- **`env_file: .env`** no serviço `app`: **todas** as variáveis do `.env` chegam ao
  container (antes, só uma lista de 9 nomes chegava — ajustar `HYDE_*`, `RERANK_*`,
  `FACT_CHECK_*`, `DB_POOL_*`, `COOKIE_KEY` no `.env` não tinha efeito nenhum)

---

## 🧪 CI/CD

O workflow `.github/workflows/ci.yml` executa em todo `push` e `pull_request`:

- **`lint`** — `ruff` (o linter configurado no `pyproject.toml`; antes rodava `flake8`
  com `--select=E9,F63,F7,F82`, que não cobria as regras do projeto)
- **`test`** — a suíte completa via `app/run_tests.sh` (um módulo por processo)
- **`integration`** — Postgres `pgvector/pgvector:pg16` + `docs/legal_test_schema.sql`,
  com os testes de ingestão e de isolamento entre donos rodando contra o banco
- **`schema`** — aplica `database/init.sql` **duas vezes** (as migrações têm de ser
  idempotentes) e confere as invariantes de segurança do schema: nenhum admin semeado e
  índice único `(file_name, owner_id)` em `sources`

Local: `make test` (roda no container) ou `bash app/run_tests.sh` (no host, com as
dependências instaladas).

---

## 🗺️ Changelog de Melhorias

### 🛡️ Hardening de segurança e isolamento (revisão de 2026-10-16)
- ✅ **Chave do cookie de sessão fora do código** — `COOKIE_KEY` obrigatória, validada
  (ausente/curta/pública ⇒ app não sobe). Antes, o literal `legal_ai_key` versionado
  permitia forjar o cookie de admin.
- ✅ **Schema não semeia mais admin** — removido o `admin@legaliz.ai`/`admin123` do
  `init.sql`; `init_admin.py` exige `ADMIN_PASSWORD` e recusa valores previsíveis
- ✅ **Escopo e exclusão por dono** (`owner_id`), nunca por nome de arquivo: um clique em
  "Tornar Global" não promove mais o documento privado homônimo de outro usuário
- ✅ **Dedup e `sources` por `(file_name, owner_id)`** — o upload do segundo usuário com
  o mesmo nome de arquivo deixa de ser descartado em silêncio
- ✅ **`sources.scope` sincronizado** com `documents.scope` na mesma transação
- ✅ **`env_file` no compose** — todo o `.env` chega ao container
- ✅ **Dependências pinadas** (+ `requirements.lock.txt`) e imports faltantes declarados
- ✅ **Testes/CI de verdade** — runner único cobrindo todos os módulos, `make test`
  funcional, CI com lint + testes + integração + verificação do schema
- ✅ **`setup.sh` valida** `POSTGRES_PASSWORD`, `ADMIN_PASSWORD` e `COOKIE_KEY` **antes**
  de subir os containers

### 📚 Documentação de trabalho
- ✅ **[`docs/EVOLUCAO.md`](docs/EVOLUCAO.md)** — diário de bordo por bloco, com o que foi
  verificado por execução e como retomar depois de uma pausa
- ✅ **[`docs/REVISAO_SEGURANCA.md`](docs/REVISAO_SEGURANCA.md)** e
  **[`docs/BACKLOG.md`](docs/BACKLOG.md)** — achados com evidência e plano priorizado
- ✅ **[`docs/adr/`](docs/adr/README.md)** — decisões de arquitetura (ADR-0001 a 0005:
  segredo do cookie, isolamento por dono, admin inicial, ambiente de desenvolvimento,
  dependências e verificação)
- ✅ **[`docs/AMBIENTE_DEV.md`](docs/AMBIENTE_DEV.md)** — ambiente de desenvolvimento sem
  Docker + checklist de ensaio de paridade

### 🔒 Segurança (Item 1)
- ✅ Credenciais externalizadas para `app/config.py`
- ✅ `.env.example` criado com todas as variáveis documentadas
- ✅ `docker-compose.yml` usa variáveis de ambiente
- ✅ `init.sql` sem dados hardcoded (após a revisão de 2026-10-16)
- ✅ `init_admin.py` para criação segura de admin na primeira execução
- ✅ `setup.sh` verifica `.env` e executa `init_admin.py`
- ✅ `python-dotenv` adicionado ao `requirements.txt` (sem uso hoje — ver P2-17)
- ✅ `.gitignore` criado com `.env`

### 📝 Prompts Modulares (Item 3)
- ✅ Pasta `app/prompts/` (SYSTEM: `system-role.md`) e `app/prompts_user/` (HUMAN: `context-block.md`)
- ✅ Função `load_prompts()` + helper `_load_md_dir()` em `agent.py` carregam prompts dinamicamente
- ✅ Contexto e pergunta na mensagem **human** (nunca no system) — elimina eco/instruction leakage do Llama 3
- ✅ Persona "Clóvis" + regras de ancoragem/veracidade consolidadas em `system-role.md`

### 🏗️ Produto (Item 4)
- ✅ `LICENSE.md` (MIT)
- ✅ `Makefile` com comandos `up`, `down`, `restart`, `logs`, `test`, `shell`, `clean`, `setup`
- ✅ Healthchecks no `docker-compose.yml`
- ✅ `.github/workflows/ci.yml` com linter
- ✅ README.md completo e atualizado

### 🧠 Técnicas de RAG (loop de melhoria contínua)
- ✅ **Citações numeradas `[n]`** — resposta jurídica cita a fonte de cada afirmação
- ✅ **Dedup de documentos** — evita duplicação de chunks idênticos/repetidos
- ✅ **Re-ranking por MMR** — reduz redundância da doutrina/notas de rodapé
- ✅ **Fact-check / Groundedness** — verificação estrutural pós-geração (anti-alucinação)
- ✅ **HyDE + Fusão RRF** — query transformation preenche o vocabulary gap jurídico
- ✅ **HyDE com `embed_document`** — doc hipotético embedado como documento (`search_document:`), não como query
- ✅ **Recuperação assimétrica `nomic-embed-text`** — wrapper `embeddings.py` aplica prefixos de tarefa + script de reindexação
- ✅ **Avaliador de RAG** — `eval/run_eval.py` + questionário baseline, com relatórios persistidos em `eval/relatorios/`
- ✅ **`LLM_MODEL` no `.env`** — respostas funcionam sem config manual (Task 4)

---

## 📄 Licença

Distribuído sob a licença MIT. Veja `LICENSE.md` para mais informações.

---

## 💻 Desenvolvimento local

O ambiente de desenvolvimento (sem Docker: banco em podman, Ollama no host, app em venv)
está documentado em **[`docs/AMBIENTE_DEV.md`](docs/AMBIENTE_DEV.md)** — inclui os
comandos (`make db-dev`, `make dev`, `make test-local`), o smoke test do ambiente
(`scripts/smoke_dev.py`) e o **checklist de ensaio de paridade** antes de release.

**Atualizando uma instalação existente:** se o banco do cliente já tem dados, aplique a
migração de schema antes de subir o container novo — ela consolida fontes duplicadas,
reaponta os chunks e cria o índice único por dono:

```bash
docker exec -i legal-db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -v ON_ERROR_STOP=1 < database/migrate_sources_owner.sql
```

---

## 🗺️ Roadmap de Evolução

- [x] **Sistema de Login:** Autenticação e Roles (Admin/User)
- [x] **Painel Admin:** Gestão de usuários e limites
- [x] **Prompts Modulares:** Prompts em arquivos .md separados
- [x] **Segurança:** Credenciais externalizadas via .env
- [x] **Citações `[n]` + Dedup** — fonte por afirmação + limpeza de duplicatas
- [x] **Re-ranking MMR** — reduz redundância no contexto recuperado
- [x] **Fact-check / Groundedness** — verificador estrutural anti-alucinação
- [x] **HyDE + Fusão RRF** — query transformation para recall jurídico
- [x] **Recuperação assimétrica** — prefixos `search_document:`/`search_query:` (nomic-embed-text)
- [x] **Prompt system/human separados** — fim do eco de diretrizes pelo LLM
- [x] **Avaliador de RAG reproduzível** — mede impacto de mudanças com relatórios versionados
- [x] **`LLM_MODEL` padrão no `.env`** — respostas sem config manual
- [x] **Isolamento de Contexto:** cada documento tem dono; recuperação, gestão, dedup e
  `sources` são escopados por `owner_id` (ver [`docs/REVISAO_SEGURANCA.md`](docs/REVISAO_SEGURANCA.md))
- [ ] **Recall de arquivo no avaliador** — ligar `expected_files` no `quiz.json` (gabarito por pergunta)
- [ ] **Calibração de threshold/TOP_K** — distâncias muito próximas (~0.22) sugerem baixa discriminação
- [ ] **Nota qualitativa manual (1-5)** no avaliador — além de groundedness, medir redação
- [ ] **Redator de Petições:** Gerador estruturado em formato `.docx`
- [ ] **Múltiplos Idiomas:** Suporte a prompts em diferentes idiomas

### Pendências de segurança/infra

O que **ainda falta** antes de expor o sistema a dados reais de cliente está em
[`docs/BACKLOG.md`](docs/BACKLOG.md) (P0-5 TLS/rede, P0-6 rotação de credenciais, P1-1
fact-check, P1-2 estado global do LLM, P1-6 PDF sem texto…).
