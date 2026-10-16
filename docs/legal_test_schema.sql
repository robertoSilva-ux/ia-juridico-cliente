-- Schema para banco de teste de integracao (porta 5440)
-- Ordem correta: users ANTES de documents (corrige o bug de ordem do init.sql)
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(50) NOT NULL DEFAULT 'user',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS documents (
    id SERIAL PRIMARY KEY,
    file_name TEXT,
    content TEXT,
    metadata JSONB,
    embedding vector(768),
    uploaded_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    owner_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    scope VARCHAR(10) DEFAULT 'private' CHECK (scope IN ('private', 'global')),
    artigo INTEGER,
    paragrafo VARCHAR(10),
    inciso VARCHAR(20),
    tipo_doc VARCHAR(50),
    numero_doc VARCHAR(20),
    ano_doc VARCHAR(4)
);

CREATE TABLE IF NOT EXISTS sources (
    id SERIAL PRIMARY KEY,
    file_name TEXT NOT NULL,
    title TEXT,
    tipo_doc VARCHAR(50),
    numero_doc VARCHAR(20),
    ano_doc VARCHAR(4),
    uploaded_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    owner_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    scope VARCHAR(10) DEFAULT 'private'
);

-- Mesma unicidade do database/init.sql: (file_name, dono), com dono nulo como um
-- único "sem dono" (COALESCE(owner_id, -1)) — em índice único NULL é distinto de
-- NULL, então sem a expressão o `ON CONFLICT` da ingestão não casaria para as
-- cargas sem dono. Sem este índice, a ingestão quebra neste banco de teste.
ALTER TABLE sources DROP CONSTRAINT IF EXISTS sources_file_name_key;
DROP INDEX IF EXISTS sources_file_name_owner_uidx;
CREATE UNIQUE INDEX IF NOT EXISTS sources_file_owner_uidx
    ON sources (file_name, COALESCE(owner_id, -1));

ALTER TABLE documents ADD COLUMN IF NOT EXISTS source_id INTEGER REFERENCES sources(id) ON DELETE CASCADE;

-- Colunas acrescentadas no bloco 7 (R-12/R-13) e no R-24 — espelham `database/init.sql`.
-- Este arquivo é o schema do banco de INTEGRAÇÃO do CI, e ele ficou para trás quando as
-- colunas entraram: o job de integração só quebrou quando o código que as grava subiu
-- (`column "content_hash" of relation "documents" does not exist` na hora de GRAVAR, não
-- antes). Quem mexer no schema: atualize os dois arquivos.
ALTER TABLE documents ADD COLUMN IF NOT EXISTS content_hash TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS pagina INTEGER;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS ordem INTEGER;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS tipo_trecho VARCHAR(20) DEFAULT 'dispositivo';

-- O `ON CONFLICT (file_name, COALESCE(owner_id, -1), content_hash)` da ingestão exige um
-- índice único equivalente, senão o INSERT falha com "no unique or exclusion constraint
-- matching the ON CONFLICT specification". Definição idêntica à do `init.sql`.
CREATE UNIQUE INDEX IF NOT EXISTS documents_file_owner_hash_uidx
    ON documents (file_name, COALESCE(owner_id, -1), content_hash);

CREATE INDEX IF NOT EXISTS idx_documents_artigo ON documents (artigo);
CREATE INDEX IF NOT EXISTS idx_documents_file_name ON documents (file_name);

-- usuario de teste (owner_id=1, usado pelo test_integration_ingest)
INSERT INTO users (email, name, password_hash, role) 
VALUES ('test@legaliz.ai', 'Teste', 'x', 'user') ON CONFLICT (email) DO NOTHING;