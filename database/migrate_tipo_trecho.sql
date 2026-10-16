-- Migração: coluna `tipo_trecho` em `documents` (R-24).
--
-- Papel do trecho no documento: `dispositivo` é texto de artigo — o que o fact-check confere
-- contra a lei — e `preambulo` é capa, apresentação, lista de leis alteradoras e comentário
-- de apostila, isto é, texto do documento que NÃO é dispositivo. Existe para a interface não
-- apresentar comentário como se fosse texto de lei.
--
-- Por que este arquivo existe, se o `init.sql` já traz a coluna: o `init.sql` roda apenas na
-- CRIAÇÃO do volume (`docker-entrypoint-initdb.d`). Numa base que já tem dados ele não é
-- executado — e a ingestão passa a falhar com `column "tipo_trecho" does not exist`. Rode
-- este arquivo uma vez em cada base existente:
--
--   podman exec legal-dev-db psql -U user -d legal_db -f - < database/migrate_tipo_trecho.sql
--
-- Idempotente: pode rodar de novo sem efeito colateral. O DEFAULT preenche as linhas já
-- existentes como `dispositivo`, que é o que elas são (foram ingeridas antes do R-24).

ALTER TABLE documents ADD COLUMN IF NOT EXISTS tipo_trecho VARCHAR(20) DEFAULT 'dispositivo';

-- Nenhuma linha deve ficar sem valor: o DEFAULT cobre as existentes, mas uma base que já
-- tenha recebido ALTER manual (ou um INSERT explícito com NULL) precisa disto.
UPDATE documents SET tipo_trecho = 'dispositivo' WHERE tipo_trecho IS NULL;

-- Conferência (deve devolver a contagem por papel):
--   SELECT tipo_trecho, count(*) FROM documents GROUP BY 1;
