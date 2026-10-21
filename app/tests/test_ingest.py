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


def _colunas(sql):
    """Mapa nome-da-coluna -> posição na linha, lido do próprio INSERT.

    Evita índice mágico: acrescentar uma coluna no fim da lista não pode fazer um teste
    de posição passar a medir outra coisa (foi o que aconteceu quando `tipo_trecho`
    entrou — três testes apontavam para `-1`/`-2`/`-3`).
    """
    lista = sql.split("(", 1)[1].split(")", 1)[0]
    return {nome.strip(): i for i, nome in enumerate(lista.split(","))}


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
        mock_enrich.side_effect = lambda c, f, m, *a, **k: dict(m)

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
             patch('ingest.enrich_chunk_metadata', side_effect=lambda c, f, m, *a, **k: dict(m)), \
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
        # Consulta foi feita para o file_name correto E para o dono (P0-4)
        cur.execute.assert_called_once_with(
            "SELECT content FROM documents "
            "WHERE file_name = %s AND owner_id IS NOT DISTINCT FROM %s",
            ("doc.pdf", None),
        )

    @patch('ingest.get_db_connection')
    def test_dedup_e_escopado_por_dono(self, mock_conn):
        """O dedup de um dono não pode descartar/ingerir arquivo de outro dono."""
        cur = MagicMock()
        cur.fetchall.return_value = []
        conn_cm = MagicMock()
        conn_cm.__enter__.return_value = conn_cm
        conn_cm.cursor.return_value.__enter__.return_value = cur
        mock_conn.return_value = conn_cm

        chunks = [_make_chunk("texto 0")]
        self.ingest._filter_existing(chunks, "peticao.pdf", owner_id=2)

        self.assertEqual(cur.execute.call_args[0][1], ("peticao.pdf", 2))

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


class TestDedupRecebeODono(unittest.TestCase):
    """O dono precisa atravessar store_in_postgres -> _filter_existing (P0-4)."""

    def setUp(self):
        from importlib import reload
        import ingest
        reload(ingest)
        self.ingest = ingest

    @patch('ingest._filter_existing')
    @patch('ingest.psycopg2.connect')
    def test_owner_id_chega_ao_dedup(self, mock_connect, mock_filtro):
        # Tudo já existente -> store_in_postgres para antes de conectar no banco.
        mock_filtro.return_value = []

        list(self.ingest.store_in_postgres(
            [_make_chunk("texto")], FakeEmbedder(), "peticao.pdf",
            owner_id=5, scope='private',
        ))

        self.assertEqual(mock_filtro.call_args[0][1], "peticao.pdf")
        self.assertEqual(mock_filtro.call_args[1].get("owner_id"), 5)
        mock_connect.assert_not_called()


