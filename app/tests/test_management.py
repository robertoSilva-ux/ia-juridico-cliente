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

    def test_list_documents_inclui_o_dono_e_agrupa_por_dono(self):
        """Dois donos com arquivos homônimos precisam aparecer separados."""
        from manage import list_documents
        cur = _mock_cursor(fetchall=[("peticao.pdf", None, 2, "private", 1, "a@x.com")])
        rows = list_documents(user_id=1, is_admin=True)
        sql = cur.execute.call_args[0][0]
        self.assertIn("d.owner_id", sql)
        self.assertIn("LEFT JOIN users", sql)
        self.assertIn("GROUP BY d.file_name, d.scope, d.owner_id, u.email", sql)
        # a tupla alimenta o unpack de main.py: (nome, data, chunks, escopo, dono, email)
        nome, _data, chunks, escopo, owner_id, owner_email = rows[0]
        self.assertEqual((nome, chunks, escopo, owner_id, owner_email),
                         ("peticao.pdf", 2, "private", 1, "a@x.com"))


class TestDeleteDocument(unittest.TestCase):
    """Testa delete_document() com mock de psycopg2.connect."""

    def setUp(self):
        psycopg2_mock.reset_mock()

    def test_admin_delete_named_is_scoped_by_owner(self):
        """Antes: `WHERE file_name = %s` apagava o arquivo homônimo de todo mundo."""
        from manage import delete_document
        cur = _mock_cursor()
        cur.rowcount = 3
        removidos = delete_document("test.pdf", user_id=1, is_admin=True)
        sql, params = cur.execute.call_args[0]
        self.assertIn("DELETE", sql.upper())
        self.assertIn("owner_id = %s", sql)
        self.assertEqual(params, ("test.pdf", 1))
        self.assertEqual(removidos, 3)
        psycopg2_mock.connect.return_value.__enter__.return_value.commit.assert_called()

    def test_admin_delete_sem_nome_so_toca_orfaos_sem_dono(self):
        from manage import delete_document
        cur = _mock_cursor()
        delete_document('SEM_NOME', user_id=1, is_admin=True)
        sql = cur.execute.call_args[0][0].upper()
        self.assertIn("FILE_NAME IS NULL", sql)
        self.assertIn("OWNER_ID IS NULL", sql)

    def test_delete_de_admin_sem_user_id_falha_alto(self):
        """Sem saber quem age não há como escopar: melhor falhar que varrer a base."""
        from manage import delete_document
        with self.assertRaises(ValueError):
            delete_document("test.pdf", is_admin=True)

    def test_user_delete_own_private_only(self):
        from manage import delete_document
        cur = _mock_cursor()
        delete_document("test.pdf", user_id=3, is_admin=False)
        sql, params = cur.execute.call_args[0]
        self.assertIn("owner_id = %s", sql)
        self.assertIn("scope = 'private'", sql)
        self.assertIn("test.pdf", params)


class TestUpdateDocumentScope(unittest.TestCase):
    """Escopo é atributo do arquivo de UM dono (ver P0-3 na revisão de segurança)."""

    def setUp(self):
        psycopg2_mock.reset_mock()

    def test_sql_escopado_por_owner(self):
        from manage import update_document_scope
        cur = _mock_cursor()
        cur.rowcount = 2
        alterados = update_document_scope("peticao.pdf", "global", user_id=7)
        sql, params = cur.execute.call_args_list[0][0]
        self.assertIn("UPDATE documents SET scope = %s", sql)
        self.assertIn("owner_id = %s", sql)
        self.assertEqual(params, ("global", "peticao.pdf", 7))
        self.assertEqual(alterados, 2)

    def test_sincroniza_sources_na_mesma_transacao(self):
        """documents e sources não podem divergir sobre o que é público."""
        from manage import update_document_scope
        cur = _mock_cursor()
        update_document_scope("peticao.pdf", "global", user_id=7)
        sqls = [c[0][0] for c in cur.execute.call_args_list]
        self.assertEqual(len(sqls), 2)
        self.assertIn("UPDATE documents", sqls[0])
        self.assertIn("UPDATE sources", sqls[1])
        psycopg2_mock.connect.return_value.__enter__.return_value.commit.assert_called()

    def test_admin_pode_agir_sobre_o_dono_informado(self):
        from manage import update_document_scope
        cur = _mock_cursor()
        update_document_scope("peticao.pdf", "private", user_id=1, is_admin=True, owner_id=2)
        self.assertEqual(cur.execute.call_args_list[0][0][1], ("private", "peticao.pdf", 2))

    def test_usuario_comum_nao_pode_agir_sobre_outro_dono(self):
        from manage import update_document_scope
        with self.assertRaises(PermissionError):
            update_document_scope("peticao.pdf", "global", user_id=7, is_admin=False, owner_id=8)

    def test_escopo_invalido_recusado_antes_de_tocar_o_banco(self):
        from manage import update_document_scope
        with self.assertRaises(ValueError):
            update_document_scope("peticao.pdf", "public", user_id=7)
        psycopg2_mock.connect.assert_not_called()

    def test_sem_user_id_falha(self):
        from manage import update_document_scope
        with self.assertRaises(ValueError):
            update_document_scope("peticao.pdf", "global")


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
