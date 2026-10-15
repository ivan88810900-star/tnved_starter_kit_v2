"""Импорт нормативного пакета и API ТН ВЭД."""
import hashlib
import os
import subprocess
import sys
import unittest
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app import db as app_db, main as app_main
from app.main import app
from app.services import (
    normative_store,
    payment_engine,
    permits_jobs,
    tnved_fts,
    ved_intel_jobs,
)
from app.services.normative_bundle import import_normative_bundle_dict, is_ett_test_hs
from app.services.normative_store import find_tnved_entry, init_db
from app.services.payment_engine import compute_payments


BACKEND_ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP_SCRIPT = (
    BACKEND_ROOT / "scripts" / "bootstrap_disposable_classification_inventory.py"
)
DEFAULT_DATABASE = BACKEND_ROOT / "customs.db"
PINNED_CATALOGUE = BACKEND_ROOT / "customs.db.backup_before_pdf_import"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _protected_paths() -> set[Path]:
    base_paths = {DEFAULT_DATABASE.resolve(), PINNED_CATALOGUE.resolve()}
    configured_url = make_url(app_db.DATABASE_URL)
    if configured_url.drivername.startswith("sqlite") and configured_url.database:
        base_paths.add(Path(configured_url.database).resolve())

    source_database = os.environ.get("TNVED_SOURCE_DB", "").strip()
    if source_database:
        if source_database.startswith("sqlite:"):
            source_url = make_url(source_database)
            if source_url.database:
                base_paths.add(Path(source_url.database).resolve())
        elif "://" not in source_database:
            base_paths.add(Path(source_database).resolve())
    return {
        candidate
        for path in base_paths
        for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm"))
    }


def _protected_fingerprints(
    paths: set[Path] | None = None,
) -> dict[Path, str | None]:
    return {
        path: _sha256(path) if path.is_file() else None
        for path in (paths if paths is not None else _protected_paths())
    }


