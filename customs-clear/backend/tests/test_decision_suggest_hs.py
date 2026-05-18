"""Агрегация кодов ТН ВЭД из журнала и hints API."""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app.services.decision_history as dh


class SuggestHsCodesTests(unittest.TestCase):
    def test_aggregates_same_hs(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "j.jsonl"
            rows = [
                {"description": "пылесос бытовой вертикальный", "confirmed_hs": "8509400000"},
                {"description": "пылесос для сухой уборки дома", "confirmed_hs": "8509400000"},
                {"description": "арматура стальная", "confirmed_hs": "7214200000"},
            ]
            p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
            with patch.object(dh, "_PATH", p):
                out = dh.suggest_hs_codes("пылесос бытовой электрический", limit=5)
                self.assertTrue(len(out) >= 1)
                self.assertEqual(out[0]["hs_code"], "8509400000")
                self.assertGreaterEqual(out[0]["count"], 1)

    def test_journal_hints_non_empty(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "j.jsonl"
            p.write_text(
                json.dumps({"description": "чайник электрический 2л", "confirmed_hs": "8516108008"}),
                encoding="utf-8",
            )
            with patch.object(dh, "_PATH", p):
                block = dh.journal_hints_for_classifier("электрический чайник пластик")
                self.assertIn("8516108008", block)
                self.assertIn("журнала", block.lower())


@unittest.skipUnless(importlib.util.find_spec("fastapi"), "fastapi")
class HintsApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app.services.normative_store import init_db

        init_db()
        from fastapi.testclient import TestClient
        from app.main import app

        cls.client = TestClient(app)
        from tests.support_auth import login_declarant

        login_declarant(cls.client)

    def test_hints_endpoint(self):
        r = self.client.get(
            "/api/assistant/decisions/hints",
            params={"q": "товар таможня", "similar_limit": 2, "hs_limit": 3},
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "OK")
        self.assertIn("similar", body)
        self.assertIn("hs_suggestions", body)

    def test_suggest_hs_endpoint(self):
        r = self.client.get("/api/assistant/decisions/suggest-hs", params={"q": "импорт", "limit": 5})
        self.assertEqual(r.status_code, 200)
        self.assertIn("items", r.json())


if __name__ == "__main__":
    unittest.main()