class TestIngestDocumentDevolveFragmentos(unittest.TestCase):
    """`ingest_document` promete "número de chunks indexados" — e precisa entregar.

    A versão anterior somava os YIELDS de `store_in_postgres`, que emite **um por
    lote**: devolvia 1 para um PDF de 128 fragmentos e 3 para um de 300. Quem
    consome (o script de carga em lote e, agora, a interface) exibia esse número
    como se fosse o total indexado.
    """

    def setUp(self):
        from importlib import reload
        import ingest
        reload(ingest)
        self.ingest = ingest

    @patch('ingest._filter_existing', side_effect=lambda chunks, *a, **k: list(chunks))
    @patch('ingest.psycopg2.extras.execute_values')
    @patch('ingest.psycopg2.connect')
    @patch('ingest.parse_chunk')
    @patch('ingest.enrich_chunk_metadata')
    def test_conta_fragmentos_e_nao_lotes(self, mock_enrich, mock_parse, mock_connect,
                                          mock_ev, mock_dedup):
        chunks = [_make_chunk(f"texto {i}") for i in range(5)]   # 5 fragmentos, lote de 2
        mock_parse.return_value = {'artigo': None, 'paragrafo': None, 'inciso': None,
                                   'tipo_doc': None, 'numero_doc': None, 'ano_doc': None}
        mock_enrich.side_effect = lambda c, f, m, *a, **k: dict(m)
        conn, cur = MagicMock(), MagicMock()
        conn.cursor.return_value.__enter__.return_value = cur
        mock_connect.return_value.__enter__.return_value = conn

        progressos = []
        total = self.ingest.ingest_document(
            "/nao-usado.pdf", FakeEmbedder(), "lei.pdf",
            owner_id=1, batch_size=2, progress_cb=progressos.append, chunks=chunks,
        )

        self.assertEqual(total, 5, "o retorno é fragmentos, não o número de lotes (3)")
        self.assertEqual(mock_ev.call_count, 3, "3 lotes de 2/2/1")
        self.assertAlmostEqual(progressos[-1], 1.0)
        self.assertAlmostEqual(progressos[0], 0.5,
                              msg="extração já feita => começa na metade da barra")

    @patch('ingest._filter_existing', side_effect=lambda chunks, *a, **k: list(chunks))
    @patch('ingest.psycopg2.extras.execute_values')
    @patch('ingest.psycopg2.connect')
    @patch('ingest.parse_chunk')
    @patch('ingest.enrich_chunk_metadata')
    def test_stats_descrevem_o_que_aconteceu(self, mock_enrich, mock_parse, mock_connect,
                                             mock_ev, mock_dedup):
        chunks = [_make_chunk(f"texto {i}") for i in range(3)]
        mock_parse.return_value = {'artigo': None, 'paragrafo': None, 'inciso': None,
                                   'tipo_doc': None, 'numero_doc': None, 'ano_doc': None}
        mock_enrich.side_effect = lambda c, f, m, *a, **k: dict(m)
        conn, cur = MagicMock(), MagicMock()
        conn.cursor.return_value.__enter__.return_value = cur
        mock_connect.return_value.__enter__.return_value = conn

        stats = {}
        list(self.ingest.store_in_postgres(chunks, FakeEmbedder(), "doc.pdf",
                                           owner_id=1, batch_size=10, stats=stats))

        self.assertEqual(stats["enviados"], 3)
        self.assertEqual(stats["indexados"], 3)
        self.assertEqual(stats["pulados"], 0)
        self.assertEqual(stats["descartados_nul"], 0)

    @patch('ingest._filter_existing')
    @patch('ingest.psycopg2.connect')
    def test_stats_marcam_dedup_e_nul(self, mock_connect, mock_dedup):
        """Chunk com NUL é descartado e o que já existia entra em `pulados`."""
        chunks = [_make_chunk("normal"), _make_chunk("com \x00 nulo"), _make_chunk("repetido")]
        mock_dedup.return_value = []      # tudo o que sobrou já estava na base

        stats = {}
        list(self.ingest.store_in_postgres(chunks, FakeEmbedder(), "doc.pdf",
                                           owner_id=1, stats=stats))

        self.assertEqual(stats["enviados"], 3)
        self.assertEqual(stats["descartados_nul"], 1)
        self.assertEqual(stats["pulados"], 2, "o NUL sai antes; sobram 2, e os dois já existiam")
        self.assertEqual(stats["indexados"], 0, "nada gravado => nada a anunciar como indexado")
        mock_connect.assert_not_called()


def tearDownModule():
    # Restore original modules to prevent test pollution
    for m, val in _original_modules.items():
        if val is None:
            sys.modules.pop(m, None)
        else:
            sys.modules[m] = val


