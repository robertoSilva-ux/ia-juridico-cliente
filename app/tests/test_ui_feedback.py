"""Testes do retorno de ações da interface (`ui_feedback`).

Cobre a regressão que motivou o módulo: a ingestão terminava com
`st.success(...)` **seguido de** `st.rerun()`, e o rerun descarta a renderização
da execução atual — a mensagem sumia no mesmo instante em que aparecia, e a única
evidência de sucesso era a linha nova na tabela de documentos.

`streamlit` não roda fora do seu runtime, então aqui entra um duplo **fiel** no
ponto que importa: atributo desconhecido levanta `AttributeError`, como no
Streamlit de verdade. Com um `MagicMock` puro, `getattr(st, "tipo-inventado")`
devolveria um mock novo e o teste do fallback nunca poderia falhar.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Módulos da app que o `ui_feedback` importa. São substituídos por duplos ANTES
# do import porque `ingest` importa `database`, que **abre o pool de conexões no
# import** (P2-27): sem isso, este teste passaria a exigir um banco alcançável só
# para ser importado — e falhava de forma intermitente quando a suíte rodava num
# ambiente sem `DATABASE_URL` (processo em segundo plano, por exemplo).
for _mod in ("config", "embeddings", "ingest", "database"):
    sys.modules.setdefault(_mod, MagicMock())


class _SessionState(dict):
    """Só o que o módulo usa de `st.session_state`: indexação por chave e `pop`."""


class _FakeStreamlit:
    """Duplo com apenas a superfície que o módulo usa."""

    def __init__(self):
        self.session_state = _SessionState()
        for nome in ("success", "error", "warning", "info", "status", "progress", "empty",
                     "markdown", "caption", "write", "expander"):
            setattr(self, nome, MagicMock())

    def reset_mock(self):
        for nome in ("success", "error", "warning", "info", "status", "progress", "empty",
                     "markdown", "caption", "write", "expander"):
            getattr(self, nome).reset_mock()


_fake_st = _FakeStreamlit()
# Definido ANTES do import do módulo sob teste.
sys.modules["streamlit"] = _fake_st

import ui_feedback  # noqa: E402

_AVISOS = ("success", "error", "warning", "info")


class TestFlash(unittest.TestCase):
    def setUp(self):
        _fake_st.session_state.clear()
        _fake_st.reset_mock()

    def test_flash_nao_exibe_na_propria_execucao(self):
        """Se exibisse agora, o rerun seguinte levaria a mensagem embora."""
        ui_feedback.flash("documento indexado")
        self.assertEqual(_fake_st.success.call_count, 0)

    def test_render_flash_exibe_e_nao_repete(self):
        ui_feedback.flash("indexado: 7 fragmentos")
        ui_feedback.render_flash()
        _fake_st.success.assert_called_once_with("indexado: 7 fragmentos")
        ui_feedback.render_flash()
        self.assertEqual(_fake_st.success.call_count, 1, "a mensagem não pode se repetir a cada rerun")

    def test_tipo_escolhe_o_aviso(self):
        ui_feedback.flash("falhou", tipo="error")
        ui_feedback.render_flash()
        _fake_st.error.assert_called_once_with("falhou")

    def test_tipo_desconhecido_nao_engole_a_mensagem(self):
        """Tipo errado não pode fazer a confirmação sumir da tela."""
        ui_feedback.flash("aviso estranho", tipo="nao-existe")
        ui_feedback.render_flash()
        _fake_st.info.assert_called_once_with("aviso estranho")

    def test_sem_pendencia_nao_exibe_nada(self):
        ui_feedback.render_flash()
        for nome in _AVISOS:
            self.assertEqual(getattr(_fake_st, nome).call_count, 0)


class TestIndexacaoPdf(unittest.TestCase):
    """A mensagem tem de refletir o que a indexação REALMENTE fez."""

    def setUp(self):
        _fake_st.reset_mock()

    def _arquivo(self, nome="lei.pdf"):
        arquivo = MagicMock()
        arquivo.name = nome
        arquivo.getbuffer.return_value = b"%PDF-1.4 conteudo falso"
        return arquivo

    def test_sucesso_reporta_fragmentos_e_escopo(self):
        with patch.object(ui_feedback, "NomicOllamaEmbeddings"), \
             patch.object(ui_feedback, "ingest_document", return_value=7) as m:
            msg, tipo = ui_feedback.render_indexacao_pdf(
                self._arquivo(), user_id=42, scope="private"
            )
        self.assertEqual(tipo, "success")
        self.assertIn("7 fragmento", msg)
        self.assertIn("lei.pdf", msg)
        self.assertEqual(m.call_args.kwargs["owner_id"], 42)
        self.assertEqual(m.call_args.kwargs["scope"], "private")

    def test_zero_fragmentos_nao_e_anunciado_como_sucesso(self):
        """PDF escaneado (sem texto) e dedup não são sucesso — antes, os dois eram (P1-6)."""
        with patch.object(ui_feedback, "NomicOllamaEmbeddings"), \
             patch.object(ui_feedback, "ingest_document", return_value=0):
            msg, tipo = ui_feedback.render_indexacao_pdf(
                self._arquivo(), user_id=1, scope="private"
            )
        self.assertEqual(tipo, "warning")
        self.assertIn("escaneado", msg)

    def test_falha_preserva_a_causa(self):
        with patch.object(ui_feedback, "NomicOllamaEmbeddings"), \
             patch.object(ui_feedback, "ingest_document", side_effect=RuntimeError("Ollama não respondeu")):
            msg, tipo = ui_feedback.render_indexacao_pdf(
                self._arquivo(), user_id=1, scope="private"
            )
        self.assertEqual(tipo, "error")
        self.assertIn("Ollama não respondeu", msg)

    def test_arquivo_temporario_e_removido_mesmo_com_erro(self):
        caminhos = []

        def _guardar(caminho, *args, **kwargs):
            with open(caminho, "rb") as fh:
                self.assertTrue(fh.read(), "o PDF precisa chegar ao disco")
            caminhos.append(caminho)
            raise RuntimeError("falha no meio")

        with patch.object(ui_feedback, "NomicOllamaEmbeddings"), \
             patch.object(ui_feedback, "ingest_document", side_effect=_guardar):
            ui_feedback.render_indexacao_pdf(self._arquivo(), user_id=1, scope="global")
        self.assertEqual(len(caminhos), 1)
        self.assertFalse(os.path.exists(caminhos[0]), "arquivo temporário ficou para trás")


class TestRespostaNaInterface(unittest.TestCase):
    """O veredito de lastro e a recusa honesta têm de chegar à TELA.

    Regressão medida em 2026-10-16: o `agent` calculava o fact-check e o `main.py`
    descartava o resultado — uma pergunta fora da base saía como resposta com 15
    fontes e selo verde. Aqui se garante que a recusa não é apresentada como
    resposta, que a ressalva de lastro aparece e que a similaridade só é exibida
    quando FOI medida (a busca por dispositivo não tem distância, e a interface
    escrevia "100,00%").
    """

    def _resultado(self, **kw):
        base = {
            'answer': "A direção do SUS cabe ao Ministério da Saúde [1].",
            'sources': [{'ref': 1, 'source_label': 'Lei 8080', 'file_name': 'lei.pdf',
                         'distance': 0.25, 'origem': 'semantico', 'citada': True}],
            'fact_check': {'enabled': True, 'total_sentences': 1, 'supported': 1,
                           'partial': 0, 'no_support': 0, 'all_grounded': True},
            'status': 'ok', 'motivo': '', 'descartada': None,
        }
        base.update(kw)
        return base

    def test_resposta_ok_exibe_texto_e_confirma_o_lastro(self):
        blocos = ui_feedback.montar_resposta(self._resultado())
        self.assertEqual(blocos[0]['tipo'], 'markdown')
        self.assertEqual(blocos[0]['texto'], self._resultado()['answer'])
        self.assertEqual(blocos[1]['tipo'], 'caption')
        self.assertIn("Lastro verificado", blocos[1]['texto'])
        self.assertEqual(blocos[-1]['tipo'], 'expander')

    def test_recusa_nao_e_apresentada_como_resposta(self):
        recusa = ("**Não encontrei a resposta na base de documentos.**\n\n"
                  "15 trecho(s) recuperado(s).")
        blocos = ui_feedback.montar_resposta(
            self._resultado(status='recusada', answer=recusa, motivo='contexto_insuficiente')
        )
        self.assertEqual(blocos[0]['tipo'], 'warning')
        self.assertNotIn('markdown', [b['tipo'] for b in blocos],
                         "recusa não pode sair com a forma de resposta")
        self.assertIn('nenhuma sustenta', blocos[-1]['titulo'])

    def test_ressalva_de_lastro_aparece_com_o_motivo(self):
        fact = {'enabled': True, 'total_sentences': 3, 'supported': 2, 'partial': 1,
                'no_support': 0, 'all_grounded': False}
        blocos = ui_feedback.montar_resposta(
            self._resultado(status='parcial', motivo='lastro_fora_do_citado', fact_check=fact)
        )
        self.assertEqual(blocos[1]['tipo'], 'warning')
        self.assertIn("ressalva", blocos[1]['texto'])
        self.assertIn("lastro_fora_do_citado", blocos[1]['texto'])

    def test_falha_sai_como_erro(self):
        blocos = ui_feedback.montar_resposta(
            self._resultado(status='erro', answer='Erro interno ao processar a consulta.')
        )
        self.assertEqual(blocos[0], {'tipo': 'error', 'texto': 'Erro interno ao processar a consulta.'})

    def test_similaridade_so_quando_foi_medida(self):
        fontes = [
            {'ref': 1, 'source_label': 'Lei 8080', 'file_name': 'lei.pdf',
             'distance': 0.25, 'origem': 'semantico', 'citada': True},
            {'ref': 2, 'source_label': 'Lei 8080, art. 9', 'file_name': 'lei.pdf',
             'distance': None, 'origem': 'dispositivo', 'citada': False},
        ]
        linhas = ui_feedback._linhas_de_fontes(fontes)
        self.assertIn("similaridade 75%", linhas[0])
        self.assertNotIn("100%", linhas[1], "resultado por dispositivo não tem similaridade")
        self.assertIn("busca por dispositivo", linhas[1])

    def test_fonte_diz_se_a_resposta_a_citou(self):
        fontes = [
            {'ref': 1, 'source_label': 'A', 'distance': 0.2, 'origem': 'semantico', 'citada': True},
            {'ref': 2, 'source_label': 'B', 'distance': 0.3, 'origem': 'semantico', 'citada': False},
        ]
        linhas = ui_feedback._linhas_de_fontes(fontes)
        self.assertIn("citada na resposta", linhas[0])
        self.assertIn("não citada", linhas[1])

    def test_render_desenha_os_blocos(self):
        _fake_st.reset_mock()
        ui_feedback.render_resposta(self._resultado())
        self.assertEqual(_fake_st.markdown.call_count, 1)
        self.assertEqual(_fake_st.caption.call_count, 1)
        self.assertEqual(_fake_st.write.call_count, 1, "uma linha por fonte")
        _fake_st.expander.assert_called_once()

    def test_render_de_recusa_usa_warning(self):
        _fake_st.reset_mock()
        ui_feedback.render_resposta(self._resultado(status='recusada', answer='**Não encontrei**'))
        self.assertEqual(_fake_st.warning.call_count, 1)
        self.assertEqual(_fake_st.markdown.call_count, 0)


if __name__ == "__main__":
    unittest.main()
