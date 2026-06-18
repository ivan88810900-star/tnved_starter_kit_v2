"""Интеграционные тесты API.

Запускаются через TestClient FastAPI без запуска реального сервера.
Охватывают: /api/health, /api/calculator/compute, /api/compliance/check,
/api/non_tariff/check, /api/sources/status.

Требует: loguru (pip install loguru).
"""
import os
import unittest
from unittest.mock import patch

try:
    from fastapi.testclient import TestClient
    from app.main import app
    from app.services.normative_store import init_db
    _INTEGRATION_AVAILABLE = True
    _IMPORT_ERROR = ""
except ImportError as e:
    _INTEGRATION_AVAILABLE = False
    _IMPORT_ERROR = str(e)


@unittest.skipIf(not _INTEGRATION_AVAILABLE, f"Integration tests require full deps: {_IMPORT_ERROR}")
class ApiIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        cls.client = TestClient(app)
        from tests.support_auth import login_declarant

        login_declarant(cls.client)

    # ------------------------------------------------------------------ health
    def test_health(self):
        r = self.client.get("/api/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "OK")

    def test_health_ready(self):
        r = self.client.get("/api/health/ready")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ready")
        self.assertTrue(body.get("database"))
        self.assertIn("assistant_llm_configured", body)

    def test_pipeline_health_endpoint_returns_ok(self):
        r = self.client.get("/api/health/pipeline")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "ok")

    def test_pipeline_health_has_required_fields(self):
        r = self.client.get("/api/health/pipeline")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["pipeline"], "claude-autonomous")
        self.assertEqual(body["version"], "1.0")
        self.assertIn("timestamp", body)
        self.assertRegex(body["timestamp"], r"\d{4}-\d{2}-\d{2}T")

    # ------------------------------------------------------------------ sources
    def test_sources_status(self):
        r = self.client.get("/api/sources/status")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("sources", body)
        self.assertIsInstance(body["sources"], list)
        codes = [s["source_code"] for s in body["sources"]]
        self.assertIn("EEC_ETT", codes)
        self.assertIn("NDS_NK164", codes)
        self.assertIn("TRADE_DEFENSE", codes)
        self.assertIn("stats", body)
        self.assertIn("hs_rates_count", body["stats"])
        self.assertIn("hints", body)
        self.assertIsInstance(body["hints"], list)

    def test_search_hs_enriched_has_title_field(self):
        r = self.client.get("/api/search/hs?q=8509&limit=5")
        self.assertEqual(r.status_code, 200)
        items = r.json().get("items") or []
        self.assertTrue(len(items) >= 1)
        self.assertIn("title", items[0])

    def test_sources_log(self):
        r = self.client.get("/api/sources/log")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("log", body)

    # ------------------------------------------------------------------ calculator
    def test_calculator_basic(self):
        r = self.client.post("/api/calculator/compute", json={
            "hs_code": "8509400000",
            "customs_value": 500_000,
            "freight": 45_000,
        })
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "OK")
        self.assertIn("breakdown", body)
        self.assertIn("data_quality", body)
        self.assertTrue("sources" in body or "documents" in body)
        self.assertGreater(body["breakdown"]["total_payable"], 0)

    def test_calculator_vat_reason_present(self):
        r = self.client.post("/api/calculator/compute", json={
            "hs_code": "0201300000",
            "customs_value": 100_000,
            "freight": 10_000,
        })
        self.assertEqual(r.status_code, 200)
        body = r.json()
        bd = body.get("breakdown") or {}
        self.assertGreater(bd.get("total_payable", 0), 0)
        if "vat_rate" in bd:
            self.assertEqual(bd["vat_rate"], 10.0)
        if "vat_reason" in bd:
            self.assertIsInstance(bd["vat_reason"], str)

    def test_calculator_antidumping_manual_review(self):
        r = self.client.post("/api/calculator/compute", json={
            "hs_code": "7214990000",
            "customs_value": 100_000,
            "freight": 0,
        })
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["data_quality"]["antidumping_status"], "manual_review")

    def test_calculator_compare(self):
        r = self.client.post(
            "/api/calculator/compare",
            json={
                "shared": {"customs_value": 400000, "freight": 40000, "country": "CN"},
                "scenarios": [
                    {"hs_code": "8509400000", "label": "A"},
                    {"hs_code": "8516108008", "label": "B"},
                ],
            },
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "OK")
        self.assertEqual(len(body["scenarios"]), 2)

    def test_calculator_invalid_value(self):
        r = self.client.post("/api/calculator/compute", json={
            "hs_code": "8509400000",
            "customs_value": 0,
        })
        self.assertEqual(r.status_code, 400)

    # ------------------------------------------------------------------ compliance
    def test_compliance_save_history(self):
        r = self.client.post(
            "/api/compliance/check",
            json={
                "items": [{
                    "hs_code": "8509400000",
                    "description": "Пылесос",
                    "country": "CN",
                    "customs_value": 100_000,
                    "freight": 10_000,
                    "permits": [],
                }],
                "save_history": True,
                "user_ref": "compliance_integration",
            },
        )
        self.assertEqual(r.status_code, 200)
        h = self.client.get("/api/calculator/history?limit=30&user_ref=compliance_integration")
        self.assertEqual(h.status_code, 200)
        kinds = [x.get("kind") for x in (h.json().get("items") or [])]
        self.assertIn("compliance", kinds)

    def test_compliance_check_single_item(self):
        r = self.client.post("/api/compliance/check", json={
            "items": [{
                "hs_code": "8509400000",
                "description": "Пылесос бытовой",
                "country": "CN",
                "customs_value": 500_000,
                "freight": 45_000,
                "permits": [],
            }]
        })
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("status", body)
        self.assertIn("items", body)
        self.assertEqual(len(body["items"]), 1)
        item = body["items"][0]
        self.assertIn("payment", item)
        self.assertIn("non_tariff", item)
        self.assertIn("documents", item)
        self.assertIn("risks", item)
        self.assertIn("data_freshness", item["non_tariff"])

    def test_compliance_check_meta(self):
        r = self.client.post("/api/compliance/check", json={
            "items": [{
                "hs_code": "8509400000",
                "description": "Тест",
                "country": "CN",
                "customs_value": 100_000,
                "freight": 0,
            }]
        })
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("meta", body)
        meta = body["meta"]
        self.assertIn("generated_at", meta)
        self.assertIn("data_confidence", meta)
        self.assertIn("any_stale_source", meta)
        self.assertIn("any_manual_review", meta)

    def test_compliance_empty_list(self):
        r = self.client.post("/api/compliance/check", json={"items": []})
        self.assertEqual(r.status_code, 400)

    def test_compliance_antidumping_flagged_in_meta(self):
        """Антидемпинг без страны → any_manual_review = True в meta."""
        r = self.client.post("/api/compliance/check", json={
            "items": [{
                "hs_code": "7214990000",
                "description": "Арматура стальная",
                "customs_value": 100_000,
                "freight": 0,
            }]
        })
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["meta"]["any_manual_review"])

    def test_compliance_risks_in_item(self):
        """Арматура без страны → risks содержит предупреждение об антидемпинге."""
        r = self.client.post("/api/compliance/check", json={
            "items": [{
                "hs_code": "7214990000",
                "description": "Арматура стальная",
                "customs_value": 100_000,
                "freight": 0,
            }]
        })
        self.assertEqual(r.status_code, 200)
        body = r.json()
        item = body["items"][0]
        self.assertIn("risks", item)
        self.assertGreater(len(item["risks"]), 0)
        risks_text = " ".join(item["risks"])
        self.assertTrue("ручн" in risks_text and "проверк" in risks_text, msg=f"Ожидалось предупреждение о ручной проверке, получено: {risks_text}")

    # ------------------------------------------------------------------ non_tariff
    def test_non_tariff_check(self):
        r = self.client.post("/api/non_tariff/check", json={
            "items": [{
                "hs_code": "8509400000",
                "description": "Пылесос",
                "country": "CN",
                "permits": [],
            }]
        })
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("status", body)
        self.assertIn("items", body)

    def test_non_tariff_missing_permits(self):
        """Код электроники без разрешительных документов → ERROR."""
        r = self.client.post("/api/non_tariff/check", json={
            "items": [{
                "hs_code": "8509400000",
                "description": "Пылесос",
                "permits": [],
            }]
        })
        self.assertEqual(r.status_code, 200)
        body = r.json()
        item = body["items"][0]
        # Should have required permits defined (СС and/or ДС for electronics)
        self.assertGreater(len(item["required_permit_types"]), 0)
        self.assertEqual(item["status"], "ERROR")

    # ------------------------------------------------------------------ tnved / ingestion / calculator history
    def test_tnved_stats_has_pipeline_counts(self):
        r = self.client.get("/api/tnved/stats")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        for key in (
            "ingested_documents_count",
            "tnved_embeddings_count",
            "customs_calculation_history_count",
        ):
            self.assertIn(key, body)

    def test_tnved_embeddings_status(self):
        r = self.client.get("/api/tnved/embeddings/status")
        self.assertEqual(r.status_code, 200)
        b = r.json()
        self.assertIn("tnved_entries", b)
        self.assertIn("openai_configured", b)

    def test_documents_ingested_list(self):
        r = self.client.get("/api/documents/ingested?limit=5")
        self.assertEqual(r.status_code, 200)
        b = r.json()
        self.assertEqual(b.get("status"), "OK")
        self.assertIn("items", b)

    def test_calculator_history_after_compute(self):
        r = self.client.post(
            "/api/calculator/compute",
            json={
                "hs_code": "8509400000",
                "customs_value": 50_000,
                "freight": 5_000,
                "save_history": True,
                "user_ref": "integration_test",
            },
        )
        self.assertEqual(r.status_code, 200)
        h = self.client.get("/api/calculator/history?limit=20&user_ref=integration_test")
        self.assertEqual(h.status_code, 200)
        items = h.json().get("items") or []
        self.assertTrue(len(items) >= 1)
        cid = items[0]["id"]
        one = self.client.get(f"/api/calculator/history/{cid}")
        self.assertEqual(one.status_code, 200)
        self.assertIn("input_payload", one.json())

    def test_calculator_history_summary_and_kind_filter(self):
        self.client.post(
            "/api/compliance/check",
            json={
                "items": [{
                    "hs_code": "8509400000",
                    "description": "тест фильтра",
                    "country": "CN",
                    "customs_value": 80_000,
                    "freight": 8_000,
                    "permits": [],
                }],
                "save_history": True,
                "user_ref": "kind_filter_user",
            },
        )
        s = self.client.get("/api/calculator/history/summary?user_ref=kind_filter_user")
        self.assertEqual(s.status_code, 200)
        body = s.json()
        self.assertIn("by_kind", body)
        self.assertGreaterEqual(body["by_kind"].get("compliance", 0), 1)
        only_c = self.client.get("/api/calculator/history?user_ref=kind_filter_user&kind=compliance&limit=50")
        self.assertEqual(only_c.status_code, 200)
        for row in only_c.json().get("items") or []:
            self.assertEqual(row.get("kind"), "compliance")

    def test_history_export_csv(self):
        with patch.dict(os.environ, {"ADMIN_API_TOKEN": "secret-export-token"}):
            r = self.client.get(
                "/api/calculator/history/export?format=csv&limit=5",
                headers={"X-Admin-Token": "secret-export-token"},
            )
        self.assertEqual(r.status_code, 200)
        ct = r.headers.get("content-type", "")
        self.assertIn("text/csv", ct)
        self.assertIn(b"id", r.content[:200].lower())

    def test_history_export_json(self):
        with patch.dict(os.environ, {"ADMIN_API_TOKEN": "secret-export-token"}):
            r = self.client.get(
                "/api/calculator/history/export?format=json&limit=3",
                headers={"X-Admin-Token": "secret-export-token"},
            )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("items", body)

    def test_history_export_requires_admin_when_token_set(self):
        with patch.dict(os.environ, {"ADMIN_API_TOKEN": "secret-export-token"}):
            r = self.client.get("/api/calculator/history/export?format=csv")
            self.assertEqual(r.status_code, 401)
            ok = self.client.get(
                "/api/calculator/history/export?format=csv",
                headers={"X-Admin-Token": "secret-export-token"},
            )
            self.assertEqual(ok.status_code, 200)

    def test_documents_ingested_calculations_not_found(self):
        r = self.client.get(
            "/api/documents/ingested/00000000-0000-0000-0000-000000000001/calculations"
        )
        self.assertEqual(r.status_code, 404)

    def test_permits_verify_jobs_list(self):
        r = self.client.get("/api/permits/verify/jobs")
        self.assertEqual(r.status_code, 200)
        b = r.json()
        self.assertIn("items", b)
        self.assertIsInstance(b["items"], list)


if __name__ == "__main__":
    unittest.main()
