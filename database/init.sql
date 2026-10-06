CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================================
-- 1. Tabelas base (sem FK para outras tabelas do projeto)
-- ============================================================

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(50) NOT NULL DEFAULT 'user',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS system_settings (
    key VARCHAR(100) PRIMARY KEY,
    value TEXT NOT NULL
);

-- ============================================================
-- 2. Tabelas com FK para users / dependentes
-- ============================================================

CREATE TABLE IF NOT EXISTS documents (
    id SERIAL PRIMARY KEY,
    file_name TEXT,
    content TEXT,
    metadata JSONB,
    embedding vector(768),
    uploaded_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    owner_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    scope VARCHAR(10) DEFAULT 'private' CHECK (scope IN ('private', 'global')),
    -- Metadados jurídicos estruturados
    artigo INTEGER,
    paragrafo VARCHAR(10),
    inciso VARCHAR(20),
    tipo_doc VARCHAR(50),
    numero_doc VARCHAR(20),
    ano_doc VARCHAR(4)
);

-- Índices para busca por metadados jurídicos
CREATE INDEX IF NOT EXISTS idx_documents_artigo ON documents (artigo);
CREATE INDEX IF NOT EXISTS idx_documents_tipo_numero ON documents (tipo_doc, numero_doc);
CREATE INDEX IF NOT EXISTS idx_documents_file_name ON documents (file_name);
-- Índice vetorial para busca semântica (cosine distance). IVFFlat acelera
-- queries 'embedding <=> %s::vector' quando a base cresce (ver migrate_vector_index.sql).
CREATE INDEX IF NOT EXISTS idx_documents_embedding ON documents USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- Migração segura para tabelas existentes sem as colunas
ALTER TABLE documents ADD COLUMN IF NOT EXISTS owner_id INTEGER REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS scope VARCHAR(10) DEFAULT 'private' CHECK (scope IN ('private', 'global'));

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

-- Chunks passam a referenciar a fonte (coluna adicionada de forma idempotente).
ALTER TABLE documents ADD COLUMN IF NOT EXISTS source_id INTEGER REFERENCES sources(id) ON DELETE CASCADE;

CREATE TABLE IF NOT EXISTS audit_log (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    user_email VARCHAR(255),
    question TEXT NOT NULL,
    response_summary TEXT,
    sources_used TEXT[],
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- 3. Dados iniciais
-- ============================================================

-- Inserir limite padrão de usuários se não existir
INSERT INTO system_settings (key, value) VALUES ('max_users', '10') ON CONFLICT DO NOTHING;

-- Inserir usuário administrador padrão (Senha: admin123)
INSERT INTO users (email, name, password_hash, role)
VALUES ('admin@legaliz.ai', 'Administrador', '$2b$12$tTamqrN04JqcD616achOFOZOglw.gbwhrC0gxeh1JFnzEtHzsdBMe', 'admin')
ON CONFLICT (email) DO NOTHING;