"""Testes de gerenciamento com mocks, sem conectar no banco real ou no Ollama.

manage.py usa psycopg2.connect(DATABASE_URL) diretamente (não o pool de database.py),
então mockamos o módulo psycopg2 ANTES de importar manage.
"""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

psycopg2_mock = None
_original_modules = {}

def setUpModule():
    global psycopg2_mock
    # Backup original modules before mocking to prevent test pollution
    mocked_modules = ['psycopg2', 'psycopg2.extras', 'pgvector', 'pgvector.psycopg2']
    for m in mocked_modules:
        _original_modules[m] = sys.modules.get(m)

    # Mock psycopg2 antes de importar config/manage
    psycopg2_mock = MagicMock()
    sys.modules['psycopg2'] = psycopg2_mock
    sys.modules['psycopg2.extras'] = MagicMock()
    sys.modules['psycopg2.extras'].RealDictCursor = MagicMock()
    sys.modules['pgvector'] = MagicMock()
    sys.modules['pgvector.psycopg2'] = MagicMock()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _mock_cursor(fetchall=None):
    """Cria um cursor mockado com contexto correto (conn.cursor().__enter__)."""
    cur = MagicMock()
    if fetchall is not None:
        cur.fetchall.return_value = fetchall
    conn_mock = MagicMock()
    conn_mock.cursor.return_value.__enter__.return_value = cur
    conn_mock.__enter__.return_value = conn_mock
    psycopg2_mock.connect.return_value = conn_mock
    return cur


class TestListDocuments(unittest.TestCase):
    """Testa list_documents() com mock de psycopg2.connect."""

    def setUp(self):
        psycopg2_mock.reset_mock()

    def test_list_documents_returns_rows(self):
        from manage import list_documents
        cur = _mock_cursor(fetchall=[
            ("doc1.pdf", "2025-01-15 10:00:00", 5, "private"),
            ("doc2.pdf", "2025-01-14 09:00:00", 3, "global"),
        ])
        result = list_documents(user_id=1)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0][0], "doc1.pdf")
        self.assertEqual(result[0][2], 5)

    def test_list_documents_empty(self):
        from manage import list_documents
        _mock_cursor(fetchall=[])
        self.assertEqual(list_documents(user_id=1), [])

    def test_list_documents_uses_owner_filter_when_not_admin(self):
        from manage import list_documents
        cur = _mock_cursor(fetchall=[])
        list_documents(user_id=7, is_admin=False)
        sql = cur.execute.call_args[0][0]
        self.assertIn("owner_id = %s", sql)
        # 'OR scope = global' garante que usuário vê docs globais
        self.assertIn("scope = 'global'", sql)

    def test_list_documents_scoped_by_user_id(self):
        from manage import list_documents
        cur = _mock_cursor(fetchall=[])
        list_documents(user_id=7, is_admin=False)
        args = cur.execute.call_args[0][1]
        self.assertEqual(args, (7,))


class TestDeleteDocument(unittest.TestCase):
    """Testa delete_document() com mock de psycopg2.connect."""

    def setUp(self):
        psycopg2_mock.reset_mock()

    def test_admin_delete_named(self):
        from manage import delete_document
        cur = _mock_cursor()
        delete_document("test.pdf", is_admin=True)
        call_args = cur.execute.call_args[0]
        self.assertIn("DELETE", call_args[0].upper())
        self.assertEqual(call_args[1], ("test.pdf",))
        psycopg2_mock.connect.return_value.__enter__.return_value.commit.assert_called()

    def test_admin_delete_sem_nome(self):
        from manage import delete_document
        cur = _mock_cursor()
        delete_document('SEM_NOME', is_admin=True)
        call_args = cur.execute.call_args[0]
        self.assertIn("DELETE", call_args[0].upper())
        self.assertIn("FILE_NAME IS NULL", call_args[0].upper())

    def test_user_delete_own_private_only(self):
        from manage import delete_document
        cur = _mock_cursor()
        delete_document("test.pdf", user_id=3, is_admin=False)
        sql, params = cur.execute.call_args[0]
        self.assertIn("owner_id = %s", sql)
        self.assertIn("scope = 'private'", sql)
        self.assertIn("test.pdf", params)


class TestIntegrationMockedFlow(unittest.TestCase):
    """Fluxo listar -> deletar com mocks."""

    def test_list_then_delete_flow(self):
        from manage import list_documents, delete_document
        _mock_cursor(fetchall=[("doc1.pdf", "2025-01-15 10:00:00", 5, "private")])
        docs = list_documents(user_id=1)
        self.assertEqual(len(docs), 1)

        cur = _mock_cursor()
        delete_document("doc1.pdf", user_id=1, is_admin=False)
        self.assertIn("doc1.pdf", cur.execute.call_args[0][1])


def tearDownModule():
    # Restore original modules to prevent test pollution
    for m, val in _original_modules.items():
        if val is None:
            sys.modules.pop(m, None)
        else:
            sys.modules[m] = val


if __name__ == "__main__":
    unittest.main()
