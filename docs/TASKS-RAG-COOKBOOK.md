# Legaliz.ai — Task List: Melhorias inspiradas no Cookbook RAG (ai-sdk.dev)

> **Fonte:** revisão do guia https://ai-sdk.dev/cookbook/guides/rag-chatbot
> comparada com o estado atual do código do Legaliz.ai (2026-09-24).
>
> **Conclusão do diagnóstico:** o motor de RAG do Legaliz.ai já está MUITO à
> frente do tutorial (embeddings assimétricos, chunking jurídico, HyDE+RRF,
> MMR, busca híbrida, fact-check). Os itens abaixo são **gaps reais** de
> performance, rastreabilidade e robustez identificados na comparação.

---

## Status

| # | Task | Prioridade | Status |
|---|------|-----------|--------|
| 6 | **Índice vetorial (HNSW/IVFFlat) na coluna `embedding`** | 🔴 Alta | ✅ concluída (commit `5e2aca8`) |
| 7 | **Rastreabilidade de fonte — tabela `sources` + FK nos chunks** | 🔴 Alta | ✅ concluída (commit `9325283`) |
| 8 | **Retry/backoff na ingestão de embeddings (Ollama)** | 🟡 Média | ✅ concluída (commit `8dd4448`) |
| 9 | Revisar `SIMILARITY_THRESHOLD=0.80` e `TOP_K=5` (recall) | 🟡 Média | 🟡 helper pronto (`sweep_tuning.py`, `7b5021f`); aguarda stack |
| 10 | Limpeza: deduplicar `tipo_map` no `legal_parser.py` | ⚪ Baixa | ✅ concluída (commit `9325283`) |

> Números continuam a sequência existente (0–5 já concluídos no docs/TASKS.md).

---

## Detalhamento

### 🔴 Task 6 — Índice vetorial na coluna `embedding`

**Problema:** `database/init.sql` cria índices apenas nos metadados jurídicos
(`idx_documents_artigo`, `idx_documents_tipo_numero`, `idx_documents_file_name`).
Nenhum índice na coluna `embedding vector(768)` — a busca semântica
(`_semantic_search`) faz **scan sequencial** da tabela inteira a cada query.

**Impacto:** latência crescente conforme a base cresce (milhares de chunks,
backup de ~61 MB). O cookbook do ai-sdk.dev é explícito sobre este ponto
(index `hnsw` com `vector_cosine_ops`).

**Melhoria proposta (SQL):**

```sql
-- IVFFlat: mais rápido de construir, adequado para base pequena/média.
-- Requer `SET ivfflat.probes` para consulta (default 1).
CREATE INDEX IF NOT EXISTS idx_documents_embedding
ON documents
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

-- Alternativa HNSW (melhor recall, construção mais pesada):
-- CREATE INDEX IF NOT EXISTS idx_documents_embedding_hnsw
-- ON documents USING hnsw (embedding vector_cosine_ops);
```

**Observações:**
- O índice depende de onde a busca está inserindo/consultando. Confirmar se o
  `_semantic_search` consulta direto a coluna `embedding` (não via
  `embedding <=> %s::vector` com filtro) para o índice ser usado.
- Após criar, rodar `ANALYZE documents`.
- Não há custo de reindexação dos textos (só do índice vetorial em si).

**Arquivos afetados:** `database/init.sql` (novo índice + migration idempotente).

---

### 🔴 Task 7 — Rastreabilidade de fonte (tabela `sources` + FK)

**Problema:** o modelo atual usa **uma única tabela `documents`** onde cada linha
já é um *chunk*. O cookbook separa `resources` (documento-fonte) de
`embeddings` (chunks com FK para o recurso). Sem essa separação, o Legaliz.ai
não tem uma entidade "documento" com metadados ricos (título oficial, ementa,
data), o que limita a citação precisa da fonte legal.

**Relação direta:** este é exatamente o objetivo do branch aberto
`feat/citacoes-fonte-legal`.

**Melhoria proposta (esquema):**

