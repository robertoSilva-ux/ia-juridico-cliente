"""Testes da validação da chave de assinatura do cookie de sessão (P0-1).

O `streamlit-authenticator` assina o cookie com JWT/HS256 usando `COOKIE_KEY`
(`models/cookie_model.py`). Se essa chave for pública, curta ou ausente, qualquer
pessoa forja um cookie de admin e entra sem senha. Este módulo cobre a função
pura `config.cookie_key_problem()`, que é o portão usado em main.py.

Sem mocks: `config` só lê variáveis de ambiente.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import (  # noqa: E402
    COOKIE_KEY_MIN_BYTES,
    cookie_key_problem,
)

CHAVE_FORTE = "kJ2mQ0vT8sPzR1xY4nL7bC3dF6gH9wZ5aE2uI8oKpQ0rS4tU7vX1yB3nM6"


class TestCookieKeyValidation(unittest.TestCase):

    def test_chave_ausente_e_recusada(self):
        """`None` significa "usar config.COOKIE_KEY".

        Sem controlar o valor do MÓDULO, este teste mede o ambiente de quem roda:
        depois de `set -a; . ./.env.dev`, a variável existe e o fallback traria a
        chave real (verde por acidente); num ambiente limpo, mediria o código. Com
        o patch, o teste vale nos dois casos.
        """
        import config
        with patch.object(config, "COOKIE_KEY", ""):
            for vazio in ("", None):
                msg = cookie_key_problem(vazio)
                self.assertIsNotNone(msg)
                self.assertIn("COOKIE_KEY", msg)

    def test_valor_publico_do_repositorio_e_recusado(self):
        """'legal_ai_key' era o literal que estava em main.py (e no repo público)."""
        msg = cookie_key_problem("legal_ai_key")
        self.assertIsNotNone(msg)
        self.assertIn("legal_ai_key", msg)

    def test_outros_valores_de_tutorial_sao_recusados(self):
        for valor in ("some_key", "changeme", "secret"):
            self.assertIsNotNone(cookie_key_problem(valor), f"{valor!r} deveria ser recusado")

    def test_chave_curta_e_recusada(self):
        msg = cookie_key_problem("chave-de-32-bytes-exatamente-01")
        self.assertIsNotNone(msg)
        self.assertIn("bytes", msg)

    def test_chave_do_tamanho_minimo_passa(self):
        chave = "a" * COOKIE_KEY_MIN_BYTES
        self.assertIsNone(cookie_key_problem(chave))

    def test_chave_forte_passa(self):
        self.assertIsNone(cookie_key_problem(CHAVE_FORTE))

    def test_minimo_atende_a_rfc_7518(self):
        """HMAC-SHA256 exige >= 32 bytes (o pyjwt avisa abaixo disso)."""
        self.assertGreaterEqual(COOKIE_KEY_MIN_BYTES, 32)

    def test_mensagem_ensina_a_gerar_a_chave(self):
        msg = cookie_key_problem("")
        self.assertIn("secrets.token_urlsafe", msg)

    def test_comprimento_conta_bytes_e_nao_caracteres(self):
        """48 caracteres multi-byte não podem passar como 48 bytes."""
        chave = "á" * 24          # 48 bytes, 24 caracteres
        self.assertIsNone(cookie_key_problem(chave))
        chave_curta = "á" * 15    # 30 bytes, 15 caracteres
        self.assertIsNotNone(cookie_key_problem(chave_curta))


if __name__ == "__main__":
    unittest.main()
