"""Импорт нормативного пакета и API ТН ВЭД."""
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.services.normative_bundle import import_normative_bundle_dict
from app.services.normative_store import find_tnved_entry, init_db
from app.services.payment_engine import compute_payments


class NormativeBundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def test_import_bundle_dict(self):
        res = import_normative_bundle_dict(
            {
                "format": "customs_clear_normative_bundle",
                "revision": "test-b1",
                "tnved": [
                    {
                        "hs_code": "8888880000",
                        "parent_hs": "",
                        "level": 10,
                        "title": "Тестовая позиция",
                        "description": "Описание",
                        "chapter": "88",
                    }
                ],
                "rates": [
                    {
                        "hs_code": "8888880000",
                        "hs_prefix": "8888",
                        "duty_rate": 7.5,
                        "vat_import_rate": 22,
                    }
                ],
                "notes": [
                    {
                        "scope_type": "prefix",
                        "scope_value": "8888",
                        "category": "ett",
                        "title": "ЕТТ",
                        "body": "Тест примечания",
                    }
                ],
            },
            filename="unit.json",
        )
        self.assertEqual(res["status"], "OK")
        self.assertGreaterEqual(res["imported"]["tnved"], 1)
        ent = find_tnved_entry("8888880000")
        self.assertIsNotNone(ent)
        self.assertIn("Тестовая", ent.title or "")

    def test_compute_includes_tnved_context(self):
        out = compute_payments({"hs_code": "8509400000", "customs_value": 100000})
        self.assertEqual(out["status"], "OK")
        self.assertIn("tnved_context", out)
        self.assertIn("notes", out["tnved_context"])

    def test_tnved_api_search(self):
        client = TestClient(app)
        r = client.get("/api/tnved/search?q=850940")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data.get("status"), "OK")
        self.assertIsInstance(data.get("results"), list)


_EXAMPLE = Path(__file__).resolve().parent.parent / "data" / "normative_bundle.example.json"


class ExampleBundleFileTests(unittest.TestCase):
    """Проверка, что репозиторный example.json валиден для импорта."""

    @classmethod
    def setUpClass(cls):
        init_db()

    def test_example_file_imports(self):
        if not _EXAMPLE.exists():
            self.skipTest("example bundle missing")
        raw = _EXAMPLE.read_bytes()
        from app.services.normative_bundle import import_normative_bundle_bytes

        res = import_normative_bundle_bytes(raw, filename="normative_bundle.example.json")
        self.assertEqual(res["status"], "OK")


if __name__ == "__main__":
    unittest.main()
