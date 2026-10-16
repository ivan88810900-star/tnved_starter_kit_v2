"""Tests for Honest Mark marking requirements."""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app import db as app_db
from app.db import SessionLocal
from scripts import seed_honest_mark_requirements


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


def _protected_fingerprints() -> dict[Path, str | None]:
    return {
        path: _sha256(path) if path.is_file() else None
        for path in (DEFAULT_DATABASE, PINNED_CATALOGUE)
    }


@pytest.fixture(scope="module")
def honest_mark_session_factory(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[sessionmaker]:
    """Build and seed an isolated catalogue without using the configured DB."""
    temp_dir = tmp_path_factory.mktemp("honest-mark")
    database = temp_dir / "honest-mark.db"
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
    patches.setattr(seed_honest_mark_requirements, "SessionLocal", factory)
    patches.setattr(seed_honest_mark_requirements, "DRY_RUN", False)

    try:
        seed_honest_mark_requirements.run()
        yield factory
    finally:
        patches.undo()
        engine.dispose()
        for suffix in ("", "-shm", "-wal"):
            candidate = Path(f"{database}{suffix}")
            if candidate.exists():
                candidate.unlink()
        assert _protected_fingerprints() == protected_hashes


class TestHonestMarkRequirements:
    @pytest.fixture(autouse=True)
    def _db(self, honest_mark_session_factory: sessionmaker):
        self.db = honest_mark_session_factory()
        try:
            yield
        finally:
            self.db.close()

    def _marking_count(self, prefix: str) -> int:
        return self.db.execute(text(
            "SELECT COUNT(*) FROM non_tariff_measures "
            "WHERE measure_type = 'marking' AND quality = 'verified' "
            "AND commodity_code LIKE :pat"
        ), {"pat": f"{prefix}%"}).scalar()

    def test_tobacco_marking_exists(self) -> None:
        count = self._marking_count("2402")
        assert count >= 1, "Tobacco (2402) should have marking entries"

    def test_footwear_marking_exists(self) -> None:
        count = self._marking_count("6403")
        assert count >= 1, "Footwear (6403) should have marking entries"

    def test_medicines_marking_exists(self) -> None:
        count = self._marking_count("3004")
        assert count >= 1, "Medicines (3004) should have marking entries"

    def test_clothing_marking_exists(self) -> None:
        count = self._marking_count("6203")
        assert count >= 1, "Clothing (6203) should have marking entries"

    def test_dairy_marking_exists(self) -> None:
        count = self._marking_count("0401")
        assert count >= 1, "Dairy (0401) should have marking entries"

    def test_tires_marking_exists(self) -> None:
        count = self._marking_count("4011")
        assert count >= 1, "Tires (4011) should have marking entries"

    def test_water_marking_exists(self) -> None:
        count = self._marking_count("2201")
        assert count >= 1, "Packaged water (2201) should have marking entries"

    def test_beer_marking_exists(self) -> None:
        count = self._marking_count("2203")
        assert count >= 1, "Beer (2203) should have marking entries"

    def test_perfumery_marking_exists(self) -> None:
        count = self._marking_count("3303")
        assert count >= 1, "Perfumery (3303) should have marking entries"

    def test_canned_marking_exists(self) -> None:
        count = self._marking_count("1602")
        assert count >= 1, "Canned products (1602) should have marking entries"

    def test_fur_marking_exists(self) -> None:
        count = self._marking_count("4303")
        assert count >= 1, "Fur (4303) should have marking entries"

    def test_total_verified_marking_above_200(self) -> None:
        total = self.db.execute(text(
            "SELECT COUNT(*) FROM non_tariff_measures "
            "WHERE measure_type = 'marking' AND quality = 'verified'"
        )).scalar()
        assert total >= 200, f"Expected >= 200 verified marking entries, got {total}"

    def test_all_entries_have_regulatory_act(self) -> None:
        missing = self.db.execute(text(
            "SELECT COUNT(*) FROM non_tariff_measures "
            "WHERE measure_type = 'marking' AND quality = 'verified' "
            "AND (regulatory_act IS NULL OR regulatory_act = '')"
        )).scalar()
        assert missing == 0, f"Found {missing} marking entries without regulatory_act"