class TestRuidoDePagina(unittest.TestCase):
    """R-10/R-11: cabeçalho/rodapé repetido sai; identidade da norma e dispositivo ficam.

    Medido na base de dev: o rodapé `Prof. Adriano de Oliveira www.estrategiaconcursos.com.br
    48 de 64` entrava em TODOS os fragmentos da Lei 8.080 (o número muda por página, então a
    comparação precisa normalizar números).
    """

    def setUp(self):
        from importlib import reload
        import ingest
        reload(ingest)
        self.ingest = ingest

    def _paginas_apostila(self, n=6):
        return [
            f"LEI-8080 ESQUEMATIZADA\n\nArt. {i}. Texto do artigo {i}.\n\n"
            f"Prof. Adriano de Oliveira www.estrategiaconcursos.com.br {i} de 64"
            for i in range(1, n + 1)
        ]

    def test_rodape_repetido_sai_e_artigo_fica(self):
        paginas = self._paginas_apostila()
        limpas = self.ingest.limpar_ruido_de_pagina(paginas)
        for i, texto in enumerate(limpas, start=1):
            self.assertNotIn("estrategiaconcursos", texto, "rodapé repetido tem de sair")
            self.assertNotIn(f"{i} de 64", texto)
            self.assertIn(f"Art. {i}. Texto do artigo {i}.", texto, "conteúdo de lei fica")

    def test_identidade_da_norma_repetida_em_toda_pagina_e_preservada(self):
        """Texto oficial do Planalto repete o cabeçalho em toda página (P2-30): é ele que dá
        o par número+ano em cada fragmento e não pode ser tratado como rodapé."""
        paginas = [
            f"LEI Nº 8.080, DE 19 DE SETEMBRO DE 1990.\n\nArt. {i}. Conteúdo do artigo {i}."
            for i in range(1, 6)
        ]
        limpas = self.ingest.limpar_ruido_de_pagina(paginas)
        for texto in limpas:
            self.assertIn("LEI Nº 8.080, DE 19 DE SETEMBRO DE 1990", texto)

    def test_linha_so_de_numero_de_pagina_sai_mesmo_em_documento_curto(self):
        paginas = ["Art. 1. Conteúdo.\n\n48", "Art. 2. Outro conteúdo.\n\n49 de 120"]
        limpas = self.ingest.limpar_ruido_de_pagina(paginas)
        self.assertNotIn("48", limpas[0].splitlines())
        self.assertNotIn("49 de 120", limpas[1].splitlines())
        self.assertIn("Art. 1. Conteúdo.", limpas[0])

    def test_rodape_com_tabs_e_com_espacos_sao_o_mesmo_ruido(self):
        """Medido no PDF real: o rodapé do cursinho aparece com tabs em quase todas as
        páginas e com espaços em 3 delas — sem colapsar espaços na chave, as 3 escapavam."""
        paginas = [f"Art. {i}. Conteúdo.\nProf.\tAdriano\tde\tOliveira\twww.estrategiaconcursos.com.br\t{i}\tde\t64"
                   for i in range(1, 5)]
        paginas.append("Art. 5. Conteúdo.\nProf. Adriano de Oliveira www.estrategiaconcursos.com.br 5 de 64")
        limpas = self.ingest.limpar_ruido_de_pagina(paginas)
        for texto in limpas:
            self.assertNotIn("estrategiaconcursos", texto)

    def test_frase_que_carrega_identidade_da_norma_fica(self):
        paginas = [f"LEI Nº 8.080, DE 19 DE SETEMBRO DE 1990.\nArt. {i}. Conteúdo." for i in range(1, 5)]
        limpas = self.ingest.limpar_ruido_de_pagina(paginas)
        for texto in limpas:
            self.assertIn("LEI Nº 8.080, DE 19 DE SETEMBRO DE 1990", texto)

    def test_documento_curto_nao_tem_ruido_por_repeticao(self):
        """Com menos de 3 páginas, repetição pode ser coincidência: não se remove nada."""
        paginas = ["Art. 1. Conteúdo.", "Art. 1. Conteúdo."]
        self.assertEqual(self.ingest._linhas_de_ruido(paginas), set())
        self.assertEqual(self.ingest.limpar_ruido_de_pagina(paginas), paginas)

    def test_linha_de_dispositivo_nao_e_removida_como_rodape(self):
        self.assertTrue(self.ingest.linha_carrega_identidade_de_norma("Art. 9º A direção do SUS é única."))
        self.assertFalse(self.ingest.linha_carrega_identidade_de_norma("48 de 64"))

    def test_fragmento_vazio_e_descartado_na_gravacao(self):
        """R-11: fragmento que ficou só rodapé (vazio após limpeza) não vai ao banco."""
        chunks = [_make_chunk("Art. 1. Conteúdo real."), _make_chunk("   "), _make_chunk("")]
        stats = {}
        with patch('ingest._filter_existing', side_effect=lambda c, *a, **k: list(c)), \
             patch('ingest.parse_chunk', return_value={'artigo': None, 'paragrafo': None,
                    'inciso': None, 'tipo_doc': None, 'numero_doc': None, 'ano_doc': None}), \
             patch('ingest.enrich_chunk_metadata', side_effect=lambda c, f, m, *a, **k: dict(m)), \
             patch('ingest.psycopg2.extras.execute_values') as mock_ev, \
             patch('ingest.psycopg2.connect') as mock_connect:
            conn, cur = MagicMock(), MagicMock()
            conn.cursor.return_value.__enter__.return_value = cur
            mock_connect.return_value.__enter__.return_value = conn
            list(self.ingest.store_in_postgres(chunks, FakeEmbedder(), "doc.pdf",
                                               batch_size=10, stats=stats))
        inseridos = mock_ev.call_args[0][2]
        self.assertEqual(len(inseridos), 1)
        self.assertEqual(inseridos[0][1], "Art. 1. Conteúdo real.")
        self.assertEqual(stats['descartados_vazio'], 2)
        self.assertEqual(stats['indexados'], 1)

    def test_nada_por_tamanho(self):
        """O descarte NÃO pode ser por tamanho: 'Art. 51. (Vetado).' é lei de verdade."""
        chunks = [_make_chunk("Art. 51. (Vetado)."), _make_chunk("Art. 42. (Vetado).")]
        with patch('ingest._filter_existing', side_effect=lambda c, *a, **k: list(c)), \
             patch('ingest.parse_chunk', return_value={'artigo': None, 'paragrafo': None,
                    'inciso': None, 'tipo_doc': None, 'numero_doc': None, 'ano_doc': None}), \
             patch('ingest.enrich_chunk_metadata', side_effect=lambda c, f, m, *a, **k: dict(m)), \
             patch('ingest.psycopg2.extras.execute_values') as mock_ev, \
             patch('ingest.psycopg2.connect') as mock_connect:
            conn, cur = MagicMock(), MagicMock()
            conn.cursor.return_value.__enter__.return_value = cur
            mock_connect.return_value.__enter__.return_value = conn
            list(self.ingest.store_in_postgres(chunks, FakeEmbedder(), "lei.pdf", batch_size=10))
        self.assertEqual(len(mock_ev.call_args[0][2]), 2, "artigo curto é conteúdo de lei")


