"""Shared disposable classification inventory for dataset regression tests.

The application default database intentionally starts without the historical
classification inventory.  Tests that assert that inventory must opt into the
explicit test-only bootstrap instead of depending on whatever database happens
to be configured for the process running pytest.
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


BACKEND_ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP_SCRIPT = BACKEND_ROOT / "scripts" / "bootstrap_disposable_classification_inventory.py"
DEFAULT_DATABASE = BACKEND_ROOT / "customs.db"
PINNED_CATALOGUE = BACKEND_ROOT / "customs.db.backup_before_pdf_import"

# The pinned catalogue stores display-only/truncated descriptions, while the
# experimental semantic-navigation suite exercises merged-subheader fragments.
# Keep those cases explicit and test-only in the disposable database.  Codes
# remain real catalogue rows; only their temporary descriptions are completed.
_SEMANTIC_NAVIGATION_DESCRIPTIONS = {
    "0302111000": "– – вид Oncorhynchus apache – лососевые:",
    "0302190000": "– – прочие виды лососевых – камбалообразные:",
    "0302298000": "– – прочие камбалообразные – тунец:",
    "0303599009": "– – прочие мороженые рыбы – тунец:",
    "8517110000": "– – аппараты с диапазоном до 2,2 – 10 ГГц",
    "8517130000": "– – аппараты с длиной волны 1270 – 1610 нм",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _install_semantic_navigation_cases(database: Path) -> None:
    """Complete the semantic merged-header cases in the disposable copy only."""
    with sqlite3.connect(database) as connection:
        for code, description in _SEMANTIC_NAVIGATION_DESCRIPTIONS.items():
            cursor = connection.execute(
                "UPDATE tnved_commodities SET description = ? WHERE code = ?",
                (description, code),
            )
            assert cursor.rowcount == 1, f"missing pinned catalogue row for {code}"
        connection.commit()


@pytest.fixture(scope="session")
def classification_inventory_session_factory(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[sessionmaker]:
    """Bootstrap one isolated inventory and remove it after the test session."""
    temp_dir = tmp_path_factory.mktemp("classification-inventory")
    database = temp_dir / "inventory.db"
    protected_hashes = {
        path: _sha256(path)
        for path in (DEFAULT_DATABASE, PINNED_CATALOGUE)
    }
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
    _install_semantic_navigation_cases(database)
    assert {
        path: _sha256(path)
        for path in (DEFAULT_DATABASE, PINNED_CATALOGUE)
    } == protected_hashes

    engine = create_engine(
        f"sqlite:///{database}",
        connect_args={"check_same_thread": False},
    )
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    try:
        yield factory
    finally:
        engine.dispose()
        for suffix in ("", "-shm", "-wal"):
            candidate = Path(f"{database}{suffix}")
            if candidate.exists():
                candidate.unlink()
        assert {
            path: _sha256(path)
            for path in (DEFAULT_DATABASE, PINNED_CATALOGUE)
        } == protected_hashes


@pytest.fixture
def classification_inventory_session_local(
    classification_inventory_session_factory: sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
) -> sessionmaker:
    """Bind both application SessionLocal references to the disposable DB."""
    from app import db as app_db
    from app.services import normative_store
    from scripts import expand_classification_rulings

    disposable_engine = classification_inventory_session_factory.kw["bind"]
    monkeypatch.setattr(app_db, "engine", disposable_engine)
    monkeypatch.setattr(app_db, "SessionLocal", classification_inventory_session_factory)
    monkeypatch.setattr(normative_store, "engine", disposable_engine)
    monkeypatch.setattr(
        normative_store,
        "SessionLocal",
        classification_inventory_session_factory,
    )
    monkeypatch.setattr(expand_classification_rulings, "engine", disposable_engine)
    monkeypatch.setattr(
        expand_classification_rulings,
        "SessionLocal",
        classification_inventory_session_factory,
    )
    return classification_inventory_session_factory
