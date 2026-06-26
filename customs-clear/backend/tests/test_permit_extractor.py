"""Тесты извлечения номеров и сверки ТН ВЭД."""
from __future__ import annotations

import unittest

from app.services.permit_extractor import extract_permits_from_text, merge_permit_lists
from app.services.permits_service import match_item_hs_to_registry


class PermitExtractorTests(unittest.TestCase):
    def test_extract_declaration(self):
        text = "Декларация ЕАЭС RU Д-RU.АЯ46.В.12345/24 действует до 2026"
        found = extract_permits_from_text(text)
        self.assertTrue(any("ДС" == x["type"] for x in found))

    def test_merge(self):
        m = merge_permit_lists([{"type": "ДС", "number": "N1"}], [{"type": "ДС", "number": "N1"}, {"type": "СС", "number": "N2"}])
        self.assertEqual(len(m), 2)


class HsMatchTests(unittest.TestCase):
    def test_ok(self):
        r = match_item_hs_to_registry("8509400000", ["8509400000"])
        self.assertEqual(r["hs_match"], "ok")

    def test_partial(self):
        r = match_item_hs_to_registry("8509400000", ["8509800000"])
        self.assertEqual(r["hs_match"], "partial")

    def test_mismatch(self):
        r = match_item_hs_to_registry("8509400000", ["0201300000"])
        self.assertEqual(r["hs_match"], "mismatch")


if __name__ == "__main__":
    unittest.main()
