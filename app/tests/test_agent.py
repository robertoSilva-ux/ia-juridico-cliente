"""Testes unitários do agent.py — foco no build_context (citações numeradas [n]).

Como o agent.py importa psycopg2/Ollama/config no nível do módulo, eles são
mockados ANTES do import para isolar a função pura build_context.
"""
import os
import sys
import unittest
import unittest.mock
from unittest.mock import MagicMock

# Backup original modules before mocking to prevent test pollution
_mocked_modules = ['psycopg2', 'psycopg2.extras', 'langchain_ollama', 'langchain_core', 'langchain_core.prompts', 'config', 'database']
_original_modules = {m: sys.modules.get(m) for m in _mocked_modules}

sys.modules['psycopg2'] = MagicMock()
sys.modules['psycopg2.extras'] = MagicMock()
sys.modules['psycopg2.extras'].RealDictCursor = MagicMock()
sys.modules['langchain_ollama'] = MagicMock()
sys.modules['langchain_core'] = MagicMock()
sys.modules['langchain_core.prompts'] = MagicMock()

module_config = MagicMock()
module_config.DATABASE_URL = "postgresql://user:pass@db:5432/legal_db"
module_config.OLLAMA_BASE_URL = "http://ollama:11434"
module_config.EMBEDDING_MODEL = "nomic-embed-text"
module_config.LLM_MODEL = "llama3"
module_config.TEMPERATURE = 0.1
module_config.SIMILARITY_THRESHOLD = 0.60
module_config.TOP_K = 5
module_config.MAX_CONTEXT_CHARS = 12000
module_config.DB_POOL_MIN = 1
module_config.DB_POOL_MAX = 10
module_config.DB_CONNECT_TIMEOUT = 5
module_config.RERANK_ENABLED = True
module_config.RERANK_TOP_K_MULTIPLIER = 3
module_config.RERANK_LAMBDA_MULT = 0.7
module_config.FACT_CHECK_ENABLED = True
module_config.FACT_CHECK_LLM_ENABLED = False
module_config.HYDE_ENABLED = True
module_config.HYDE_TOP_K = 8
module_config.HYDE_QUERY_WEIGHT = 1.4
sys.modules['config'] = module_config

db_module = MagicMock()
db_module.get_db_connection = MagicMock()
sys.modules['database'] = db_module

# Adiciona o caminho para poder importar o agent
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Importa as funções do agent sob a proteção dos mocks
from agent import (
    build_context, _source_label, _cosine_sim, _to_vector, _mmr_rerank,
    _split_sentences, _extract_citations, _classify_sentence_grounded,
    _fact_check_answer, _fuse_rrf, _generate_hypothetical_doc,
    _semantic_hyde, _check_semantic_grounding,
    _infer_regime_profile, _apply_regime_boost, _merge_unique_docs
)

# Restaura sys.modules imediatamente após o import
for m, val in _original_modules.items():
    if val is None:
        sys.modules.pop(m, None)
    else:
        sys.modules[m] = val


def _doc(**kw):
    """Cria um dict de documento com os campos que o build_context lê."""
    base = {
        "id": 1,
        "file_name": "decreto-3048.pdf",
        "content": "Art. 54. O adicional de insalubridade...",
        "scope": "global",
        "artigo": "54",
        "tipo_doc": "decreto",
        "numero_doc": "3048",
    }
    base.update(kw)
    return base


class TestRegimeBoost(unittest.TestCase):
    def test_lc142_detecta_documento_alvo(self):
        profile = _infer_regime_profile("O que precisa para se aposentar com as regras da LC 142?")
        self.assertIn(("lei_complementar", "142"), profile["preferred"])

    def test_rgps_detecta_previdencia_geral(self):
        profile = _infer_regime_profile("Até qual idade do dependente é pago o salário família?")
        self.assertIn(("decreto", "3048"), profile["preferred"])
        self.assertIn(("lei", "8213"), profile["preferred"])

    def test_boost_prioriza_regime_sem_perder_documento(self):
        docs = [
            _doc(id=1, tipo_doc=None, numero_doc=None, file_name="Vade_mecum.pdf", distance=0.10),
            _doc(id=2, tipo_doc="decreto", numero_doc="3048", file_name="Decreto 3.048-99.pdf", distance=0.20),
        ]
        boosted = _apply_regime_boost("Até qual idade do dependente é pago o salário família?", docs)
        self.assertEqual([doc["id"] for doc in boosted], [2, 1])
        self.assertEqual(len(boosted), 2)

    def test_salario_familia_prioriza_decreto_regulamentador(self):
        docs = [
            _doc(id=1, tipo_doc="lei", numero_doc="8213", file_name="L8213consol.pdf", distance=0.10),
            _doc(id=2, tipo_doc="decreto", numero_doc="3048", file_name="Decreto 3.048-99.pdf", distance=0.20),
        ]
        boosted = _apply_regime_boost("Até qual idade do dependente é pago o salário família?", docs)
        self.assertEqual([doc["id"] for doc in boosted], [2, 1])

    def test_boost_reconhece_lcp_por_nome_mesmo_sem_metadados(self):
        docs = [
            _doc(id=1, tipo_doc=None, numero_doc=None, file_name="Vade_mecum.pdf", distance=0.05),
            _doc(id=2, tipo_doc=None, numero_doc=None, file_name="Lcp 142.pdf", distance=0.20),
        ]
        boosted = _apply_regime_boost("O que precisa para se aposentar com as regras da LC 142?", docs)
        self.assertEqual([doc["id"] for doc in boosted], [2, 1])

    def test_merge_regime_insere_documento_alvo_sem_duplicar(self):
        semantic = [_doc(id=1), _doc(id=2)]
        regime = [_doc(id=2), _doc(id=3)]
        merged = _merge_unique_docs(semantic, regime)
        self.assertEqual([doc["id"] for doc in merged], [1, 2, 3])

    def test_mmr_preserva_boost_de_regime(self):
        docs = [
            _doc(id=1, file_name="Vade_mecum.pdf", distance=0.05, embedding=[1.0, 0.0], regime_score=-0.10),
            _doc(id=2, file_name="Decreto 3.048-99.pdf", distance=0.20, embedding=[0.99, 0.01], regime_score=0.25),
        ]
        from agent import _mmr_rerank
        ranked = _mmr_rerank([1.0, 0.0], docs, limit=1)
        self.assertEqual(ranked[0]["id"], 2)


