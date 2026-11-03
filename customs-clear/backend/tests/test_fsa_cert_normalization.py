"""Нормализация номеров FSA для lookup в opendata (префиксы ЕАЭС/РОСС/ВП)."""

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
from app.services.opendata_registry import lookup_fsa_certificate
from app.services.permits_service import (
    canonical_cert_number,
    cert_number_search_variants,
    normalize_number,
)


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
def _fsa_lookup_database(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[sessionmaker]:
    """Run FSA lookup mutations only against a disposable catalogue."""
    temp_dir = tmp_path_factory.mktemp("fsa-lookup")
    database = temp_dir / "fsa-lookup.db"
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


class CertNumberVariantsTests(unittest.TestCase):
    def test_short_dt_form_generates_eaeu_variant(self) -> None:
        short = "RU С-CN.АД50.В.05226/22"
        variants = cert_number_search_variants(short)
        self.assertIn("RUС-CN.АД50.В.05226/22", variants)
        self.assertIn("ЕАЭСRUС-CN.АД50.В.05226/22", variants)

    def test_full_db_form_keeps_core(self) -> None:
        full = "ЕАЭСRU С-CN.АД50.В.04618/22"
        self.assertEqual(canonical_cert_number(full), "RUС-CN.АД50.В.04618/22")
        self.assertIn("ЕАЭСRUС-CN.АД50.В.04618/22", cert_number_search_variants(full))

    def test_ross_prefix(self) -> None:
        full = "РОССRUС-RU.НВ70.В.03706/25"
        self.assertEqual(canonical_cert_number(full), "RUС-RU.НВ70.В.03706/25")
        self.assertIn("РОССRUС-RU.НВ70.В.03706/25", cert_number_search_variants(full))


class FsaLookupNormalizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_db()

    def test_short_number_finds_row_with_eaeu_prefix(self) -> None:
        reg = f"ЕАЭСRUС-CN.ТЕ{uuid.uuid4().hex[:4].upper()}.В.00001/99"
        core = canonical_cert_number(reg)
        with SessionLocal() as db:
            db.add(
                FsaCertificate(
                    registry_number=reg,
                    doc_type="СС",
                    status="Действует",
                    applicant="TEST LOOKUP",
                    product_name="Тест",
                )
            )
            db.commit()

        short = core.replace("RUС-", "RU С-", 1)
        found = lookup_fsa_certificate(short, "СС")
        self.assertIsNotNone(found)
        assert found is not None
        self.assertEqual(found["status"], "VALID")
        self.assertEqual(found["number"], normalize_number(reg))
        self.assertEqual(found["source_kind"], "opendata_local")
        self.assertEqual(found["holder"], "TEST LOOKUP")

        with SessionLocal() as db:
            db.query(FsaCertificate).filter(FsaCertificate.registry_number == reg).delete()
            db.commit()


if __name__ == "__main__":
    unittest.main()
