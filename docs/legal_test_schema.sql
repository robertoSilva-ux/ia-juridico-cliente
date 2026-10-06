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
    file_name TEXT NOT NULL UNIQUE,
    title TEXT,
    tipo_doc VARCHAR(50),
    numero_doc VARCHAR(20),
    ano_doc VARCHAR(4),
    uploaded_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    owner_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    scope VARCHAR(10) DEFAULT 'private'
);

ALTER TABLE documents ADD COLUMN IF NOT EXISTS source_id INTEGER REFERENCES sources(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS idx_documents_artigo ON documents (artigo);
CREATE INDEX IF NOT EXISTS idx_documents_file_name ON documents (file_name);

-- usuario de teste (owner_id=1, usado pelo test_integration_ingest)
INSERT INTO users (email, name, password_hash, role) 
VALUES ('test@legaliz.ai', 'Teste', 'x', 'user') ON CONFLICT (email) DO NOTHING;