class TestBuildContext(unittest.TestCase):

    def test_rotulos_numerados(self):
        """Cada documento deve ser rotulado [DOC 1], [DOC 2]... no contexto."""
        from agent import build_context
        docs = [
            _doc(id=1, file_name="lei-8213.pdf", tipo_doc="lei", numero_doc="8213", artigo="59"),
            _doc(id=2, file_name="decreto-3048.pdf", tipo_doc="decreto", numero_doc="3048", artigo="54"),
        ]
        ctx = build_context(docs)
        self.assertIn("[DOC 1]", ctx)
        self.assertIn("[DOC 2]", ctx)
        # O rótulo deve aparecer ANTES do conteúdo
        self.assertLess(ctx.index("[DOC 1]"), ctx.index("Art. 54."))

    def test_referencia_bibliografica_no_rotulo(self):
        """O rótulo [DOC n] deve incluir a referência (tipo + número + artigo)."""
        from agent import build_context
        docs = [_doc(tipo_doc="decreto", numero_doc="3048", artigo="54")]
        ctx = build_context(docs)
        # Deve conter algo como "Decreto 3048, art. 54" (com capitalização aplicada)
        self.assertIn("Decreto 3048", ctx)
        self.assertIn("art. 54", ctx)
        # O nome do arquivo também deve estar presente
        self.assertIn("decreto-3048.pdf", ctx)

    def test_sem_metadados_usando_arquivo(self):
        """Sem tipo/número/artigo, usa o file_name como referência."""
        from agent import build_context
        docs = [_doc(artigo=None, tipo_doc=None, numero_doc=None, file_name="manual.pdf")]
        ctx = build_context(docs)
        self.assertIn("manual.pdf", ctx)
        # Não deve colocar "None" na referência
        self.assertNotIn("None", ctx.split("[DOC 1]")[1][:60])

    def test_rotulo_legivel_medida_provisoria(self):
        """tipo_doc 'medida_provisoria' deve virar 'Medida Provisória' e não 'Medida_provisoria'."""
        from agent import build_context
        docs = [_doc(tipo_doc="medida_provisoria", numero_doc="123", artigo="7")]
        ctx = build_context(docs)
        self.assertIn("Medida Provisória 123", ctx)
        self.assertNotIn("Medida_provisoria", ctx)

    def test_rotulo_legivel_constituicao(self):
        """tipo_doc 'constituicao' deve virar 'Constituição'."""
        from agent import build_context
        docs = [_doc(tipo_doc="constituicao", numero_doc="1988", artigo="5")]
        ctx = build_context(docs)
        self.assertIn("Constituição 1988", ctx)
        self.assertNotIn("Constituicao", ctx)

    def test_source_label_no_get_response(self):
        """_source_label produz rótulo único usado tanto no contexto quanto na UI."""
        from agent import _source_label
        self.assertEqual(
            _source_label(_doc(tipo_doc="decreto", numero_doc="3048", artigo="54")),
            "Decreto 3048, art. 54",
        )
        self.assertEqual(
            _source_label(_doc(tipo_doc="lei", numero_doc="8213", artigo=None)),
            "Lei 8213",
        )
        self.assertEqual(
            _source_label(_doc(artigo=None, tipo_doc=None, numero_doc=None, file_name="manual.pdf")),
            "manual.pdf",
        )

    def test_vazio(self):
        """Com lista vazia retorna mensagem padrão."""
        from agent import build_context
        self.assertEqual(build_context([]), "Nenhum documento relevante encontrado.")

    def test_limite_max_chars(self):
        """Respeita MAX_CONTEXT_CHARS (12000)."""
        from agent import build_context
        docs = [_doc(content="X" * 8000) for _ in range(3)]
        ctx = build_context(docs)
        self.assertLessEqual(len(ctx), 12000)


class TestMMRRerank(unittest.TestCase):
    """Testes do re-ranking por MMR (Task: retirada de redundância da doutrina).

    _cosine_sim / _to_vector / _mmr_rerank são funções puras (só numpy) e
    podem ser testadas diretamente, sem mock de langchain.
    """

    def _mk_doc(self, doc_id, vec):
        return {
            "id": doc_id,
            "file_name": f"doc-{doc_id}.pdf",
            "content": "texto",
            "scope": "global",
            "artigo": None,
            "tipo_doc": None,
            "numero_doc": None,
            "distance": 0.3,
            "embedding": list(vec),
        }

    def test_cosine_sim_idênticos(self):
        """Vetores iguais -> similaridade 1.0."""
        from agent import _cosine_sim
        v = [1.0, 0.0, 0.0]
        self.assertAlmostEqual(_cosine_sim(v, v), 1.0, places=5)

    def test_cosine_sim_ortogonais(self):
        """Vetores ortogonais -> similaridade 0.0."""
        from agent import _cosine_sim
        self.assertAlmostEqual(_cosine_sim([1.0, 0.0, 0.0], [0.0, 1.0, 0.0]), 0.0, places=5)

    def test_to_vector_string_pgvector(self):
        """Converte string estilo pgvector '[1,2,3]' em lista de floats."""
        from agent import _to_vector
        arr = _to_vector('[1,2,3]')
        self.assertIsInstance(arr, list)
        self.assertEqual(arr, [1.0, 2.0, 3.0])

    def test_mmr_reduz_redundancia(self):
        """Com lambda baixo, MMR prioriza diversidade e seleciona docs diferentes
        em vez de duplicar contexto redundante (notas de rodapé da doutrina).
        """
        from agent import _mmr_rerank
        # query aponta pra direção X
        q = [1.0, 0.0, 0.0]
        # doc1 e doc2 são muito parecidos (ambos próximos de X); doc3 é diferente
        docs = [
            self._mk_doc(1, [1.0, 0.0, 0.0]),
            self._mk_doc(2, [0.95, 0.05, 0.0]),
            self._mk_doc(3, [0.0, 1.0, 0.0]),
        ]
        # lambda baixo (0.1) força diversidade: penaliza fortemente redundância
        sel = _mmr_rerank(q, docs, limit=2, lambda_mult=0.1)
        ids = [d["id"] for d in sel]
        # O doc3 (diferente) deve entrar junto com o mais relevante (doc1)
        self.assertIn(3, ids)
        self.assertIn(1, ids)
        self.assertLessEqual(len(sel), 2)

    def test_mmr_respeita_limit(self):
        """Retorna no máximo `limit` docs."""
        from agent import _mmr_rerank
        docs = [self._mk_doc(i, [1.0, 0.0, 0.0]) for i in range(5)]
        sel = _mmr_rerank([1.0, 0.0, 0.0], docs, limit=3)
        self.assertEqual(len(sel), 3)

    def test_mmr_cada_doc_uma_vez(self):
        """Nenhum doc se repete no resultado."""
        from agent import _mmr_rerank
        docs = [self._mk_doc(i, [float(i), 0.0, 0.0]) for i in range(4)]
        sel = _mmr_rerank([1.0, 0.0, 0.0], docs, limit=4)
        ids = [d["id"] for d in sel]
        self.assertEqual(len(ids), len(set(ids)))

    def test_mmr_adiciona_mmr_score(self):
        """Cada doc selecionado ganha a chave mmr_score."""
        from agent import _mmr_rerank
        docs = [self._mk_doc(1, [1.0, 0.0, 0.0]), self._mk_doc(2, [0.0, 1.0, 0.0])]
        sel = _mmr_rerank([1.0, 0.0, 0.0], docs, limit=1)
        self.assertIn("mmr_score", sel[0])


