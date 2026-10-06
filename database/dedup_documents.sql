-- =============================================================
-- dedup_documents.sql
-- Remove duplicatas de conteúdo na tabela documents.
--
-- Contexto: alguns PDFs foram ingeridos mais de uma vez, gerando
-- chunks com EXATAMENTE o mesmo conteúdo (mesmo file_name) mas ids
-- diferentes. Isso polui a busca semântica (TOP_K lotado com cópias)
-- e desperdiça o limite de contexto do LLM.
--
-- Regra: para cada (file_name, content) duplicado, mantém o MENOR id
-- (a cópia original) e remove as demais.
--
-- Uso:
--   docker exec legal-db psql -U user -d legal_db -f /path/dedup_documents.sql
--
-- A contagem de linhas afetadas aparece ao final (delete count).
-- =============================================================

-- 1. (Opcional) Pré-visualização — quantas duplicatas por arquivo
--    Descomente para inspecionar antes de deletar:
-- SELECT file_name,
--        count(*) AS total,
--        count(DISTINCT content) AS unicos,
--        count(*) - count(DISTINCT content) AS duplicados
-- FROM documents
-- GROUP BY file_name
-- HAVING count(*) - count(DISTINCT content) > 0
-- ORDER BY duplicados DESC;

-- 2. Remove as cópias duplicadas, mantendo a de menor id
DELETE FROM documents a
USING documents b
WHERE a.id > b.id
  AND a.file_name = b.file_name
  AND a.content = b.content;

-- 3. Confirmação do estado final
SELECT file_name,
       count(*) AS total,
       count(DISTINCT content) AS unicos,
       count(*) - count(DISTINCT content) AS duplicados_restantes
FROM documents
GROUP BY file_name
HAVING count(*) - count(DISTINCT content) > 0;
