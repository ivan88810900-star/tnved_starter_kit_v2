"""P0: разбор инвойсов без клиентского api_key, только env сервера."""
from __future__ import annotations

import asyncio
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
def _isolated_documents_analyze_database(tmp_path_factory: pytest.TempPathFactory):
    """Exercise document analysis authorization without ambient SQLite access."""
    protected_hashes = _protected_fingerprints()
    temp_dir = tmp_path_factory.mktemp("documents-analyze-security")
    database = temp_dir / "documents-analyze-security.db"
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


class AnalyzeInvoiceFileEnvTests(unittest.TestCase):
    def test_returns_llm_not_configured_without_server_keys(self) -> None:
        import app.services.document_invoice_analyze as dia

        keys = ("GEMINI_API_KEY", "GOOGLE_API_KEY")
        saved = {k: os.environ.pop(k, None) for k in keys}
        try:
            out = asyncio.run(
                dia.analyze_invoice_file(
                    data=b"a;b\n1;2",
                    filename="t.csv",
                    content_type="text/csv",
                )
            )
            self.assertEqual(out.get("status"), "ERROR")
            self.assertEqual(out.get("error_code"), "llm_not_configured")
            self.assertIn("GEMINI_API_KEY", out.get("error", ""))
        finally:
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v


@unittest.skipUnless(importlib.util.find_spec("fastapi"), "fastapi")
class DocumentsV1AnalyzeHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_db()
        from fastapi.testclient import TestClient
        from app.main import app

        cls.client = TestClient(app)

    def test_v1_analyze_503_without_server_keys(self) -> None:
        keys = ("GEMINI_API_KEY", "GOOGLE_API_KEY")
        saved = {k: os.environ.pop(k, None) for k in keys}
        try:
            login_declarant(self.client)
            r = self.client.post(
                "/api/v1/documents/analyze",
                files={"file": ("t.csv", b"a;b\n1;2", "text/csv")},
                data={"api_key": "client-key-must-not-be-used"},
            )
            self.assertEqual(r.status_code, 503, r.text)
            body = r.json()
            self.assertEqual(body.get("error_code"), "llm_not_configured")
        finally:
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v


if __name__ == "__main__":
    unittest.main()
