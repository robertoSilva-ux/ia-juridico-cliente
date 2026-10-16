"""Escopo e limite do índice de dispositivos do fact-check (P1-1 / R-17).

Regressão: o índice era carregado uma única vez, para a **base inteira** — validava
dispositivo citado contra documento de OUTRO cliente e varria todo o corpus dentro de um
container de 512 MB. Passa a ser por dono, com teto de linhas e de caracteres, invalidado
pela ingestão.

`config` e `database` são substituídos ANTES do import: `factcheck` importa os dois no
nível do módulo, e o `database` real abre o pool no import (P2-27).
"""
import os
import sys
import unittest
import unittest.mock
from unittest.mock import MagicMock

_config = MagicMock()
_config.FACT_CHECK_ENABLED = True
_config.FACT_CHECK_LLM_ENABLED = True
_config.FACT_CHECK_CACHE_MAX_ROWS = 1000
_config.FACT_CHECK_CACHE_MAX_CHARS = 50
sys.modules["config"] = _config
sys.modules["database"] = MagicMock()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import factcheck  # noqa: E402


class _Cursor:
    """Duplo do cursor: registra as consultas e itera as linhas que o teste definir."""

    def __init__(self, rows):
        self.rows = rows
        self.consultas: list[tuple[str, tuple | None]] = []
        self.consumidas = 0

    def execute(self, sql, params=None):
        self.consultas.append((sql, params))

    def __iter__(self):
        for linha in self.rows:
            self.consumidas += 1
            yield linha

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _Conn:
    def __init__(self, cursor):
        self._cursor = cursor
        self.commit = MagicMock()

    def cursor(self):
        return self._cursor

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _Banco:
    """Fábrica de conexão que devolve sempre o mesmo cursor e conta as conexões."""

    def __init__(self, rows):
        self.cursor = _Cursor(rows)
        self.conexoes = 0

    def __call__(self):
        self.conexoes += 1
        return _Conn(self.cursor)


def _doc(**kw):
    base = {"id": 1, "file_name": "lei-8080.pdf", "content": "Art. 25. A carência é exigida.",
            "tipo_doc": "lei", "numero_doc": "8080", "ano_doc": "1990", "distance": 0.2}
    base.update(kw)
    return base


class TestEscopoDoIndice(unittest.TestCase):
    def setUp(self):
        factcheck.invalidate_dispositivos_cache()

    def test_sql_filtra_pelo_dono(self):
        banco = _Banco([("Art. 25 e art. 26.",)])
        with unittest.mock.patch.object(factcheck, "get_db_connection", banco):
            factcheck._load_dispositivos_base(9)
        sql, params = banco.cursor.consultas[0]
        self.assertIn("scope = 'global' OR owner_id = %s", sql)
        self.assertEqual(params, (9, _config.FACT_CHECK_CACHE_MAX_ROWS),
                         "o dono e o teto de linhas vão como parâmetro, nunca interpolados")

    def test_sem_dono_usa_global_e_legado_sem_dono(self):
        """Carga em lote/legado entra com owner_id NULL e scope 'global'."""
        banco = _Banco([("Art. 5.",)])
        with unittest.mock.patch.object(factcheck, "get_db_connection", banco):
            factcheck._load_dispositivos_base(None)
        sql, params = banco.cursor.consultas[0]
        self.assertIn("owner_id IS NULL", sql)
        self.assertEqual(params, (_config.FACT_CHECK_CACHE_MAX_ROWS,))

    def test_cache_e_por_dono_e_nao_mistura(self):
        banco = _Banco([("Art. 25.",)])
        with unittest.mock.patch.object(factcheck, "get_db_connection", banco):
            factcheck._load_dispositivos_base(9)
            factcheck._load_dispositivos_base(7)
        self.assertEqual(banco.conexoes, 2, "donos diferentes não compartilham índice")
        self.assertEqual([p[1][0] for p in banco.cursor.consultas], [9, 7])

    def test_cache_memoiza_dentro_do_mesmo_dono(self):
        banco = _Banco([("Art. 25.",)])
        with unittest.mock.patch.object(factcheck, "get_db_connection", banco):
            primeira = factcheck._load_dispositivos_base(9)
            segunda = factcheck._load_dispositivos_base(9)
        self.assertEqual(banco.conexoes, 1)
        self.assertIs(primeira, segunda)

    def test_teto_de_caracteres_interrompe_a_leitura(self):
        """Sem teto, a varredura da base inteira é o caminho do OOM (P1-1)."""
        linhas = [(f"Art. {n}. " + "x" * 20,) for n in range(1, 6)]      # 5 linhas de 28 chars
        banco = _Banco(linhas)
        with unittest.mock.patch.object(factcheck, "get_db_connection", banco):
            achados = factcheck._load_dispositivos_base(9)
        # teto de 50 caracteres: para depois da segunda linha (2 × 28 = 56 ≥ 50)
        self.assertLess(banco.cursor.consumidas, len(linhas), "não deve ler além do teto")
        self.assertIn("art2", achados)
        self.assertNotIn("art5", achados, "linha depois do teto não é lida")

    def test_invalidate_limpa_todos_os_donos(self):
        banco = _Banco([("Art. 25.",)])
        with unittest.mock.patch.object(factcheck, "get_db_connection", banco):
            factcheck._load_dispositivos_base(9)
            factcheck._load_dispositivos_base(7)
            factcheck.invalidate_dispositivos_cache()
            factcheck._load_dispositivos_base(9)
        self.assertEqual(banco.conexoes, 3, "depois de invalidar, recarrega")

    def test_falha_de_bd_nao_vira_alucinacao(self):
        """Base inacessível desliga a validação — não marca tudo como sem lastro."""
        def _explode():
            raise RuntimeError("banco fora do ar")

        with unittest.mock.patch.object(factcheck, "get_db_connection", _explode):
            self.assertEqual(factcheck._load_dispositivos_base(9), frozenset())
        status, _ = factcheck._check_semantic_grounding(
            "Aplica-se o art. 25 da Lei 8.213.", "Art. 25. A carência é exigida.", 9)
        self.assertEqual(status, "supported")


