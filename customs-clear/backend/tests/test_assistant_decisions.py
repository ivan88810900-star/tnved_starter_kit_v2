"""API истории решений ассистента."""
from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app.services.decision_history as decision_history
from tests.support_auth import login_declarant


@unittest.skipUnless(importlib.util.find_spec("fastapi"), "fastapi")
class AssistantDecisionsApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app.services.normative_store import init_db

        init_db()
        from fastapi.testclient import TestClient
        from app.main import app

        cls.client = TestClient(app)
        login_declarant(cls.client)

    def test_log_and_recent(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "decisions.jsonl"
            with patch.object(decision_history, "_PATH", p):
                r = self.client.post(
                    "/api/assistant/decisions/log",
                    json={
                        "description": "чайник",
                        "suggested_hs": "8516108008",
                        "confirmed_hs": "8516108008",
                        "source": "test",
                        "notes": "ok",
                    },
                )
                self.assertEqual(r.status_code, 200, r.text)
                self.assertTrue(p.is_file())
                r2 = self.client.get("/api/assistant/decisions/recent?limit=5")
                self.assertEqual(r2.status_code, 200)
                body = r2.json()
                self.assertEqual(body["status"], "OK")
                self.assertTrue(len(body["items"]) >= 1)
                self.assertEqual(body["items"][-1].get("confirmed_hs"), "8516108008")

    def test_log_requires_confirmed_hs(self):
        r = self.client.post(
            "/api/assistant/decisions/log",
            json={"description": "x", "suggested_hs": "", "confirmed_hs": "  "},
        )
        self.assertEqual(r.status_code, 400)

    def test_similar_endpoint(self):
        r = self.client.get("/api/assistant/decisions/similar", params={"q": "абв", "limit": 3})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json().get("status"), "OK")
        self.assertIn("items", r.json())

    def test_export_denied_when_admin_token_not_configured(self):
        with patch.dict(os.environ, {"ADMIN_API_TOKEN": ""}):
            r = self.client.get("/api/assistant/decisions/export", params={"format": "json"})
        self.assertEqual(r.status_code, 401)

    def test_export_requires_admin_when_set(self):
        with patch.dict(os.environ, {"ADMIN_API_TOKEN": "test-admin-secret"}):
            r = self.client.get("/api/assistant/decisions/export")
            self.assertEqual(r.status_code, 401)
            r2 = self.client.get(
                "/api/assistant/decisions/export",
                headers={"X-Admin-Token": "test-admin-secret"},
            )
            self.assertEqual(r2.status_code, 200)


if __name__ == "__main__":
    unittest.main()