class TestFactCheck(unittest.TestCase):
    """Testes do fact-check / groundedness pós-geração (Task 3).

    O núcleo determinístico (_split_sentences, _extract_citations,
    _classify_sentence_grounded, _fact_check_answer) é formado por funções
    puras — testadas diretamente, sem chamada LLM.
    """

    def test_split_sentences_basico(self):
        """Divide resposta em sentenças por . ! ?"""
        from agent import _split_sentences
        sents = _split_sentences("Primeira frase. Segunda frase! Terceira?")
        self.assertEqual(sents, ["Primeira frase.", "Segunda frase!", "Terceira?"])

    def test_split_sentences_preserva_abreviacao(self):
        """Não quebra em 'art. 54' (abreviação jurídica)."""
        from agent import _split_sentences
        sents = _split_sentences("Segundo o art. 54 do decreto. Isso é válido.")
        # 'art. 54 do decreto.' pertence à mesma sentença
        self.assertEqual(len(sents), 2)
        self.assertIn("art. 54 do decreto.", sents[0])

    def test_extract_citations(self):
        """Extrai os números de citação [n] de uma sentença."""
        from agent import _extract_citations
        self.assertEqual(_extract_citations("Deve 40% [1] e 20% [2]."), [1, 2])
        self.assertEqual(_extract_citations("Sem citação aqui."), [])

    def test_classify_supported(self):
        """Sentença com [n] válido -> supported."""
        from agent import _classify_sentence_grounded
        self.assertEqual(_classify_sentence_grounded("O adicional é 40% [1].", {1}), "supported")

    def test_classify_no_support_citacao_fabricada(self):
        """Sentença citando [n] inexistente (fabricado) -> no_support."""
        from agent import _classify_sentence_grounded
        # valid_refs = {1,2}; cita [9] que não existe
        self.assertEqual(_classify_sentence_grounded("Valor é 40% [9].", {1, 2}), "no_support")

    def test_classify_no_support_sem_citacao(self):
        """Sentença factual sem citação nenhuma -> aceita na postura suavizada."""
        from agent import _classify_sentence_grounded
        self.assertEqual(_classify_sentence_grounded("A aposentadoria especial exige 25 anos.", {1, 2}), "supported")

    def test_classify_partial(self):
        """Sentença com citação mista (válida + inválida) -> partial."""
        from agent import _classify_sentence_grounded
        self.assertEqual(_classify_sentence_grounded("É 40% [1] e 20% [9].", {1, 2}), "partial")

    def test_classify_lista_fontes(self):
        """A linha 'Fontes:' não é conta como afirmação sem suporte."""
        from agent import _classify_sentence_grounded
        self.assertEqual(_classify_sentence_grounded("Fontes:\n[1] Decreto 3048", {1}), "supported")

    def test_fact_check_answer_monta_resultado(self):
        """_fact_check_answer monta o resumo e flag de sentenças não suportadas.

        O conteúdo dos documentos traz os fatos que as frases afirmam porque a
        checagem passou a conferir o dado contra o FRAGMENTO CITADO (R-4): uma
        frase que afirma "40% [1]" num [DOC 1] sem 40% não é lastreada.
        """
        from agent import _fact_check_answer
        docs = [
            _doc(id=1, content="Art. 54. O adicional é de 40% sobre o salário de contribuição."),
            _doc(id=2, content="Art. 2. Aplica-se o disposto neste artigo aos casos indicados."),
        ]
        answer = "O adicional é 40% [1]. A aposentadoria exige 25 anos [9]. Aplica-se o art. 2 [2]."
        res = _fact_check_answer(answer, docs)
        self.assertEqual(res["total_sentences"], 3)
        self.assertEqual(res["supported"], 2)
        self.assertEqual(res["no_support"], 1)  # a que cita [9]
        self.assertFalse(res["all_grounded"])
        self.assertEqual(len(res["flagged_sentences"]), 1)
        self.assertEqual(res["flagged_sentences"][0]["status"], "no_support")
        self.assertIn(9, res["flagged_sentences"][0]["invalid_citations"])

    def test_regex_captura_afirmacao_completa(self):
        """Regressão (loop q6): findall deve capturar '18 anos' (número+unidade),
        não apenas 'anos' — o bug deixava alucinação numérica passar."""
        from agent import _FACTUAL_NUM_PATTERN
        hits = _FACTUAL_NUM_PATTERN.findall("o salário família é pago até a idade de 18 anos")
        self.assertEqual(hits, ["18 anos"])

    def test_citacao_aceita_as_duas_grafias(self):
        """`[3]` e `[DOC 3]` são a mesma citação — o prompt manda usar `[DOC n]`."""
        from agent import _extract_citations
        self.assertEqual(_extract_citations("o prazo é de 180 dias [3]."), [3])
        self.assertEqual(_extract_citations("o prazo é de 180 dias [DOC 3]."), [3])
        self.assertEqual(_extract_citations("[doc 12] e [2] sustentam."), [12, 2])
        self.assertEqual(_extract_citations("sem citação [DOC] aqui."), [])

    def test_factual_grounded_extenso_vs_digitos(self):
        """Lei diz 'quatorze', modelo responde '14' — canonicalização considera lastreado."""
        from agent import _factual_claim_grounded
        ctx = ("Art. 83. O valor da cota do salário-família por filho ou equiparado "
               "de qualquer condição, até quatorze anos de idade ou inválido, é de R$ 8,65.")
        self.assertTrue(_factual_claim_grounded("O salário-família é pago até 14 anos de idade.", ctx))

    def test_factual_grounded_alucinacao_reprovada(self):
        """Modelo responde '18 anos' sem lastro — deve reprovar (não lastreado)."""
        from agent import _factual_claim_grounded
        ctx = ("Art. 83. O valor da cota do salário-família por filho ou equiparado "
               "de qualquer condição, até quatorze anos de idade ou inválido, é de R$ 8,65.")
        self.assertFalse(_factual_claim_grounded("o salário família é pago até a idade de 18 anos", ctx))

    def test_factual_grounded_composto_extenso(self):
        """Lei traz 'cinqüenta e cinco anos' (composto + trema) vs resposta '55 anos'."""
        from agent import _factual_claim_grounded
        ctx = "aposentadoria especial aos cinquenta e cinco anos de idade, se do sexo feminino"
        self.assertTrue(_factual_claim_grounded("A aposentadoria especial exige 55 anos de contribuição.", ctx))