class TestDedupEGrafoNoBanco(unittest.TestCase):
    """R-12/R-13: hash de conteúdo na chave única e rastreabilidade do fragmento.

    O alvo do `ON CONFLICT` tem de ser escrito IGUAL ao índice
    `documents_file_owner_hash_uidx` — é a armadilha já documentada no bloco de `sources`
    (índice com `COALESCE(owner_id, -1)`), e aqui ela é conferida lendo os DOIS arquivos.
    """

    def setUp(self):
        from importlib import reload
        import ingest
        reload(ingest)
        self.ingest = ingest

    def _executar(self, chunks, rowcount=None):
        stats = {}
        with patch('ingest._filter_existing', side_effect=lambda c, *a, **k: list(c)), \
             patch('ingest.parse_chunk', return_value={'artigo': None, 'paragrafo': None,
                    'inciso': None, 'tipo_doc': 'lei', 'numero_doc': '8080', 'ano_doc': '1990'}), \
             patch('ingest.enrich_chunk_metadata', side_effect=lambda c, f, m, *a, **k: dict(m)), \
             patch('ingest.psycopg2.extras.execute_values') as mock_ev, \
             patch('ingest.psycopg2.connect') as mock_connect:
            conn, cur = MagicMock(), MagicMock()
            if rowcount is not None:
                cur.rowcount = rowcount
            conn.cursor.return_value.__enter__.return_value = cur
            mock_connect.return_value.__enter__.return_value = conn
            list(self.ingest.store_in_postgres(chunks, FakeEmbedder(), "lei-8080.pdf",
                                               owner_id=9, batch_size=10, stats=stats))
        sql, linhas = mock_ev.call_args[0][1], mock_ev.call_args[0][2]
        return sql, linhas, stats

    def test_hash_md5_do_conteudo_vai_na_linha(self):
        import hashlib
        conteudo = "Art. 9º A direção do SUS é única."
        sql, linhas, _ = self._executar([_make_chunk(conteudo)])
        self.assertIn("content_hash", sql)
        col = _colunas(sql)
        self.assertEqual(linhas[0][col["content_hash"]],
                         hashlib.md5(conteudo.encode("utf-8")).hexdigest())

    def test_on_conflict_escrito_igual_ao_indice(self):
        from pathlib import Path
        sql, _, _ = self._executar([_make_chunk("Art. 1. Conteúdo.")])
        alvo = "ON CONFLICT (file_name, (COALESCE(owner_id, -1)), content_hash)"
        self.assertIn(alvo, sql)
        self.assertIn("DO NOTHING", sql)
        init_sql = Path(__file__).resolve().parents[2] / "database" / "init.sql"
        fonte = init_sql.read_text(encoding="utf-8")
        self.assertIn("ON documents (file_name, COALESCE(owner_id, -1), content_hash)", fonte,
                      "o índice do banco precisa casar com o alvo do ON CONFLICT")

    def test_pagina_e_ordem_rastreaveis(self):
        chunks = [_make_chunk("Art. 1. Um.", {"page": 4}), _make_chunk("Art. 2. Dois."),
                  _make_chunk("Art. 3. Três.", {"page": 9})]
        sql, linhas, _ = self._executar(chunks)
        col = _colunas(sql)
        self.assertEqual([linha[col["pagina"]] for linha in linhas], [5, None, 10],
                         "página 1-based, ausente = None")
        self.assertEqual([linha[col["ordem"]] for linha in linhas], [1, 2, 3],
                         "ordem do fragmento no documento")

    def test_ordem_sobrevive_ao_dedup(self):
        """A posição é a do documento original, não a da lista já filtrada."""
        chunks = [_make_chunk("Art. 1. Um."), _make_chunk("Art. 2. Dois."), _make_chunk("Art. 3. Três.")]
        with patch('ingest._filter_existing', side_effect=lambda c, *a, **k: [c[1], c[2]]):
            stats = {}
            with patch('ingest.parse_chunk', return_value={'artigo': None, 'paragrafo': None,
                        'inciso': None, 'tipo_doc': None, 'numero_doc': None, 'ano_doc': None}), \
                 patch('ingest.enrich_chunk_metadata', side_effect=lambda c, f, m, *a, **k: dict(m)), \
                 patch('ingest.psycopg2.extras.execute_values') as mock_ev, \
                 patch('ingest.psycopg2.connect') as mock_connect:
                conn, cur = MagicMock(), MagicMock()
                conn.cursor.return_value.__enter__.return_value = cur
                mock_connect.return_value.__enter__.return_value = conn
                list(self.ingest.store_in_postgres(chunks, FakeEmbedder(), "lei.pdf",
                                                   batch_size=10, stats=stats))
        sql = mock_ev.call_args[0][1]
        col = _colunas(sql)
        self.assertEqual([linha[col["ordem"]] for linha in mock_ev.call_args[0][2]], [2, 3])

    def test_contagem_reflete_o_que_o_banco_inseriu(self):
        """`ON CONFLICT DO NOTHING` pode descartar linha: o contador não pode mentir."""
        _, _, stats = self._executar([_make_chunk("Art. 1. Um."), _make_chunk("Art. 1. Um.")],
                                     rowcount=1)
        self.assertEqual(stats['indexados'], 1)

    def test_lote_insertado_numa_pagina_so(self):
        """O `page_size` do psycopg2 (100) deixa o `rowcount` sendo o da ÚLTIMA página.

        Medido na reingestão da apostila: 157 fragmentos gravados foram contados como 57
        (100 + 57) — quem opera leria que 100 fragmentos se perderam.
        """
        chunks = [_make_chunk(f"Art. {i}. Conteúdo.") for i in range(1, 4)]
        with patch('ingest._filter_existing', side_effect=lambda c, *a, **k: list(c)), \
             patch('ingest.psycopg2.extras.execute_values') as mock_ev, \
             patch('ingest.psycopg2.connect') as mock_connect:
            conn, cur = MagicMock(), MagicMock()
            conn.cursor.return_value.__enter__.return_value = cur
            mock_connect.return_value.__enter__.return_value = conn
            list(self.ingest.store_in_postgres(chunks, FakeEmbedder(), "lei.pdf",
                                               batch_size=10, stats={}))
        self.assertEqual(mock_ev.call_args.kwargs.get('page_size'), len(chunks))


