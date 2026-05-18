"""Batch copilot API."""
from __future__ import annotations

import importlib.util
import unittest
from unittest.mock import AsyncMock, patch

from app.services.normative_store import init_db
from tests.support_auth import login_declarant


@unittest.skipUnless(importlib.util.find_spec("fastapi"), "fastapi")
class CopilotBatchApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        from fastapi.testclient import TestClient
        from app.main import app

        cls.client = TestClient(app)
        login_declarant(cls.client)

    @patch("app.api.assistant.analyze_copilot_bundle", new_callable=AsyncMock)
    def test_batch_two_positions(self, mock_ai):
        mock_ai.return_value = {"status": "OK", "summary": "ok", "risks": []}
        r = self.client.post(
            "/api/assistant/copilot/batch",
            json={
                "items": [
                    {
                        "description": "Пылесос",
                        "hs_code": "8509400000",
                        "country": "CN",
                        "customs_value": 100000,
                        "freight": 0,
                        "permits": [],
                    },
                    {
                        "description": "Чайник",
                        "hs_code": "8516108008",
                        "country": "CN",
                        "customs_value": 50000,
                        "permits": [],
                    },
                ],
                "run_registry_verify": False,
            },
        )
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(len(body["bundles"]), 2)
        self.assertIn("positions", body["context_for_ai"])


if __name__ == "__main__":
    unittest.main()
