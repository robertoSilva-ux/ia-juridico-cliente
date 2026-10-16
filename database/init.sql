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
    file_name TEXT NOT NULL,
    title TEXT,
    tipo_doc VARCHAR(50),
    numero_doc VARCHAR(20),
    ano_doc VARCHAR(4),
    uploaded_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    owner_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    scope VARCHAR(10) DEFAULT 'private'
);

-- Unicidade da fonte é por (arquivo, DONO) — nunca só pelo nome do arquivo.
-- Dois usuários podem subir "peticao.pdf" cada um, e a versão anterior
-- (UNIQUE só em file_name) fazia o upsert do segundo sobrescrever owner/scope
-- da fonte do primeiro: metadado de um tenant apontando para outro.
-- Idempotente: derruba a constraint antiga se existir e garante o índice novo.
ALTER TABLE sources DROP CONSTRAINT IF EXISTS sources_file_name_key;
CREATE UNIQUE INDEX IF NOT EXISTS sources_file_name_owner_uidx ON sources (file_name, owner_id);

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

-- ============================================================
-- NOTA: o usuário administrador NÃO é criado aqui.
-- ============================================================
-- O schema não deve semear credencial nenhuma: a versão anterior inseria
-- 'admin@legaliz.ai' com o hash de 'admin123' fixo no SQL, então todo banco novo
-- nascia com credencial de admin conhecida (docs/REVISAO_SEGURANCA.md, P0-2).
-- O admin inicial é criado por `init_admin.py`, que EXIGE ADMIN_PASSWORD no .env.
-- Para migrar um banco que ainda tenha a credencial padrão, troque a senha pelo
-- painel (Gestão de Usuários → Resetar Senha) ou rode:
--   UPDATE users SET password_hash = <novo hash bcrypt> WHERE email = 'admin@legaliz.ai';