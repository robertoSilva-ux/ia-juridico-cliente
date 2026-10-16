"""Testes unitários do legal_parser.py — extração de metadados jurídicos (puros, sem deps)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from legal_parser import (
    extract_article_num, extract_paragraph, extract_inciso,
    parse_file_name, parse_chunk, enrich_chunk_metadata,
    identidade_do_documento, parse_norm_header,
)


class TestExtractArticleNum(unittest.TestCase):
    def test_art_decimal(self):
        self.assertEqual(extract_article_num("Art. 54. A aposentadoria."), 54)

    def test_art_ordinal(self):
        self.assertEqual(extract_article_num("\nArt. 7º Os direitos."), 7)

    def test_artigo_extenso(self):
        self.assertEqual(extract_article_num("Artigo 5° da constituicao"), 5)

    def test_art_maiusculo(self):
        self.assertEqual(extract_article_num("ART. 12 ta definido"), 12)

    def test_sem_artigo(self):
        self.assertIsNone(extract_article_num("apenas texto solto sem referencia"))


class TestExtractParagraph(unittest.TestCase):
    def test_paragrafo_paragrafo(self):
        self.assertEqual(extract_paragraph("§ 1º O segurado"), "1")

    def test_paragrafo_grave(self):
        self.assertEqual(extract_paragraph("§ 2° texto"), "2")

    def test_paragrafo_unico(self):
        self.assertEqual(extract_paragraph("Parágrafo único. Doe."), "único")

    def test_sem_paragrafo(self):
        self.assertIsNone(extract_paragraph("texto comum"))


class TestExtractInciso(unittest.TestCase):
    def test_inciso_romano(self):
        self.assertEqual(extract_inciso("I - Contribuir"), "I")

    def test_inciso_romano_segundo(self):
        self.assertEqual(extract_inciso("\nII – alinea"), "II")

    def test_inciso_alfabetico(self):
        self.assertEqual(extract_inciso("\na) primeira"), "a")

    def test_sem_inciso(self):
        self.assertIsNone(extract_inciso("sem inciso aqui"))


class TestParseFileName(unittest.TestCase):
    def test_decreto(self):
        meta = parse_file_name("Decreto 3.048-99.pdf")
        self.assertEqual(meta["tipo"], "decreto")
        self.assertEqual(meta["numero"], "3048")
        self.assertEqual(meta["ano"], "1999")

    def test_lei(self):
        meta = parse_file_name("Lei 8.213-91.pdf")
        self.assertEqual(meta["tipo"], "lei")
        self.assertEqual(meta["numero"], "8213")
        self.assertEqual(meta["ano"], "1991")

    def test_cf(self):
        meta = parse_file_name("CF-88.pdf")
        self.assertEqual(meta["tipo"], "constituicao")
        self.assertEqual(meta["ano"], "1988")

    def test_lei_recente(self):
        meta = parse_file_name("Lei 14.133-2021.pdf")
        self.assertEqual(meta["tipo"], "lei")
        self.assertEqual(meta["numero"], "14133")
        self.assertEqual(meta["ano"], "2021")

    def test_padrao_planalto(self):
        meta = parse_file_name("L14126.pdf")
        self.assertEqual(meta["tipo"], "lei")
        self.assertEqual(meta["numero"], "14126")

    def test_lei_complementar_142(self):
        meta = parse_file_name("Lcp 142.pdf")
        self.assertEqual(meta["tipo"], "lei_complementar")
        self.assertEqual(meta["numero"], "142")

    def test_vazio(self):
        self.assertEqual(parse_file_name(""), {"tipo": None, "numero": None, "ano": None})

    def test_lei_sem_pontos_no_fim_do_nome(self):
        """'LEI 8080.pdf' — número terminando o nome (regressão do bloco 5).

        O padrão antigo exigia espaço DEPOIS do número, então este formato ficava
        com numero=None e o rótulo degenerava para "Lei" — foi assim que um modelo
        leu "8080" do nome do arquivo e escreveu "Lei nº 8080/2011".
        """
        meta = parse_file_name("LEI 8080.pdf")
        self.assertEqual(meta["tipo"], "lei")
        self.assertEqual(meta["numero"], "8080")

    def test_lei_entre_hifens_com_sufixo(self):
        """'LEI-8080-ESQUEMATIZADA1.pdf' — número entre hífens, com sufixo livre."""
        meta = parse_file_name("LEI-8080-ESQUEMATIZADA1.pdf")
        self.assertEqual(meta["tipo"], "lei")
        self.assertEqual(meta["numero"], "8080")
        self.assertIsNone(meta["ano"], "o sufixo 'ESQUEMATIZADA1' não é ano")

    def test_lei_com_underscore(self):
        meta = parse_file_name("lei_8213_1991.pdf")
        self.assertEqual(meta["numero"], "8213")
        self.assertEqual(meta["ano"], "1991")

    def test_nao_confunde_ano_curto_com_numero(self):
        """'CF-88.pdf' não pode passar a devolver numero=88."""
        meta = parse_file_name("CF-88.pdf")
        self.assertEqual(meta["tipo"], "constituicao")
        self.assertIsNone(meta["numero"])


class TestParseChunk(unittest.TestCase):
    def test_parse_completo(self):
        result = parse_chunk(
            "Art. 54. § 1º O segurado...\nI - item",
            "Decreto 3.048-99.pdf",
        )
        self.assertEqual(result["artigo"], 54)
        self.assertEqual(result["paragrafo"], "1")
        self.assertEqual(result["inciso"], "I")
        self.assertEqual(result["tipo_doc"], "decreto")
        self.assertEqual(result["numero_doc"], "3048")
        self.assertEqual(result["ano_doc"], "1999")

    def test_enrich_preserva_metadata_existente(self):
        original = {"pagina": 3, "source": "pdf"}
        enriched = enrich_chunk_metadata("Art. 1. texto", "Lei 8.213-91.pdf", original)
        self.assertEqual(enriched["pagina"], 3)
        self.assertEqual(enriched["source"], "pdf")
        self.assertEqual(enriched["artigo"], 1)
        self.assertEqual(enriched["tipo_doc"], "lei")


class TestIdentidadeDoDocumento(unittest.TestCase):
    """R-9: a identidade da norma vem do CONTEÚDO do documento (cabeçalho oficial).

    Na base de dev, 120 de 122 fragmentos estavam sem `numero_doc` e a única identidade
    da Lei 8.080 era o nome `LEI-8080-ESQUEMATIZADA1.pdf` — o que fazia o rótulo do
    contexto e o fact-check dependerem do nome do arquivo.
    """

    def test_cabecalho_do_planalto_da_numero_e_ano_juntos(self):
        meta = identidade_do_documento("LEI Nº 8.080, DE 19 DE SETEMBRO DE 1990.\n\nO PRESIDENTE...")
        self.assertEqual((meta['tipo'], meta['numero'], meta['ano']), ('lei', '8080', '1990'))

    def test_formatos_de_cabecalho_reais(self):
        casos = [
            ("LEI Nº 8.213, DE 24 DE JULHO DE 1991.", ('lei', '8213', '1991')),
            ("LEI Nº 8.213/91.", ('lei', '8213', '1991')),
            ("DECRETO Nº 3.048, DE 6 DE MAIO DE 1999.", ('decreto', '3048', '1999')),
            ("DECRETO Nº 3.048/99", ('decreto', '3048', '1999')),
            ("LEI COMPLEMENTAR Nº 142, DE 8 DE MAIO DE 2013.", ('lei_complementar', '142', '2013')),
            ("EMENDA CONSTITUCIONAL Nº 103, DE 12 DE NOVEMBRO DE 2019", ('emenda', '103', '2019')),
            ("LEI Nº 14.133, DE 1º DE ABRIL DE 2021.", ('lei', '14133', '2021')),
            ("CONSTITUIÇÃO DA REPÚBLICA FEDERATIVA DO BRASIL DE 1988", ('constituicao', None, '1988')),
        ]
        for texto, esperado in casos:
            with self.subTest(texto=texto):
                meta = identidade_do_documento(texto)
                self.assertEqual((meta['tipo'], meta['numero'], meta['ano']), esperado)

    def test_mp_com_reedicao_nao_vira_ano(self):
        """'MP nº 2.164-41' é a 41ª reedição: o -41 não pode virar 1941."""
        meta = identidade_do_documento("Medida Provisória nº 2.164-41, de 24 de agosto de 2001")
        self.assertEqual((meta['tipo'], meta['numero'], meta['ano']),
                         ('medida_provisoria', '2164', '2001'))

    def test_norma_citada_nao_vira_identidade_do_documento(self):
        """A armadilha medida: a apostila começa com '(Incluído pela Lei nº 12.401, de 2011)'
        e era identificada como a LEI 12.401/2011 — contaminando TODOS os fragmentos."""
        meta = identidade_do_documento(
            "Art. 19-Q. (Incluído pela Lei nº 12.401, de 2011)\nArt. 19-R. (Vide Lei nº 12.401, de 2011)",
            "LEI-8080-ESQUEMATIZADA1.pdf")
        self.assertEqual((meta['tipo'], meta['numero'], meta['ano']), ('lei', '8080', None))

    def test_citacao_longe_do_inicio_nao_interfere(self):
        texto = "LEI Nº 9.717, DE 27 DE NOVEMBRO DE 1998. " + "x" * 5000 + " (Incluído pela Lei nº 12.401, de 2011)"
        meta = identidade_do_documento(texto)
        self.assertEqual((meta['numero'], meta['ano']), ('9717', '1998'))

    def test_redacao_dada_pela_lei_nao_e_identidade(self):
        meta = identidade_do_documento("LEI Nº 8.213/91. (Redação dada pela Lei nº 13.135, de 2015)")
        self.assertEqual((meta['numero'], meta['ano']), ('8213', '1991'))

    def test_sem_cabecalho_cai_no_nome_do_arquivo(self):
        meta = identidade_do_documento("Texto solto sem cabeçalho de norma.", "Lei 8.213-91.pdf")
        self.assertEqual((meta['tipo'], meta['numero'], meta['ano']), ('lei', '8213', '1991'))

    def test_sem_cabecalho_e_sem_nome_nao_inventa(self):
        meta = identidade_do_documento("Texto solto.", None)
        self.assertEqual((meta['tipo'], meta['numero'], meta['ano']), (None, None, None))

    def test_lista_de_leis_alteradoras_nao_vira_identidade(self):
        """Medido no PDF real da apostila: a primeira norma com 'nº' no cabeçalho é
        `Decreto nº 1.651, de 28 de setembro de 1995` — linha da **lista do que alterou** a
        8.080, não a identidade do documento."""
        cabecalho = (
            "LEIB.080 ESQUEMATIZADA\nProf. Adriano de Oliveira\n"
            "Apresentarei a você neste artigo a Lei 8.080, de 19 de setembro de 1990, "
            "também conhecida como Lei Orgânica da Saúde.\n\n"
            + "Texto de contextualização sobre o SUS. " * 20
            + "\nDecreto nº 1.651, de 28 de setembro de 1995\n"
            "Lei nº 9.836, de 23 de setembro de 1999\n"
        )
        meta = identidade_do_documento(cabecalho, "LEI-8080-ESQUEMATIZADA1.pdf")
        self.assertEqual((meta['tipo'], meta['numero'], meta['ano']), ('lei', '8080', '1990'))

    def test_escolha_e_por_posicao_e_nao_por_padrao(self):
        """Entre dois anúncios, vence o que aparece primeiro — mas citação em prosa não é
        anúncio: 'conforme a Lei 10.741' é recusada pela pista de citação."""
        texto = ("Idade mínima de 65 anos, conforme a Lei 10.741, de 1º de outubro de 2003.\n"
                 "LEI Nº 8.080, DE 19 DE SETEMBRO DE 1990.\n")
        self.assertEqual(identidade_do_documento(texto)['numero'], '8080')

    def test_titulo_em_prosa_vence_a_lista_com_numero(self):
        """Padrão não decide, posição decide: 'a Lei 8.080, de 19 de setembro de 1990'
        (prosa, sem 'nº') vem antes do 'Decreto nº 1.651, de 28 de setembro de 1995'."""
        texto = ("Apresentarei a seguir a Lei 8.080, de 19 de setembro de 1990.\n"
                 + "Contexto. " * 200 +
                 "\nDecreto nº 1.651, de 28 de setembro de 1995\n")
        self.assertEqual(identidade_do_documento(texto)['numero'], '8080')

    def test_norma_citada_no_corpo_nao_vira_identidade(self):
        texto = ("LEI Nº 8.080, DE 19 DE SETEMBRO DE 1990.\n\nArt. 1º Esta lei regula...\n"
                 "Decreto nº 1.651, de 28 de setembro de 1995\n" + "x" * 3000)
        meta = identidade_do_documento(texto, "documento.pdf")
        self.assertEqual((meta['numero'], meta['ano']), ('8080', '1990'))

    def test_titulo_alem_do_limite_cai_para_o_nome_do_arquivo(self):
        """Preço declarado do limite curto: degrada para o nome do arquivo, nunca inventa."""
        texto = "Prefácio longo. " * 200 + "LEI Nº 8.080, DE 19 DE SETEMBRO DE 1990."
        meta = identidade_do_documento(texto, "LEI-8080-ESQUEMATIZADA1.pdf")
        self.assertEqual((meta['numero'], meta['ano']), ('8080', None))

    def test_parse_norm_header_devolve_vazio_sem_texto(self):
        self.assertEqual(parse_norm_header(""),
                         {'tipo': None, 'numero': None, 'ano': None})

    def test_identidade_vale_para_todo_fragmento(self):
        """`parse_chunk` com identidade usa a identidade nos três campos de norma."""
        identidade = {'tipo': 'lei', 'numero': '8080', 'ano': '1990'}
        meta = parse_chunk("Art. 55. Revogam-se as disposições em contrário.",
                           "LEI-8080-ESQUEMATIZADA1.pdf", identidade)
        self.assertEqual((meta['tipo_doc'], meta['numero_doc'], meta['ano_doc']),
                         ('lei', '8080', '1990'))
        self.assertEqual(meta['artigo'], 55)

    def test_enrich_com_identidade(self):
        identidade = {'tipo': 'decreto', 'numero': '3048', 'ano': '1999'}
        enriched = enrich_chunk_metadata("Art. 83. Até quatorze anos.", "quadro.pdf",
                                         {"page": 3}, identidade)
        self.assertEqual((enriched['tipo_doc'], enriched['numero_doc'], enriched['ano_doc']),
                         ('decreto', '3048', '1999'))
        self.assertEqual(enriched['page'], 3)


if __name__ == "__main__":
    unittest.main()
