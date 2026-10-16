"""API истории решений ассистента."""
from __future__ import annotations

import importlib.util
import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.services.decision_history as decision_history


BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = BACKEND_ROOT / "customs.db"
PINNED_CATALOGUE = BACKEND_ROOT / "customs.db.backup_before_pdf_import"


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
def _isolated_assistant_decisions_database(tmp_path_factory: pytest.TempPathFactory):
    """Exercise the decisions API without reading or creating ambient SQLite."""
    if importlib.util.find_spec("fastapi") is None:
        yield
        return

    protected_hashes = _protected_fingerprints()
    temp_dir = tmp_path_factory.mktemp("assistant-decisions")
    database = temp_dir / "assistant-decisions.db"
    patches = pytest.MonkeyPatch()
    patches.setenv("DATABASE_URL", f"sqlite:///{database}")
    patches.delenv("TNVED_SOURCE_DB", raising=False)
    bootstrap = subprocess.run(
        [
            sys.executable,
            "-c",
            "from app.services.normative_store import init_db; init_db()",
        ],
        cwd=BACKEND_ROOT,
        env=os.environ.copy(),
        text=True,
        capture_output=True,
        check=False,
    )
    assert bootstrap.returncode == 0, bootstrap.stdout + bootstrap.stderr
    assert _protected_fingerprints() == protected_hashes

    from app import db as app_db, main as app_main

    assert _protected_fingerprints() == protected_hashes
    original_session = app_db.SessionLocal
    original_engine = app_db.engine
    engine = create_engine(
        f"sqlite:///{database}",
        connect_args={"check_same_thread": False},
    )
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    for module_name, module in tuple(sys.modules.items()):
        if module is None or not (module_name == "app" or module_name.startswith("app.")):
            continue
        if getattr(module, "SessionLocal", None) is original_session:
            patches.setattr(module, "SessionLocal", factory)
        if getattr(module, "engine", None) is original_engine:
            patches.setattr(module, "engine", engine)

    patches.setattr(app_main, "init_db", lambda: None)

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


@unittest.skipUnless(importlib.util.find_spec("fastapi"), "fastapi")
class AssistantDecisionsApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app.services.normative_store import init_db

        init_db()
        from fastapi.testclient import TestClient
        from app.main import app
        from tests.support_auth import login_declarant

        cls.client = TestClient(app)
        login_declarant(cls.client)

    def test_log_and_recent(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "decisions.jsonl"
            with patch.object(decision_history, "_PATH", p):
                r = self.client.post(
                    "/api/assistant/decisions/log",
                    json={
                        "description": "чайник",
                        "suggested_hs": "8516108008",
                        "confirmed_hs": "8516108008",
                        "source": "test",
                        "notes": "ok",
                    },
                )
                self.assertEqual(r.status_code, 200, r.text)
                self.assertTrue(p.is_file())
                r2 = self.client.get("/api/assistant/decisions/recent?limit=5")
                self.assertEqual(r2.status_code, 200)
                body = r2.json()
                self.assertEqual(body["status"], "OK")
                self.assertTrue(len(body["items"]) >= 1)
                self.assertEqual(body["items"][-1].get("confirmed_hs"), "8516108008")

    def test_log_requires_confirmed_hs(self):
        r = self.client.post(
            "/api/assistant/decisions/log",
            json={"description": "x", "suggested_hs": "", "confirmed_hs": "  "},
        )
        self.assertEqual(r.status_code, 400)

    def test_similar_endpoint(self):
        r = self.client.get("/api/assistant/decisions/similar", params={"q": "абв", "limit": 3})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json().get("status"), "OK")
        self.assertIn("items", r.json())

    def test_export_denied_when_admin_token_not_configured(self):
        with patch.dict(os.environ, {"ADMIN_API_TOKEN": ""}):
            r = self.client.get("/api/assistant/decisions/export", params={"format": "json"})
        self.assertEqual(r.status_code, 401)

    def test_export_requires_admin_when_set(self):
        with patch.dict(os.environ, {"ADMIN_API_TOKEN": "test-admin-secret"}):
            r = self.client.get("/api/assistant/decisions/export")
            self.assertEqual(r.status_code, 401)
            r2 = self.client.get(
                "/api/assistant/decisions/export",
                headers={"X-Admin-Token": "test-admin-secret"},
            )
            self.assertEqual(r2.status_code, 200)


if __name__ == "__main__":
    unittest.main()
