"""Операционный периметр: запись в БД, аналитика, тяжёлые/внешние вызовы — не без сессии или admin-токена."""
from __future__ import annotations

import importlib.util
import os
import unittest
from unittest.mock import AsyncMock, patch

from app.services.normative_store import init_db
from tests.support_auth import login_declarant


@unittest.skipUnless(importlib.util.find_spec("fastapi"), "fastapi")
class OperationalAdminSurfaceAuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_db()
        from fastapi.testclient import TestClient
        from app.main import app

        cls.anon = TestClient(app)
        cls.auth = TestClient(app)
        login_declarant(cls.auth)

    @patch("app.api.finance.update_exchange_rates_from_cbrf", new_callable=AsyncMock)
    def test_finance_rates_update_requires_admin_token(self, mock_upd: AsyncMock) -> None:
        mock_upd.return_value = {"ok": True}
        with patch.dict(os.environ, {"ADMIN_API_TOKEN": "fin-secret"}):
            r = self.anon.post("/api/v1/finance/rates/update")
            self.assertEqual(r.status_code, 401, r.text)
            bad = self.anon.post(
                "/api/v1/finance/rates/update",
                headers={"X-Admin-Token": "wrong"},
            )
            self.assertEqual(bad.status_code, 401, bad.text)
            ok = self.anon.post(
                "/api/v1/finance/rates/update",
                headers={"X-Admin-Token": "fin-secret"},
            )
            self.assertEqual(ok.status_code, 200, ok.text)

    @patch("app.api.analytics.redis_ping", new_callable=AsyncMock)
    @patch("app.api.analytics.build_analytics_overview")
    def test_analytics_overview_requires_admin_token(self, mock_build, mock_redis: AsyncMock) -> None:
        mock_build.return_value = {"status": "OK", "generated_at": "t0", "database_reachable": True}
        mock_redis.return_value = True
        with patch.dict(os.environ, {"ADMIN_API_TOKEN": "an-secret"}):
            r = self.anon.get("/api/analytics/overview")
            self.assertEqual(r.status_code, 401, r.text)
            ok = self.anon.get("/api/analytics/overview", headers={"X-Admin-Token": "an-secret"})
            self.assertEqual(ok.status_code, 200, ok.text)

    @patch("app.api.permits.check_permits", new_callable=AsyncMock)
    def test_permits_verify_requires_authenticated_user(self, mock_cp: AsyncMock) -> None:
        mock_cp.return_value = []
        body = {"permits": [{"type": "ДС", "number": "ЕАЭС RU Д-CN.12345"}], "hs_code": "8509400000"}
        r = self.anon.post("/api/permits/verify", json=body)
        self.assertEqual(r.status_code, 401, r.text)
        ok = self.auth.post("/api/permits/verify", json=body)
        self.assertEqual(ok.status_code, 200, ok.text)

    def test_compliance_check_requires_authenticated_user(self) -> None:
        body = {
            "items": [
                {
                    "hs_code": "8509400000",
                    "description": "пылесос",
                    "country": "CN",
                    "permits": [],
                    "customs_value": 100000.0,
                    "freight": 0.0,
                }
            ],
            "save_history": False,
        }
        r = self.anon.post("/api/compliance/check", json=body)
        self.assertEqual(r.status_code, 401, r.text)
        ok = self.auth.post("/api/compliance/check", json=body)
        self.assertIn(ok.status_code, (200, 400, 500), ok.text)

    def test_alta_status_requires_authenticated_user(self) -> None:
        r = self.anon.get("/api/integrations/alta/status")
        self.assertEqual(r.status_code, 401, r.text)
        ok = self.auth.get("/api/integrations/alta/status")
        self.assertEqual(ok.status_code, 200, ok.text)

    @patch("app.api.tnved.semantic_search_tnved")
    def test_tnved_semantic_search_requires_authenticated_user(self, mock_sem) -> None:
        mock_sem.return_value = []
        r = self.anon.get("/api/tnved/search/semantic?q=телефон&limit=3")
        self.assertEqual(r.status_code, 401, r.text)
        ok = self.auth.get("/api/tnved/search/semantic?q=телефон&limit=3")
        self.assertEqual(ok.status_code, 200, ok.text)

    @patch("app.api.non_tariff.check_position_non_tariff", new_callable=AsyncMock)
    def test_non_tariff_check_requires_authenticated_user(self, mock_nt: AsyncMock) -> None:
        mock_nt.return_value = {
            "status": "OK",
            "hs_code": "8509400000",
            "description": "x",
            "tr_ts": [],
            "permits": [],
            "notes": [],
        }
        body = {"items": [{"hs_code": "8509400000", "description": "пылесос", "country": "CN", "permits": []}]}
        r = self.anon.post("/api/non_tariff/check", json=body)
        self.assertEqual(r.status_code, 401, r.text)
        ok = self.auth.post("/api/non_tariff/check", json=body)
        self.assertEqual(ok.status_code, 200, ok.text)


if __name__ == "__main__":
    unittest.main()
