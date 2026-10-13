"""Обязательная JWT/cookie-auth для дорогих и чувствительных API."""
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

from tests.support_auth import login_declarant

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
def _isolated_sensitive_endpoints_database(tmp_path_factory: pytest.TempPathFactory):
    """Exercise sensitive authorization without reading or creating ambient SQLite."""
    protected_hashes = _protected_fingerprints()
    temp_dir = tmp_path_factory.mktemp("sensitive-endpoints-auth")
    database = temp_dir / "sensitive-endpoints-auth.db"
    patches = pytest.MonkeyPatch()
    preloaded_app_modules = {
        module_name
        for module_name in sys.modules
        if module_name == "app" or module_name.startswith("app.")
    }
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

    test_module = sys.modules[__name__]
    patches.setattr(test_module, "init_db", lambda: None, raising=False)
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
        ):
            if path.exists():
                path.unlink()
        assert _protected_fingerprints() == protected_hashes


@unittest.skipUnless(importlib.util.find_spec("fastapi"), "fastapi")
class SensitiveEndpointsAuthTests(unittest.TestCase):
    """Отдельные TestClient: cookie сессии не должны протекать между анонимными и авторизованными кейсами."""

    @classmethod
    def setUpClass(cls) -> None:
        init_db()
        from fastapi.testclient import TestClient
        from app.main import app

        cls.anon = TestClient(app)
        cls.auth = TestClient(app)
        login_declarant(cls.auth)

    def test_classify_unauthorized_without_session(self) -> None:
        r = self.anon.post(
            "/api/classify",
            json={"description": "тест", "use_custom_classifier": False},
        )
        self.assertEqual(r.status_code, 401, r.text)
        d = r.json().get("detail")
        if isinstance(d, dict):
            self.assertEqual(d.get("error_code"), "authentication_required")
        else:
            self.fail("ожидался detail-объект с error_code")

    def test_documents_v1_analyze_unauthorized(self) -> None:
        r = self.anon.post(
            "/api/v1/documents/analyze",
            files={"file": ("t.csv", b"a;b\n1;2", "text/csv")},
        )
        self.assertEqual(r.status_code, 401, r.text)

    def test_assistant_copilot_unauthorized(self) -> None:
        r = self.anon.post(
            "/api/assistant/copilot",
            json={
                "description": "x",
                "hs_code": "8509400000",
                "run_ai_classification": False,
                "run_payment": False,
                "run_registry_verify": False,
            },
        )
        self.assertEqual(r.status_code, 401, r.text)

    def test_ai_ask_unauthorized(self) -> None:
        r = self.anon.post("/api/ai/ask", json={"question": "что такое ТН ВЭД?", "code": "", "notes": ""})
        self.assertEqual(r.status_code, 401, r.text)

    @patch("app.api.assistant.analyze_copilot_bundle", new_callable=AsyncMock)
    def test_assistant_copilot_ok_with_session(self, mock_ai: AsyncMock) -> None:
        mock_ai.return_value = {"status": "OK", "summary": "ok", "risks": []}
        r = self.auth.post(
            "/api/assistant/copilot",
            json={
                "description": "Бытовой пылесос",
                "hs_code": "8509400000",
                "country": "CN",
                "customs_value": 100000,
                "freight": 5000,
                "permits": [],
                "run_ai_classification": False,
                "run_payment": True,
                "run_registry_verify": False,
            },
        )
        self.assertEqual(r.status_code, 200, r.text)

    def test_admin_sync_status_requires_admin_header_even_when_logged_in(self) -> None:
        with patch.dict(os.environ, {"ADMIN_API_TOKEN": "sync-test-secret"}):
            r = self.auth.get("/api/v1/admin/sync/status")
            self.assertEqual(r.status_code, 401, r.text)
            ok = self.auth.get(
                "/api/v1/admin/sync/status",
                headers={"X-Admin-Token": "sync-test-secret"},
            )
            self.assertEqual(ok.status_code, 200, ok.text)


if __name__ == "__main__":
    unittest.main()
