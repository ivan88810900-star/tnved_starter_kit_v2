"""Регрессия badge нетарифки в preview (/api/v1/tnved/preview/{code})."""

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
from app.api.tnved_catalog import clear_preview_cache
from app.main import app
from app.services import normative_store, payment_engine, rate_display

client = TestClient(app)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP_SCRIPT = (
    BACKEND_ROOT / "scripts" / "bootstrap_disposable_classification_inventory.py"
)
DEFAULT_DATABASE = BACKEND_ROOT / "customs.db"
PINNED_CATALOGUE = BACKEND_ROOT / "customs.db.backup_before_pdf_import"
DEFAULT_PREVIEW_REVISION = BACKEND_ROOT / "data" / "tnved_preview_cache_revision.txt"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _protected_paths() -> set[Path]:
    paths = {
        DEFAULT_DATABASE.resolve(),
        PINNED_CATALOGUE.resolve(),
        DEFAULT_PREVIEW_REVISION.resolve(),
    }
    configured_url = make_url(app_db.DATABASE_URL)
    if configured_url.drivername.startswith("sqlite") and configured_url.database:
        configured_database = Path(configured_url.database)
        if not configured_database.is_absolute():
            configured_database = BACKEND_ROOT / configured_database
        paths.add(configured_database.resolve())

    source_database = os.environ.get("TNVED_SOURCE_DB", "").strip()
    if source_database:
        if source_database.startswith("sqlite:"):
            source_url = make_url(source_database)
            if source_url.database:
                paths.add(Path(source_url.database).resolve())
        elif "://" not in source_database:
            paths.add(Path(source_database).resolve())

    configured_revision = os.environ.get(
        "TNVED_PREVIEW_CACHE_REVISION_FILE", ""
    ).strip()
    if configured_revision:
        paths.add(Path(configured_revision).expanduser().resolve())
    return paths


def _protected_fingerprints() -> dict[Path, str | None]:
    paths = {
        candidate
        for path in _protected_paths()
        for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm"))
    }
    return {
        path: _sha256(path) if path.is_file() else None
        for path in paths
    }


@pytest.fixture(scope="module", autouse=True)
def _disposable_preview_catalog_database(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[None]:
    """Run preview badge checks against a disposable catalogue and revision marker."""
    temp_dir = tmp_path_factory.mktemp("preview-permit-badges")
    database = temp_dir / "preview-permit-badges.db"
    preview_revision = temp_dir / "tnved-preview-cache-revision.txt"
    protected_hashes = _protected_fingerprints()
    env = os.environ.copy()
    env.pop("DATABASE_URL", None)
    env.pop("TNVED_SOURCE_DB", None)
    env.pop("TNVED_PREVIEW_CACHE_REVISION_FILE", None)
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
    patches.setenv("TNVED_PREVIEW_CACHE_REVISION_FILE", str(preview_revision))
    patches.setattr(app_main, "init_db", lambda: None)
    patches.setattr(app_main, "engine", engine)
    patches.setattr(app_db, "engine", engine)
    patches.setattr(app_db, "SessionLocal", factory)
    patches.setattr(normative_store, "engine", engine)
    patches.setattr(normative_store, "SessionLocal", factory)
    patches.setattr(tnved_catalog, "SessionLocal", factory)
    patches.setattr(payment_engine, "SessionLocal", factory)
    patches.setattr(rate_display, "SessionLocal", factory)

    try:
        yield
    finally:
        try:
            tnved_catalog.clear_preview_cache()
        finally:
            patches.undo()
            engine.dispose()
            for path in (
                database,
                Path(f"{database}-shm"),
                Path(f"{database}-wal"),
                preview_revision,
            ):
                if path.exists():
                    path.unlink()
            assert _protected_fingerprints() == protected_hashes


PREVIEW_BADGE_CASES: dict[str, list[str]] = {
    "5208211000": ["ДС"],
    "6101100000": ["ДС"],
    "6401100000": ["ДС"],
    "9503001000": ["СС"],
    "0401100000": ["ВС"],
    "3304100000": ["ДС"],
    "8517130000": ["ДС"],
    "8401100000": [],
    "2204101100": ["ЛЗ"],
    "9401100000": ["ДС"],
}


def test_preview_measure_badges_regression() -> None:
    clear_preview_cache()
    for code, expected in PREVIEW_BADGE_CASES.items():
        r = client.get(f"/api/v1/tnved/preview/{code}")
        assert r.status_code == 200, f"{code}: {r.status_code} {r.text[:200]}"
        badges = r.json().get("non_tariff", {}).get("measure_badges") or []
        if expected == []:
            assert badges == [], f"{code}: expected empty, got {badges}"
        else:
            assert all(e in badges for e in expected), f"{code}: expected {expected}, got {badges}"
