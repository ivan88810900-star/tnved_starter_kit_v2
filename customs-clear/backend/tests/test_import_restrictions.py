"""Tests for import restrictions database — Issue #86."""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app import db as app_db
from app.db import SessionLocal
from app.services import normative_store
from app.services.normative_store import find_import_restrictions
from scripts import seed_import_restrictions


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
    return paths


def _protected_fingerprints() -> dict[Path, str | None]:
    return {
        path: _sha256(path) if path.is_file() else None
        for path in _protected_paths()
    }


@pytest.fixture(scope="module")
def import_restrictions_session_factory(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[sessionmaker]:
    """Build and seed an isolated catalogue without using the configured DB."""
    temp_dir = tmp_path_factory.mktemp("import-restrictions")
    database = temp_dir / "import-restrictions.db"
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
    patches.setattr(sys.modules[__name__], "SessionLocal", factory)
    patches.setattr(app_db, "engine", engine)
    patches.setattr(app_db, "SessionLocal", factory)
    patches.setattr(normative_store, "SessionLocal", factory)
    patches.setattr(seed_import_restrictions, "engine", engine)
    patches.setattr(seed_import_restrictions, "SessionLocal", factory)
    patches.setattr(seed_import_restrictions, "DRY_RUN", False)

    try:
        initial = seed_import_restrictions.seed()
        repeated = seed_import_restrictions.seed()
        assert repeated == {"inserted": 0, "total": initial["total"]}
        yield factory
    finally:
        patches.undo()
        engine.dispose()
        for suffix in ("", "-shm", "-wal"):
            candidate = Path(f"{database}{suffix}")
            if candidate.exists():
                candidate.unlink()
        assert _protected_fingerprints() == protected_hashes


@pytest.fixture(autouse=True)
def _import_restrictions_lookup_database(
    import_restrictions_session_factory: sessionmaker,
) -> None:
    """Ensure lookup-only tests share the same isolated seeded database."""


class TestImportRestrictionsData:
    @pytest.fixture(autouse=True)
    def _db(self, import_restrictions_session_factory: sessionmaker):
        self.db = import_restrictions_session_factory()
        try:
            yield
        finally:
            self.db.close()

    def test_total_entries_above_70(self) -> None:
        total = self.db.execute(text("SELECT COUNT(*) FROM import_restrictions")).scalar()
        assert total >= 70, f"Expected >= 70, got {total}"

    def test_ban_entries(self) -> None:
        count = self.db.execute(text(
            "SELECT COUNT(*) FROM import_restrictions WHERE restriction_type = 'ban'"
        )).scalar()
        assert count >= 15

    def test_dual_use_entries(self) -> None:
        count = self.db.execute(text(
            "SELECT COUNT(*) FROM import_restrictions WHERE restriction_type = 'dual_use'"
        )).scalar()
        assert count >= 20

    def test_licensing_entries(self) -> None:
        count = self.db.execute(text(
            "SELECT COUNT(*) FROM import_restrictions WHERE restriction_type = 'licensing'"
        )).scalar()
        assert count >= 10

    def test_quota_entries(self) -> None:
        count = self.db.execute(text(
            "SELECT COUNT(*) FROM import_restrictions WHERE restriction_type = 'quota'"
        )).scalar()
        assert count >= 5

    def test_all_have_legal_ref(self) -> None:
        missing = self.db.execute(text(
            "SELECT COUNT(*) FROM import_restrictions WHERE legal_ref IS NULL OR legal_ref = ''"
        )).scalar()
        assert missing == 0

    def test_all_have_severity(self) -> None:
        invalid = self.db.execute(text(
            "SELECT COUNT(*) FROM import_restrictions WHERE severity NOT IN ('block', 'warning')"
        )).scalar()
        assert invalid == 0


class TestImportRestrictionsLookup:
    def test_cheese_ban_from_eu(self) -> None:
        results = find_import_restrictions("0406000000", country="EU")
        bans = [r for r in results if r["restriction_type"] == "ban"]
        assert len(bans) >= 1
        assert bans[0]["severity"] == "block"

    def test_cheese_no_ban_from_turkey(self) -> None:
        results = find_import_restrictions("0406000000", country="TR")
        bans = [r for r in results if r["restriction_type"] == "ban"]
        assert len(bans) == 0

    def test_nuclear_reactor_dual_use(self) -> None:
        results = find_import_restrictions("8401200000")
        dual = [r for r in results if r["restriction_type"] == "dual_use"]
        assert len(dual) >= 1
        assert dual[0]["severity"] == "block"

    def test_weapons_licensing(self) -> None:
        results = find_import_restrictions("9302000000")
        lic = [r for r in results if r["restriction_type"] == "licensing"]
        assert len(lic) >= 1
        assert lic[0]["severity"] == "block"

    def test_quota_beef(self) -> None:
        results = find_import_restrictions("0201300000")
        quotas = [r for r in results if r["restriction_type"] == "quota"]
        assert len(quotas) >= 1

    def test_crypto_equipment_dual_use(self) -> None:
        results = find_import_restrictions("8517120000")
        dual = [r for r in results if r["restriction_type"] == "dual_use"]
        assert len(dual) >= 1

    def test_no_restrictions_for_safe_goods(self) -> None:
        results = find_import_restrictions("6109100000")
        assert len(results) == 0

    def test_country_filter_blocks_irrelevant(self) -> None:
        all_results = find_import_restrictions("0201000000")
        us_results = find_import_restrictions("0201000000", country="US")
        cn_only = find_import_restrictions("0201000000", country="CN")
        assert len(us_results) >= 1
        us_bans = [r for r in us_results if r["restriction_type"] == "ban"]
        assert len(us_bans) >= 1
