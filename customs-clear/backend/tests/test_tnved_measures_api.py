"""GET /api/v1/tnved/{code} — поле measures для фронта frontend/web."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app import db as app_db, main as app_main
from app.api import tnved_catalog
from app.db import SessionLocal
from app.main import app
from app.models.core import HsRate
from app.services import normative_store
from app.services.normative_store import init_db

client = TestClient(app)

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

MEASURES_CASES: dict[str, list[str]] = {
    "5208211000": ["ДС"],
    "6101100000": ["ДС"],
    "6401100000": ["ДС"],
    "9503001000": ["СС"],
    "3304100000": ["ДС"],
    "8517130000": ["ДС"],
    "8401100000": [],
}


@pytest.fixture(scope="module", autouse=True)
def _exact_rate_evidence_for_measure_cases(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[None]:
    """Give the endpoint exact persisted evidence that every fixture code exists.

    The production endpoint deliberately rejects an arbitrary 10-digit code
    when neither a commodity nor an exact tariff row exists.  This test owns
    only a disposable catalogue and the tariff-existence fixtures it creates;
    configured and repository databases remain read-only.
    """
    temp_dir = tmp_path_factory.mktemp("tnved-measures-api")
    database = temp_dir / "tnved-measures-api.db"
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
    patches.setattr(sys.modules[__name__], "init_db", lambda: None)
    patches.setattr(sys.modules[__name__], "SessionLocal", factory)
    patches.setattr(app_main, "init_db", lambda: None)
    patches.setattr(app_main, "engine", engine)
    patches.setattr(app_db, "engine", engine)
    patches.setattr(app_db, "SessionLocal", factory)
    patches.setattr(normative_store, "engine", engine)
    patches.setattr(normative_store, "SessionLocal", factory)
    patches.setattr(tnved_catalog, "SessionLocal", factory)

    inserted_ids: list[int] = []
    try:
        init_db()
        revision = "test-tnved-measures-api"
        with SessionLocal() as db:
            existing = {
                row[0]
                for row in db.query(HsRate.hs_code)
                .filter(HsRate.hs_code.in_(MEASURES_CASES))
                .all()
            }
            inserted = [
                HsRate(
                    hs_code=code,
                    hs_prefix=code,
                    duty_rate="0",
                    source_revision=revision,
                )
                for code in MEASURES_CASES
                if code not in existing
            ]
            db.add_all(inserted)
            db.flush()
            inserted_ids = [row.id for row in inserted]
            db.commit()
        yield
    finally:
        try:
            if inserted_ids:
                with SessionLocal() as db:
                    db.query(HsRate).filter(HsRate.id.in_(inserted_ids)).delete(
                        synchronize_session=False
                    )
                    db.commit()
        finally:
            patches.undo()
            engine.dispose()
            for suffix in ("", "-shm", "-wal"):
                candidate = Path(f"{database}{suffix}")
                if candidate.exists():
                    candidate.unlink()
            assert _protected_fingerprints() == protected_hashes


def test_commodity_measures_regression() -> None:
    for code, expected in MEASURES_CASES.items():
        r = client.get(f"/api/v1/tnved/{code}")
        assert r.status_code == 200, f"{code}: {r.status_code}"
        measures = [m.get("type", "") for m in r.json().get("measures", [])]
        if expected == []:
            assert measures == [], f"{code}: expected empty, got {measures}"
        else:
            assert all(e in measures for e in expected), f"{code}: expected {expected}, got {measures}"
            assert len(measures) > 0
