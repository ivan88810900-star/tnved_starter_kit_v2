"""Изоляция permits verify jobs по владельцу (JWT username); admin видит все."""
from __future__ import annotations

import importlib.util
import hashlib
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from tests.support_auth import login_admin, login_declarant, login_viewer

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
def _isolated_permits_verify_jobs_database(tmp_path_factory: pytest.TempPathFactory):
    """Exercise permits job ownership without reading or creating ambient SQLite."""
    protected_hashes = _protected_fingerprints()
    temp_dir = tmp_path_factory.mktemp("permits-verify-jobs-ownership")
    database = temp_dir / "permits-verify-jobs-ownership.db"
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
    from app.datetime_util import utc_now_naive as isolated_utc_now_naive
    from app.models import PermitsVerifyJob as IsolatedPermitsVerifyJob

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
    patches.setattr(test_module, "SessionLocal", factory, raising=False)
    patches.setattr(test_module, "PermitsVerifyJob", IsolatedPermitsVerifyJob, raising=False)
    patches.setattr(test_module, "utc_now_naive", isolated_utc_now_naive, raising=False)
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


def _insert_done_job(*, job_id: str, owner: str | None) -> None:
    with SessionLocal() as db:
        db.add(
            PermitsVerifyJob(
                id=job_id,
                created_by_username=owner,
                status="done",
                created_at=utc_now_naive(),
                finished_at=utc_now_naive(),
                error=None,
                summary={"total": 1, "valid": 0},
                items=[{"type": "ДС", "number": "TEST", "status": "UNKNOWN"}],
                request_payload={"rows": [{"type": "ДС", "number": "TEST"}], "hs_code": "", "enrich": True},
            )
        )
        db.commit()


def _delete_job(job_id: str) -> None:
    with SessionLocal() as db:
        row = db.get(PermitsVerifyJob, job_id)
        if row:
            db.delete(row)
            db.commit()


@unittest.skipUnless(importlib.util.find_spec("fastapi"), "fastapi")
class PermitsVerifyJobsOwnershipTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_db()
        from fastapi.testclient import TestClient
        from app.main import app

        cls.client_decl = TestClient(app)
        cls.client_view = TestClient(app)
        cls.client_adm = TestClient(app)
        login_declarant(cls.client_decl)
        login_viewer(cls.client_view)
        login_admin(cls.client_adm)

    def tearDown(self) -> None:
        for jid in getattr(self, "_cleanup_ids", []):
            _delete_job(jid)

    def test_user_sees_only_own_jobs_in_list_and_detail(self) -> None:
        self._cleanup_ids = []
        jid_decl = uuid4().hex
        jid_view = uuid4().hex
        self._cleanup_ids.extend([jid_decl, jid_view])
        _insert_done_job(job_id=jid_decl, owner="declarant")
        _insert_done_job(job_id=jid_view, owner="viewer")

        lst_a = self.client_decl.get("/api/permits/verify/jobs?limit=50")
        self.assertEqual(lst_a.status_code, 200, lst_a.text)
        ids_a = {x.get("job_id") for x in (lst_a.json().get("items") or [])}
        self.assertIn(jid_decl, ids_a)
        self.assertNotIn(jid_view, ids_a)

        lst_b = self.client_view.get("/api/permits/verify/jobs?limit=50")
        self.assertEqual(lst_b.status_code, 200, lst_b.text)
        ids_b = {x.get("job_id") for x in (lst_b.json().get("items") or [])}
        self.assertIn(jid_view, ids_b)
        self.assertNotIn(jid_decl, ids_b)

        # Regression: the legacy /verify/{number:path} catch-all must not
        # intercept jobs/detail and trigger an external registry lookup.
        with patch("app.api.permits.check_permits", new_callable=AsyncMock) as registry_lookup:
            self.assertEqual(self.client_decl.get(f"/api/permits/verify/jobs/{jid_view}").status_code, 404)
            self.assertEqual(self.client_view.get(f"/api/permits/verify/jobs/{jid_decl}").status_code, 404)
            registry_lookup.assert_not_awaited()

        ok_a = self.client_decl.get(f"/api/permits/verify/jobs/{jid_decl}")
        self.assertEqual(ok_a.status_code, 200, ok_a.text)
        self.assertEqual(ok_a.json().get("job_id"), jid_decl)

    def test_admin_sees_all_jobs(self) -> None:
        self._cleanup_ids = []
        jid_decl = uuid4().hex
        jid_view = uuid4().hex
        self._cleanup_ids.extend([jid_decl, jid_view])
        _insert_done_job(job_id=jid_decl, owner="declarant")
        _insert_done_job(job_id=jid_view, owner="viewer")

        lst = self.client_adm.get("/api/permits/verify/jobs?limit=50")
        self.assertEqual(lst.status_code, 200, lst.text)
        ids = {x.get("job_id") for x in (lst.json().get("items") or [])}
        self.assertIn(jid_decl, ids)
        self.assertIn(jid_view, ids)

    def test_legacy_job_without_owner_hidden_from_non_admin(self) -> None:
        self._cleanup_ids = []
        jid = uuid4().hex
        self._cleanup_ids.append(jid)
        _insert_done_job(job_id=jid, owner=None)

        with patch("app.api.permits.check_permits", new_callable=AsyncMock) as registry_lookup:
            self.assertEqual(self.client_decl.get(f"/api/permits/verify/jobs/{jid}").status_code, 404)
            registry_lookup.assert_not_awaited()
        self.assertEqual(self.client_adm.get(f"/api/permits/verify/jobs/{jid}").status_code, 200)

    def test_export_with_admin_token_unaffected(self) -> None:
        self._cleanup_ids = []
        jid = uuid4().hex
        self._cleanup_ids.append(jid)
        _insert_done_job(job_id=jid, owner="declarant")
        with patch.dict(os.environ, {"ADMIN_API_TOKEN": "perm-export-secret"}):
            r = self.client_decl.get(
                f"/api/permits/verify/jobs/{jid}/export?format=json",
                headers={"X-Admin-Token": "perm-export-secret"},
            )
            self.assertEqual(r.status_code, 200, r.text)
            body = r.json()
            self.assertEqual(body.get("job_id"), jid)
            self.assertIn("items", body)


if __name__ == "__main__":
    unittest.main()
