"""Приоритет записей журнала по client_id."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app.services.decision_history as dh


class ClientBoostTests(unittest.TestCase):
    def test_multiplier_same_client(self):
        self.assertEqual(dh.client_score_multiplier("u1", "u1"), dh._CLIENT_BOOST_MULT)
        self.assertEqual(dh.client_score_multiplier("u1", "u2"), 1.0)
        self.assertEqual(dh.client_score_multiplier(None, "u1"), 1.0)

    def test_suggest_hs_prefers_same_client(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "j.jsonl"
            rows = [
                {"description": "труба стальная оцинкованная для воды", "confirmed_hs": "7306300000", "client_id": "other"},
                {"description": "пылесос вертикальный для дома бытовой", "confirmed_hs": "8509400000", "client_id": "me"},
            ]
            p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
            with patch.object(dh, "_PATH", p):
                out_me = dh.suggest_hs_codes("пылесос вертикальный дом", limit=5, prefer_client_id="me")
            codes_me = [x["hs_code"] for x in out_me]
            self.assertTrue(len(codes_me) >= 1)
            self.assertEqual(codes_me[0], "8509400000")
            self.assertGreaterEqual(out_me[0].get("client_boosted_rows") or 0, 1)


if __name__ == "__main__":
    unittest.main()