class TestFactCheckNormas(unittest.TestCase):
    """Citação de norma (lei/decreto/EC) na resposta x o que a base sustenta.

    Regressão medida em 2026-10-16, com a base real: o modelo respondeu
    *"A Lei nº 8080/2011 regula o Sistema Único de Saúde"*. O **8080** vinha do
    NOME DO ARQUIVO (`LEI-8080-ESQUEMATIZADA1.pdf`, que aparece no cabeçalho de
    cada [DOC] do contexto) e o **2011**, de um trecho de OUTRA lei —
    *"(Incluído pela Lei nº 12.401, de 2011)"*. Cada pedaço existia em algum lugar
    do contexto, então os checks por token aprovavam: `all_grounded: True` numa
    resposta errada (a Lei 8.080 é de 19/09/1990).

    A severidade é graduada: número inexistente é invenção (no_support); número
    que existe mas com OUTRO ano no material é composição de normas (no_support);
    número certo com ano que o material não registra é não verificável (partial).
    """

    def _arquivo_sem_metadado(self, conteudo_extra=""):
        """Reproduz o registro real: `numero_doc` NULL no banco e o número só no
        nome do arquivo; o conteúdo traz a lei 12.401/2011 (a fonte do ano)."""
        return [
            _doc(id=1, file_name="LEI-8080-ESQUEMATIZADA1.pdf", numero_doc=None,
                 content=("Art. 19-Q. (Incluído pela Lei nº 12.401, de 2011) "
                          "A incorporação de tecnologia em saúde no SUS." + conteudo_extra)),
        ]

    def test_ano_roubado_de_outra_lei_e_sinalizado(self):
        """O caso relatado: número do arquivo + ano de outra lei."""
        from agent import _fact_check_answer
        res = _fact_check_answer(
            "A Lei nº 8080/2011 regula o Sistema Único de Saúde (SUS).",
            self._arquivo_sem_metadado(),
        )
        self.assertFalse(res["all_grounded"])
        # O material não registra o ano da Lei 8.080, então o ano é
        # *inverificável* (partial), não uma contradição provada.
        self.assertEqual(res["partial"], 1)
        self.assertEqual(res["flagged_sentences"][0]["reason"], "ano_nao_consta")

    def test_ano_conflitante_com_a_base_e_invencao(self):
        """Se a base diz 1990 e a resposta diz 2011, o par é incompatível."""
        from agent import _fact_check_answer
        docs = [_doc(id=1, file_name="lei-8080.pdf", numero_doc=None,
                     content="LEI Nº 8.080, DE 19 DE SETEMBRO DE 1990. Dispõe sobre o SUS.")]
        res = _fact_check_answer("A Lei nº 8.080/2011 dispõe sobre o SUS.", docs)
        self.assertFalse(res["all_grounded"])
        self.assertEqual(res["no_support"], 1)
        self.assertEqual(res["flagged_sentences"][0]["reason"], "ano_incompativel")

    def test_numero_inventado_e_invencao(self):
        """Número que não existe em lugar nenhum do material."""
        from agent import _fact_check_answer
        res = _fact_check_answer(
            "A Lei nº 8.830, de 1993, organiza o SUS.",
            self._arquivo_sem_metadado(),
        )
        self.assertFalse(res["all_grounded"])
        self.assertEqual(res["flagged_sentences"][0]["reason"], "norma_sem_lastro")

    def test_citacao_correta_nao_e_reprovada(self):
        """Guarda contra falso positivo: a resposta certa continua limpa."""
        from agent import _fact_check_answer
        docs = [_doc(id=1, file_name="lei-8080.pdf", numero_doc="8080", ano_doc="1990",
                     content=("LEI Nº 8.080, DE 19 DE SETEMBRO DE 1990. Dispõe sobre as "
                              "condições para a promoção, proteção e recuperação da saúde."))]
        res = _fact_check_answer(
            "A Lei nº 8.080/1990 dispõe sobre a promoção, proteção e recuperação da saúde [1].", docs)
        self.assertTrue(res["all_grounded"], res["flagged_sentences"])

    def test_identidade_do_metadado_sustenta_a_citacao(self):
        """O rótulo que o pipeline fornece ('Arquivo X é a Lei 8.213/1991') pode
        ser citado mesmo quando o conteúdo recuperado não repete o ano."""
        from agent import _fact_check_answer
        docs = [_doc(id=1, file_name="Lei 8.213-91.pdf", numero_doc=None,
                     content="Art. 25. A carência exigida é de 180 contribuições mensais.")]
        res = _fact_check_answer(
            "A carência é de 180 contribuições mensais (Lei nº 8.213/1991) [1].", docs)
        self.assertTrue(res["all_grounded"], res["flagged_sentences"])

    def test_norma_citada_conta_como_afirmacao_factual(self):
        """Sem isso, sentença que só cita lei (sem [n] e sem prazo) escapava do check."""
        from agent import _has_factual_claim
        self.assertTrue(_has_factual_claim("A Lei nº 8.080/1990 é a Lei Orgânica da Saúde."))
        self.assertFalse(_has_factual_claim("O sistema de saúde é importante para o país."))


