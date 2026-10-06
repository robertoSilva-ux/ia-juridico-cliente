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


if __name__ == '__main__':
    unittest.main()
