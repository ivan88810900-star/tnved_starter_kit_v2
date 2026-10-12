"""Статистика журнала решений."""
from __future__ import annotations

import importlib.util
import hashlib
import json
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

import app.services.decision_history as dh


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
def _isolated_journal_stats_database(tmp_path_factory: pytest.TempPathFactory):
    """Exercise the stats endpoint without reading or creating ambient SQLite."""
    if importlib.util.find_spec("fastapi") is None:
        yield
        return

    protected_hashes = _protected_fingerprints()
    temp_dir = tmp_path_factory.mktemp("journal-stats")
    database = temp_dir / "journal-stats.db"
    patches = pytest.MonkeyPatch()
    patches.setenv("DATABASE_URL", f"sqlite:///{database}")
    patches.delenv("TNVED_SOURCE_DB", raising=False)
    env = os.environ.copy()
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


class ComputeJournalStatsTests(unittest.TestCase):
    def test_empty_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "empty.jsonl"
            p.write_text("", encoding="utf-8")
            with patch.object(dh, "_PATH", p):
                s = dh.compute_journal_stats()
            self.assertEqual(s["records_in_index"], 0)
            self.assertEqual(s["top_confirmed_hs"], [])

    def test_counts_top_hs(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "j.jsonl"
            lines = [
                {"description": "a", "confirmed_hs": "8509400000", "source": "ui", "client_id": "c1", "ts": "2025-01-01T00:00:00+00:00"},
                {"description": "b", "confirmed_hs": "8509400000", "source": "ui", "ts": "2025-01-02T00:00:00+00:00"},
                {"description": "c", "confirmed_hs": "8516108008", "source": "demo", "ts": "2025-01-03T00:00:00+00:00"},
            ]
            p.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in lines), encoding="utf-8")
            with patch.object(dh, "_PATH", p):
                s = dh.compute_journal_stats()
            self.assertEqual(s["records_in_index"], 3)
            self.assertEqual(s["unique_confirmed_hs_codes"], 2)
            self.assertEqual(s["unique_client_ids"], 1)
            self.assertEqual(s["top_confirmed_hs"][0]["hs_code"], "8509400000")
            self.assertEqual(s["top_confirmed_hs"][0]["count"], 2)


@unittest.skipUnless(importlib.util.find_spec("fastapi"), "fastapi")
class StatsApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app.services.normative_store import init_db

        init_db()
        from fastapi.testclient import TestClient
        from app.main import app

        cls.client = TestClient(app)
        from tests.support_auth import login_declarant

        login_declarant(cls.client)

    def test_stats_endpoint(self):
        r = self.client.get("/api/assistant/decisions/stats")
        self.assertEqual(r.status_code, 200)
        b = r.json()
        self.assertEqual(b.get("status"), "OK")
        self.assertIn("records_in_index", b)


if __name__ == "__main__":
    unittest.main()
