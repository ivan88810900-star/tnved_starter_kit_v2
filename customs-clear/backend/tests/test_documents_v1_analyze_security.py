"""P0: разбор инвойсов без клиентского api_key, только env сервера."""
from __future__ import annotations

import asyncio
import importlib.util
import os
import unittest

from app.services.normative_store import init_db
from tests.support_auth import login_declarant


class AnalyzeInvoiceFileEnvTests(unittest.TestCase):
    def test_returns_llm_not_configured_without_server_keys(self) -> None:
        import app.services.document_invoice_analyze as dia

        keys = ("GEMINI_API_KEY", "GOOGLE_API_KEY")
        saved = {k: os.environ.pop(k, None) for k in keys}
        try:
            out = asyncio.run(
                dia.analyze_invoice_file(
                    data=b"a;b\n1;2",
                    filename="t.csv",
                    content_type="text/csv",
                )
            )
            self.assertEqual(out.get("status"), "ERROR")
            self.assertEqual(out.get("error_code"), "llm_not_configured")
            self.assertIn("GEMINI_API_KEY", out.get("error", ""))
        finally:
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v


@unittest.skipUnless(importlib.util.find_spec("fastapi"), "fastapi")
class DocumentsV1AnalyzeHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_db()
        from fastapi.testclient import TestClient
        from app.main import app

        cls.client = TestClient(app)

    def test_v1_analyze_503_without_server_keys(self) -> None:
        keys = ("GEMINI_API_KEY", "GOOGLE_API_KEY")
        saved = {k: os.environ.pop(k, None) for k in keys}
        try:
            login_declarant(self.client)
            r = self.client.post(
                "/api/v1/documents/analyze",
                files={"file": ("t.csv", b"a;b\n1;2", "text/csv")},
                data={"api_key": "client-key-must-not-be-used"},
            )
            self.assertEqual(r.status_code, 503, r.text)
            body = r.json()
            self.assertEqual(body.get("error_code"), "llm_not_configured")
        finally:
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v


if __name__ == "__main__":
    unittest.main()
