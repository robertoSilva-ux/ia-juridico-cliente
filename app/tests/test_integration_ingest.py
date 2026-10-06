"""Teste de INTEGRAÇÃO do ingest.py contra um Postgres pgvector REAL (via Docker).

Pré-requisito: um banco pgvector de teste na porta 5440, user/password, db legal_test,
com o schema de users + documents criado (ver docs/TESTING.md).

Este teste NÃO usa o Ollama real: usa um embedder fake determinístico. Ele valida
que o store_in_postgres persiste de verdade no banco (vetor, metadados jurídicos,
scope) e que a busca semântica por similaridade funciona de ponta a ponta.

Se o banco de teste não estiver disponível, o teste é pulado (skip) — não falha.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock

_original_modules = {}

def setUpModule():
    # Backup original modules before mocking to prevent test pollution
    mocked_modules = ['langchain_community', 'langchain_community.document_loaders', 'langchain_text_splitters']
    for m in mocked_modules:
        _original_modules[m] = sys.modules.get(m)

    # Mock dos loaders do langchain (não usados aqui) ANTES de importar ingest.
    # psycopg2/pgvector ficam REAIS (integração de verdade com o banco).
    sys.modules['langchain_community'] = MagicMock()
    sys.modules['langchain_community.document_loaders'] = MagicMock()
    sys.modules['langchain_community.document_loaders'].PyPDFLoader = MagicMock()
    sys.modules['langchain_text_splitters'] = MagicMock()
    sys.modules['langchain_text_splitters'].RecursiveCharacterTextSplitter = MagicMock()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql://user:password@localhost:5440/legal_test",
)

# Config o DATABASE_URL para o banco de teste ANTES de qualquer import de app.
# (database.py cria o pool no import usando config.DATABASE_URL.)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ.setdefault("OLLAMA_BASE_URL", "http://localhost:11434")


def _db_available():
    try:
        import psycopg2
        conn = psycopg2.connect(TEST_DATABASE_URL, connect_timeout=2)
        conn.close()
        return True
    except Exception:
        return False


DB_AVAILABLE = _db_available()


class FakeChunk:
    def __init__(self, content, metadata=None):
        self.page_content = content
        self.metadata = metadata or {}


class FakeEmbedder:
    """Embedder determinístico — vetor de 768 dims derivado do índice do texto."""

    def embed_documents(self, texts):
        return [[float(i) / 100] * 768 for i in range(len(texts))]


@unittest.skipUnless(DB_AVAILABLE, "Banco pgvector de teste indisponível na porta 5440")
class TestStoreInPostgresIntegration(unittest.TestCase):
    """Integração real com Postgres pgvector."""

    @classmethod
    def setUpClass(cls):
        import psycopg2
        import ingest
        cls.ingest = ingest
        cls.psycopg2 = psycopg2
        conn = cls.psycopg2.connect(TEST_DATABASE_URL)
        conn.autocommit = True
        with conn.cursor() as cur:
            # garante um owner_id válido (FK p/ users)
            cur.execute("INSERT INTO users (email, name, password_hash, role) "
                        "VALUES ('test@legaliz.ai', 'Teste', 'x', 'user') "
                        "ON CONFLICT (email) DO NOTHING")
        conn.close()

    def setUp(self):
        # limpa os documentos a cada teste (independência entre casos)
        conn = self.psycopg2.connect(TEST_DATABASE_URL)
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("DELETE FROM documents")
        conn.close()

    def _connect(self):
        return self.psycopg2.connect(TEST_DATABASE_URL)

    def _store(self, chunks, file_name, **kw):
        """Roda store_in_postgres contra o banco de teste (DATABASE_URL já aponta p/ ele)."""
        list(self.ingest.store_in_postgres(chunks, FakeEmbedder(), file_name, **kw))

    def _count_docs(self):
        conn = self._connect()
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM documents")
            n = cur.fetchone()[0]
        conn.close()
        return n

    def test_insere_chunks_com_metadados_juridicos(self):
        chunks = [
            FakeChunk("Art. 54. A aposentadoria por tempo de contribuicao.", {"src": "p1"}),
            FakeChunk("§ 1º O segurado homem completa 35 anos.", {"src": "p2"}),
        ]
        self._store(chunks, "Lei 8.213-91.pdf", owner_id=None, scope='global', batch_size=10)

        self.assertEqual(self._count_docs(), 2)

        conn = self._connect()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT file_name, artigo, tipo_doc, numero_doc, scope, "
                "vector_dims(embedding) FROM documents ORDER BY id")
            rows = cur.fetchall()
        conn.close()

        self.assertEqual(len(rows), 2)
        fname, artigo, tipo, num, scope, dim = rows[0]
        self.assertEqual(fname, "Lei 8.213-91.pdf")
        self.assertEqual(artigo, 54)          # parse de conteúdo
        self.assertEqual(tipo, "lei")          # parse do nome de arquivo
        self.assertEqual(num, "8213")
        self.assertEqual(scope, "global")
        self.assertEqual(dim, 768)             # vetor de verdade

    def test_filtra_nul_realmente_no_banco(self):
        chunks = [
            FakeChunk("Conteudo limpo aqui."),
            FakeChunk("Conteudo com \x00 byte nulo."),
        ]
        self._store(chunks, "doc.pdf", batch_size=10)
        # 1 chunk descartado por NUL -> 1 inserido
        self.assertEqual(self._count_docs(), 1)

    def test_busca_semantica_por_similaridade(self):
        """Após inserir, busca semântica retorna o doc com menor distância (mais similar)."""
        from pgvector.psycopg2 import register_vector
        chunks = [
            FakeChunk("Decreto 3048 diz que a aposentadoria especial e devida."),
            FakeChunk("Lei 8213 trata de salario de contribuicao."),
        ]
        self._store(chunks, "Decreto 3.048-99.pdf", owner_id=1, scope='private', batch_size=10)

        conn = self._connect()
        register_vector(conn)
        with conn.cursor() as cur:
            # o embedding do 1o chunk = [0.0]*768 (i=0) -> q vetor=0 é o mais próximo dele
            q = [0.0] * 768
            cur.execute(
                "SELECT file_name, content, embedding <-> %s::vector AS dist "
                "FROM documents ORDER BY embedding <-> %s::vector LIMIT 1",
                (q, q))
            row = cur.fetchone()
        conn.close()
        self.assertIsNotNone(row)
        # o chunk de índice 0 é o mais similar ao vetor q=0
        self.assertIn("Decreto", row[0])
        self.assertAlmostEqual(row[2], 0.0, places=6)


def tearDownModule():
    # Restore original modules to prevent test pollution
    for m, val in _original_modules.items():
        if val is None:
            sys.modules.pop(m, None)
        else:
            sys.modules[m] = val


# registra o db de teste como opção p/ rodar fora do container
if __name__ == "__main__":
    unittest.main()
