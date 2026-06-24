"""Тесты: API-ключи и URL провайдеров не попадают в HTTP-ответы."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient

from app.main import app
from app.services.safe_http_errors import (
    AI_SERVICE_UNAVAILABLE,
    contains_sensitive_error_text,
    safe_ai_unavailable_message,
)


class SafeHttpErrorsTests(unittest.TestCase):
    def test_detects_proxyapi_and_key_in_error(self) -> None:
        msg = (
            "Server error '503' for url "
            "'https://api.proxyapi.ru/google/v1beta/models/gemini:generateContent?key=sk-SECRET123'"
        )
        self.assertTrue(contains_sensitive_error_text(msg))
        self.assertEqual(safe_ai_unavailable_message(Exception(msg)), AI_SERVICE_UNAVAILABLE)


class ClassifyApiErrorMaskingTests(unittest.TestCase):
    def test_classify_masks_llm_http_error(self) -> None:
        leak = (
            "Server error '503 Service Unavailable' for url "
            "'https://api.proxyapi.ru/google/v1beta/models/gemini-2.0-flash:generateContent?key=sk-SECRET'"
        )
        err = httpx.HTTPStatusError(
            leak,
            request=httpx.Request("POST", "http://x"),
            response=httpx.Response(503),
        )
        from app.security import require_authenticated_user

        app.dependency_overrides[require_authenticated_user] = lambda: {"sub": "test"}
        try:
            with patch("app.api.classify.classify_hs_code", new=AsyncMock(side_effect=err)):
                client = TestClient(app)
                r = client.post("/api/classify", json={"description": "тест"})
        finally:
            app.dependency_overrides.clear()
        self.assertEqual(r.status_code, 503)
        body = r.json()
        detail = body.get("detail", "")
        self.assertEqual(detail, AI_SERVICE_UNAVAILABLE)
        self.assertNotIn("proxyapi", detail.lower())
        self.assertNotIn("sk-", detail)
        self.assertNotIn("key=", detail.lower())


if __name__ == "__main__":
    unittest.main()
