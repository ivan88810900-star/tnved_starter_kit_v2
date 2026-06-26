"""POST /api/documents/ved-report-pdf — генерация PDF без ИИ."""
from __future__ import annotations

import importlib.util
import unittest

try:
    from fastapi.testclient import TestClient
    from app.main import app
    from app.services.normative_store import init_db

    _OK = True
except ImportError:
    _OK = False


@unittest.skipUnless(_OK, "нужен полный стек")
class VedReportPdfApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        cls.client = TestClient(app)
        from tests.support_auth import login_declarant

        login_declarant(cls.client)

    def test_ved_report_pdf_returns_pdf_bytes(self):
        body = {
            "exported_at": "2025-01-01T00:00:00Z",
            "document_id": "abcdef12-0000-0000-0000-000000000000",
            "ved_intel_status": "OK",
            "status": "OK",
            "declaration_draft": {
                "declaration_lines": [
                    {
                        "line": 1,
                        "commercial_description": "Товар тест",
                        "hs_code": "1234567890",
                        "graf31_ru": "Графа 31",
                        "quantity": 2,
                        "unit": "шт",
                        "weight_gross_kg": 1.5,
                    }
                ]
            },
            "ai_analyst": {"summary": "Краткая сводка", "risks": ["Риск 1"], "next_steps": ["Шаг 1"]},
            "copilot_positions": [
                {"effective_hs_code": "1234567890", "non_tariff_status": "OK", "total_payable": 100}
            ],
            "summary": {"errors": 0, "warnings": 0, "passed": 1},
        }
        r = self.client.post("/api/documents/ved-report-pdf", json=body)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.headers.get("content-type", "").split(";")[0], "application/pdf")
        self.assertTrue(r.content.startswith(b"%PDF"), r.content[:20])


if __name__ == "__main__":
    unittest.main()