class TestHyDE(unittest.TestCase):
    """Testes do HyDE (Hypothetical Document Embeddings) + fusão RRF (Task 2).

    O núcleo determinístico (_fuse_rrf) é uma função pura — testado direto.
    _generate_hypothetical_doc é testado com o LLM mockado (None p/ HyDE off,
    objeto com .content p/ HyDE on).
    """

    def _doc(self, did):
        return {"id": did, "file_name": f"f{did}", "content": f"conteúdo {did}", "distance": 0.1}

    def test_fuse_rrf_transicao_entre_rankings(self):
        """Docs presentes em ambos os rankings sobem na fusão RRF."""
        from agent import _fuse_rrf
        # ranking 1: A,B,C | ranking 2: B,D
        r1 = [self._doc("A"), self._doc("B"), self._doc("C")]
        r2 = [self._doc("B"), self._doc("D")]
        fused = _fuse_rrf([r1, r2], limit=10)
        ids = [d["id"] for d in fused]
        # B está em ambas; score RRF(B) = 1/61 + 1/61 > score de A (1/61)
        self.assertEqual(ids[0], "B")
        self.assertIn("A", ids)
        self.assertIn("C", ids)
        self.assertIn("D", ids)
        # não duplica
        self.assertEqual(len(ids), len(set(ids)))

    def test_fuse_rrf_respeita_limit(self):
        """Retorna no máximo `limit` docs."""
        from agent import _fuse_rrf
        r1 = [self._doc(i) for i in range(6)]
        r2 = [self._doc(10 + i) for i in range(6)]
        fused = _fuse_rrf([r1, r2], limit=4)
        self.assertEqual(len(fused), 4)

    def test_fuse_rrf_desempate_eh_ordem_do_primeiro_ranking(self):
        """Sem interseção, a ordem segue o ranking com maior score por posição."""
        from agent import _fuse_rrf
        r1 = [self._doc("X"), self._doc("Y")]
        r2 = [self._doc("W"), self._doc("Z")]
        fused = _fuse_rrf([r1, r2], limit=4)
        ids = [d["id"] for d in fused]
        # X e W (pos 1) empatam em RRF; stable -> X primeiro (veio antes)
        self.assertEqual(ids[0], "X")
        self.assertEqual(ids[1], "W")

    def test_fuse_rrf_peso_faz_ranking_dominar(self):
        """Peso maior num ranking faz o doc dele subir mesmo estando em posição menor."""
        from agent import _fuse_rrf
        # r1 domina (peso alto): doc do r1 na pos 2 vence doc do r2 na pos 1
        r1 = [self._doc("A"), self._doc("B")]
        r2 = [self._doc("C")]  # C é o único do r2
        # peso r1 bem alto: score(B) = w/62 > score(C) = 1/61
        fused = _fuse_rrf([r1, r2], limit=3, weights=[2.0, 1.0])
        ids = [d["id"] for d in fused]
        # A (pos1, peso 2) vem primeiro
        self.assertEqual(ids[0], "A")
        # C (peso 1) ainda aparece porque está sozinho no r2 e é relevante
        self.assertIn("C", ids)

    def test_fuse_rrf_peso_preserva_doc_da_query_no_top(self):
        """Com peso da query > 1, docs da query sobem em relação aos do HyDE."""
        from agent import _fuse_rrf
        # query: [A,B] (peso 1.4) | hyde: [C,D] (peso 1.0)
        rq = [self._doc("A"), self._doc("B")]
        rh = [self._doc("C"), self._doc("D")]
        fused = _fuse_rrf([rq, rh], limit=4, weights=[1.4, 1.0])
        ids = [d["id"] for d in fused]
        # A(2ª) e C(1ª) -> score A=1.4/61=0.0229, C=1.0/61=0.0164 -> A vem antes
        self.assertEqual(ids[0], "A")

    def test_generate_hyde_sem_llm_retorna_none(self):
        """Sem LLM disponível, HyDE degrada para None (fallback gracioso)."""
        from agent import _generate_hypothetical_doc
        # Simula LLM indisponível (None global) — a função lê o global
        with unittest.mock.patch("agent.LLM", None):
            self.assertIsNone(_generate_hypothetical_doc("aposentadoria"))

    def _fake_llm(self, content):
        """LLM fake: invoke(prompt) retorna um objeto com .content."""
        fake = unittest.mock.MagicMock()
        resp = unittest.mock.MagicMock()
        resp.content = content
        fake.invoke.return_value = resp
        return fake

    def test_generate_hyde_com_llm_retorna_texto(self):
        """Com LLM disponível, gera o documento hipotético (texto)."""
        from agent import _generate_hypothetical_doc
        fake = self._fake_llm("A aposentadoria por tempo de contribuição exige observar a carência e o período de contribuição previstos na legislação previdenciária.")
        with unittest.mock.patch("agent.LLM", fake), \
             unittest.mock.patch("agent.HYDE_ENABLED", True):
            out = _generate_hypothetical_doc("quanto tempo para aposentar")
            self.assertIsNotNone(out)
            self.assertIsInstance(out, str)
            self.assertIn("carência", out)

    def test_generate_hyde_ignora_resposta_curta(self):
        """Resposta LLM muito curta (<20 chars) não vira âncora HyDE."""
        from agent import _generate_hypothetical_doc
        fake = self._fake_llm("ok.")
        with unittest.mock.patch("agent.LLM", fake), \
             unittest.mock.patch("agent.HYDE_ENABLED", True):
            self.assertIsNone(_generate_hypothetical_doc("teste"))

    def test_generate_hyde_falha_do_llm_retorna_none(self):
        """exceção do LLM -> None (sem quebrar o retrieval)."""
        from agent import _generate_hypothetical_doc
        fake = unittest.mock.MagicMock()
        fake.invoke.side_effect = RuntimeError("llm down")
        with unittest.mock.patch("agent.LLM", fake), \
             unittest.mock.patch("agent.HYDE_ENABLED", True):
            self.assertIsNone(_generate_hypothetical_doc("teste"))

    def test_semantic_hyde_sem_llm_cai_para_none(self):
        """Se o doc hipotético não for gerado, _semantic_hyde retorna None
        (o chamador cai na busca comum)."""
        from agent import _semantic_hyde
        with unittest.mock.patch("agent._generate_hypothetical_doc", return_value=None):
            self.assertIsNone(_semantic_hyde("query", [1.0, 0.0], None, limit=5))


class TestPromptContract(unittest.TestCase):
    """Garante que o agente não invente uma data de corte do treinamento."""

    def test_prompt_proibe_ressalva_temporal_do_modelo(self):
        prompt_path = os.path.join(os.path.dirname(__file__), "..", "prompts", "system-role.md")
        with open(prompt_path, encoding="utf-8") as handle:
            prompt = handle.read().lower()
        self.assertIn("não mencione data de corte", prompt)
        self.assertIn("março de 2023", prompt)
        self.assertIn("vigência não está indicada nos documentos recuperados", prompt)

    def test_prompt_tem_contrato_de_saida_e_recusa(self):
        """R-7: o prompt precisa exigir a citação do trecho e a forma da recusa.

        Sem isso o verificador descarta a resposta por falta de citação — e o
        produto passaria a recusar perguntas que a base responde.
        """
        prompt_path = os.path.join(os.path.dirname(__file__), "..", "prompts", "system-role.md")
        with open(prompt_path, encoding="utf-8") as handle:
            prompt = handle.read()
        self.assertIn("CONTRATO DE SAÍDA", prompt)
        self.assertIn("[DOC 1]", prompt)
        self.assertIn("NÃO ENCONTRADO NA BASE", prompt)
        self.assertNotIn("ARBITRAGEM DE REGIME JURÍDICO (obrigatória", prompt)


