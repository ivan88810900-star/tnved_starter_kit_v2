"""Batch copilot API."""
from __future__ import annotations

import importlib.util
import hashlib
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


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
def _isolated_assistant_batch_database(tmp_path_factory: pytest.TempPathFactory):
    """Exercise the batch API without reading or creating ambient SQLite."""
    if importlib.util.find_spec("fastapi") is None:
        yield
        return

    protected_hashes = _protected_fingerprints()
    temp_dir = tmp_path_factory.mktemp("assistant-batch")
    database = temp_dir / "assistant-batch.db"
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
        for module_name, module in tuple(sys.modules.items()):
            if module is None or not (module_name == "app" or module_name.startswith("app.")):
                continue
            if getattr(module, "SessionLocal", None) is factory:
                setattr(module, "SessionLocal", original_session)
            if getattr(module, "engine", None) is engine:
                setattr(module, "engine", original_engine)
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
class CopilotBatchApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app.services.normative_store import init_db

        init_db()
        from fastapi.testclient import TestClient
        from app.main import app
        from tests.support_auth import login_declarant

        cls.client = TestClient(app)
        login_declarant(cls.client)

    @patch("app.api.assistant.analyze_copilot_bundle", new_callable=AsyncMock)
    def test_batch_two_positions(self, mock_ai):
        mock_ai.return_value = {"status": "OK", "summary": "ok", "risks": []}
        r = self.client.post(
            "/api/assistant/copilot/batch",
            json={
                "items": [
                    {
                        "description": "Пылесос",
                        "hs_code": "8509400000",
                        "country": "CN",
                        "customs_value": 100000,
                        "freight": 0,
                        "permits": [],
                    },
                    {
                        "description": "Чайник",
                        "hs_code": "8516108008",
                        "country": "CN",
                        "customs_value": 50000,
                        "permits": [],
                    },
                ],
                "run_registry_verify": False,
            },
        )
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(len(body["bundles"]), 2)
        self.assertIn("positions", body["context_for_ai"])


if __name__ == "__main__":
    unittest.main()