class TestDonoChegaAoIndice(unittest.TestCase):
    def test_fact_check_answer_repassa_o_dono(self):
        """O dono entra no índice de dispositivos por `_fact_check_answer`."""
        registrado = []
        with unittest.mock.patch.object(factcheck, "_load_dispositivos_base",
                                       side_effect=lambda user_id=None: registrado.append(user_id) or frozenset()):
            factcheck._fact_check_answer("Aplica-se o art. 25 [1].", [_doc()], user_id=9)
        self.assertIn(9, registrado)

    def test_sem_dono_explicito_o_indice_e_do_escopo_sem_dono(self):
        registrado = []
        with unittest.mock.patch.object(factcheck, "_load_dispositivos_base",
                                       side_effect=lambda user_id=None: registrado.append(user_id) or frozenset()):
            factcheck._fact_check_answer("Aplica-se o art. 25 [1].", [_doc()])
        self.assertEqual(registrado, [None])


class TestIngestaoInvalida(unittest.TestCase):
    """A ingestão muda a base: o índice do fact-check não pode ficar velho (P1-1)."""

    @classmethod
    def setUpClass(cls):
        for mod in ("config", "database", "embeddings", "langchain_community.document_loaders",
                    "langchain_text_splitters", "pgvector", "pgvector.psycopg2", "legal_parser"):
            sys.modules.setdefault(mod, MagicMock())
        sys.modules["factcheck"] = factcheck
        global _ingest
        import ingest as _ingest  # noqa: PLC0415

    def test_invalidacao_e_a_mesma_funcao_do_factcheck(self):
        self.assertIs(_ingest.invalidate_dispositivos_cache,
                      factcheck.invalidate_dispositivos_cache)

    def test_store_in_postgres_invalida_o_indice(self):
        chunk = MagicMock()
        chunk.page_content = "Art. 25. A carência é exigida ao segurado."
        chunk.metadata = {}
        with unittest.mock.patch.object(_ingest, "_filter_existing", return_value=[chunk]), \
             unittest.mock.patch.object(_ingest, "_get_or_create_source", return_value=1), \
             unittest.mock.patch.object(_ingest, "_embed_with_retry", return_value=[[0.0] * 768]), \
             unittest.mock.patch.object(_ingest.psycopg2, "connect", return_value=MagicMock()), \
             unittest.mock.patch.object(_ingest, "register_vector"), \
             unittest.mock.patch.object(_ingest.psycopg2.extras, "execute_values"), \
             unittest.mock.patch.object(_ingest, "invalidate_dispositivos_cache") as invalidar:
            progresso = list(_ingest.store_in_postgres(
                [chunk], MagicMock(), "lei-8080.pdf", owner_id=9, batch_size=1))
        self.assertEqual(progresso, [1.0], "a gravação do lote precisa ter acontecido")
        invalidar.assert_called()


if __name__ == "__main__":
    unittest.main()
