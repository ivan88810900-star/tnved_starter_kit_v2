"""Парсинг HTML-ответов ФСА (таблица vs SPA-оболочка)."""
from __future__ import annotations

import unittest

from app.services.permits_service import _extract_fsa_from_html


class FsaHtmlExtractTests(unittest.TestCase):
    def test_table_with_rows_is_valid(self):
        html = """<html><body>
        <table><tr><th>A</th></tr><tr><td>cell</td></tr></table>
        </body></html>"""
        r = _extract_fsa_from_html(html, "СС", "ЕАЭС RU С-X")
        self.assertEqual(r["status"], "VALID")
        self.assertEqual(r["raw"].get("rows_count"), 1)

    def test_not_found_phrase(self):
        html = "<html><body><p>Ничего не найдено по запросу</p></body></html>"
        r = _extract_fsa_from_html(html, "ДС", "X")
        self.assertEqual(r["status"], "NOT_FOUND")

    def test_spa_shell_marks_note(self):
        html = """<!doctype html><html lang="ru" data-critters-container>
        <head><title>ФГИС</title></head><body><p>Загрузка</p></body></html>"""
        r = _extract_fsa_from_html(html, "СС", "ЕАЭСRUС-TEST")
        self.assertEqual(r["status"], "UNKNOWN")
        self.assertTrue((r.get("raw") or {}).get("spa_shell"))
        self.assertIn("браузере", (r.get("raw") or {}).get("note", ""))


if __name__ == "__main__":
    unittest.main()
