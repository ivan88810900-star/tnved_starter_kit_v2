"""Операционный периметр: запись в БД, аналитика, тяжёлые/внешние вызовы — не без сессии или admin-токена."""
from __future__ import annotations

import hashlib
import importlib.util
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
def _isolated_operational_admin_database(tmp_path_factory: pytest.TempPathFactory):
    """Exercise operational authorization without reading or creating ambient SQLite."""
    protected_hashes = _protected_fingerprints()
    temp_dir = tmp_path_factory.mktemp("operational-admin-auth")
    database = temp_dir / "operational-admin-auth.db"
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
class OperationalAdminSurfaceAuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_db()
        from fastapi.testclient import TestClient
        from app.main import app

        cls.anon = TestClient(app)
        cls.auth = TestClient(app)
        login_declarant(cls.auth)

    @patch("app.api.finance.update_exchange_rates_from_cbrf", new_callable=AsyncMock)
    def test_finance_rates_update_requires_admin_token(self, mock_upd: AsyncMock) -> None:
        mock_upd.return_value = {"ok": True}
        with patch.dict(os.environ, {"ADMIN_API_TOKEN": "fin-secret"}):
            r = self.anon.post("/api/v1/finance/rates/update")
            self.assertEqual(r.status_code, 401, r.text)
            bad = self.anon.post(
                "/api/v1/finance/rates/update",
                headers={"X-Admin-Token": "wrong"},
            )
            self.assertEqual(bad.status_code, 401, bad.text)
            ok = self.anon.post(
                "/api/v1/finance/rates/update",
                headers={"X-Admin-Token": "fin-secret"},
            )
            self.assertEqual(ok.status_code, 200, ok.text)

    @patch("app.api.analytics.redis_ping", new_callable=AsyncMock)
    @patch("app.api.analytics.build_analytics_overview")
    def test_analytics_overview_requires_admin_token(self, mock_build, mock_redis: AsyncMock) -> None:
        mock_build.return_value = {"status": "OK", "generated_at": "t0", "database_reachable": True}
        mock_redis.return_value = True
        with patch.dict(os.environ, {"ADMIN_API_TOKEN": "an-secret"}):
            r = self.anon.get("/api/analytics/overview")
            self.assertEqual(r.status_code, 401, r.text)
            ok = self.anon.get("/api/analytics/overview", headers={"X-Admin-Token": "an-secret"})
            self.assertEqual(ok.status_code, 200, ok.text)

    @patch("app.api.permits.check_permits", new_callable=AsyncMock)
    def test_permits_verify_requires_authenticated_user(self, mock_cp: AsyncMock) -> None:
        mock_cp.return_value = []
        body = {"permits": [{"type": "ДС", "number": "ЕАЭС RU Д-CN.12345"}], "hs_code": "8509400000"}
        r = self.anon.post("/api/permits/verify", json=body)
        self.assertEqual(r.status_code, 401, r.text)
        ok = self.auth.post("/api/permits/verify", json=body)
        self.assertEqual(ok.status_code, 200, ok.text)

    def test_compliance_check_requires_authenticated_user(self) -> None:
        body = {
            "items": [
                {
                    "hs_code": "8509400000",
                    "description": "пылесос",
                    "country": "CN",
                    "permits": [],
                    "customs_value": 100000.0,
                    "freight": 0.0,
                }
            ],
            "save_history": False,
        }
        r = self.anon.post("/api/compliance/check", json=body)
        self.assertEqual(r.status_code, 401, r.text)
        ok = self.auth.post("/api/compliance/check", json=body)
        self.assertIn(ok.status_code, (200, 400, 500), ok.text)

    def test_alta_status_requires_authenticated_user(self) -> None:
        r = self.anon.get("/api/integrations/alta/status")
        self.assertEqual(r.status_code, 401, r.text)
        ok = self.auth.get("/api/integrations/alta/status")
        self.assertEqual(ok.status_code, 200, ok.text)

    @patch("app.api.tnved.semantic_search_tnved")
    def test_tnved_semantic_search_requires_authenticated_user(self, mock_sem) -> None:
        mock_sem.return_value = []
        r = self.anon.get("/api/tnved/search/semantic?q=телефон&limit=3")
        self.assertEqual(r.status_code, 401, r.text)
        ok = self.auth.get("/api/tnved/search/semantic?q=телефон&limit=3")
        self.assertEqual(ok.status_code, 200, ok.text)

    @patch("app.api.non_tariff.check_position_non_tariff", new_callable=AsyncMock)
    def test_non_tariff_check_requires_authenticated_user(self, mock_nt: AsyncMock) -> None:
        mock_nt.return_value = {
            "status": "OK",
            "hs_code": "8509400000",
            "description": "x",
            "tr_ts": [],
            "permits": [],
            "notes": [],
        }
        body = {"items": [{"hs_code": "8509400000", "description": "пылесос", "country": "CN", "permits": []}]}
        r = self.anon.post("/api/non_tariff/check", json=body)
        self.assertEqual(r.status_code, 401, r.text)
        ok = self.auth.post("/api/non_tariff/check", json=body)
        self.assertEqual(ok.status_code, 200, ok.text)


if __name__ == "__main__":
    unittest.main()