class TestLastroNoFragmentoCitado(unittest.TestCase):
    """R-4: o dado afirmado tem de estar no trecho que a frase CITA.

    Citar [1] e afirmar o dado que está no [3] não fundamenta nada: o advogado
    clica em [1] e não encontra o número.
    """

    def _res(self, answer, docs):
        from agent import _fact_check_answer
        return _fact_check_answer(answer, docs)

    def test_dado_em_outro_fragmento_reprova(self):
        docs = [
            _doc(id=1, content="Art. 1º Esta lei dispõe sobre o registro de dados de saúde."),
            _doc(id=2, content="Art. 54. A aposentadoria é devida ao segurado com 35 anos de contribuição."),
        ]
        res = self._res("A aposentadoria exige 35 anos de contribuição [1].", docs)
        self.assertEqual(res["partial"], 1)
        self.assertEqual(res["flagged_sentences"][0]["reason"], "lastro_fora_do_citado")
        self.assertEqual(res["veredito"], "parcial")

    def test_dado_no_fragmento_citado_passa(self):
        docs = [
            _doc(id=1, content="Art. 1º Esta lei dispõe sobre o registro de dados de saúde."),
            _doc(id=2, content="Art. 54. A aposentadoria é devida ao segurado com 35 anos de contribuição."),
        ]
        res = self._res("A aposentadoria exige 35 anos de contribuição [2].", docs)
        self.assertEqual(res["partial"], 0)
        self.assertEqual(res["veredito"], "fundamentada")

    def test_citar_varios_trechos_aceita_o_que_tem_o_dado(self):
        """O dado pode vir de qualquer um dos trechos citados."""
        docs = [
            _doc(id=1, content="Art. 1º Esta lei dispõe sobre o registro de dados de saúde."),
            _doc(id=2, content="Art. 54. A aposentadoria é devida ao segurado com 35 anos de contribuição."),
        ]
        res = self._res("A aposentadoria consta do art. 54 [1][2].", docs)
        self.assertEqual([f["reason"] for f in res["flagged_sentences"]
                          if f["reason"] == "lastro_fora_do_citado"], [])

    def test_grafia_do_dispositivo_nao_gera_falso_positivo(self):
        """'artigo 9' e 'Art. 9º' são o mesmo dispositivo."""
        docs = [_doc(id=1, content="Art. 9º A direção do Sistema Único de Saúde é exercida pelo Ministério da Saúde.")]
        res = self._res("A direção cabe ao Ministério da Saúde, conforme o artigo 9 [1].", docs)
        self.assertEqual(res["partial"], 0)


class TestVereditoDaResposta(unittest.TestCase):
    """O veredito é o que o `agent` usa para decidir o que EXIBIR."""

    def _res(self, answer, docs):
        from agent import _fact_check_answer
        return _fact_check_answer(answer, docs)

    def test_norma_inventada_da_sem_lastro(self):
        docs = [_doc(id=1, content="Art. 9º A direção do SUS é exercida pelo Ministério da Saúde.")]
        res = self._res("A Lei nº 8.080/2011 regula o SUS [1].", docs)
        self.assertEqual(res["veredito"], "sem_lastro")
        self.assertEqual(res["motivo"], "norma_sem_lastro")

    def test_resposta_sem_unidade_verificavel_vira_ressalva(self):
        """Resposta sem nada a conferir NÃO é recusa nem invenção: vira aviso.

        Medido: descartá-la trocava uma resposta CORRETA por uma recusa (d2 do
        mini-quiz — "os municípios podem constituir consórcios", sem citação).
        """
        docs = [_doc(id=1, content="O contrato se forma com o acordo de vontades entre as partes.")]
        res = self._res("O tema envolve princípios gerais de direito administrativo e a organização do sistema.", docs)
        self.assertEqual(res["veredito"], "parcial")
        self.assertEqual(res["motivo"], "sem_fonte")

    def test_recusa_do_modelo_e_reconhecida_como_recusa(self):
        docs = [_doc(id=1)]
        res = self._res("A base recuperada não contém o dispositivo que responde à pergunta.", docs)
        self.assertEqual(res["veredito"], "recusou")

    def test_recusa_com_dispositivo_citado_continua_sendo_recusa(self):
        """Caso medido: a recusa mencionava o art. 55 e era exibida como FUNDAMENTADA.

        O [DOC] carrega a identidade da lei (metadado/nome do arquivo, como na base
        real): sem ela, a norma citada na recusa seria lida como invenção — e o
        veredito `sem_lastro` (que prevalece) dispararia uma reescrita inútil.
        """
        docs = [_doc(id=1, content="Art. 55. Revogam-se as disposições em contrário.",
                     numero_doc="8080", tipo_doc="lei", file_name="LEI-8080-ESQUEMATIZADA1.pdf")]
        res = self._res("A base não contém informações sobre quais leis foram revogadas pelo art. 55 da Lei 8.080.", docs)
        self.assertEqual(res["veredito"], "recusou")

    def test_marcador_do_prompt_e_reconhecido(self):
        docs = [_doc(id=1)]
        res = self._res("NÃO ENCONTRADO NA BASE A RESPONDER A PERGUNTA DO ADVOGADO.", docs)
        self.assertEqual(res["veredito"], "recusou")

    def test_recusa_com_palavra_deformada_pelo_modelo_e_reconhecida(self):
        """Caso medido (f4): o modelo escreveu "NÃO ENCONTRAR NA BASE" — e a recusa
        deformada passava como resposta sem citação."""
        docs = [_doc(id=1, content="Art. 22. A licitação será dispensada em razão do valor.")]
        res = self._res("NÃO ENCONTRAR NA BASE A REGIME JURÍDICO (norma revogada/alterada).", docs)
        self.assertEqual(res["veredito"], "recusou")

    def test_nao_ha_no_meio_de_uma_resposta_nao_e_recusa(self):
        """'Não há dúvida de que…' no meio de resposta concreta continua sendo resposta."""
        docs = [_doc(id=1, content="Art. 54. A aposentadoria é devida com 35 anos de contribuição.")]
        res = self._res("Não há dúvida de que o prazo é de 35 anos de contribuição [1].", docs)
        self.assertIn(res["veredito"], ("fundamentada", "parcial"))

    def test_resposta_ancorada_e_fundamentada(self):
        docs = [_doc(id=1, content="Art. 54. A aposentadoria é devida ao segurado com 35 anos de contribuição.")]
        res = self._res("O homem precisa de 35 anos de contribuição [1].", docs)
        self.assertEqual(res["veredito"], "fundamentada")
        self.assertEqual(res["citadas"], [1])

    def test_resposta_vazia_nao_e_recusa(self):
        res = self._res("   ", [_doc(id=1)])
        self.assertEqual(res["veredito"], "sem_lastro")
        self.assertEqual(res["motivo"], "resposta_vazia")

    def test_citacao_fabricada_da_sem_lastro(self):
        res = self._res("O prazo é de 180 dias [9].", [_doc(id=1)])
        self.assertEqual(res["veredito"], "sem_lastro")


