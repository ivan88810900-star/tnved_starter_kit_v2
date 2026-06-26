"""Tests for TROIS fuzzy + permits helpers (#151)."""

from __future__ import annotations

import unittest

from app.services.permits_service import build_fsa_manual_link, infer_doc_type_from_number, normalize_number
from app.services.trois_fuzzy import fuzzy_match_score, fuzzy_variants, normalize_brand_key


class TroisFuzzyTests(unittest.TestCase):
    def test_cyrillic_alias_nike(self) -> None:
        self.assertIn("nike", fuzzy_variants("Найк"))

    def test_cyrillic_alias_apple(self) -> None:
        self.assertEqual(normalize_brand_key("Эппл"), "apple")

    def test_fuzzy_score_nike(self) -> None:
        self.assertGreaterEqual(fuzzy_match_score("N1KE", "nike"), 0.7)


class PermitsHelperTests(unittest.TestCase):
    def test_infer_ss_from_ross(self) -> None:
        self.assertEqual(infer_doc_type_from_number("РОСС.CN.АЯ46.А12345"), "СС")

    def test_manual_link_contains_filter(self) -> None:
        norm = normalize_number("РОСС.CN.АЯ46.А12345")
        link = build_fsa_manual_link("СС", norm)
        self.assertIn("filter=", link)
        self.assertIn("pub.fsa.gov.ru", link)


if __name__ == "__main__":
    unittest.main()
