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
├── ingest.py                # código sob teste (batch de embeddings)
├── legal_parser.py          # extração de metadados jurídicos
├── manage.py                # gestão de documentos
├── auth.py                  # autenticação
└── tests/
    ├── __init__.py
    ├── test_auth.py         # (pré-existente)
    ├── test_management.py   # gestão com mocks
    ├── test_legal_parser.py # parser — 21 casos, puros
    ├── test_ingest.py       # unit — batch, NUL, progresso
    └── test_integration_ingest.py  # integração — banco pgvector real
```

## Como rodar

### Unitários (rápidos, sem dependências)

Os testes **unitários mockam `psycopg2`/`pgvector` no `import`** (padrão do projeto).
Por isso devem rodar **um arquivo por vez** (executar vários no mesmo processo causa
colisão dos `sys.modules` mockados). Use o runner:

```bash
cd app
bash ../scripts/run_tests.sh          # unitários (cada arquivo isolado)
```

ou manualmente:

```bash
cd app
python3 -m unittest tests.test_legal_parser -v
python3 -m unittest tests.test_ingest -v
python3 -m unittest tests.test_management -v
```

### Integração (requer Postgres pgvector)

Os testes de integração usam um banco **pgvector real** com o schema de `documents`/`users`
(user/password, portas abaixo). Se o banco não estiver disponível, são **pulados** (skip),
não falham.

Suba o banco de teste (porta **5440**, isolada — não conflita com o app na 5439):

```bash
docker run -d --name legal-test-db \
  -e POSTGRES_USER=user -e POSTGRES_PASSWORD=password -e POSTGRES_DB=legal_test \
  -p 5440:5432 ankane/pgvector

# aplicar o schema (USERS ANTES de DOCUMENTS — o init.sql do app tem bug de ordem)
docker cp /tmp/legal_test_schema.sql legal-test-db:/schema.sql
docker exec legal-test-db psql -U user -d legal_test -v ON_ERROR_STOP=1 -f /schema.sql
```

Rode (num venv com `psycopg2-binary` e `pgvector`):

```bash
cd app
TEST_DATABASE_URL="postgresql://user:password@localhost:5440/legal_test" \
  python3 -m unittest tests.test_integration_ingest -v
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

### `test_legal_parser.py` (unit)
- Extração de `artigo`, `parágrafo`, `inciso` e metadados de nome de arquivo
  (decreto/lei/constituição, números, anos, padrão Planalto `L14126.pdf`).

## Achados durante a montagem da estratégia

1. **`app/init.sql` tem bug de ordem**: cria `documents` (com FK p/ `users`) **antes**
   da tabela `users`. Em banco novo quebra. O app só funciona porque o banco já existia.
   Correção recomendada em separado (fora do escopo desta tarefa).
2. **`test_management.py` (antigo) estava quebrado**: mockava `manage.get_db_cursor`,
   mas `manage.py` usa `psycopg2.connect` direto. Foi reescrito com mocks corretos.
3. **`test_auth.py` tem 1 erro pré-existente** (`test_get_all_users` — mock de cursor
   sem `__getitem__`). Fora do escopo; documentado aqui.

## Próximos passos sugeridos (roadmap de testes)
- [ ] Corrigir `database/init.sql` (ordem users → documents) e testar com banco limpo.
- [ ] Corrigir `test_auth.py::test_get_all_users` (mock `RealDictCursor` com `__getitem__`).
- [ ] Testes de integração para `agent._parse_article_reference` / `_metadata_search`.
- [ ] E2E: subir Docker Compose e testar upload real de PDF + ingest com Ollama.
