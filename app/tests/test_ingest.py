"""Testes unitários do ingest.py — mocks de banco e embedder, sem Ollama/Postgres reais.

Valida o comportamento do lote de embeddings (batch_size), o filtro de NUL (0x00)
e o fluxo de inserção com metadados jurídicos.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

_original_modules = {}

def setUpModule():
    # Backup original modules before mocking to prevent test pollution
    mocked_modules = ['psycopg2', 'psycopg2.extras', 'psycopg2.pool', 'pgvector', 'pgvector.psycopg2', 'langchain_community', 'langchain_community.document_loaders', 'langchain_text_splitters', 'config', 'ingest']
    for m in mocked_modules:
        _original_modules[m] = sys.modules.get(m)

    # ---------------------------------------------------------------
    # Mocks de dependências externas ANTES de importar ingest
    # ---------------------------------------------------------------
    sys.modules['psycopg2'] = MagicMock()
    sys.modules['psycopg2.extras'] = MagicMock()
    sys.modules['psycopg2.extras'].Json = MagicMock(side_effect=lambda v: ('JSON', v))
    sys.modules['psycopg2.extras'].execute_values = MagicMock()
    sys.modules['psycopg2.pool'] = MagicMock()
    sys.modules['psycopg2.pool'].SimpleConnectionPool = MagicMock()
    sys.modules['psycopg2.extras'].RealDictCursor = MagicMock()
    sys.modules['pgvector'] = MagicMock()
    sys.modules['pgvector.psycopg2'] = MagicMock()
    sys.modules['pgvector.psycopg2'].register_vector = MagicMock()
    sys.modules['langchain_community'] = MagicMock()
    sys.modules['langchain_community.document_loaders'] = MagicMock()
    sys.modules['langchain_community.document_loaders'].PyPDFLoader = MagicMock()
    sys.modules['langchain_text_splitters'] = MagicMock()
    sys.modules['langchain_text_splitters'].RecursiveCharacterTextSplitter = MagicMock()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _make_chunk(content, metadata=None):
    """Cria um objeto com a interface mínima de chunk do LangChain (page_content + metadata)."""
    return type('Chunk', (), {
        'page_content': content,
        'metadata': metadata or {},
    })()


class FakeEmbedder:
    """Embedder fake que registra os textos recebidos e devolve vetores determinísticos."""

    def __init__(self):
        self.calls = []

    def embed_documents(self, texts):
        self.calls.append(list(texts))
        # vetor de 768 dims com valor = hash simples do texto
        return [[float(len(t))] * 768 for t in texts]


class TestDefaultBatchSize(unittest.TestCase):
    def test_store_in_postgres_default_uses_config(self):
        from importlib import reload
        import config
        reload(config)
        import ingest
        reload(ingest)
        # defaults: (owner_id=None, scope='private', batch_size=EMBED_BATCH_SIZE)
        sig = ingest.store_in_postgres.__defaults__
        self.assertEqual(sig[2], 128)  # EMBED_BATCH_SIZE default


class TestBatchLoop(unittest.TestCase):
    def setUp(self):
        from importlib import reload
        import ingest
        reload(ingest)
        self.ingest = ingest

    @patch('ingest.psycopg2.extras.execute_values')
    @patch('ingest.psycopg2.connect')
    @patch('ingest.parse_chunk')
    @patch('ingest.enrich_chunk_metadata')
    def test_embedder_receives_batches(self, mock_enrich, mock_parse, mock_connect, mock_ev):
        # 10 chunks, batch de 4 -> 3 chamadas (4,4,2)
        chunks = [_make_chunk(f"texto {i}") for i in range(10)]
        mock_parse.return_value = {'artigo': None, 'paragrafo': None, 'inciso': None,
                                   'tipo_doc': 'lei', 'numero_doc': None, 'ano_doc': None}
        mock_enrich.side_effect = lambda c, f, m: dict(m)

        embedder = FakeEmbedder()

        conn = MagicMock()
        cur = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cur
        mock_connect.return_value.__enter__.return_value = conn

        progresses = list(self.ingest.store_in_postgres(chunks, embedder, "lei.pdf", owner_id=1,
                                                        scope='private', batch_size=4))

        # embed_documents chamado 3x com os lotes corretos
        self.assertEqual(len(embedder.calls), 3)
        self.assertEqual(len(embedder.calls[0]), 4)
        self.assertEqual(len(embedder.calls[1]), 4)
        self.assertEqual(len(embedder.calls[2]), 2)
        # progress reporta 100% no final
        self.assertAlmostEqual(progresses[-1], 1.0)

    @patch('ingest.psycopg2.connect')
    def test_filtra_chunks_com_nul(self, mock_connect):
        chunks = [
            _make_chunk("texto normal"),
            _make_chunk("texto com \x00 nulo"),
            _make_chunk("outro normal"),
        ]
        embedder = FakeEmbedder()
        conn = MagicMock()
        cur = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cur
        mock_connect.return_value.__enter__.return_value = conn

        from ingest import parse_chunk, enrich_chunk_metadata
        with patch('ingest.parse_chunk', return_value={'artigo': None, 'paragrafo': None,
                   'inciso': None, 'tipo_doc': None, 'numero_doc': None, 'ano_doc': None}), \
             patch('ingest.enrich_chunk_metadata', side_effect=lambda c, f, m: dict(m)), \
             patch('ingest.psycopg2.extras.execute_values') as mock_ev:
            list(self.ingest.store_in_postgres(chunks, embedder, "doc.pdf", batch_size=10))
            # apenas 2 chunks válidos inseridos
            inserted = mock_ev.call_args[0][2]
            self.assertEqual(len(inserted), 2)
            # conteúdo NUL não deve estar entre os inseridos
            contents = [row[1] for row in inserted]
            self.assertNotIn("texto com \x00 nulo", contents)

    @patch('ingest.psycopg2.connect')
    def test_vazio_retorna_sem_chamar_embedder(self, mock_connect):
        embedder = FakeEmbedder()
        result = list(self.ingest.store_in_postgres([], embedder, "doc.pdf"))
        self.assertEqual(result, [])
        self.assertEqual(embedder.calls, [])


class TestProcessPdf(unittest.TestCase):
    def setUp(self):
        from importlib import reload
        import ingest
        reload(ingest)
        self.ingest = ingest

    @patch('ingest.PyPDFLoader')
    def test_process_pdf_splitter_used(self, mock_loader):
        # page_content precisa ser texto real: process_pdf agora normaliza
        # whitespace por página antes de fragmentar.
        doc_mock = MagicMock()
        doc_mock.page_content = "Art.  42  A aposentadoria sera devida."
        loader_inst = MagicMock()
        loader_inst.load.return_value = [doc_mock, doc_mock]
        mock_loader.return_value = loader_inst

        splitter_inst = MagicMock()
        splitter_inst.split_documents.return_value = ['c1', 'c2']
        from ingest import RecursiveCharacterTextSplitter
        RecursiveCharacterTextSplitter.return_value = splitter_inst

        chunks = self.ingest.process_pdf('/tmp/arquivo.pdf')
        self.assertEqual(chunks, ['c1', 'c2'])
        mock_loader.assert_called_once_with('/tmp/arquivo.pdf')

    def test_process_pdf_normaliza_whitespace_antes_do_split(self):
        """A normalização roda por página, antes do split jurídico."""
        from ingest import process_pdf, normalize_whitespace

        paginas = []
        for texto in ["Art.  42  devida.", "texto\u00a0com\u00a0nbsp"]:
            d = _make_chunk(texto)
            paginas.append(d)

        with patch.object(self.ingest, 'PyPDFLoader') as mock_loader:
            mock_loader.return_value.load.return_value = paginas
            with patch.object(self.ingest, 'split_legal_documents', side_effect=lambda docs: docs):
                resultado = process_pdf('/tmp/x.pdf')

        self.assertEqual(resultado[0].page_content, "Art. 42 devida.")
        self.assertEqual(resultado[1].page_content, "texto com nbsp")

    def test_normalize_whitespace_preserva_marcador_de_artigo(self):
        """O separador canônico de 'Art. N' sobrevive à normalização."""
        from ingest import normalize_whitespace, _ARTICLE_START

        for entrada in ["Art.  83. O salario-familia", "Art.83. colado", "Art. 83. ok"]:
            saida = normalize_whitespace(entrada)
            self.assertIsNotNone(
                _ARTICLE_START.search(saida),
                f"_ARTICLE_START não reconheceu {saida!r}",
            )

    def test_split_legal_documents_preserva_limites_dos_artigos(self):
        """Artigos consecutivos não devem ser cortados no mesmo chunk."""
        from ingest import split_legal_documents

        doc = _make_chunk(
            "Preâmbulo. Art. 82. A cota será paga mensalmente.\n"
            "§ 1º O pagamento observará a regra aplicável.\n"
            "Art. 83. O salário-família será devido até quatorze anos de idade."
        )

        splitter = MagicMock()
        splitter.split_documents.side_effect = lambda docs: docs
        with patch.object(self.ingest, 'RecursiveCharacterTextSplitter', return_value=splitter):
            chunks = split_legal_documents([doc])
        contents = [c.page_content for c in chunks]

        self.assertEqual(len(contents), 2)
        self.assertIn("Art. 82.", contents[0])
        self.assertIn("§ 1º", contents[0])
        self.assertNotIn("Art. 83.", contents[0])
        self.assertIn("Art. 83.", contents[1])
        self.assertNotIn("Art. 82.", contents[1])

    def test_continuacao_de_pagina_fica_no_artigo_anterior(self):
        """Página sem novo Art. N continua o dispositivo iniciado antes."""
        from ingest import split_legal_documents

        first = _make_chunk("Art. 82. O benefício será devido conforme a regra")
        second = _make_chunk("do parágrafo anterior. Art. 83. Novo dispositivo.")

        splitter = MagicMock()
        splitter.split_documents.side_effect = lambda docs: docs
        with patch.object(self.ingest, 'RecursiveCharacterTextSplitter', return_value=splitter):
            chunks = split_legal_documents([first, second])

        contents = [c.page_content for c in chunks]
        self.assertEqual(len(contents), 2)
        self.assertIn("do parágrafo anterior.", contents[0])
        self.assertNotIn("Art. 83.", contents[0])
        self.assertIn("Art. 83.", contents[1])


class TestFilterExisting(unittest.TestCase):
    """Testes do dedup estrutural (_filter_existing)."""

    def setUp(self):
        from importlib import reload
        import ingest
        reload(ingest)
        self.ingest = ingest

    @patch('ingest.get_db_connection')
    def test_filtra_chunks_ja_existentes(self, mock_conn):
        """Chunks com conteúdo já no banco (mesmo file_name) são removidos."""
        cur = MagicMock()
        # Já existentes: 'texto 0' e 'texto 2'
        cur.fetchall.return_value = [('texto 0',), ('texto 2',)]
        conn_cm = MagicMock()
        conn_cm.__enter__.return_value = conn_cm
        conn_cm.cursor.return_value.__enter__.return_value = cur
        mock_conn.return_value = conn_cm

        chunks = [_make_chunk(f"texto {i}") for i in range(4)]
        result = self.ingest._filter_existing(chunks, "doc.pdf")

        # Só os que não existem (texto 1, texto 3) são mantidos
        self.assertEqual(len(result), 2)
        contents = [c.page_content for c in result]
        self.assertIn("texto 1", contents)
        self.assertIn("texto 3", contents)
        self.assertNotIn("texto 0", contents)
        self.assertNotIn("texto 2", contents)
        # Consulta foi feita para o file_name correto
        cur.execute.assert_called_once_with(
            "SELECT content FROM documents WHERE file_name = %s", ("doc.pdf",)
        )

    @patch('ingest.get_db_connection', side_effect=Exception("db down"))
    def test_falha_no_dedup_nao_bloqueia_ingestao(self, mock_conn):
        """Se a consulta do dedup falhar, retorna todos os chunks (não bloqueia)."""
        chunks = [_make_chunk(f"texto {i}") for i in range(3)]
        result = self.ingest._filter_existing(chunks, "doc.pdf")
        self.assertEqual(len(result), 3)

    @patch('ingest.get_db_connection')
    def test_sem_existentes_retorna_todos(self, mock_conn):
        """Se nada existir no banco, todos os chunks são mantidos."""
        cur = MagicMock()
        cur.fetchall.return_value = []
        conn_cm = MagicMock()
        conn_cm.__enter__.return_value = conn_cm
        conn_cm.cursor.return_value.__enter__.return_value = cur
        mock_conn.return_value = conn_cm

        chunks = [_make_chunk(f"texto {i}") for i in range(3)]
        result = self.ingest._filter_existing(chunks, "doc.pdf")
        self.assertEqual(len(result), 3)


def tearDownModule():
    # Restore original modules to prevent test pollution
    for m, val in _original_modules.items():
        if val is None:
            sys.modules.pop(m, None)
        else:
            sys.modules[m] = val


if __name__ == "__main__":
    unittest.main()
