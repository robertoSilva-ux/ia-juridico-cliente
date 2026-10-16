"""Testes do init_admin.py — o admin inicial não pode nascer adivinhável (P0-2).

Antes, `init_admin.py` caía em `admin123` quando `ADMIN_PASSWORD` não estava
definida, e o próprio `database/init.sql` semeava o mesmo admin com o hash fixo
(verificado por execução: o hash do SQL corresponde a 'admin123'). Aqui se
garante que o script falha em vez de criar credencial conhecida.

Mocka psycopg2/bcrypt antes de importar (padrão do projeto — ver docs/TESTING.md).
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Os mocks de infra precisam existir ANTES do primeiro import de `init_admin`
# (que importa psycopg2/bcrypt no topo) — mesmo padrão de test_auth.py: o setup
# roda no nível do módulo, não dentro de setUpModule, que só é chamado depois.
_mocked_modules = ['psycopg2', 'bcrypt']
_original_modules = {m: sys.modules.get(m) for m in _mocked_modules}
sys.modules['psycopg2'] = MagicMock()
sys.modules['bcrypt'] = MagicMock()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bcrypt  # noqa: E402  (mockado)
import psycopg2  # noqa: E402  (mockado)

from init_admin import (  # noqa: E402
    MIN_SENHA,
    SENHAS_PROIBIDAS,
    init_admin,
    validar_senha_admin,
)


class TestValidarSenhaAdmin(unittest.TestCase):

    def test_senha_ausente_e_recusada(self):
        for vazio in ("", None):
            msg = validar_senha_admin(vazio)
            self.assertIsNotNone(msg)
            self.assertIn("ADMIN_PASSWORD", msg)

    def test_senha_padrao_historica_e_recusada(self):
        msg = validar_senha_admin("admin123")
        self.assertIsNotNone(msg)
        self.assertIn("admin123", msg)

    def test_outras_senhas_previsiveis_sao_recusadas(self):
        for valor in SENHAS_PROIBIDAS:
            self.assertIsNotNone(validar_senha_admin(valor), f"{valor!r} deveria ser recusada")

    def test_senha_curta_e_recusada(self):
        msg = validar_senha_admin("a" * (MIN_SENHA - 1))
        self.assertIsNotNone(msg)
        self.assertIn(str(MIN_SENHA), msg)

    def test_senha_aceitavel_passa(self):
        self.assertIsNone(validar_senha_admin("S3nh4-de-advogado!"))


class TestInitAdminComMocks(unittest.TestCase):

    def setUp(self):
        import bcrypt
        bcrypt.reset_mock()
        bcrypt.hashpw.return_value = b'$2b$12$hash'
        bcrypt.gensalt.return_value = b'$2b$12$salt'
        psycopg2.reset_mock()

    def _mock_conn(self, fetchone=(1,)):
        conn = MagicMock()
        cur = MagicMock()
        cur.fetchone.return_value = fetchone
        conn.cursor.return_value.__enter__.return_value = cur
        conn.__enter__.return_value = conn
        psycopg2.connect.return_value = conn
        return cur

    @staticmethod
    def _run(env):
        """Roda init_admin() capturando o exit code e a mensagem impressa."""
        import contextlib
        import io
        saida = io.StringIO()
        with patch.dict(os.environ, env), contextlib.redirect_stdout(saida):
            code = init_admin()
        return code, saida.getvalue()

    def test_sem_admin_password_nao_toca_no_banco(self):
        code, msg = self._run({"ADMIN_PASSWORD": ""})
        self.assertEqual(code, 1, "deveria falhar quando ADMIN_PASSWORD não está definida")
        self.assertIn("ADMIN_PASSWORD", msg)
        psycopg2.connect.assert_not_called()
        import bcrypt
        bcrypt.hashpw.assert_not_called()

    def test_senha_padrao_nao_cria_admin(self):
        code, msg = self._run({"ADMIN_PASSWORD": "admin123"})
        self.assertEqual(code, 1)
        self.assertIn("admin123", msg)
        psycopg2.connect.assert_not_called()

    def test_senha_valida_cria_admin_com_hash(self):
        cur = self._mock_conn()
        code, msg = self._run({"ADMIN_EMAIL": "dono@cliente.com",
                               "ADMIN_PASSWORD": "S3nh4-de-advogado!"})
        self.assertEqual(code, 0)
        self.assertIn("dono@cliente.com", msg)
        import bcrypt
        bcrypt.hashpw.assert_called_once()
        sqls = [c[0][0] for c in cur.execute.call_args_list]
        insert = [s for s in sqls if "INSERT INTO users" in s]
        self.assertEqual(len(insert), 1)
        # a senha nunca vai em claro para o SQL: só o hash
        params = [c[0][1] for c in cur.execute.call_args_list
                  if "INSERT INTO users" in c[0][0]][0]
        self.assertNotIn("S3nh4-de-advogado!", params)
        self.assertIn("dono@cliente.com", params)

    def test_admin_existente_nao_reescreve_a_senha_e_avisa_do_legado(self):
        """Idempotente: rodar de novo não pode resetar a senha de quem já existe."""
        self._mock_conn(fetchone=None)   # ON CONFLICT DO NOTHING -> sem linha
        code, msg = self._run({"ADMIN_PASSWORD": "S3nh4-de-advogado!"})
        self.assertEqual(code, 0)
        self.assertIn("já existia", msg)
        # banco legado com a senha padrão antiga precisa de orientação explícita
        self.assertIn("admin123", msg)


def tearDownModule():
    for m, val in _original_modules.items():
        if val is None:
            sys.modules.pop(m, None)
        else:
            sys.modules[m] = val


if __name__ == "__main__":
    unittest.main()
