"""Testes das buscas de regime/artigo usando injeção de dependência (conn_factory).

Sem banco real: passa um conn_factory fake (context manager) e um cursor mock.
Cobre _metadata_search, _keyword_search (regime.py) e _semantic_search (agent.py),
que antes dependiam do get_db_connection global e ficavam sem cobertura unitária.
"""
import os
import sys
import unittest
from contextlib import contextmanager
from unittest.mock import MagicMock

_orig = {}

def setUpModule():
    for m in ['psycopg2', 'psycopg2.extras', 'psycopg2.pool', 'pgvector', 'pgvector.psycopg2']:
        _orig[m] = sys.modules.get(m)
    sys.modules['psycopg2'] = MagicMock()
    sys.modules['psycopg2.extras'] = MagicMock()
    sys.modules['psycopg2.extras'].RealDictCursor = MagicMock()
    sys.modules['psycopg2.pool'] = MagicMock()
    sys.modules['psycopg2.pool'].SimpleConnectionPool = MagicMock()
    sys.modules['pgvector'] = MagicMock()
    sys.modules['pgvector.psycopg2'] = MagicMock()

def tearDownModule():
    for m, v in _orig.items():
        if v is None:
            sys.modules.pop(m, None)
        else:
            sys.modules[m] = v


def _fake_conn(fetchall=None):
    """Retorna (conn_factory, cursor_mock) onde conn_factory é um context manager.

    conn_factory() -> conn (context manager) com conn.cursor(cursor_factory=...) -> cur.
    """
    cur = MagicMock()
    if fetchall is not None:
        cur.fetchall.return_value = fetchall
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur

    @contextmanager
    def factory():
        yield conn

    return factory, cur, conn


class TestMetadataSearch(unittest.TestCase):
    def test_metadata_search_usa_conn_factory_e_retorna_rows(self):
        from regime import _metadata_search
        rows = [{"id": 1, "file_name": "Decreto 3.048-99.pdf", "artigo": 54, "tipo_doc": "decreto", "numero_doc": "3048"}]
        factory, cur, conn = _fake_conn(fetchall=rows)
        result = _metadata_search("artigo 54 do decreto 3048", conn_factory=factory)
        self.assertEqual(result, rows)
        # cursor executou com SQL contendo filtros de artigo + tipo + numero
        sql, params = cur.execute.call_args[0]
        self.assertIn("artigo = %s", sql)
        self.assertIn("tipo_doc = %s", sql)
        self.assertIn("numero_doc = %s", sql)
        self.assertIn(54, params)

    def test_metadata_search_sem_artigo_retorna_vazio(self):
        from regime import _metadata_search
        factory, cur, conn = _fake_conn(fetchall=[])
        result = _metadata_search("qual a carência para aposentar?", conn_factory=factory)
        self.assertEqual(result, [])
        cur.execute.assert_not_called()

    def test_metadata_search_com_scope_do_usuario(self):
        from regime import _metadata_search
        factory, cur, conn = _fake_conn(fetchall=[])
        _metadata_search("art. 54 do decreto 3048", user_id=7, conn_factory=factory)
        sql, params = cur.execute.call_args[0]
        self.assertIn("scope", sql)
        self.assertIn(7, params)


class TestKeywordSearch(unittest.TestCase):
    def test_keyword_search_monta_regex_de_artigo(self):
        from regime import _keyword_search
        factory, cur, conn = _fake_conn(fetchall=[{"id": 2}])
        result = _keyword_search("art. 54 do decreto 3048", conn_factory=factory)
        self.assertEqual(len(result), 1)
        sql, params = cur.execute.call_args[0]
        # padrão regex do artigo (evita match parcial 545 -> 54)
        self.assertIn("54", params[0])
        self.assertIn("content ~ %s", sql)

    def test_keyword_search_sem_artigo_retorna_vazio(self):
        from regime import _keyword_search
        factory, cur, conn = _fake_conn(fetchall=[])
        result = _keyword_search("aposentadoria rural", conn_factory=factory)
        self.assertEqual(result, [])
        cur.execute.assert_not_called()