class TestFluxoDeResposta(unittest.TestCase):
    """R-2/R-5/R-6: o caminho completo — o que o chat exibe em cada caso.

    `retrieve_context`, `_gerar`, `_contexto_suficiente` e `ensure_llm` são
    substituídos: o alvo aqui é a DECISÃO (recusar, regenerar, exibir), não o modelo.
    """

    DOCS = [_doc(id=1, content="Art. 9º A direção do Sistema Único de Saúde é exercida pelo Ministério da Saúde.")]
    INVENTADA = "A Lei nº 8.080/2011 regula o SUS e a direção cabe ao Ministério da Saúde [1]."
    ANCORADA = "A direção do SUS no âmbito da União cabe ao Ministério da Saúde [1]."

    def _executar(self, respostas, docs=None, suficiente=None):
        import agent
        with unittest.mock.patch.object(agent, "ensure_llm", return_value=True), \
             unittest.mock.patch.object(agent, "retrieve_context", return_value=self.DOCS if docs is None else docs), \
             unittest.mock.patch.object(agent, "_contexto_suficiente", return_value=suficiente), \
             unittest.mock.patch.object(agent, "_auditar") as auditoria, \
             unittest.mock.patch.object(agent, "_gerar", side_effect=respostas) as gerar:
            resultado = agent.get_response("quem dirige o SUS?", [], user_id=9, user_email="dev@legaliz.local")
        return resultado, gerar, auditoria

    def test_contexto_insuficiente_recusa_sem_gerar(self):
        """Pergunta fora da base: recusa canônica, sem chamar o modelo que responde."""
        resultado, gerar, _ = self._executar([], suficiente=False)
        self.assertEqual(resultado["status"], "recusada")
        self.assertEqual(resultado["motivo"], "contexto_insuficiente")
        self.assertEqual(gerar.call_count, 0, "não se gera resposta quando a base não responde")
        self.assertIn("Não encontrei a resposta", resultado["answer"])

    def test_sem_recuperacao_recusa_sem_gerar(self):
        resultado, gerar, _ = self._executar([], docs=[])
        self.assertEqual(resultado["status"], "recusada")
        self.assertEqual(resultado["motivo"], "sem_recuperacao")
        self.assertEqual(gerar.call_count, 0)

    def test_norma_inventada_regenera_uma_vez_e_recusa(self):
        resultado, gerar, _ = self._executar([self.INVENTADA, self.INVENTADA], suficiente=True)
        self.assertEqual(gerar.call_count, 2, "uma regeneração, não um laço")
        self.assertEqual(resultado["status"], "recusada")
        self.assertEqual(resultado["motivo"], "norma_sem_lastro")
        self.assertEqual(resultado["descartada"], self.INVENTADA)
        self.assertNotIn("8.080/2011", resultado["answer"], "texto sem lastro não vai para a tela")

    def test_reescrita_ancorada_e_exibida(self):
        resultado, gerar, _ = self._executar([self.INVENTADA, self.ANCORADA], suficiente=True)
        self.assertEqual(gerar.call_count, 2)
        self.assertEqual(resultado["status"], "ok")
        self.assertEqual(resultado["answer"], self.ANCORADA)
        self.assertEqual(resultado["descartada"], self.INVENTADA)

    def test_recusa_do_modelo_vira_recusa_canonica(self):
        resultado, gerar, _ = self._executar(
            ["A base recuperada não contém o dispositivo que responde."] * 2, suficiente=None)
        self.assertEqual(resultado["status"], "recusada")
        self.assertEqual(resultado["motivo"], "modelo_recusou")
        self.assertIn("Não encontrei a resposta", resultado["answer"])

    def test_veredito_parcial_exibe_com_ressalva(self):
        resultado, _, _ = self._executar([self.ANCORADA + " O restante da doutrina diverge."],
                                         suficiente=True)
        self.assertIn(resultado["status"], ("ok", "parcial"))
        self.assertEqual(resultado["sources"][0]["citada"], True)

    def test_recusa_com_material_suficiente_tem_segunda_leitura(self):
        """Recusar o que a base responde é tão grave quanto inventar: uma 2ª leitura."""
        resultado, gerar, _ = self._executar(
            ["A base recuperada não contém o dispositivo que responde.", self.ANCORADA],
            suficiente=True,
        )
        self.assertEqual(gerar.call_count, 2)
        self.assertEqual(resultado["status"], "ok")
        self.assertEqual(resultado["answer"], self.ANCORADA)
        self.assertEqual(gerar.call_args.kwargs["feedback_motivo"], "modelo_recusou")

    def test_recusa_repetida_vira_recusa_canonica(self):
        resultado, gerar, _ = self._executar(
            ["A base recuperada não contém o dispositivo que responde."] * 2, suficiente=True
        )
        self.assertEqual(gerar.call_count, 2, "uma segunda chance, não um laço")
        self.assertEqual(resultado["status"], "recusada")
        self.assertEqual(resultado["motivo"], "modelo_recusou")

    def test_recusa_sem_veredito_de_suficiencia_tambem_tem_segunda_leitura(self):
        """Sem o portão (None) não se sabe se o material responde: procura de novo."""
        resultado, gerar, _ = self._executar(
            ["A base recuperada não contém o dispositivo que responde.", self.ANCORADA],
            suficiente=None,
        )
        self.assertEqual(gerar.call_count, 2)
        self.assertEqual(resultado["status"], "ok")

    def test_retry_que_vira_recusa_encerra_sem_terceira_chamada(self):
        """Regressão medida: a segunda leitura que terminava em recusa disparava uma
        3ª chamada (recusa sobre recusa) antes de a resposta ser recusada."""
        resultado, gerar, _ = self._executar(
            [self.INVENTADA, "A base não contém a resposta."], suficiente=True)
        self.assertEqual(gerar.call_count, 2, "uma segunda leitura, nunca duas")
        self.assertEqual(resultado["status"], "recusada")
        self.assertEqual(resultado["descartada"], self.INVENTADA)

    def test_citacao_no_formato_doc_nao_e_lida_como_sem_fonte(self):
        """O prompt manda citar [DOC n]: essa citação tem de contar como citação."""
        resultado, gerar, _ = self._executar(
            ["A direção do SUS cabe ao Ministério da Saúde. [DOC 1]"], suficiente=True)
        self.assertEqual(gerar.call_count, 1, "não há defeito a corrigir")
        self.assertEqual(resultado["status"], "ok")
        self.assertEqual(resultado["sources"][0]["citada"], True)

    def test_resposta_correta_sem_citacao_e_exibida_com_aviso(self):
        """Regressão medida (d2): resposta correta e sem citação era DESCARTADA, a
        reescrita desistia e o advogado recebia recusa no lugar da resposta."""
        resultado, gerar, _ = self._executar(
            ["Os municípios podem constituir consórcios entre si para ações de saúde."],
            suficiente=True)
        self.assertEqual(gerar.call_count, 1, "não se joga fora resposta correta por falta de citação")
        self.assertEqual(resultado["status"], "parcial")
        self.assertEqual(resultado["motivo"], "sem_fonte")
        self.assertIn("consórcios", resultado["answer"])

    def test_sem_modelo_configurado_devolve_erro(self):
        import agent
        with unittest.mock.patch.object(agent, "ensure_llm", return_value=False):
            resultado = agent.get_response("pergunta", [])
        self.assertEqual(resultado["status"], "erro")
        self.assertEqual(resultado["motivo"], "sem_modelo")

    def test_fontes_nao_inventam_similaridade(self):
        """Busca por dispositivo não tem distância: `distance` é None, não 0.0."""
        docs = [dict(self.DOCS[0], distance=None, origem="dispositivo")]
        resultado, _, _ = self._executar([self.ANCORADA], docs=docs, suficiente=True)
        self.assertIsNone(resultado["sources"][0]["distance"])
        self.assertEqual(resultado["sources"][0]["origem"], "dispositivo")

    def test_auditoria_registra_recusa_com_motivo(self):
        _, _, auditoria = self._executar([], suficiente=False)
        resumo = auditoria.call_args.args[3]
        self.assertIn("[RECUSA: contexto_insuficiente]", resumo)


