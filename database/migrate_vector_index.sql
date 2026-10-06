-- =============================================================
-- migrate_vector_index.sql
-- Cria índice vetorial IVFFlat na coluna embedding (cosine distance).
--
-- Contexto: antes deste índice a busca semântica (_semantic_search)
-- fazia scan sequencial da tabela documents inteira a cada query
-- (embedding <=> %s::vector). Com o IVFFlat, queries de similaridade
-- se tornam eficientes conforme a base cresce.
--
-- Idempotente: usa CREATE INDEX IF NOT EXISTS.
-- Executar dentro do container:
--   docker exec legal-db psql -U user -d legal_db -f /path/migrate_vector_index.sql
--
-- Nota: IVFFlat exige SET ivfflat.probes = N para bons resultados.
-- Para uma base pequena/média, probes=10 é um bom trade-off recall/latência.
-- =============================================================

CREATE INDEX IF NOT EXISTS idx_documents_embedding
ON documents
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

ANALYZE documents;
