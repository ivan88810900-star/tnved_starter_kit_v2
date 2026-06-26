"""Сводная аналитика GET /api/analytics/overview."""
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
class AnalyticsOverviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        cls.client = TestClient(app)

    def test_overview_ok(self):
        r = self.client.get("/api/analytics/overview")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body.get("status"), "OK")
        for key in (
            "generated_at",
            "database_reachable",
            "integrated_stats",
            "normative_sync_summary",
            "normative_sources_preview",
            "normative_hints",
            "calculation_history_summary",
            "decisions_journal",
            "ai_configuration",
            "permits_metrics",
            "narrative_brief_ru",
            "redis_reachable",
        ):
            self.assertIn(key, body)
        self.assertIsInstance(body["narrative_brief_ru"], list)
        self.assertIn("hs_rates_count", body["integrated_stats"])


if __name__ == "__main__":
    unittest.main()
