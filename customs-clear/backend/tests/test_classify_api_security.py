"""Безопасность /api/classify: без клиентского api_key, только серверные ключи."""
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
def _isolated_classify_api_database(tmp_path_factory: pytest.TempPathFactory):
    """Exercise classify authorization without reading or creating ambient SQLite."""
    protected_hashes = _protected_fingerprints()
    temp_dir = tmp_path_factory.mktemp("classify-api-security")
    database = temp_dir / "classify-api-security.db"
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
class ClassifyApiSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_db()
        from fastapi.testclient import TestClient
        from app.main import app

        cls.client = TestClient(app)

    def test_classify_llm_path_503_when_no_server_keys_even_if_legacy_api_key_sent(self) -> None:
        keys = ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY")
        saved = {k: os.environ.pop(k, None) for k in keys}
        try:
            login_declarant(self.client)
            r = self.client.post(
                "/api/classify",
                json={
                    "description": "электрическая дрель bosch 500w",
                    "use_custom_classifier": False,
                    "fallback_to_llm": True,
                    "api_key": "sk-ant-client-supplied-must-not-be-used",
                },
            )
            self.assertEqual(r.status_code, 503, r.text)
            body = r.json()
            self.assertEqual(body.get("error_code"), "llm_not_configured")
            self.assertIn("GEMINI_API_KEY", body.get("note", ""))
        finally:
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v

    @patch("app.api.classify.classify_hs_code", new_callable=AsyncMock)
    def test_classify_invokes_classify_hs_code_without_api_key_kwarg(self, mock_cf: AsyncMock) -> None:
        mock_cf.return_value = {"status": "OK", "results": [{"hs_code": "8509400000"}]}
        login_declarant(self.client)
        r = self.client.post(
            "/api/classify",
            json={"description": "пылесос", "use_custom_classifier": False},
        )
        self.assertEqual(r.status_code, 200, r.text)
        mock_cf.assert_called_once()
        _args, kwargs = mock_cf.call_args
        self.assertNotIn("api_key", kwargs)

    @patch("app.api.classify.get_smart_classifier")
    def test_smart_classifier_manual_review_is_preserved_by_api(self, mock_get_classifier) -> None:
        from app.services.smart_classifier import ClassifyResult

        classifier = mock_get_classifier.return_value
        classifier.classify = AsyncMock(
            return_value=ClassifyResult(
                results=[{"hs_code": "8501529000", "confidence": 0.7, "recommended": False}],
                web_search_used=False,
                status="MANUAL_REVIEW",
                note="Поиск технических характеристик не дал подтверждённых данных.",
                extra={
                    "manual_review_required": True,
                    "web_search_attempted": True,
                    "web_search_status": "unavailable",
                },
            )
        )
        login_declarant(self.client)

        response = self.client.post(
            "/api/classify",
            json={
                "description": "двигатель",
                "article": "YL-90L-4",
                "manufacturer": "Dongfa",
                "use_smart_classifier": True,
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["status"], "MANUAL_REVIEW")
        self.assertTrue(body["manual_review_required"])
        self.assertEqual(body["web_search_status"], "unavailable")
        self.assertFalse(body["web_search_used"])
        self.assertFalse(body["results"][0]["recommended"])
        self.assertNotIn("web_context", body)


if __name__ == "__main__":
    unittest.main()