```sql
-- Entidade "documento-fonte" (o PDF original indexado)
CREATE TABLE IF NOT EXISTS sources (
    id SERIAL PRIMARY KEY,
    file_name TEXT NOT NULL,          -- nome original do arquivo
    title TEXT,                       -- título oficial / ementa (opcional)
    tipo_doc VARCHAR(50),             -- lei, decreto, jurisprudencia...
    numero_doc VARCHAR(20),
    ano_doc VARCHAR(4),
    uploaded_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    owner_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    scope VARCHAR(10) DEFAULT 'private',
    UNIQUE (file_name)               -- evita reindexar o mesmo arquivo
);

-- chunks passam a referenciar a fonte (mantém columns existentes)
ALTER TABLE documents ADD COLUMN IF NOT EXISTS source_id INTEGER
    REFERENCES sources(id) ON DELETE CASCADE;
```

**Benefício:** resposta pode citar "Lei 8.213/91, Art. 54, § 1º" com
rastreabilidade completa até o documento original (título + número + ano),
sem depender só do `file_name` parseado.

**Arquivos afetados:** `database/init.sql`, `ingest.py` (inserir em `sources`
antes dos chunks), `agent.py` (retornar `source_id`/titulo na resposta),
`legal_parser.py` (extrair título/ementa).

---

### 🟡 Task 8 — Retry/backoff na ingestão de embeddings (Ollama)

**Problema:** `ingest.py:store_in_postgres` chama
`embeddings_model.embed_documents(texts)` em lote (`EMBED_BATCH_SIZE=128`), mas
sem tratamento de retry. Se o Ollama cair/rate-limitar no meio, o lote inteiro
falha e aborta a ingestão.

**Melhoria proposta:**
- Envolver a chamada de embedding em retry com backoff exponencial
  (ex.: 3 tentativas, `delay = 2^tentativa` segundos).
- Em falha definitiva, logar e pular o lote (ou marcar para reindexação),
  em vez de abortar o documento inteiro.
- Registrar progresso real por lote para permitir retomada (já existe
  `chunks` reutilizável no `ingest_document`).

**Arquivos afetados:** `ingest.py`.

---

### 🟡 Task 9 — Revisar `SIMILARITY_THRESHOLD` e `TOP_K`

**Problema:** `config.py` tem `SIMILARITY_THRESHOLD=0.80` (cosseno) e `TOP_K=5`.
Valores conservadores que podem estar cortando contexto jurídico relevante —
especialmente combinados com o reranking MMR (que já reduz `TOP_K*3` → `TOP_K`).

**Melhoria proposta:**
- Rodar o eval existing (quiz baseline) variando `TOP_K` (5→8) e threshold
  (0.80→0.70) e medir impacto em recall/precisão.
- Documentar o trade-off no `docs/plano_melhoria_modelo_prompt_recuperacao.md`.

**Arquivos afetados:** `config.py` (defaults), docs de eval.

---

### ⚪ Task 10 — Limpeza: deduplicar `tipo_map` no `legal_parser.py`

**Problema:** `parse_file_name` tem a chave `'lei complementar'` duplicada no
dicionário `tipo_map` (linhas coladas). Cosmético, mas sinal de manutenção.

**Melhoria:** remover a linha duplicada. Trivial, baixo risco.

**Arquivos afetados:** `legal_parser.py`.

---

## Ordem sugerida de execução

1. **Task 6** (índice vetorial): maior ganho de performance por menor esforço;
   reversível e não exige reindexar textos.
2. **Task 7** (tabela `sources`): fecha o branch `feat/citacoes-fonte-legal` e
   agrega valor jurídico real; é a mais trabalhosa (toca ingest + agent).
3. **Task 8** (retry na ingestão): robustez essencial antes de rodar a stack
   continuamente em produção.
4. **Task 9** (threshold/TOP_K): tuning de recall — fazer depois de 6 e 7
   estabilizados, usando o eval para medir.
5. **Task 10** (limpeza): encaixa em qualquer commit.

## Notas técnicas

- Stack continua desligada (containers `legal-app`, `legal-db`, `legal-ollama`
  em `Exited` há ~3 dias). Para testar Tasks 6–9 é preciso subir a stack:
  `docker compose up -d`.
- Backups recentes disponíveis em `.backups/` (último: `backup_pre_reingest_20260921_0024.dump`).
- Migração do índice vetorial (Task 6) deve ser feita em migration idempotente
  (não só no `init.sql`), para não quebrar bases já existentes.