class TestSemanticSearch(unittest.TestCase):
    def test_semantic_search_com_conn_factory(self):
        from agent import _semantic_search
        rows = [{"id": 5, "distance": 0.1}]
        factory, cur, conn = _fake_conn(fetchall=rows)
        result = _semantic_search([0.1, 0.2], limit=5, conn_factory=factory)
        self.assertEqual(result, rows)
        sql, params = cur.execute.call_args[0]
        self.assertIn("embedding <=>", sql)

    def test_semantic_search_filtra_por_numero_da_norma(self):
        """P2-32: com norma, o SQL restringe por numero_doc e o parâmetro vai na ordem."""
        from agent import _semantic_search
        factory, cur, conn = _fake_conn(fetchall=[])
        _semantic_search([0.1, 0.2], user_id=7, limit=15, conn_factory=factory,
                         norma=("lei", "8080"))
        sql, params = cur.execute.call_args[0]
        self.assertIn("numero_doc = %s", sql)
        self.assertIn("8080", params)
        # ordem dos placeholders: vetor, vetor, limiar, dono, norma, limite
        self.assertEqual(params[3], 7)
        self.assertEqual(params[4], "8080")
        self.assertEqual(params[5], 15)

    def test_semantic_search_sem_numero_usa_tipo(self):
        """Norma sem número ("a Constituição") filtra por tipo_doc."""
        from agent import _semantic_search
        factory, cur, conn = _fake_conn(fetchall=[])
        _semantic_search([0.1, 0.2], limit=5, conn_factory=factory,
                         norma=("constituicao", None))
        sql, params = cur.execute.call_args[0]
        self.assertIn("tipo_doc = %s", sql)
        self.assertIn("constituicao", params)

    def test_semantic_search_sem_norma_nao_filtra(self):
        from agent import _semantic_search
        factory, cur, conn = _fake_conn(fetchall=[])
        _semantic_search([0.1, 0.2], limit=5, conn_factory=factory)
        sql, _ = cur.execute.call_args[0]
        self.assertNotIn("numero_doc = %s", sql)
        self.assertNotIn("tipo_doc = %s", sql)


class TestParseNormReference(unittest.TestCase):
    """P2-32: a norma que a PERGUNTA nomeia, mesmo sem artigo no texto."""

    def test_lei_com_numero_sem_artigo(self):
        from regime import _parse_norm_reference
        self.assertEqual(_parse_norm_reference("O que a Lei 8.080 diz sobre consórcios?"),
                         ("lei", "8080"))

    def test_decreto_com_numero(self):
        from regime import _parse_norm_reference
        self.assertEqual(
            _parse_norm_reference("Qual a cota do salário-família no Decreto 3.048?"),
            ("decreto", "3048"))

    def test_lei_complementar_nao_vira_lei(self):
        from regime import _parse_norm_reference
        self.assertEqual(_parse_norm_reference("O que diz a Lei Complementar 142?"),
                         ("lei_complementar", "142"))

    def test_constituicao_sem_numero(self):
        from regime import _parse_norm_reference
        self.assertEqual(_parse_norm_reference("O que diz a Constituição sobre saúde?"),
                         ("constituicao", None))

    def test_tema_sem_norma_devolve_none(self):
        from regime import _parse_norm_reference
        self.assertIsNone(_parse_norm_reference("Qual o prazo de prescrição do usucapião?"))
        self.assertIsNone(_parse_norm_reference("Como funciona a rescisão indireta?"))

    def test_artigo_sem_norma_nao_inventa_norma(self):
        from regime import _parse_norm_reference
        self.assertIsNone(_parse_norm_reference("O que diz o artigo 54?"))


class TestParseArticleReferenceCompat(unittest.TestCase):
    """Os exemplos documentados em `_parse_article_reference` continuam valendo.

    A extração de norma foi factorada para `_extrair_norma` (P2-32); este teste
    trava o contrato antigo — o refactor não podia mudar a referência de artigo.
    """

    def test_exemplos_documentados(self):
        from regime import _parse_article_reference as p
        self.assertEqual(p("artigo 54 do decreto 3048"), ("54", "decreto", "3048", None))
        self.assertEqual(p("art. 5o da constituição"), ("5", "constituicao", None, None))
        self.assertEqual(p("art 5 da cf"), ("5", "constituicao", None, None))
        self.assertEqual(p("art. 7 § 2 do decreto 3048"), ("7", "decreto", "3048", "2"))
        self.assertEqual(p("o que diz o artigo 6"), ("6", None, None, None))
        self.assertIsNone(p("células tronco"))


if __name__ == '__main__':
    unittest.main()
