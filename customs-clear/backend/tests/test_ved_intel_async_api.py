"""POST /api/documents/ved-intelligent-analyze/async + GET ved-intel-jobs/{id}."""
from __future__ import annotations

import importlib.util
import io
import unittest
from unittest.mock import AsyncMock, patch

try:
    from fastapi.testclient import TestClient
    from app.main import app
    from app.services.normative_store import init_db

    _OK = True
except ImportError:
    _OK = False


@unittest.skipUnless(_OK, "нужен полный стек")
class VedIntelAsyncApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        cls.client = TestClient(app)
        from tests.support_auth import login_declarant

        login_declarant(cls.client)

    @patch("app.services.ved_intel_jobs.run_ved_intel_analyze_core", new_callable=AsyncMock)
    def test_async_job_returns_result_on_poll(self, mock_core):
        mock_core.return_value = {
            "status": "OK",
            "comparison_mode": "invoice_only",
            "document_id": "async-doc-1",
            "ved_intel_status": "OK",
            "items": [],
            "checks": [],
            "summary": {"errors": 0, "warnings": 0, "passed": 1},
        }
        r = self.client.post(
            "/api/documents/ved-intelligent-analyze/async",
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
        self.assertEqual(body.get("status"), "accepted")
        job_id = body.get("job_id")
        self.assertTrue(job_id)
        jr = self.client.get(f"/api/documents/ved-intel-jobs/{job_id}")
        self.assertEqual(jr.status_code, 200, jr.text)
        st = jr.json()
        self.assertEqual(st.get("status"), "done")
        self.assertIn("result", st)
        self.assertEqual(st["result"].get("ved_intel_status"), "OK")
        mock_core.assert_awaited_once()

    def test_ved_intel_job_not_found(self):
        r = self.client.get("/api/documents/ved-intel-jobs/ffffffffffffffffffffffffffffffff")
        self.assertEqual(r.status_code, 404)


if __name__ == "__main__":
    unittest.main()
