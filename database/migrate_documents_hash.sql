-- Migração para base EXISTENTE: dedup de fragmento garantido pelo banco (P2-16 / R-12).
--
-- Mesmos comandos do bloco correspondente em `database/init.sql` (a diferença é só a
-- intenção: aqui é a migração a rodar uma vez num banco em uso). Idempotente: pode rodar
-- de novo sem efeito.
--
--   psql "$DATABASE_URL" -f database/migrate_documents_hash.sql
--
-- Ordem importa: preencher o hash -> consolidar duplicatas -> criar o índice único. Num
-- banco com duplicatas, o CREATE UNIQUE INDEX falha (foi por isso que a migração de
-- `sources` também consolida antes).
--
-- Antes de rodar em produção, faça backup do volume/banco: a consolidação APAGA linhas
-- duplicadas (mantém o menor id de cada grupo, que é o que a ingestão teria gravado).

BEGIN;

ALTER TABLE documents ADD COLUMN IF NOT EXISTS content_hash TEXT;

UPDATE documents
   SET content_hash = md5(content)
 WHERE content_hash IS NULL
   AND content IS NOT NULL;

-- Quantas duplicatas existem (informativo: aparece na saída do psql).
SELECT count(*) AS duplicatas_a_consolidar
  FROM (
    SELECT 1
      FROM documents
     WHERE content_hash IS NOT NULL
     GROUP BY file_name, COALESCE(owner_id, -1), content_hash
    HAVING count(*) > 1
  ) AS grupos;

WITH duplicatas AS (
    SELECT id,
           MIN(id) OVER (PARTITION BY file_name, COALESCE(owner_id, -1), content_hash) AS manter
    FROM documents
    WHERE content_hash IS NOT NULL
)
DELETE FROM documents d
 USING duplicatas
 WHERE d.id = duplicatas.id
   AND duplicatas.id <> duplicatas.manter;

CREATE UNIQUE INDEX IF NOT EXISTS documents_file_owner_hash_uidx
    ON documents (file_name, COALESCE(owner_id, -1), content_hash);

COMMIT;
