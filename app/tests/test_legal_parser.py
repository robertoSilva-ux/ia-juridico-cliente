"""Testes unitários do legal_parser.py — extração de metadados jurídicos (puros, sem deps)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from legal_parser import (
    extract_article_num, extract_paragraph, extract_inciso,
    parse_file_name, parse_chunk, enrich_chunk_metadata,
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


if __name__ == "__main__":
    unittest.main()
