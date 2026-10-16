# Estratégia de Testes — Legaliz.ai

Este documento define a estratégia de testes (unitários + integração) do Legaliz.ai,
cobrindo a alteração de embeddings em batch (`EMBED_BATCH_SIZE`) e o fluxo de ingestão.

## Visão Geral

| Camada | O que valida | Dependências | Onde |
|---|---|---|---|
| **Unitário** | Lógica pura (parser, validações, agrupamento de batch) | Nenhuma (mocks) | `app/tests/test_*.py` |
| **Integração** | Persistência real (pgvector), metadados jurídicos, busca semântica | Postgres pgvector via Docker | `app/tests/test_integration_ingest.py` |
| **E2E (futuro)** | Fluxo Streamlit + Ollama completo | Docker Compose | não implementado ainda |

## Estrutura

```
app/
├── ingest.py                # código sob teste (batch de embeddings, dedup por dono)
├── legal_parser.py          # extração de metadados jurídicos
├── manage.py                # gestão de documentos (escopo/exclusão por dono)
├── auth.py                  # autenticação
├── init_admin.py            # admin inicial (não aceita senha padrão)
├── config.py                # config centralizada (inclui cookie_key_problem)
├── run_tests.sh             # runner: todos os tests/test_*.py, um por processo
└── tests/
    ├── __init__.py
    ├── test_auth.py                    # validações + CRUD com mocks
    ├── test_backfill_sources.py        # upsert de sources por (arquivo, dono)
    ├── test_config_cookie.py           # validação da chave do cookie de sessão
    ├── test_init_admin.py              # admin inicial sem senha padrão
    ├── test_management.py              # escopo/exclusão por dono (mocks)
    ├── test_legal_parser.py            # parser — puros
    ├── test_ingest.py                  # batch, NUL, progresso, dedup por dono
    ├── test_regime_db.py               # busca por metadados/keyword (conn_factory)
    ├── test_agent.py                   # ranking/MMR/RRF e fact-check
    ├── test_integration_ingest.py      # integração — pgvector real
    └── test_integration_tenancy.py     # integração — isolamento entre donos
```

## Como rodar

### Unitários (rápidos, sem dependências)

Os testes **unitários mockam `psycopg2`/`pgvector`/`langchain*` no `import`** (padrão do
projeto). Por isso devem rodar **um arquivo por processo** (executar vários no mesmo
processo causa colisão dos `sys.modules` mockados). Use o runner — ele descobre
automaticamente todos os `tests/test_*.py` e imprime o total de casos:

```bash
# a partir da raiz do repositório
bash app/run_tests.sh          # no host (exige as deps instaladas)
make test                      # dentro do container (ambiente real)
make test-local                # no host, via Makefile
```

> A lista de módulos **não** é fixa: adicionar `tests/test_novo.py` já o inclui na
> execução local e no CI. (A versão anterior do runner tinha 4 módulos fixos, então 5
> arquivos — incluindo o `test_agent.py` — nunca eram executados.)

### Integração (requer Postgres pgvector)

Os testes de integração usam um banco **pgvector real** com o schema de `documents`/`users`
(user/password, portas abaixo). Se o banco não estiver disponível, são **pulados** (skip),
não falham.

Suba o banco de teste (porta **5440**, isolada — não conflita com o app na 5439):

```bash
docker run -d --name legal-test-db \
  -e POSTGRES_USER=user -e POSTGRES_PASSWORD=password -e POSTGRES_DB=legal_test \
  -p 5440:5432 pgvector/pgvector:pg16

# aplicar o schema de teste
docker exec -i legal-test-db psql -U user -d legal_test -v ON_ERROR_STOP=1 \
  < docs/legal_test_schema.sql
```

Rode (num venv com `app/requirements.txt` instalado):

```bash
cd app
TEST_DATABASE_URL="postgresql://user:password@localhost:5440/legal_test" \
  python3 -m unittest tests.test_integration_ingest -v
TEST_DATABASE_URL="postgresql://user:password@localhost:5440/legal_test" \
  python3 -m unittest tests.test_integration_tenancy -v
```

Para parar/limpar: `docker rm -f legal-test-db`.

## O que os testes cobrem (alteração de batch)

### `test_ingest.py` (unit)
- **`embed_documents` recebe os lotes corretos** — com 10 chunks e batch=4, garante 3 chamadas
  (4, 4, 2) e progresso = 1.0 no final.
- **Default usa `EMBED_BATCH_SIZE`** da config (128).
- **Filtro de NUL (0x00)** antes de inserir — chunks com byte nulo são descartados
  (contornava erros de `pgvector`).
- **Chunks vazios** não chamam o embedder.

### `test_integration_ingest.py` (integração)
- **Persistência real** — após `store_in_postgres`, o banco tem os registros certos,
  com `artigo`, `tipo_doc`, `numero_doc`, `scope` e vetor de 768 dims.
- **Filtro NUL de verdade** — o registro com byte nulo não entra no banco.
- **Busca semântica** — após inserir, consulta por similaridade (`embedding <->`) retorna
  o chunk mais parecido com distância ~0 (ponta a ponta).

### `test_integration_tenancy.py` (integração)
- **Dedup por dono** — o upload do segundo usuário com o mesmo nome de arquivo é
  indexado de verdade (antes era 100% descartado).
- **`sources` por dono** — fontes homônimas coexistem; o upsert não troca o dono da linha
  existente e cada chunk aponta para a fonte do próprio dono.
- **Escopo por dono** — promover/excluir o arquivo de um dono não altera o homônimo de
  outro; `sources.scope` acompanha `documents.scope`.
- **Regras de acesso** — usuário comum não gerencia documento alheio; escopo inválido é
  recusado; operação sem `user_id` falha em vez de varrer a base.

### `test_legal_parser.py` (unit)
- Extração de `artigo`, `parágrafo`, `inciso` e metadados de nome de arquivo
  (decreto/lei/constituição, números, anos, padrão Planalto `L14126.pdf`).

## Achados durante a montagem da estratégia

1. ~~`app/init.sql` tem bug de ordem~~ — **resolvido/verificado**: no
   `database/init.sql` atual a tabela `users` é criada antes de `documents`, e o CI aplica
   o arquivo inteiro em banco vazio (duas vezes, para checar idempotência) sem erro.
2. **`test_management.py` (antigo) estava quebrado**: mockava `manage.get_db_cursor`, mas
   `manage.py` usa `psycopg2.connect` direto. Foi reescrito com mocks corretos.
3. ~~`test_auth.py` tem 1 erro pré-existente~~ — **resolvido**: o módulo passa (12 casos).
4. **Mocks de infra precisam ser instalados no nível do módulo**, antes do primeiro import
   do código sob teste (`init_admin`/`auth` importam `psycopg2`/`bcrypt` no topo). Dentro
   de `setUpModule()` é tarde: o import já aconteceu.

## Próximos passos sugeridos (roadmap de testes)
- [x] Ampliar o runner para todos os módulos (feito em `app/run_tests.sh`).
- [x] Integração de isolamento entre donos (`test_integration_tenancy.py`).
- [ ] Testes de integração para `agent._parse_article_reference` / `_metadata_search`.
- [ ] Testes para `factcheck._fact_check_answer` com respostas reais do modelo.
- [ ] E2E: subir Docker Compose e testar upload real de PDF + ingest com Ollama.
