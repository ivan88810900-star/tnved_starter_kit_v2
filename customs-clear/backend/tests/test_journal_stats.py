"""Статистика журнала решений."""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app.services.decision_history as dh


class ComputeJournalStatsTests(unittest.TestCase):
    def test_empty_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "empty.jsonl"
            p.write_text("", encoding="utf-8")
            with patch.object(dh, "_PATH", p):
                s = dh.compute_journal_stats()
            self.assertEqual(s["records_in_index"], 0)
            self.assertEqual(s["top_confirmed_hs"], [])

    def test_counts_top_hs(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "j.jsonl"
            lines = [
                {"description": "a", "confirmed_hs": "8509400000", "source": "ui", "client_id": "c1", "ts": "2025-01-01T00:00:00+00:00"},
                {"description": "b", "confirmed_hs": "8509400000", "source": "ui", "ts": "2025-01-02T00:00:00+00:00"},
                {"description": "c", "confirmed_hs": "8516108008", "source": "demo", "ts": "2025-01-03T00:00:00+00:00"},
            ]
            p.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in lines), encoding="utf-8")
            with patch.object(dh, "_PATH", p):
                s = dh.compute_journal_stats()
            self.assertEqual(s["records_in_index"], 3)
            self.assertEqual(s["unique_confirmed_hs_codes"], 2)
            self.assertEqual(s["unique_client_ids"], 1)
            self.assertEqual(s["top_confirmed_hs"][0]["hs_code"], "8509400000")
            self.assertEqual(s["top_confirmed_hs"][0]["count"], 2)


@unittest.skipUnless(importlib.util.find_spec("fastapi"), "fastapi")
class StatsApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app.services.normative_store import init_db

        init_db()
        from fastapi.testclient import TestClient
        from app.main import app

        cls.client = TestClient(app)
        from tests.support_auth import login_declarant

        login_declarant(cls.client)

    def test_stats_endpoint(self):
        r = self.client.get("/api/assistant/decisions/stats")
        self.assertEqual(r.status_code, 200)
        b = r.json()
        self.assertEqual(b.get("status"), "OK")
        self.assertIn("records_in_index", b)


if __name__ == "__main__":
    unittest.main()
