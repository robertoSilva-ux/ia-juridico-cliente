-- Migração: unicidade de `sources` por (arquivo, DONO), com dono nulo tratado
-- como um único "sem dono".
--
-- Contexto (ver docs/REVISAO_SEGURANCA.md, P0-4): a unicidade era `UNIQUE
-- (file_name)`, o que fazia o upsert da ingestão sobrescrever owner/scope da
-- fonte de OUTRO usuário quando dois arquivos tinham o mesmo nome.
--
-- Por que a expressão COALESCE(owner_id, -1) e não só (file_name, owner_id):
-- em índice único, NULL é distinto de NULL. Com a coluna crua, o
-- `ON CONFLICT (file_name, owner_id)` NUNCA casa quando o dono é nulo — que é o
-- caso das cargas em lote/legado (`scripts/indexar_lote.py` usa --owner-id None,
-- e é assim que o corpus de leis "global" entra). Resultado: cada carga inseria
-- uma NOVA linha de sources em vez de atualizar a existente.
--
-- Idempotente: pode ser rodada mais de uma vez.
--
-- Uso (no servidor, com o banco no ar):
--   docker exec -i legal-db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
--     -v ON_ERROR_STOP=1 < database/migrate_sources_owner.sql

BEGIN;

-- 1. Remove a unicidade antiga (só file_name) e o índice intermediário.
ALTER TABLE sources DROP CONSTRAINT IF EXISTS sources_file_name_key;
DROP INDEX IF EXISTS sources_file_name_owner_uidx;

-- 2. Consolida duplicatas de "sem dono" (owner_id IS NULL) acumuladas antes
--    desta migração. ORDEM IMPORTA: `documents.source_id` tem ON DELETE CASCADE,
--    então os chunks precisam ser reapontados para a linha que fica ANTES de as
--    duplicatas serem removidas — caso contrário o delete levaria os chunks.
WITH duplicatas AS (
    SELECT id,
           MIN(id) OVER (PARTITION BY file_name, COALESCE(owner_id, -1)) AS manter
    FROM sources
    WHERE owner_id IS NULL
)
UPDATE documents d
   SET source_id = duplicatas.manter
  FROM duplicatas
 WHERE d.source_id = duplicatas.id
   AND duplicatas.id <> duplicatas.manter;

WITH duplicatas AS (
    SELECT id,
           MIN(id) OVER (PARTITION BY file_name, COALESCE(owner_id, -1)) AS manter
    FROM sources
    WHERE owner_id IS NULL
)
DELETE FROM sources s
 USING duplicatas
 WHERE s.id = duplicatas.id
   AND duplicatas.id <> duplicatas.manter;

-- 3. O novo índice único: um arquivo por dono, e "sem dono" como um único bucket.
--    (-1 é seguro como sentinela: `owner_id` tem FK para users(id) e SERIAL
--    começa em 1, então -1 nunca colide com um usuário real.)
CREATE UNIQUE INDEX IF NOT EXISTS sources_file_owner_uidx
    ON sources (file_name, COALESCE(owner_id, -1));

COMMIT;
