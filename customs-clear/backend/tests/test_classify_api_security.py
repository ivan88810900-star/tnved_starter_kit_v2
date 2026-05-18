"""Безопасность /api/classify: без клиентского api_key, только серверные ключи."""
from __future__ import annotations

import importlib.util
import os
import unittest
from unittest.mock import AsyncMock, patch

from app.services.normative_store import init_db
from tests.support_auth import login_declarant


@unittest.skipUnless(importlib.util.find_spec("fastapi"), "fastapi")
class ClassifyApiSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_db()
        from fastapi.testclient import TestClient
        from app.main import app

        cls.client = TestClient(app)

    def test_classify_llm_path_503_when_no_server_keys_even_if_legacy_api_key_sent(self) -> None:
        keys = ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY")
        saved = {k: os.environ.pop(k, None) for k in keys}
        try:
            login_declarant(self.client)
            r = self.client.post(
                "/api/classify",
                json={
                    "description": "электрическая дрель bosch 500w",
                    "use_custom_classifier": False,
                    "fallback_to_llm": True,
                    "api_key": "sk-ant-client-supplied-must-not-be-used",
                },
            )
            self.assertEqual(r.status_code, 503, r.text)
            body = r.json()
            self.assertEqual(body.get("error_code"), "llm_not_configured")
            self.assertIn("GEMINI_API_KEY", body.get("note", ""))
        finally:
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v

    @patch("app.api.classify.classify_hs_code", new_callable=AsyncMock)
    def test_classify_invokes_classify_hs_code_without_api_key_kwarg(self, mock_cf: AsyncMock) -> None:
        mock_cf.return_value = {"status": "OK", "results": [{"hs_code": "8509400000"}]}
        login_declarant(self.client)
        r = self.client.post(
            "/api/classify",
            json={"description": "пылесос", "use_custom_classifier": False},
        )
        self.assertEqual(r.status_code, 200, r.text)
        mock_cf.assert_called_once()
        _args, kwargs = mock_cf.call_args
        self.assertNotIn("api_key", kwargs)


if __name__ == "__main__":
    unittest.main()
