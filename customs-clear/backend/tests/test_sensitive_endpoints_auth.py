"""Обязательная JWT/cookie-auth для дорогих и чувствительных API."""
from __future__ import annotations

import importlib.util
import os
import unittest
from unittest.mock import AsyncMock, patch

from app.services.normative_store import init_db
from tests.support_auth import login_declarant


@unittest.skipUnless(importlib.util.find_spec("fastapi"), "fastapi")
class SensitiveEndpointsAuthTests(unittest.TestCase):
    """Отдельные TestClient: cookie сессии не должны протекать между анонимными и авторизованными кейсами."""

    @classmethod
    def setUpClass(cls) -> None:
        init_db()
        from fastapi.testclient import TestClient
        from app.main import app

        cls.anon = TestClient(app)
        cls.auth = TestClient(app)
        login_declarant(cls.auth)

    def test_classify_unauthorized_without_session(self) -> None:
        r = self.anon.post(
            "/api/classify",
            json={"description": "тест", "use_custom_classifier": False},
        )
        self.assertEqual(r.status_code, 401, r.text)
        d = r.json().get("detail")
        if isinstance(d, dict):
            self.assertEqual(d.get("error_code"), "authentication_required")
        else:
            self.fail("ожидался detail-объект с error_code")

    def test_documents_v1_analyze_unauthorized(self) -> None:
        r = self.anon.post(
            "/api/v1/documents/analyze",
            files={"file": ("t.csv", b"a;b\n1;2", "text/csv")},
        )
        self.assertEqual(r.status_code, 401, r.text)

    def test_assistant_copilot_unauthorized(self) -> None:
        r = self.anon.post(
            "/api/assistant/copilot",
            json={
                "description": "x",
                "hs_code": "8509400000",
                "run_ai_classification": False,
                "run_payment": False,
                "run_registry_verify": False,
            },
        )
        self.assertEqual(r.status_code, 401, r.text)

    def test_ai_ask_unauthorized(self) -> None:
        r = self.anon.post("/api/ai/ask", json={"question": "что такое ТН ВЭД?", "code": "", "notes": ""})
        self.assertEqual(r.status_code, 401, r.text)

    @patch("app.api.assistant.analyze_copilot_bundle", new_callable=AsyncMock)
    def test_assistant_copilot_ok_with_session(self, mock_ai: AsyncMock) -> None:
        mock_ai.return_value = {"status": "OK", "summary": "ok", "risks": []}
        r = self.auth.post(
            "/api/assistant/copilot",
            json={
                "description": "Бытовой пылесос",
                "hs_code": "8509400000",
                "country": "CN",
                "customs_value": 100000,
                "freight": 5000,
                "permits": [],
                "run_ai_classification": False,
                "run_payment": True,
                "run_registry_verify": False,
            },
        )
        self.assertEqual(r.status_code, 200, r.text)

    def test_admin_sync_status_requires_admin_header_even_when_logged_in(self) -> None:
        with patch.dict(os.environ, {"ADMIN_API_TOKEN": "sync-test-secret"}):
            r = self.auth.get("/api/v1/admin/sync/status")
            self.assertEqual(r.status_code, 401, r.text)
            ok = self.auth.get(
                "/api/v1/admin/sync/status",
                headers={"X-Admin-Token": "sync-test-secret"},
            )
            self.assertEqual(ok.status_code, 200, ok.text)


if __name__ == "__main__":
    unittest.main()