class TestPreambuloR24(unittest.TestCase):
    """R-24: o texto anterior ao primeiro dispositivo não pode sair do índice.

    Medido no PDF da apostila de dev (65 páginas): 25 páginas sem nenhum dispositivo —
    36,2 % dos caracteres — não entravam em fragmento nenhum: capa, apresentação, lista
    das leis que alteraram a norma e comentários. A pergunta cuja resposta estava ali era
    irrecuperável (o produto recusava onde havia resposta).
    """

    def setUp(self):
        from importlib import reload
        import ingest
        reload(ingest)
        self.ingest = ingest

    def _fragmentar(self, paginas):
        """Fragmenta com um splitter pass-through, para ler o conteúdo das seções."""
        splitter = MagicMock()
        splitter.split_documents.side_effect = lambda docs: docs
        with patch.object(self.ingest, 'RecursiveCharacterTextSplitter', return_value=splitter):
            return self.ingest.split_legal_documents(paginas)

    def _executar_store(self, chunks):
        """Roda `store_in_postgres` com banco duplo e devolve (mapa de colunas, linhas)."""
        with patch('ingest._filter_existing', side_effect=lambda c, *a, **k: list(c)), \
             patch('ingest.psycopg2.extras.execute_values') as mock_ev, \
             patch('ingest.psycopg2.connect') as mock_connect:
            conn, cur = MagicMock(), MagicMock()
            conn.cursor.return_value.__enter__.return_value = cur
            mock_connect.return_value.__enter__.return_value = conn
            list(self.ingest.store_in_postgres(chunks, FakeEmbedder(), "lei-8080.pdf",
                                               owner_id=9, batch_size=10, stats={}))
        return _colunas(mock_ev.call_args[0][1]), mock_ev.call_args[0][2]

    def test_texto_antes_do_primeiro_dispositivo_vira_fragmento_marcado(self):
        paginas = [
            _make_chunk("Estratégia CONCURSOS NA SAÚDE — LEI 8.080 ESQUEMATIZADA", {"page": 0}),
            _make_chunk("Lista das leis: Lei nº 10.424, de 15 de abril de 2002.", {"page": 1}),
            _make_chunk("Art. 10. Os municípios poderão constituir consórcios.", {"page": 2}),
        ]
        chunks = self._fragmentar(paginas)

        self.assertEqual(len(chunks), 3, "as duas páginas de preâmbulo têm de virar fragmento")
        preambulos = [c for c in chunks if c.metadata.get('tipo_trecho') == 'preambulo']
        self.assertEqual(len(preambulos), 2)
        self.assertIn("Estratégia CONCURSOS", preambulos[0].page_content)
        self.assertIn("Lei nº 10.424", preambulos[1].page_content)
        # a página de origem sobrevive ao split (R-13)
        self.assertEqual([c.metadata.get('page') for c in preambulos], [0, 1])
        dispositivos = [c for c in chunks if c.metadata.get('tipo_trecho') == 'dispositivo']
        self.assertEqual(len(dispositivos), 1)
        self.assertIn("Art. 10.", dispositivos[0].page_content)

    def test_documento_que_abre_com_dispositivo_nao_tem_preambulo(self):
        chunks = self._fragmentar([_make_chunk("Art. 10. Os municípios poderão constituir consórcios.")])
        self.assertEqual([c.metadata.get('tipo_trecho') for c in chunks], ['dispositivo'])

    def test_documento_sem_dispositivo_nenhum_segue_no_splitter(self):
        """Sem 'Art. N' no documento, o caminho antigo (splitter puro) continua valendo."""
        splitter = MagicMock()
        splitter.split_documents.return_value = ['generico']
        with patch.object(self.ingest, 'RecursiveCharacterTextSplitter', return_value=splitter):
            chunks = self.ingest.split_legal_documents([_make_chunk("Texto sem dispositivo algum.")])
        self.assertEqual(chunks, ['generico'])

    def test_continuacao_de_pagina_depois_do_dispositivo_nao_vira_preambulo(self):
        paginas = [
            _make_chunk("Art. 82. O benefício será devido conforme a regra"),
            _make_chunk("do parágrafo anterior, que continua na página seguinte."),
        ]
        chunks = self._fragmentar(paginas)
        self.assertEqual([c.metadata.get('tipo_trecho') for c in chunks], ['dispositivo'])
        self.assertIn("do parágrafo anterior", chunks[0].page_content)

    def test_grafia_ordinal_sem_ponto_no_inicio_da_linha_e_dispositivo(self):
        """R-25: 'Art. 9º A direção…' é cabeçalho; referência inline não é."""
        from ingest import _ARTICLE_START

        self.assertIsNotNone(
            _ARTICLE_START.search("Art. 9º A direção do Sistema Único de Saúde é única."))
        self.assertIsNotNone(
            _ARTICLE_START.search("Texto qualquer.\nArt. 2º Esta Lei regula os serviços."))
        # referências no meio da frase continuam fora (era o motivo de exigir pontuação)
        self.assertIsNone(
            _ARTICLE_START.search("na forma do art. 2º desta Lei, aplica-se o previsto"))
        self.assertIsNone(
            _ARTICLE_START.search("conforme o inciso I do art. 198 da Constituição"))

        chunks = self._fragmentar([_make_chunk("Art. 9º A direção do SUS é única.")])
        self.assertEqual([c.metadata.get('tipo_trecho') for c in chunks], ['dispositivo'])

    def test_identidade_e_lida_das_paginas_e_nao_dos_fragmentos(self):
        """R-9 depende do texto do DOCUMENTO: o que o chunker separa não decide a norma.

        O título da lei vive no preâmbulo — justamente o texto que o R-24 descartava. Se a
        identidade é lida da concatenação dos fragmentos, ela some junto.
        """
        from ingest import ingest_document

        pagina = _make_chunk("LEI Nº 10.424, DE 15 DE ABRIL DE 2002\n"
                             "Acrescenta capítulo à Lei 8.080, de 19 de setembro de 1990.")
        capturado = {}

        def fake_store(chunks, embedder, file_name, **kwargs):
            capturado.update(kwargs)
            return iter([1.0])

        with patch.object(self.ingest, "extrair_paginas", return_value=[pagina]), \
             patch.object(self.ingest, "split_legal_documents",
                          return_value=[_make_chunk("Art. 1º Esta Lei acrescenta dispositivo.")]), \
             patch.object(self.ingest, "store_in_postgres", side_effect=fake_store):
            ingest_document("/tmp/x.pdf", FakeEmbedder(), "documento-sem-identidade-no-nome.pdf")

        identidade = capturado["identidade"]
        self.assertEqual(identidade["tipo"], "lei")
        self.assertEqual(identidade["numero"], "10424")
        self.assertEqual(identidade["ano"], "2002")

    def test_fragmento_de_preambulo_nao_grava_artigo(self):
        """O 'artigo' encontrado em comentário não pode virar cabeçalho no banco."""
        chunk = _make_chunk("Comentário: nesse artigo, o art. 10 trata dos consórcios.",
                            {"page": 3, "tipo_trecho": "preambulo"})
        col, linhas = self._executar_store([chunk])
        self.assertEqual(linhas[0][col["tipo_trecho"]], "preambulo")
        self.assertIsNone(linhas[0][col["artigo"]])
        self.assertEqual(linhas[0][col["pagina"]], 4)      # page (0-based) + 1

    def test_fragmento_de_dispositivo_grava_artigo_e_marca(self):
        chunk = _make_chunk("Art. 10. Os municípios poderão constituir consórcios.",
                            {"page": 25, "tipo_trecho": "dispositivo"})
        col, linhas = self._executar_store([chunk])
        self.assertEqual(linhas[0][col["tipo_trecho"]], "dispositivo")
        self.assertEqual(linhas[0][col["artigo"]], 10)
        self.assertEqual(linhas[0][col["pagina"]], 26)

    def test_prosa_que_comeca_com_numero_de_artigo_sem_ponto_nao_e_cabecalho(self):
        """Sem indicador ordinal e sem pontuação, o início de linha NÃO é dispositivo.

        Foi o que a primeira versão da regra nova passou a aceitar por engano —
        'Art. 42 A aposentadoria será devida' virava cabeçalho.
        """
        from ingest import _ARTICLE_START

        self.assertIsNone(_ARTICLE_START.search("Art. 42 A aposentadoria será devida"))
        self.assertIsNotNone(_ARTICLE_START.search("Art. 42. A aposentadoria será devida"))