@pytest.fixture(scope="module", autouse=True)
def _normative_bundle_database(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[sessionmaker]:
    """Import test bundles only into a disposable bootstrapped catalogue."""
    temp_dir = tmp_path_factory.mktemp("normative-bundle")
    database = temp_dir / "normative-bundle.db"
    protected_paths = _protected_paths()
    protected_hashes = _protected_fingerprints(protected_paths)
    original_engine = app_db.engine
    original_session = app_db.SessionLocal
    preloaded_app_modules = {
        module_name
        for module_name in sys.modules
        if module_name == "app" or module_name.startswith("app.")
    }
    engine = None
    factory = None
    patches = pytest.MonkeyPatch()

    try:
        database_url = f"sqlite:///{database}"
        patches.setenv("DATABASE_URL", database_url)
        patches.delenv("TNVED_SOURCE_DB", raising=False)
        result = subprocess.run(
            [sys.executable, str(BOOTSTRAP_SCRIPT), str(database)],
            cwd=BACKEND_ROOT,
            env=os.environ.copy(),
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert _protected_fingerprints(protected_paths) == protected_hashes

        engine = create_engine(
            database_url,
            connect_args={"check_same_thread": False},
        )
        factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

        # Rebind every preloaded alias by identity.  A fixed module list misses
        # aliases imported by an earlier test module (for example rate_display).
        for module_name, module in tuple(sys.modules.items()):
            if module is None or not (
                module_name == "app" or module_name.startswith("app.")
            ):
                continue
            if getattr(module, "SessionLocal", None) is original_session:
                patches.setattr(module, "SessionLocal", factory)
            if getattr(module, "engine", None) is original_engine:
                patches.setattr(module, "engine", engine)

        patches.setattr(sys.modules[__name__], "init_db", lambda: None)
        patches.setattr(app_main, "init_db", lambda: None)
        patches.setattr(normative_store, "engine", engine)
        patches.setattr(normative_store, "SessionLocal", factory)
        patches.setattr(payment_engine, "SessionLocal", factory)
        patches.setattr(tnved_fts, "engine", engine)
        patches.setattr(tnved_fts, "_fts_ready", None)
        patches.setattr(permits_jobs, "mark_interrupted_jobs_on_startup", lambda: None)
        patches.setattr(
            ved_intel_jobs,
            "mark_interrupted_ved_intel_jobs_on_startup",
            lambda: None,
        )

        async def _skip_exchange_rate_update() -> None:
            return None

        patches.setattr(
            app_main,
            "update_exchange_rates_from_cbrf",
            _skip_exchange_rate_update,
        )

        yield factory
    finally:
        try:
            patches.undo()
        finally:
            try:
                if factory is not None and engine is not None:
                    # Modules imported after the initial scan copy the
                    # disposable aliases from app.db; restore those aliases
                    # before discarding them.
                    for module_name, module in tuple(sys.modules.items()):
                        if module is None or not (
                            module_name == "app" or module_name.startswith("app.")
                        ):
                            continue
                        if getattr(module, "SessionLocal", None) is factory:
                            setattr(module, "SessionLocal", original_session)
                        if getattr(module, "engine", None) is engine:
                            setattr(module, "engine", original_engine)
                    for module_name in tuple(sys.modules):
                        if (
                            module_name not in preloaded_app_modules
                            and (
                                module_name == "app"
                                or module_name.startswith("app.")
                            )
                        ):
                            sys.modules.pop(module_name, None)
            finally:
                try:
                    if engine is not None:
                        engine.dispose()
                finally:
                    for suffix in ("", "-shm", "-wal"):
                        candidate = Path(f"{database}{suffix}")
                        if candidate.exists():
                            candidate.unlink()
                    assert _protected_fingerprints(protected_paths) == protected_hashes


class NormativeBundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def test_import_bundle_dict(self):
        res = import_normative_bundle_dict(
            {
                "format": "customs_clear_normative_bundle",
                "revision": "test-b1",
                "tnved": [
                    {
                        "hs_code": "8812345670",
                        "parent_hs": "",
                        "level": 10,
                        "title": "Тестовая позиция",
                        "description": "Описание",
                        "chapter": "88",
                    }
                ],
                "rates": [
                    {
                        "hs_code": "8812345670",
                        "hs_prefix": "8888",
                        "duty_rate": 7.5,
                        "vat_import_rate": 22,
                    }
                ],
                "notes": [
                    {
                        "scope_type": "prefix",
                        "scope_value": "8888",
                        "category": "ett",
                        "title": "ЕТТ",
                        "body": "Тест примечания",
                    }
                ],
            },
            filename="unit.json",
        )
        self.assertEqual(res["status"], "OK")
        self.assertGreaterEqual(res["imported"]["tnved"], 1)
        ent = find_tnved_entry("8812345670")
        self.assertIsNotNone(ent)
        self.assertIn("Тестовая", ent.title or "")

    def test_compute_includes_tnved_context(self):
        out = compute_payments({"hs_code": "8509400000", "customs_value": 100000})
        self.assertEqual(out["status"], "OK")
        self.assertIn("tnved_context", out)
        self.assertIn("notes", out["tnved_context"])

    def test_tnved_api_search(self):
        client = TestClient(app)
        r = client.get("/api/tnved/search?q=850940")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data.get("status"), "OK")
        self.assertIsInstance(data.get("results"), list)

    def test_blank_row_revision_inherits_bundle_revision(self):
        import_normative_bundle_dict(
            {
                "format": "customs_clear_normative_bundle",
                "revision": "ett:2026-05-01",
                "rates": [
                    {
                        "hs_code": "6666010000",
                        "hs_prefix": "7777",
                        "duty_rate": 5,
                        "vat_import_rate": 22,
                        "source_revision": "",
                    }
                ],
            },
            filename="unit-inherit.json",
        )
        from app.db import SessionLocal
        from app.models.core import HsRate

        with SessionLocal() as db:
            row = db.query(HsRate).filter(HsRate.hs_code == "6666010000").first()
        self.assertIsNotNone(row)
        self.assertEqual(row.source_revision, "ett:2026-05-01")

    def test_explicit_seed_row_revision_preserved(self):
        import_normative_bundle_dict(
            {
                "format": "customs_clear_normative_bundle",
                "revision": "ett:2026-05-01",
                "rates": [
                    {
                        "hs_code": "6666010001",
                        "hs_prefix": "7777",
                        "duty_rate": 5,
                        "vat_import_rate": 22,
                        "source_revision": "seed-2026-03",
                    }
                ],
            },
            filename="unit-explicit-seed.json",
        )
        from app.db import SessionLocal
        from app.models.core import HsRate

        with SessionLocal() as db:
            row = db.query(HsRate).filter(HsRate.hs_code == "6666010001").first()
        self.assertIsNotNone(row)
        self.assertEqual(row.source_revision, "seed-2026-03")

    def test_ett_test_hs_codes_skipped_on_import(self):
        res = import_normative_bundle_dict(
            {
                "format": "customs_clear_normative_bundle",
                "revision": "ett:test-guard",
                "rates": [
                    {
                        "hs_code": "7777770000",
                        "hs_prefix": "7777",
                        "duty_rate": 5,
                        "vat_import_rate": 22,
                    },
                    {
                        "hs_code": "6666020000",
                        "hs_prefix": "6666",
                        "duty_rate": 5,
                        "vat_import_rate": 22,
                    },
                ],
            },
            filename="unit-blocklist.json",
        )
        self.assertEqual(res["status"], "OK")
        self.assertEqual(res["skipped"]["rates"], 1)
        self.assertTrue(is_ett_test_hs("7777770000"))
        from app.db import SessionLocal
        from app.models.core import HsRate

        with SessionLocal() as db:
            self.assertIsNone(db.query(HsRate).filter(HsRate.hs_code == "7777770000").first())
            self.assertIsNotNone(db.query(HsRate).filter(HsRate.hs_code == "6666020000").first())


_EXAMPLE = Path(__file__).resolve().parent.parent / "data" / "normative_bundle.example.json"


class ExampleBundleFileTests(unittest.TestCase):
    """Проверка, что репозиторный example.json валиден для импорта."""

    @classmethod
    def setUpClass(cls):
        init_db()

    def test_example_file_imports(self):
        if not _EXAMPLE.exists():
            self.skipTest("example bundle missing")
        raw = _EXAMPLE.read_bytes()
        from app.services.normative_bundle import import_normative_bundle_bytes

        res = import_normative_bundle_bytes(raw, filename="normative_bundle.example.json")
        self.assertEqual(res["status"], "OK")


if __name__ == "__main__":
    unittest.main()
