"""Агрегация кодов ТН ВЭД из журнала и hints API."""
from __future__ import annotations

import hashlib
import importlib.util
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
DEFAULT_PREVIEW_REVISION = BACKEND_ROOT / "data" / "tnved_preview_cache_revision.txt"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _protected_fingerprints() -> dict[Path, str | None]:
    paths = {
        candidate
        for path in (DEFAULT_DATABASE, PINNED_CATALOGUE, DEFAULT_PREVIEW_REVISION)
        for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm"))
    }
    return {
        path: _sha256(path) if path.is_file() else None
        for path in paths
    }


@pytest.fixture(scope="module", autouse=True)
def _isolated_decision_suggest_hs_database(tmp_path_factory: pytest.TempPathFactory):
    """Exercise decision hints without reading or creating ambient SQLite."""
    if importlib.util.find_spec("fastapi") is None:
        yield
        return

    protected_hashes = _protected_fingerprints()
    temp_dir = tmp_path_factory.mktemp("decision-suggest-hs")
    database = temp_dir / "decision-suggest-hs.db"
    preview_revision = temp_dir / "tnved-preview-cache-revision.txt"
    patches = pytest.MonkeyPatch()
    preloaded_app_modules = {
        module_name
        for module_name in sys.modules
        if module_name == "app" or module_name.startswith("app.")
    }
    patches.setenv("DATABASE_URL", f"sqlite:///{database}")
    patches.delenv("TNVED_SOURCE_DB", raising=False)
    patches.setenv("TNVED_PREVIEW_CACHE_REVISION_FILE", str(preview_revision))
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
    from app.services import normative_store

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

    patches.setattr(normative_store, "init_db", lambda: None)
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
        for module_name in tuple(sys.modules):
            if (
                module_name not in preloaded_app_modules
                and (module_name == "app" or module_name.startswith("app."))
            ):
                sys.modules.pop(module_name, None)
        engine.dispose()
        for path in (
            database,
            Path(f"{database}-wal"),
            Path(f"{database}-shm"),
            preview_revision,
        ):
            if path.exists():
                path.unlink()
        assert _protected_fingerprints() == protected_hashes


class SuggestHsCodesTests(unittest.TestCase):
    def test_aggregates_same_hs(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "j.jsonl"
            rows = [
                {"description": "пылесос бытовой вертикальный", "confirmed_hs": "8509400000"},
                {"description": "пылесос для сухой уборки дома", "confirmed_hs": "8509400000"},
                {"description": "арматура стальная", "confirmed_hs": "7214200000"},
            ]
            p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
            with patch.object(dh, "_PATH", p):
                out = dh.suggest_hs_codes("пылесос бытовой электрический", limit=5)
                self.assertTrue(len(out) >= 1)
                self.assertEqual(out[0]["hs_code"], "8509400000")
                self.assertGreaterEqual(out[0]["count"], 1)

    def test_journal_hints_non_empty(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "j.jsonl"
            p.write_text(
                json.dumps({"description": "чайник электрический 2л", "confirmed_hs": "8516108008"}),
                encoding="utf-8",
            )
            with patch.object(dh, "_PATH", p):
                block = dh.journal_hints_for_classifier("электрический чайник пластик")
                self.assertIn("8516108008", block)
                self.assertIn("журнала", block.lower())


@unittest.skipUnless(importlib.util.find_spec("fastapi"), "fastapi")
class HintsApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app.services.normative_store import init_db

        init_db()
        from fastapi.testclient import TestClient
        from app.main import app

        cls.client = TestClient(app)
        from tests.support_auth import login_declarant

        login_declarant(cls.client)

    def test_hints_endpoint(self):
        r = self.client.get(
            "/api/assistant/decisions/hints",
            params={"q": "товар таможня", "similar_limit": 2, "hs_limit": 3},
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "OK")
        self.assertIn("similar", body)
        self.assertIn("hs_suggestions", body)

    def test_suggest_hs_endpoint(self):
        r = self.client.get("/api/assistant/decisions/suggest-hs", params={"q": "импорт", "limit": 5})
        self.assertEqual(r.status_code, 200)
        self.assertIn("items", r.json())


if __name__ == "__main__":
    unittest.main()
