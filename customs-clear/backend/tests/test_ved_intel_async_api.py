"""POST /api/documents/ved-intelligent-analyze/async + GET ved-intel-jobs/{id}."""
from __future__ import annotations

import hashlib
import importlib.util
import io
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

try:
    from fastapi.testclient import TestClient
    from app.main import app
    from app.services.normative_store import init_db

    _OK = True
except ImportError:
    _OK = False


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
def _isolated_ved_intel_async_database(tmp_path_factory: pytest.TempPathFactory):
    """Exercise async VED analysis without reading or creating ambient SQLite."""
    if not _OK:
        yield
        return

    protected_hashes = _protected_fingerprints()
    temp_dir = tmp_path_factory.mktemp("ved-intel-async-api")
    database = temp_dir / "ved-intel-async-api.db"
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

    test_module = sys.modules[__name__]
    patches.setattr(test_module, "init_db", lambda: None, raising=False)
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


@unittest.skipUnless(_OK, "нужен полный стек")
class VedIntelAsyncApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        cls.client = TestClient(app)
        from tests.support_auth import login_declarant

        login_declarant(cls.client)

    @patch("app.services.ved_intel_jobs.run_ved_intel_analyze_core", new_callable=AsyncMock)
    def test_async_job_returns_result_on_poll(self, mock_core):
        mock_core.return_value = {
            "status": "OK",
            "comparison_mode": "invoice_only",
            "document_id": "async-doc-1",
            "ved_intel_status": "OK",
            "items": [],
            "checks": [],
            "summary": {"errors": 0, "warnings": 0, "passed": 1},
        }
        r = self.client.post(
            "/api/documents/ved-intelligent-analyze/async",
            files={"document": ("pack.xlsx", io.BytesIO(b"x"), "application/octet-stream")},
            data={
                "country": "CN",
                "freight_total_rub": "0",
                "extract_permits": "false",
                "verify_fsa": "false",
                "skip_registry_verify": "true",
                "use_ai_declaration": "true",
                "persist": "false",
                "run_payment": "false",
            },
        )
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body.get("status"), "accepted")
        job_id = body.get("job_id")
        self.assertTrue(job_id)
        jr = self.client.get(f"/api/documents/ved-intel-jobs/{job_id}")
        self.assertEqual(jr.status_code, 200, jr.text)
        st = jr.json()
        self.assertEqual(st.get("status"), "done")
        self.assertIn("result", st)
        self.assertEqual(st["result"].get("ved_intel_status"), "OK")
        mock_core.assert_awaited_once()

    def test_ved_intel_job_not_found(self):
        r = self.client.get("/api/documents/ved-intel-jobs/ffffffffffffffffffffffffffffffff")
        self.assertEqual(r.status_code, 404)


if __name__ == "__main__":
    unittest.main()
