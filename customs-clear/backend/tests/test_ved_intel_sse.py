"""SSE GET /api/documents/ved-intel-jobs/{id}/events."""
import unittest

try:
    from fastapi.testclient import TestClient
    from app.main import app
    from app.services.normative_store import init_db

    _OK = True
except ImportError:
    _OK = False


@unittest.skipUnless(_OK, "нужен полный стек")
class VedIntelSseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        cls.client = TestClient(app)
        from tests.support_auth import login_declarant

        login_declarant(cls.client)

    def test_events_unknown_job_404(self):
        r = self.client.get(
            "/api/documents/ved-intel-jobs/00000000-0000-0000-0000-000000000000/events",
        )
        self.assertEqual(r.status_code, 404, r.text)


if __name__ == "__main__":
    unittest.main()
