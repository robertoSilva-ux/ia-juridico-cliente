#!/usr/bin/env python3
"""Testes unitários do backfill_sources.py (Task 7).

Testa a lógica pura de _get_or_create_source SEM banco real: mocka o cursor e
valida que o SQL de upsert é montado com os parâmetros corretos (title/tipo/
numero/ano derivados de parse_file_name + build_title) e que o id retornado
vem do fetchone.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock

_original_modules = {}

def setUpModule():
    # Mock das deps de infra ANTES de importar o script (padrão do projeto).
    _original_modules['database'] = sys.modules.get('database')
    _original_modules['legal_parser'] = sys.modules.get('legal_parser')
    db = MagicMock()
    db.get_db_connection = MagicMock()
    sys.modules['database'] = db
    # legal_parser fica REAL (lógica pura que queremos exercitar)

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def tearDownModule():
    for m, val in _original_modules.items():
        if val is None:
            sys.modules.pop(m, None)
        else:
            sys.modules[m] = val


class TestGetOrCreateSource(unittest.TestCase):
    def _load(self):
        # importa o script com os mocks ativos
        import importlib
        import scripts.backfill_sources as bs
        return bs

    def _fake_cursor(self, returned_id):
        cur = MagicMock()
        cur.fetchone.return_value = (returned_id,)
        return cur

    def test_retorna_id_do_fetchone(self):
        bs = self._load()
        cur = self._fake_cursor(42)
        sid = bs._get_or_create_source(cur, "Lei 8.213-91.pdf", owner_id=None, scope='global')
        self.assertEqual(sid, 42)
        cur.execute.assert_called_once()

    def test_upsert_com_parametros_de_titulo(self):
        """O UPSSERT deve receber file_name, title e tipo/numero/ano derivados."""
        bs = self._load()
        cur = self._fake_cursor(7)
        bs._get_or_create_source(cur, "Decreto 3.048-99.pdf", owner_id=1, scope='global')
        sql, params = cur.execute.call_args[0]
        self.assertIn("ON CONFLICT (file_name)", sql)
        self.assertIn("RETURNING id", sql)
        # params = (file_name, title, tipo, numero, ano, owner_id, scope)
        self.assertEqual(params[0], "Decreto 3.048-99.pdf")
        self.assertEqual(params[1], "Decreto 3.048/99")  # title via build_title
        self.assertEqual(params[2], "decreto")
        self.assertEqual(params[3], "3048")
        self.assertEqual(params[4], "1999")
        self.assertEqual(params[5], 1)
        self.assertEqual(params[6], 'global')

    def test_retorna_none_quando_fetchone_vazio(self):
        bs = self._load()
        cur = MagicMock()
        cur.fetchone.return_value = None
        sid = bs._get_or_create_source(cur, "doc.pdf")
        self.assertIsNone(sid)


if __name__ == '__main__':
    unittest.main()
