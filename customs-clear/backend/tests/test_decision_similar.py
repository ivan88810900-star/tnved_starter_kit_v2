"""Похожие записи журнала решений."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app.services.decision_history as dh


class SimilarityScoreTests(unittest.TestCase):
    def test_identical_high(self):
        s = dh.similarity_score("электрический чайник 2 литра", "электрический чайник 2 литра")
        self.assertGreater(s, 0.85)

    def test_unrelated_low(self):
        s = dh.similarity_score("чайник электрический", "труба стальная оцинкованная")
        self.assertLess(s, 0.35)


class FindSimilarTests(unittest.TestCase):
    def test_finds_by_description(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "j.jsonl"
            rows = [
                {"description": "пылесос бытовой с контейнером", "confirmed_hs": "8509400000"},
                {"description": "стальная арматура a500", "confirmed_hs": "7214200000"},
            ]
            p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
            with patch.object(dh, "_PATH", p):
                out = dh.find_similar_decisions("пылесос для дома с пылесборником", limit=5, min_score=0.12)
                self.assertTrue(len(out) >= 1)
                self.assertEqual(out[0].get("confirmed_hs"), "8509400000")


if __name__ == "__main__":
    unittest.main()
