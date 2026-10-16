"""Тесты импорта FSA opendata (dedupe по registry_number)."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import unittest
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app import db as app_db
from app.db import SessionLocal
from app.models.tnved import FsaCertificate
from app.services import normative_store, opendata_fsa, opendata_registry
from app.services.normative_store import init_db
from app.services.opendata_fsa import _upsert_fsa_rows


BACKEND_ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP_SCRIPT = BACKEND_ROOT / "scripts" / "bootstrap_disposable_classification_inventory.py"
DEFAULT_DATABASE = BACKEND_ROOT / "customs.db"
PINNED_CATALOGUE = BACKEND_ROOT / "customs.db.backup_before_pdf_import"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _protected_paths() -> set[Path]:
    paths = {DEFAULT_DATABASE.resolve(), PINNED_CATALOGUE.resolve()}
    configured_url = make_url(app_db.DATABASE_URL)
    if configured_url.drivername.startswith("sqlite") and configured_url.database:
        paths.add(Path(configured_url.database).resolve())

    source_database = os.environ.get("TNVED_SOURCE_DB", "").strip()
    if source_database:
        if source_database.startswith("sqlite:"):
            source_url = make_url(source_database)
            if source_url.database:
                paths.add(Path(source_url.database).resolve())
        elif "://" not in source_database:
            paths.add(Path(source_database).resolve())
    return paths


def _protected_fingerprints() -> dict[Path, str | None]:
    return {
        path: _sha256(path) if path.is_file() else None
        for path in _protected_paths()
    }


@pytest.fixture(scope="module", autouse=True)
def _fsa_upsert_database(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[sessionmaker]:
    """Run FSA upserts only against a disposable bootstrapped catalogue."""
    temp_dir = tmp_path_factory.mktemp("fsa-upsert")
    database = temp_dir / "fsa-upsert.db"
    protected_hashes = _protected_fingerprints()
    env = os.environ.copy()
    env.pop("DATABASE_URL", None)
    env.pop("TNVED_SOURCE_DB", None)
    result = subprocess.run(
        [sys.executable, str(BOOTSTRAP_SCRIPT), str(database)],
        cwd=BACKEND_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert _protected_fingerprints() == protected_hashes

    engine = create_engine(
        f"sqlite:///{database}",
        connect_args={"check_same_thread": False},
    )
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    patches = pytest.MonkeyPatch()
    patches.setenv("DATABASE_URL", f"sqlite:///{database}")
    patches.setenv("TNVED_SOURCE_DB", str(PINNED_CATALOGUE))
    patches.setattr(sys.modules[__name__], "SessionLocal", factory)
    patches.setattr(sys.modules[__name__], "init_db", lambda: None)
    patches.setattr(app_db, "engine", engine)
    patches.setattr(app_db, "SessionLocal", factory)
    patches.setattr(normative_store, "engine", engine)
    patches.setattr(normative_store, "SessionLocal", factory)
    patches.setattr(opendata_fsa, "SessionLocal", factory)
    patches.setattr(opendata_registry, "SessionLocal", factory)

    try:
        yield factory
    finally:
        patches.undo()
        engine.dispose()
        for suffix in ("", "-shm", "-wal"):
            candidate = Path(f"{database}{suffix}")
            if candidate.exists():
                candidate.unlink()
        assert _protected_fingerprints() == protected_hashes


class FsaUpsertDedupeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_db()

    def test_duplicate_registry_number_in_batch_collapses(self) -> None:
        reg = f"TEST-DEDUPE-{uuid.uuid4().hex[:12]}"
        rows = [
            {
                "registry_number": reg,
                "doc_type": "СС",
                "status": "Действует",
                "product_name": "Первая строка",
            },
            {
                "registry_number": reg,
                "doc_type": "СС",
                "status": "Действует",
                "product_name": "Последняя строка",
            },
        ]
        stats = _upsert_fsa_rows(rows, snapshot_id="test-dedupe-snap")
        self.assertEqual(stats["created"], 1)
        self.assertEqual(stats["updated"], 0)
        self.assertEqual(stats["skipped"], 0)

        with SessionLocal() as db:
            count = db.query(FsaCertificate).filter(FsaCertificate.registry_number == reg).count()
            row = db.query(FsaCertificate).filter(FsaCertificate.registry_number == reg).one()
        self.assertEqual(count, 1)
        self.assertEqual(row.product_name, "Последняя строка")

        stats2 = _upsert_fsa_rows(rows, snapshot_id="test-dedupe-snap-2")
        self.assertEqual(stats2["created"], 0)
        self.assertEqual(stats2["updated"], 1)


if __name__ == "__main__":
    unittest.main()
