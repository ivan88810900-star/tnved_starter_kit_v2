"""Regression tests for the explicit disposable classification bootstrap."""
from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = BACKEND_ROOT / "scripts" / "bootstrap_disposable_classification_inventory.py"
CATALOGUE = BACKEND_ROOT / "customs.db.backup_before_pdf_import"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("DATABASE_URL", None)
    env.pop("TNVED_SOURCE_DB", None)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=BACKEND_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_bootstrap_builds_expected_inventory(tmp_path: Path) -> None:
    target = tmp_path / "classification-inventory.db"
    result = _run(str(target))
    assert result.returncode == 0, result.stdout + result.stderr

    connection = sqlite3.connect(target)
    try:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT COUNT(*) FROM tnved_commodities").fetchone()[0] == 13_979
        assert connection.execute(
            "SELECT COUNT(*) FROM regulatory_documents "
            "WHERE agency = 'FTS' AND doc_type = 'letter' AND doc_number LIKE '06-73/%'"
        ).fetchone()[0] >= 200
        assert connection.execute(
            "SELECT COUNT(*) FROM classification_rulings WHERE is_official = 1"
        ).fetchone()[0] >= 50
        assert connection.execute(
            "SELECT COUNT(*) FROM classification_rulings "
            "WHERE agency = 'ТНВЭД-REF' AND is_official = 0"
        ).fetchone()[0] >= 500
    finally:
        connection.close()


def test_bootstrap_refuses_existing_database(tmp_path: Path) -> None:
    target = tmp_path / "existing.db"
    original = b"do-not-touch"
    target.write_bytes(original)

    result = _run(str(target))

    assert result.returncode != 0
    assert "refusing existing target database" in result.stderr
    assert target.read_bytes() == original


def test_bootstrap_refuses_cached_application_database(tmp_path: Path) -> None:
    existing = tmp_path / "existing-app.db"
    target = tmp_path / "new-target.db"
    program = """
import os
import sqlite3
import sys
from pathlib import Path

existing = Path(sys.argv[1])
target = Path(sys.argv[2])
os.environ["DATABASE_URL"] = f"sqlite:///{existing}"
from app.services.normative_store import init_db
init_db()
from scripts.bootstrap_disposable_classification_inventory import bootstrap
try:
    bootstrap(target)
except SystemExit as exc:
    assert "fresh Python interpreter" in str(exc)
else:
    raise AssertionError("cached application database was not rejected")
assert not target.exists()
with sqlite3.connect(existing) as connection:
    assert connection.execute("SELECT COUNT(*) FROM classification_rulings").fetchone()[0] == 0
    assert connection.execute(
        "SELECT COUNT(*) FROM regulatory_documents "
        "WHERE agency = 'FTS' AND doc_number LIKE '06-73/%'"
    ).fetchone()[0] == 0
"""
    env = os.environ.copy()
    env.pop("DATABASE_URL", None)
    result = subprocess.run(
        [sys.executable, "-c", program, str(existing), str(target)],
        cwd=BACKEND_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_catalogue_is_read_without_wal_sidecars(tmp_path: Path) -> None:
    catalogue = tmp_path / "catalogue.db"
    target = tmp_path / "classification-inventory.db"
    shutil.copyfile(CATALOGUE, catalogue)

    result = _run(str(target), "--catalogue", str(catalogue))

    assert result.returncode == 0, result.stdout + result.stderr
    assert not Path(f"{catalogue}-shm").exists()
    assert not Path(f"{catalogue}-wal").exists()


def test_bootstrap_rejects_unpinned_catalogue(tmp_path: Path) -> None:
    catalogue = tmp_path / "catalogue.db"
    target = tmp_path / "classification-inventory.db"
    catalogue.write_bytes(b"not-the-pinned-catalogue")

    result = _run(str(target), "--catalogue", str(catalogue))

    assert result.returncode != 0
    assert "catalogue source fingerprint mismatch" in result.stderr
    assert not target.exists()