class TestSuficienciaDoContexto(unittest.TestCase):
    """R-8: o portão de suficiência por LLM — e o silêncio dele quando falha."""

    def _llm(self, resposta):
        return unittest.mock.MagicMock(**{"invoke.return_value": unittest.mock.MagicMock(content=resposta)})

    def test_resposta_negativa_interrompe(self):
        import agent
        with unittest.mock.patch.object(agent, "FACT_CHECK_LLM_ENABLED", True):
            self.assertFalse(agent._contexto_suficiente("q", "contexto", llm=self._llm("NAO")))

    def test_resposta_afirmativa_libera(self):
        import agent
        with unittest.mock.patch.object(agent, "FACT_CHECK_LLM_ENABLED", True):
            self.assertTrue(agent._contexto_suficiente("q", "contexto", llm=self._llm("SIM — art. 9º")))

    def test_acentuado_e_markdown_nao_enganam(self):
        import agent
        with unittest.mock.patch.object(agent, "FACT_CHECK_LLM_ENABLED", True):
            self.assertFalse(agent._contexto_suficiente("q", "c", llm=self._llm("**NÃO**")))

    def test_resposta_inesperada_nao_vira_recusa(self):
        """Ambigüidade não pode derrubar pergunta legítima: segue o fluxo normal."""
        import agent
        with unittest.mock.patch.object(agent, "FACT_CHECK_LLM_ENABLED", True):
            self.assertIsNone(agent._contexto_suficiente("q", "c", llm=self._llm("talvez")))

    def test_llm_fora_do_ar_nao_vira_recusa(self):
        import agent
        llm = unittest.mock.MagicMock()
        llm.invoke.side_effect = RuntimeError("Ollama fora do ar")
        with unittest.mock.patch.object(agent, "FACT_CHECK_LLM_ENABLED", True):
            self.assertIsNone(agent._contexto_suficiente("q", "c", llm=llm))

    def test_verificacao_desligada_nao_consulta_o_modelo(self):
        import agent
        llm = unittest.mock.MagicMock()
        with unittest.mock.patch.object(agent, "FACT_CHECK_LLM_ENABLED", False):
            self.assertIsNone(agent._contexto_suficiente("q", "c", llm=llm))
        self.assertEqual(llm.invoke.call_count, 0)


class TestSemanticGrounding(unittest.TestCase):
    """Testes do groundedness semântico (lastro no contexto recuperado).

    Detecta vazamento de conhecimento pré-treinado do modelo (ex.: transcrever
    doutrina de um autor que NÃO está nos chunks) e cobertura lexical fraca —
    casos que a checagem estrutural só de [n] não pega.
    """

    def test_autor_sem_lastro_detectado(self):
        """Sentença citando autor/obra ausente do contexto -> no_support."""
        from agent import _check_semantic_grounding
        s = "Segundo MELLO, 2019b, o contrato é o negócio jurídico por excelência."
        ctx = "O contrato se forma com o acordo de vontades. Obrigações para as partes."
        status, reason = _check_semantic_grounding(s, ctx)
        self.assertEqual(status, "no_support")
        self.assertEqual(reason, "autor_sem_lastro")

    def test_autor_com_lastro_suportado(self):
        """Sentença citando autor que ESTÁ no contexto -> não é rebaixada."""
        from agent import _check_semantic_grounding
        s = "Segundo MELLO, 2019b, o contrato é o negócio jurídico."
        ctx = "MELLO, 2019b define o contrato como negócio jurídico por excelência."
        status, _ = _check_semantic_grounding(s, ctx)
        self.assertEqual(status, "supported")

    def test_cobertura_baixa_gera_weak(self):
        """Sentença com pouca sobreposição lexical ao contexto -> weak."""
        from agent import _check_semantic_grounding
        s = "a aposentadoria exige carência de 180 contribuições mensais"
        ctx = "O contrato se forma com o acordo de vontades entre as partes."
        status, reason = _check_semantic_grounding(s, ctx)
        self.assertEqual(status, "weak")
        self.assertEqual(reason, "cobertura_baixa")

    def test_fact_check_rebaixa_autor_sem_lastro(self):
        """_fact_check_answer rebaixa sentença com autor sem lastro para no_support,
        mesmo citando um [n] existente (caso 'MELLO, 2019b' de conhecimento interno)."""
        from agent import _fact_check_answer
        docs = [_doc(id=1), _doc(id=2)]
        answer = "Segundo MELLO, 2019b, o contrato é o negócio jurídico por excelência [1]."
        res = _fact_check_answer(answer, docs)
        self.assertEqual(res["no_support"], 1)
        self.assertEqual(res["flagged_sentences"][0]["reason"], "autor_sem_lastro")
        self.assertFalse(res["all_grounded"])


if __name__ == "__main__":
    unittest.main()
