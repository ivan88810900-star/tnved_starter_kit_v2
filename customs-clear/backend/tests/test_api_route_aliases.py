"""Обратная совместимость legacy API paths (Block 3)."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app
from app.security import require_authenticated_user


class LegacyRouteAliasTests(unittest.TestCase):
    def setUp(self) -> None:
        app.dependency_overrides[require_authenticated_user] = lambda: {"sub": "test"}

    def tearDown(self) -> None:
        app.dependency_overrides.clear()

    def test_assistant_chat_legacy_path_not_405(self) -> None:
        with patch(
            "app.api.assistant.run_assistant_chat",
            new=AsyncMock(return_value="8471300000 — ноутбуки"),
        ):
            client = TestClient(app)
            r = client.post(
                "/api/assistant/chat",
                json={"message": "Какой код ТН ВЭД у ноутбука?"},
            )
        self.assertNotEqual(r.status_code, 405, r.text)
        self.assertEqual(r.status_code, 200)
        self.assertIn("answer", r.json())

    def test_classify_legacy_path_not_405(self) -> None:
        with patch(
            "app.api.classify.classify_hs_code",
            new=AsyncMock(return_value={"status": "OK", "results": []}),
        ):
            client = TestClient(app)
            r = client.post(
                "/api/tnved/classify",
                json={"description": "Кроссовки"},
            )
        self.assertNotEqual(r.status_code, 405, r.text)
        self.assertEqual(r.status_code, 200)


if __name__ == "__main__":
    unittest.main()
