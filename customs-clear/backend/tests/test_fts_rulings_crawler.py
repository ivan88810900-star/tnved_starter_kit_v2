"""Tests for FTS rulings systematic crawler (#143)."""

from __future__ import annotations

import unittest

from app.services.fts_rulings_crawler import (
    discover_pagination_urls,
    extract_hs_codes,
    extract_links,
    is_classification_relevant,
    normalize_hs_code,
    parse_date_to_iso,
    parse_document_html,
)


SAMPLE_FOLDER_HTML = """
<html><body>
<div class="pagination">
  <a href="https://customs.gov.ru/folder/519?page=1">Назад</a>
  <a href="https://customs.gov.ru/folder/519?page=3">Вперёд</a>
</div>
<a href="/document/text/123456">Решение о классификации</a>
<a href="/storage/document/document_statistics_file/x.xlsx">stats</a>
</body></html>
"""

SAMPLE_DOC_HTML = """
<html><head><title>Предварительное решение № 12-34/2024</title></head>
<body>
<p>Дата: 15.03.2024</p>
<p>Товар: ноутбук портативный</p>
<p>Код товара по ТН ВЭД ЕАЭС: 8471 30 000 0</p>
<p>Обоснование: товар классифицирован по ОПИ 1 и 6.</p>
</body></html>
"""


class FtsRulingsCrawlerTests(unittest.TestCase):
    def test_normalize_hs_from_spaced(self) -> None:
        self.assertEqual(normalize_hs_code("8471 30 000 0"), "8471300000")

    def test_extract_hs_codes_multiple_formats(self) -> None:
        text = "коды 8471.30.000.0 и 8517120000"
        codes = extract_hs_codes(text)
        self.assertIn("8471300000", codes)
        self.assertIn("8517120000", codes)

    def test_parse_date_dmy(self) -> None:
        self.assertEqual(parse_date_to_iso("от 15.03.2024 года"), "2024-03-15")

    def test_discover_pagination(self) -> None:
        urls = discover_pagination_urls("https://customs.gov.ru/folder/519", SAMPLE_FOLDER_HTML)
        self.assertIn("https://customs.gov.ru/folder/519", urls)
        self.assertIn("https://customs.gov.ru/folder/519?page=3", urls)

    def test_extract_links_skips_xlsx(self) -> None:
        links = extract_links(SAMPLE_FOLDER_HTML, "https://customs.gov.ru/folder/519")
        self.assertTrue(any("/document/text/" in u for u in links))
        self.assertFalse(any(".xlsx" in u for u in links))

    def test_parse_document_html(self) -> None:
        parsed = parse_document_html(SAMPLE_DOC_HTML, "https://customs.gov.ru/document/text/123456")
        assert parsed is not None
        self.assertEqual(parsed.assigned_hs_code, "8471300000")
        self.assertEqual(parsed.ruling_date, "2024-03-15")
        self.assertIn("классифицир", parsed.rationale.lower())

    def test_is_classification_relevant_by_hs(self) -> None:
        self.assertTrue(is_classification_relevant("товар 8517120000", "https://customs.gov.ru/doc"))

    def test_non_classification_doc_returns_none(self) -> None:
        html = "<html><body><p>Статистика экспорта по месяцам</p></body></html>"
        self.assertIsNone(parse_document_html(html, "https://customs.gov.ru/folder/519"))


if __name__ == "__main__":
    unittest.main()
