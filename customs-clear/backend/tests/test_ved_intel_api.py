"""POST /api/documents/ved-intelligent-analyze — проводка без тяжёлого ИИ/ФСА (моки)."""
from __future__ import annotations

import importlib.util
import io
import unittest
from unittest.mock import AsyncMock, patch

try:
    from fastapi.testclient import TestClient
    from app.main import app
    from app.services.normative_store import init_db
    from app.services.ved_intel_service import run_ved_intel_pipeline

    _OK = True
except ImportError:
    _OK = False


@unittest.skipUnless(_OK, "нужен полный стек")
class VedIntelAnalyzeApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        cls.client = TestClient(app)
        from tests.support_auth import login_declarant

        login_declarant(cls.client)

    @patch("app.api.documents.run_ved_intel_analyze_core", new_callable=AsyncMock)
    def test_ved_intel_merges_base_and_intel(self, mock_core):
        mock_core.return_value = {
            "status": "OK",
            "comparison_mode": "invoice_only",
            "items": [],
            "checks": [],
            "summary": {"errors": 0, "warnings": 0, "passed": 1},
            "ved_intel_status": "OK",
            "declaration_draft": {
                "status": "OK",
                "declaration_lines": [],
                "summary": {"lines_count": 0},
                "disclaimer": "test",
            },
            "extracted_permits": [],
            "permits_registry_check": [],
            "copilot_batch": {"bundles": [], "merged_context_for_ai": {"positions_count": 0}},
            "ai_analyst": {"summary": "мок", "status": "OK"},
            "disclaimer_ved_intel": "disk",
            "document_id": "test-doc-id",
        }

        r = self.client.post(
            "/api/documents/ved-intelligent-analyze",
            files={"document": ("pack.xlsx", io.BytesIO(b"x"), "application/octet-stream")},
            data={
                "country": "CN",
                "freight_total_rub": "0",
                "extract_permits": "false",
                "verify_fsa": "false",
                "skip_registry_verify": "true",
                "use_ai_declaration": "true",
                "persist": "false",
                "run_payment": "false",
            },
        )
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body.get("ved_intel_status"), "OK")
        self.assertEqual(body.get("comparison_mode"), "invoice_only")
        self.assertIn("ai_analyst", body)
        mock_core.assert_awaited_once()


@unittest.skipUnless(_OK, "нужен полный стек")
class VedIntelScopePropagationTests(unittest.IsolatedAsyncioTestCase):
    async def test_invoice_manufacturer_reaches_copilot_batch(self):
        draft = {
            "status": "OK",
            "declaration_lines": [
                {
                    "line": 1,
                    "commercial_description": "Прокат горячекатаный",
                    "hs_code": "7208100000",
                    "quantity": 2,
                }
            ],
        }
        batch_result = {
            "bundles": [],
            "merged_context_for_ai": {"positions": [], "positions_count": 0},
        }
        with (
            patch(
                "app.services.ved_intel_service.build_declaration_draft",
                new=AsyncMock(return_value=draft),
            ),
            patch(
                "app.services.ved_intel_service.run_copilot_batch",
                new=AsyncMock(return_value=batch_result),
            ) as run_batch,
            patch(
                "app.services.ved_intel_service.analyze_copilot_bundle",
                new=AsyncMock(return_value={"status": "OK"}),
            ),
        ):
            await run_ved_intel_pipeline(
                invoice_data={
                    "items": [
                        {
                            "manufacturer_exporter": "Alpha Steel Co",
                            "total_price": 100_000,
                        }
                    ]
                },
                packing_data=None,
                has_packing=False,
                validation_snapshot={},
                country="CN",
                hs_code_hint="",
                use_ai_declaration=True,
                extract_permits=False,
                verify_fsa=False,
                skip_registry=True,
                run_payment=True,
                freight_total_rub=0,
                prefer_client_id=None,
            )

        item = run_batch.await_args.args[0][0]
        self.assertEqual(item["manufacturer"], "Alpha Steel Co")
        self.assertEqual(item["description"], "Прокат горячекатаный")
        self.assertEqual(item["country"], "CN")


if __name__ == "__main__":
    unittest.main()
