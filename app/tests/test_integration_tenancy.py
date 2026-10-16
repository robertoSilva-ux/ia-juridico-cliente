"""Teste de INTEGRAÇÃO do isolamento por dono contra um Postgres pgvector REAL.

Cobre, de ponta a ponta, as regressões corrigidas em docs/REVISAO_SEGURANCA.md:

  * P0-3: mudar o escopo de um arquivo NÃO pode afetar arquivos homônimos de
    outros donos (`manage.update_document_scope`);
  * P0-4: o upload do segundo dono com o mesmo nome de arquivo não pode ser
    descartado pelo dedup, nem roubar a linha de `sources` do primeiro
    (`ingest._filter_existing` / `ingest._get_or_create_source`);
  * exclusão escopada por dono (`manage.delete_document`).

Pré-requisito: banco pgvector de teste com o schema de `docs/legal_test_schema.sql`
(ver docs/TESTING.md). Se o banco não estiver disponível, o módulo é pulado.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock

_original_modules = {}


def setUpModule():
    # Backup original modules before mocking to prevent test pollution
    mocked_modules = ['langchain_community', 'langchain_community.document_loaders', 'langchain_text_splitters']
    for m in mocked_modules:
        _original_modules[m] = sys.modules.get(m)

    # Só os loaders do langchain são mockados (não usados aqui).
    # psycopg2/pgvector ficam REAIS: o ponto do teste é o banco de verdade.
    sys.modules['langchain_community'] = MagicMock()
    sys.modules['langchain_community.document_loaders'] = MagicMock()
    sys.modules['langchain_community.document_loaders'].PyPDFLoader = MagicMock()
    sys.modules['langchain_text_splitters'] = MagicMock()
    sys.modules['langchain_text_splitters'].RecursiveCharacterTextSplitter = MagicMock()


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql://user:***@localhost:5440/legal_test",
)

# database.py cria o pool no import a partir de config.DATABASE_URL: aponta para
# o banco de teste ANTES de qualquer import da app.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ.setdefault("OLLAMA_BASE_URL", "http://localhost:11434")


def _db_available():
    try:
        import psycopg2
        conn = psycopg2.connect(TEST_DATABASE_URL, connect_timeout=2)
        conn.close()
        return True
    except Exception:
        return False


DB_AVAILABLE = _db_available()

ALICE = "alice@tenant-a.legaliz.ai"
BRUNO = "bruno@tenant-b.legaliz.ai"
ADMIN = "admin@legaliz.ai"
MESMO_ARQUIVO = "peticao.pdf"


class FakeChunk:
    def __init__(self, content, metadata=None):
        self.page_content = content
        self.metadata = metadata or {}


class FakeEmbedder:
    """Embedder determinístico — vetor de 768 dims derivado do índice do texto."""

    def embed_documents(self, texts):
        return [[float(i + 1) / 100] * 768 for i in range(len(texts))]


@unittest.skipUnless(DB_AVAILABLE, "Banco pgvector de teste indisponível na porta 5440")
class TestIsolamentoPorDono(unittest.TestCase):
    """P0-3/P0-4: um dono nunca deve sofrer efeito colateral do arquivo de outro."""

    @classmethod
    def setUpClass(cls):
        import psycopg2
        import ingest
        import manage

        cls.ingest = ingest
        cls.manage = manage
        cls.psycopg2 = psycopg2

        conn = psycopg2.connect(TEST_DATABASE_URL)
        conn.autocommit = True
        with conn.cursor() as cur:
            for email, papel in ((ALICE, 'user'), (BRUNO, 'user'), (ADMIN, 'admin')):
                cur.execute(
                    "INSERT INTO users (email, name, password_hash, role) "
                    "VALUES (%s, %s, 'x', %s) ON CONFLICT (email) DO NOTHING",
                    (email, email.split('@')[0], papel),
                )
            cur.execute("SELECT email, id FROM users WHERE email = ANY(%s)", ([ALICE, BRUNO, ADMIN],))
            cls.ids = dict(cur.fetchall())
        conn.close()

    def setUp(self):
        # Limpa a base de teste por inteiro: os módulos de integração compartilham
        # o mesmo banco e o irmão (test_integration_ingest) deixa documentos e
        # fontes para trás. Sem isso, `scope = 'global'` do vizinho entra nas
        # contagens de visibilidade e o teste falha por contaminação, não por bug.
        conn = self.psycopg2.connect(TEST_DATABASE_URL)
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("DELETE FROM documents")
            cur.execute("DELETE FROM sources")
        conn.close()

    # ---------- helpers ----------

    def _store(self, chunks, owner_id, scope='private'):
        list(self.ingest.store_in_postgres(
            chunks, FakeEmbedder(), MESMO_ARQUIVO, owner_id=owner_id, scope=scope, batch_size=10,
        ))

    def _query(self, sql, params=()):
        conn = self.psycopg2.connect(TEST_DATABASE_URL)
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        conn.close()
        return rows

    def _chunks_visiveis_para(self, owner_id):
        """Reproduz o filtro de escopo do chat (agent._semantic_search)."""
        return self._query(
            "SELECT content FROM documents WHERE scope = 'global' OR owner_id = %s",
            (owner_id,),
        )

    # ---------- P0-4: dedup e sources por dono ----------

    def test_upload_do_segundo_dono_com_mesmo_nome_e_indexado(self):
        """Antes: os chunks do 2º dono eram 100% filtrados pelo dedup do 1º."""
        alice, bruno = self.ids[ALICE], self.ids[BRUNO]
        conteudo = ["Art. 54. Aposentadoria por tempo de contribuicao.", "§ 1º Carência."]

        self._store([FakeChunk(c) for c in conteudo], owner_id=alice)
        self._store([FakeChunk(c) for c in conteudo], owner_id=bruno)

        self.assertEqual(
            len(self._query("SELECT id FROM documents WHERE owner_id = %s", (alice,))), 2,
        )
        self.assertEqual(
            len(self._query("SELECT id FROM documents WHERE owner_id = %s", (bruno,))), 2,
            "o upload do segundo dono foi descartado (dedup atravessando donos)",
        )
        self.assertEqual(len(self._chunks_visiveis_para(bruno)), 2)

    def test_dedup_continua_valendo_para_o_mesmo_dono(self):
        """O dedup não foi desligado: reindexar o MESMO dono não duplica."""
        alice = self.ids[ALICE]
        conteudo = ["Art. 54. Aposentadoria por tempo de contribuicao."]
        self._store([FakeChunk(c) for c in conteudo], owner_id=alice)
        self._store([FakeChunk(c) for c in conteudo], owner_id=alice)
        self.assertEqual(
            len(self._query("SELECT id FROM documents WHERE owner_id = %s", (alice,))), 1,
        )

    def test_sources_nao_troca_de_dono(self):
        """Antes: o upsert do 2º dono reescrevia owner_id da fonte do 1º."""
        alice, bruno = self.ids[ALICE], self.ids[BRUNO]
        self._store([FakeChunk("Art. 54. Texto da Alice.")], owner_id=alice)
        self._store([FakeChunk("Art. 54. Texto do Bruno.")], owner_id=bruno)

        fontes = dict(self._query(
            "SELECT owner_id, id FROM sources WHERE file_name = %s", (MESMO_ARQUIVO,),
        ))
        self.assertEqual(set(fontes), {alice, bruno}, "as fontes homônimas devem coexistir, uma por dono")
        self.assertNotEqual(fontes[alice], fontes[bruno])

        # os chunks de cada dono apontam para a PRÓPRIA fonte
        for dono in (alice, bruno):
            source_ids = {r[0] for r in self._query(
                "SELECT source_id FROM documents WHERE owner_id = %s", (dono,))}
            self.assertEqual(source_ids, {fontes[dono]})

    # ---------- P0-3: escopo por dono ----------

    def test_tornar_global_um_documento_nao_promove_o_homonimo_de_outro_dono(self):
        alice, bruno = self.ids[ALICE], self.ids[BRUNO]
        self._store([FakeChunk("Segredo da Alice.")], owner_id=alice)
        self._store([FakeChunk("Peça do Bruno.")], owner_id=bruno)

        # O admin promove a peça do Bruno (a linha certa, um dono por vez)
        alterados = self.manage.update_document_scope(
            MESMO_ARQUIVO, 'global', user_id=self.ids[ADMIN], is_admin=True, owner_id=bruno,
        )
        self.assertEqual(alterados, 1)

        escopos = dict(self._query("SELECT owner_id, scope FROM documents"))
        self.assertEqual(escopos[bruno], 'global')
        self.assertEqual(escopos[alice], 'private',
                         "o documento privado da Alice vazou junto (regressão do P0-3)")

        # O que cada um vê no chat (filtro de escopo do agent):
        #  - Bruno: só o próprio documento (o da Alice segue privado);
        #  - Alice: o dela + o que virou global (o do Bruno) — efeito pretendido.
        visiveis_bruno = {c for (c,) in self._chunks_visiveis_para(bruno)}
        self.assertEqual(visiveis_bruno, {"Peça do Bruno."})
        visiveis_alice = {c for (c,) in self._chunks_visiveis_para(alice)}
        self.assertEqual(visiveis_alice, {"Segredo da Alice.", "Peça do Bruno."})

    def test_sources_acompanha_a_mudanca_de_escopo(self):
        """documents e sources não podem divergir sobre o que é público."""
        alice = self.ids[ALICE]
        self._store([FakeChunk("Segredo da Alice.")], owner_id=alice)
        self.manage.update_document_scope(
            MESMO_ARQUIVO, 'global', user_id=self.ids[ADMIN], is_admin=True, owner_id=alice,
        )
        self.assertEqual(self._query("SELECT scope FROM sources"), [('global',)])

    def test_usuario_comum_nao_gerencia_documento_de_outro_dono(self):
        alice, bruno = self.ids[ALICE], self.ids[BRUNO]
        self._store([FakeChunk("Segredo da Alice.")], owner_id=alice)
        with self.assertRaises(PermissionError):
            self.manage.update_document_scope(
                MESMO_ARQUIVO, 'global', user_id=bruno, is_admin=False, owner_id=alice,
            )

    def test_escopo_invalido_e_recusado(self):
        alice = self.ids[ALICE]
        self._store([FakeChunk("Texto.")], owner_id=alice)
        with self.assertRaises(ValueError):
            self.manage.update_document_scope(
                MESMO_ARQUIVO, 'public', user_id=alice, is_admin=False,
            )

    def test_gerenciamento_sem_user_id_falha_alto(self):
        """Sem saber quem age, a operação não pode varrer a base inteira: falha."""
        with self.assertRaises(ValueError):
            self.manage.delete_document(MESMO_ARQUIVO, is_admin=True)

    def test_delete_escopado_por_dono(self):
        alice, bruno = self.ids[ALICE], self.ids[BRUNO]
        self._store([FakeChunk("Segredo da Alice.")], owner_id=alice)
        self._store([FakeChunk("Peça do Bruno.")], owner_id=bruno)

        removidos = self.manage.delete_document(
            MESMO_ARQUIVO, user_id=self.ids[ADMIN], is_admin=True, owner_id=bruno,
        )
        self.assertEqual(removidos, 1)
        self.assertEqual(len(self._query("SELECT id FROM documents WHERE owner_id = %s", (alice,))), 1,
                         "o arquivo privado da Alice foi apagado junto (regressão)")
        self.assertEqual(len(self._query("SELECT id FROM documents WHERE owner_id = %s", (bruno,))), 0)

    def test_delete_do_usuario_comum_nao_apaga_o_global_de_outro(self):
        """Usuário comum só apaga o que é privado e seu."""
        alice, bruno = self.ids[ALICE], self.ids[BRUNO]
        self._store([FakeChunk("Documento global da lei.")], owner_id=alice, scope='global')
        removidos = self.manage.delete_document(MESMO_ARQUIVO, user_id=bruno, is_admin=False)
        self.assertEqual(removidos, 0)
        self.assertEqual(len(self._query("SELECT id FROM documents")), 1)


def tearDownModule():
    for m, val in _original_modules.items():
        if val is None:
            sys.modules.pop(m, None)
        else:
            sys.modules[m] = val


if __name__ == "__main__":
    unittest.main()
