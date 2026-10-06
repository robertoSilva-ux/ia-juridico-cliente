"""Testes unitários do agent.py — foco no build_context (citações numeradas [n]).

Como o agent.py importa psycopg2/Ollama/config no nível do módulo, eles são
mockados ANTES do import para isolar a função pura build_context.
"""
import os
import sys
import unittest
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
        """_fact_check_answer monta o resumo e flag de sentenças não suportadas."""
        from agent import _fact_check_answer
        docs = [_doc(id=1), _doc(id=2)]
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
