"""Testes de autenticação com mocks, sem conectar no banco real."""
import os
import sys
import json
import unittest
from unittest.mock import patch, MagicMock, PropertyMock

# Backup original modules before mocking to prevent test pollution
_mocked_modules = ['psycopg2', 'psycopg2.extras', 'psycopg2.pool', 'pgvector', 'pgvector.psycopg2', 'bcrypt']
_original_modules = {m: sys.modules.get(m) for m in _mocked_modules}

# Mock psycopg2 e pgvector antes de importar auth/database
sys.modules['psycopg2'] = MagicMock()
sys.modules['psycopg2.extras'] = MagicMock()
sys.modules['psycopg2.extras'].RealDictCursor = MagicMock()
sys.modules['psycopg2.pool'] = MagicMock()
sys.modules['psycopg2.pool'].SimpleConnectionPool = MagicMock()
sys.modules['pgvector'] = MagicMock()
sys.modules['pgvector.psycopg2'] = MagicMock()

# Mock bcrypt também (evita dep na lib)
sys.modules['bcrypt'] = MagicMock()

import bcrypt

# Adiciona o diretório atual ao path para importar os módulos da app
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from auth import validate_email, validate_password
from auth import add_user, get_all_users_for_auth, update_password

# Restore original modules immediately after import to prevent test pollution
for m, val in _original_modules.items():
    if val is None:
        sys.modules.pop(m, None)
    else:
        sys.modules[m] = val


class TestAuthValidation(unittest.TestCase):
    """Testes de validação de input puros (sem banco)."""

    def test_validate_email_valid(self):
        self.assertTrue(validate_email("user@example.com"))
        self.assertTrue(validate_email("user.name+tag@example.co"))
        self.assertTrue(validate_email("admin@legaliz.ai"))

    def test_validate_email_invalid(self):
        self.assertFalse(validate_email(""))
        self.assertFalse(validate_email("not-an-email"))
        self.assertFalse(validate_email("user@"))
        self.assertFalse(validate_email("@domain.com"))
        self.assertFalse(validate_email("user@.com"))

    def test_validate_password_valid(self):
        valid, msg = validate_password("12345678")
        self.assertTrue(valid)

    def test_validate_password_too_short(self):
        valid, msg = validate_password("1234567")
        self.assertFalse(valid)
        self.assertIn("8 caracteres", msg)

    def test_validate_password_empty(self):
        valid, msg = validate_password("")
        self.assertFalse(valid)
        self.assertIn("8 caracteres", msg)


class TestAddUserWithMocks(unittest.TestCase):
    """Testa add_user() com mock do banco."""

    def setUp(self):
        # Garante bcrypt mockado
        bcrypt.hashpw.return_value = b'$2b$12$hashedpassword'
        bcrypt.gensalt.return_value = b'$2b$12$salt'

    @patch("auth.get_db_connection")
    def test_add_user_success(self, mock_get_db_conn):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_get_db_conn.return_value.__enter__.return_value = mock_conn

        success, msg = add_user("user@test.com", "Test User", "password123", "user")

        self.assertTrue(success)
        self.assertIn("sucesso", msg.lower())
        mock_cursor.execute.assert_called_once()
        mock_conn.commit.assert_called_once()

    @patch("auth.get_db_connection")
    def test_add_user_invalid_email(self, mock_get_db_conn):
        success, msg = add_user("invalido", "Test User", "password123", "user")

        self.assertFalse(success)
        self.assertIn("email inválido", msg.lower())
        mock_get_db_conn.assert_not_called()

    @patch("auth.get_db_connection")
    def test_add_user_empty_name(self, mock_get_db_conn):
        success, msg = add_user("user@test.com", "", "password123", "user")

        self.assertFalse(success)
        self.assertIn("vazio", msg.lower())
        mock_get_db_conn.assert_not_called()

    @patch("auth.get_db_connection")
    def test_add_user_short_password(self, mock_get_db_conn):
        success, msg = add_user("user@test.com", "Test User", "123", "user")

        self.assertFalse(success)
        self.assertIn("8 caracteres", msg.lower())
        mock_get_db_conn.assert_not_called()

    @patch("auth.get_db_connection")
    def test_add_user_duplicate_email(self, mock_get_db_conn):
        class UniqueViolation(Exception):
            pass

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.execute.side_effect = UniqueViolation("duplicate key value")
        mock_get_db_conn.return_value.__enter__.return_value = mock_conn

        success, msg = add_user("existing@test.com", "Existing", "password123", "user")

        self.assertFalse(success)
        self.assertTrue(len(msg) > 0)


class TestGetUsersWithMocks(unittest.TestCase):
    """Testa get_all_users_for_auth() com mock."""

    @patch("auth.get_db_connection")
    def test_get_all_users(self, mock_get_db_conn):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        mock_cursor.fetchall.return_value = [
            {"id": 1, "email": "admin@legaliz.ai", "name": "Admin", "password_hash": "hash1", "role": "admin"},
            {"id": 2, "email": "user@test.com", "name": "User", "password_hash": "hash2", "role": "user"},
        ]
        mock_get_db_conn.return_value.__enter__.return_value = mock_conn

        creds = get_all_users_for_auth()

        self.assertIn("admin@legaliz.ai", creds["usernames"])
        self.assertIn("user@test.com", creds["usernames"])
        self.assertEqual(creds["usernames"]["admin@legaliz.ai"]["role"], "admin")


class TestUpdatePasswordWithMocks(unittest.TestCase):
    """Testa update_password() com mock."""

    @patch("auth.get_db_connection")
    def test_update_password(self, mock_get_db_conn):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_get_db_conn.return_value.__enter__.return_value = mock_conn

        update_password("user@test.com", "newpass123")

        mock_cursor.execute.assert_called_once()
        call_args = mock_cursor.execute.call_args[0]
        self.assertIn("UPDATE", call_args[0].upper())
        self.assertEqual(call_args[1][1], "user@test.com")
        mock_conn.commit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