class TestCorpusEmTexto(unittest.TestCase):
    """P2-30: o corpus oficial do Planalto entra como TEXTO, não como PDF.

    Texto plano não tem paginação, mas o pipeline é por página (limpeza de ruído
    comparando páginas, metadado `pagina`, estado do dispositivo entre páginas).
    `extrair_paginas` pagina o `.txt` sinteticamente, em fronteira de parágrafo, e o resto
    do caminho é o mesmo do PDF.
    """

    def setUp(self):
        from importlib import reload
        import ingest
        reload(ingest)
        self.ingest = ingest

    def _arquivo(self, texto, sufixo=".txt"):
        import tempfile
        descritor, caminho = tempfile.mkstemp(suffix=sufixo, text=True)
        with os.fdopen(descritor, "w", encoding="utf-8") as arquivo:
            arquivo.write(texto)
        self.addCleanup(os.unlink, caminho)
        return caminho

    def _fragmentar(self, paginas):
        splitter = MagicMock()
        splitter.split_documents.side_effect = lambda docs: docs
        with patch.object(self.ingest, 'RecursiveCharacterTextSplitter', return_value=splitter):
            return self.ingest.split_legal_documents(paginas)

    def test_txt_e_paginado_em_fronteira_de_paragrafo(self):
        paragrafos = [f"Parágrafo número {i} " + "x" * 300 for i in range(40)]
        paginas = self.ingest.extrair_paginas(self._arquivo("\n\n".join(paragrafos)))

        self.assertGreater(len(paginas), 1, "40 parágrafos de ~330 chars têm de gerar mais de uma página")
        for pagina in paginas:
            self.assertLessEqual(len(pagina.page_content), self.ingest.PAGINA_TXT_CHARS + 400)
            self.assertTrue(pagina.page_content.startswith("Parágrafo número"),
                            f"página começa no meio de um parágrafo: {pagina.page_content[:60]!r}")

    def test_pagina_do_txt_e_numerada_no_metadado(self):
        paginas = self.ingest.extrair_paginas(
            self._arquivo("\n\n".join("z" * 2000 for _ in range(5))))
        self.assertEqual([p.metadata.get("page") for p in paginas], list(range(len(paginas))))

    def test_split_do_txt_marca_dispositivo_e_guarda_o_cabecalho(self):
        """Preâmbulo na MESMA página do 1º artigo acompanha o artigo (regra do splitter)."""
        texto = ("LEI Nº 8.080, DE 19 DE SETEMBRO DE 1990.\n\n"
                 "Dispõe sobre as condições para a promoção da saúde.\n\n"
                 "Art. 1º Esta lei regula as ações e serviços de saúde.\n\n"
                 "Art. 2º A saúde é um direito fundamental do ser humano.\n")
        chunks = self._fragmentar(self.ingest.extrair_paginas(self._arquivo(texto)))

        self.assertEqual([c.metadata.get("tipo_trecho") for c in chunks],
                         ["dispositivo"] * len(chunks))
        self.assertIn("LEI Nº 8.080", chunks[0].page_content,
                      "o cabeçalho da norma não pode se perder: é ele que carrega número e ano")
        self.assertEqual(chunks[0].metadata.get("tipo_trecho"), "dispositivo")
        self.assertTrue(chunks[0].page_content.startswith("LEI Nº 8.080, DE 19 DE SETEMBRO DE 1990."),
                        chunks[0].page_content[:80])
        self.assertIn("Art. 1º", chunks[0].page_content)

    def test_split_do_txt_marca_preambulo_em_pagina_propria(self):
        """Preâmbulo maior que uma página sintética vira seção própria (R-24), não lixo."""
        cabecalho = [
            "LEI Nº 8.080, DE 19 DE SETEMBRO DE 1990.",
            "Dispõe sobre as condições para a promoção da saúde.",
            "TÍTULO I — DAS DISPOSIÇÕES GERAIS",
        ] + ["Comentário de apresentação " + "c" * 400 for _ in range(12)]
        texto = "\n\n".join(cabecalho + ["Art. 1º Esta lei regula as ações de saúde."])
        chunks = self._fragmentar(self.ingest.extrair_paginas(self._arquivo(texto)))
        tipos = [c.metadata.get("tipo_trecho") for c in chunks]

        self.assertIn("preambulo", tipos)
        self.assertIn("dispositivo", tipos)

    def test_linha_repetida_no_texto_oficial_nao_e_tratada_como_rodape(self):
        """A limpeza de ruído é do PDF paginado; em texto oficial 'TÍTULO I' se repete e fica."""
        texto = "\n\n".join(["TÍTULO I"] + ["w" * 1500 for _ in range(8)])
        paginas = self.ingest.extrair_paginas(self._arquivo(texto))
        self.assertIn("TÍTULO I", "\n\n".join(p.page_content for p in paginas))

    def test_pdf_continua_indo_para_o_pypdfloader(self):
        caminho = self._arquivo("conteúdo", sufixo=".pdf")
        with patch.object(self.ingest, 'PyPDFLoader') as mock_loader:
            mock_loader.return_value.load.return_value = []
            self.ingest.extrair_paginas(caminho)
        mock_loader.assert_called_once_with(caminho)


if __name__ == "__main__":
    unittest.main()
