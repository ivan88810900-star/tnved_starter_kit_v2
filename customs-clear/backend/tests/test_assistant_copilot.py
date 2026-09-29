"""Оркестратор copilot и пропуск реестра в нетарифке."""
from __future__ import annotations

import importlib.util
import unittest
from copy import deepcopy
from unittest.mock import AsyncMock, patch

from app.services.assistant_orchestrator import (
    bundle_for_llm,
    pick_hs_from_classification,
    run_copilot_pipeline,
)
from app.services.claude_service import analyze_copilot_bundle
from app.services.normative_store import init_db


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


class CopilotNormativeFreshnessIntegrationTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _bundle(data_freshness):
        return {
            "effective_hs_code": "8509400000",
            "description": "пылесос",
            "country": "CN",
            "non_tariff": {
                "status": "NEEDS_DOCUMENTS",
                "normative_block": {
                    "status": "NEEDS_DOCUMENTS",
                    "required_documents": [
                        {
                            "permit_type": "СС",
                            "tr_ts": "ТР ТС 004/2011",
                            "source": "ntm_v2",
                            "source_label": "NTM v2",
                            "applicability": "definite",
                            "reason": "Обязательная сертификация",
                        }
                    ],
                    "missing_documents": [
                        {
                            "permit_type": "СС",
                            "tr_ts": "ТР ТС 004/2011",
                            "source": "ntm_v2",
                            "source_label": "NTM v2",
                            "applicability": "definite",
                            "reason": "Номер документа не предоставлен",
                        }
                    ],
                    "advisory_requirements": [
                        {
                            "permit_type": "ДС",
                            "tr_ts": "ТР ЕАЭС 037/2016",
                            "source": "ntm_v2",
                            "source_label": "NTM v2",
                            "applicability": "needs_clarification",
                            "reason": "Зависит от характеристик товара",
                        }
                    ],
                    "data_freshness": data_freshness,
                    "empty_message": None,
                },
            },
        }

    async def test_bundle_for_llm_propagates_freshness_into_real_copilot_path(self):
        fresh = {
            "state": "fresh",
            "source_name": "Технический реестр источников",
            "source_code": "NTM_TEST",
            "synced_at": "2026-09-16T09:00:00+00:00",
            "revision": "test-revision",
            "is_stale": False,
            "scope": "technical_source_status_only",
            "ntm_coverage_verified": False,
        }
        cases = (
            (fresh, "Полнота и юридическая актуальность"),
            (
                {"state": "stale", "is_stale": True, "ntm_coverage_verified": False},
                "помечены как устаревшие",
            ),
            ("malformed", "Актуальность данных нетарифного контура не подтверждена"),
        )

        expected_documents = None
        for data_freshness, expected_warning in cases:
            with self.subTest(data_freshness=data_freshness):
                slim = bundle_for_llm(self._bundle(data_freshness))
                requirements = slim["normative_requirements"]
                self.assertEqual(requirements["data_freshness"], data_freshness)

                document_rows = {
                    key: deepcopy(requirements[key])
                    for key in (
                        "required_documents",
                        "missing_documents",
                        "advisory_requirements",
                    )
                }
                if expected_documents is None:
                    expected_documents = document_rows
                self.assertEqual(document_rows, expected_documents)

                with patch(
                    "app.services.claude_service._choose_provider",
                    return_value=("none", None),
                ):
                    result = await analyze_copilot_bundle(slim)

                self.assertIn(expected_warning, result["non_tariff_comment"])
                self.assertIn("СС", result["documents_comment"])
                self.assertTrue(
                    any("СС" in item for item in result["risks"]),
                    result["risks"],
                )
                self.assertTrue(
                    any(expected_warning in item for item in result["risks"]),
                    result["risks"],
                )


if __name__ == "__main__":
    unittest.main()
