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
-- Rastreabilidade do fragmento (R-13): página do PDF e ordem no documento.
ALTER TABLE documents ADD COLUMN IF NOT EXISTS pagina INTEGER;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS ordem INTEGER;

-- Papel do trecho no documento (R-24): `dispositivo` é texto de artigo — o que o fact-check
-- confere contra a lei — e `preambulo` é capa, apresentação, lista de leis alteradoras e
-- comentário de apostila, isto é, texto do documento que NÃO é dispositivo. Existe para a
-- interface não apresentar comentário como se fosse texto de lei. O default preenche as
-- linhas de uma base já existente (o comando é idempotente).
ALTER TABLE documents ADD COLUMN IF NOT EXISTS tipo_trecho VARCHAR(20) DEFAULT 'dispositivo';

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

-- Chunks passam a referenciar a fonte (coluna adicionada de forma idempotente).
-- Precisa vir ANTES do bloco de consolidação abaixo, que reaponta `source_id`.
ALTER TABLE documents ADD COLUMN IF NOT EXISTS source_id INTEGER REFERENCES sources(id) ON DELETE CASCADE;

-- Unicidade da fonte é por (arquivo, DONO) — nunca só pelo nome do arquivo.
-- Dois usuários podem subir "peticao.pdf" cada um, e a versão anterior
-- (UNIQUE só em file_name) fazia o upsert do segundo sobrescrever owner/scope
-- da fonte do primeiro: metadado de um tenant apontando para outro.
--
-- O dono entra como COALESCE(owner_id, -1) porque, em índice único, NULL é
-- distinto de NULL: com a coluna crua o `ON CONFLICT (file_name, owner_id)` não
-- casaria para os documentos sem dono (cargas em lote/legado — é assim que o
-- corpus global entra via scripts/indexar_lote.py) e cada carga criaria uma
-- linha nova. -1 como sentinela é seguro: owner_id tem FK para users(id) e
-- SERIAL começa em 1.
--
-- Em banco EXISTENTE, use database/migrate_sources_owner.sql (que consolida
-- duplicatas antes de criar o índice — num banco com duplicatas o CREATE UNIQUE
-- INDEX falha). Os blocos abaixo são os mesmos, para o init.sql ser idempotente.
ALTER TABLE sources DROP CONSTRAINT IF EXISTS sources_file_name_key;
DROP INDEX IF EXISTS sources_file_name_owner_uidx;

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

CREATE UNIQUE INDEX IF NOT EXISTS sources_file_owner_uidx
    ON sources (file_name, COALESCE(owner_id, -1));

-- ============================================================
-- Dedup de fragmento garantido pelo BANCO (P2-16 / R-12)
-- ============================================================
-- O dedup era só de aplicação (`ingest._filter_existing`), que evita reembeddar mas não
-- impede duplicata por concorrência — e fragmento duplicado enche o TOP_K de cópias.
-- `content_hash` (md5 do conteúdo) entra na chave com arquivo e dono, como em `sources`.
ALTER TABLE documents ADD COLUMN IF NOT EXISTS content_hash TEXT;

-- Backfill das linhas que já existem (idempotente: só preenche o que está nulo).
UPDATE documents SET content_hash = md5(content)
 WHERE content_hash IS NULL AND content IS NOT NULL;

-- Consolida duplicatas antes de criar o índice único: num banco que já tem duplicatas o
-- CREATE UNIQUE INDEX falha (mesma ordem do bloco de `sources` acima).
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

-- O alvo do ON CONFLICT da ingestão precisa ser escrito IGUAL a este índice
-- (`file_name, (COALESCE(owner_id, -1)), content_hash`) — ver app/ingest.py.
CREATE UNIQUE INDEX IF NOT EXISTS documents_file_owner_hash_uidx
    ON documents (file_name, COALESCE(owner_id, -1), content_hash);

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