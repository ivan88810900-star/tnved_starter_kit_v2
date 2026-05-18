"""Оркестратор copilot и пропуск реестра в нетарифке."""
from __future__ import annotations

import importlib.util
import unittest
from unittest.mock import AsyncMock, patch

from app.services.normative_store import init_db
from app.services.assistant_orchestrator import run_copilot_pipeline, pick_hs_from_classification, bundle_for_llm


class PickHsTests(unittest.TestCase):
    def test_from_recommended_dict(self):
        d = pick_hs_from_classification({"recommended": {"code": "8509 40 000 0"}})
        self.assertTrue(d.startswith("8509"))

    def test_from_results(self):
        d = pick_hs_from_classification({"results": [{"hs_code": "8516108008"}]})
        self.assertEqual(d, "8516108008")


class NonTariffSkipRegistryTests(unittest.IsolatedAsyncioTestCase):
    async def test_skipped_rows_when_no_fsa(self):
        from app.services.non_tariff_service import check_position_non_tariff

        r = await check_position_non_tariff(
            "8509400000",
            "пылесос",
            "CN",
            [{"type": "ДС", "number": "ЕАЭС RU Д-TEST.XX.В.1/25"}],
            skip_registry_verify=True,
        )
        self.assertTrue(r.get("permits"))
        self.assertEqual(r["permits"][0].get("status"), "SKIPPED")


@unittest.skipUnless(importlib.util.find_spec("fastapi"), "fastapi")
class CopilotApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        from fastapi.testclient import TestClient
        from app.main import app

        cls.client = TestClient(app)
        from tests.support_auth import login_declarant

        login_declarant(cls.client)

    @patch("app.api.assistant.analyze_copilot_bundle", new_callable=AsyncMock)
    def test_copilot_endpoint_smoke(self, mock_ai):
        mock_ai.return_value = {"status": "OK", "summary": "Тест", "risks": []}
        r = self.client.post(
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
        body = r.json()
        self.assertEqual(body["status"], "OK")
        self.assertIn("bundle", body)
        self.assertIn("ai", body)
        self.assertEqual(body["bundle"]["effective_hs_code"], "8509400000")


class CopilotPipelineTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    async def test_pipeline_payment_and_nt(self):
        b = await run_copilot_pipeline(
            description="пылесос",
            hs_code="8509400000",
            country="CN",
            customs_value=50_000,
            freight=0,
            permits=[],
            run_ai_classification=False,
            run_payment=True,
            run_registry_verify=False,
        )
        self.assertEqual(b["effective_hs_code"], "8509400000")
        self.assertIsNotNone(b.get("payment"))
        self.assertIn("non_tariff", b)
        slim = bundle_for_llm(b)
        self.assertIn("payment_summary", slim)


if __name__ == "__main__":
    unittest.main()
