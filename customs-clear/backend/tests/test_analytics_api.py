"""Сводная аналитика GET /api/analytics/overview."""
import hashlib
import importlib.util
import os
import subprocess
import sys
import unittest
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

try:
    from fastapi.testclient import TestClient
    from app import db as app_db, main as app_main
    from app.main import app
    from app.services.normative_store import init_db

    _OK = True
except ImportError:
    _OK = False


BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = BACKEND_ROOT / "customs.db"
PINNED_CATALOGUE = BACKEND_ROOT / "customs.db.backup_before_pdf_import"
TEST_ADMIN_TOKEN = "test-analytics-admin-token"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _protected_fingerprints() -> dict[Path, str | None]:
    paths = {
        candidate
        for path in (DEFAULT_DATABASE, PINNED_CATALOGUE)
        for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm"))
    }
    return {
        path: _sha256(path) if path.is_file() else None
        for path in paths
    }


@pytest.fixture(scope="module", autouse=True)
def _isolated_analytics_database(tmp_path_factory: pytest.TempPathFactory):
    """Exercise the analytics endpoint without reading or creating ambient SQLite."""
    if not _OK:
        yield
        return

    protected_hashes = _protected_fingerprints()
    original_session = app_db.SessionLocal
    original_engine = app_db.engine
    temp_dir = tmp_path_factory.mktemp("analytics-api")
    database = temp_dir / "analytics.db"
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{database}"
    env.pop("TNVED_SOURCE_DB", None)
    bootstrap = subprocess.run(
        [
            sys.executable,
            "-c",
            "from app.services.normative_store import init_db; init_db()",
        ],
        cwd=BACKEND_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert bootstrap.returncode == 0, bootstrap.stdout + bootstrap.stderr
    assert _protected_fingerprints() == protected_hashes

    engine = create_engine(
        f"sqlite:///{database}",
        connect_args={"check_same_thread": False},
    )
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    patches = pytest.MonkeyPatch()

    for module_name, module in tuple(sys.modules.items()):
        if module is None or not (module_name == "app" or module_name.startswith("app.")):
            continue
        if getattr(module, "SessionLocal", None) is original_session:
            patches.setattr(module, "SessionLocal", factory)
        if getattr(module, "engine", None) is original_engine:
            patches.setattr(module, "engine", engine)

    patches.setattr(sys.modules[__name__], "init_db", lambda: None)
    patches.setattr(app_main, "init_db", lambda: None)
    patches.setenv("ADMIN_API_TOKEN", TEST_ADMIN_TOKEN)

    try:
        yield
    finally:
        patches.undo()
        engine.dispose()
        for path in (
            database,
            Path(f"{database}-wal"),
            Path(f"{database}-shm"),
        ):
            if path.exists():
                path.unlink()
        assert _protected_fingerprints() == protected_hashes


@unittest.skipUnless(_OK, "нужен полный стек")
class AnalyticsOverviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        cls.client = TestClient(app)
        cls.client.headers["X-Admin-Token"] = TEST_ADMIN_TOKEN

    def test_overview_requires_admin_token(self):
        r = self.client.get("/api/analytics/overview", headers={"X-Admin-Token": ""})
        self.assertEqual(r.status_code, 401, r.text)
        self.assertIn("invalid or missing X-Admin-Token", str(r.json().get("detail")))

    def test_overview_rejects_invalid_admin_token(self):
        r = self.client.get(
            "/api/analytics/overview",
            headers={"X-Admin-Token": "invalid-test-token"},
        )
        self.assertEqual(r.status_code, 401, r.text)
        self.assertIn("invalid or missing X-Admin-Token", str(r.json().get("detail")))

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
