"""Tests for recycling fees (утильсбор) — Issue #85."""
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
from app.services import normative_store, payment_engine, rate_display
from app.services.normative_store import get_recycling_fee
from app.services.payment_engine import compute_payments
from scripts import seed_recycling_fees


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


@pytest.fixture(scope="module")
def recycling_fees_session_factory(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[sessionmaker]:
    """Build and seed an isolated catalogue without using configured databases."""
    temp_dir = tmp_path_factory.mktemp("recycling-fees")
    database = temp_dir / "recycling-fees.db"
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
    patches.setattr(payment_engine, "SessionLocal", factory)
    patches.setattr(rate_display, "SessionLocal", factory)
    patches.setattr(seed_recycling_fees, "engine", engine)
    patches.setattr(seed_recycling_fees, "SessionLocal", factory)
    patches.setattr(seed_recycling_fees, "DRY_RUN", False)

    try:
        initial = seed_recycling_fees.seed()
        repeated = seed_recycling_fees.seed()
        assert initial == {"inserted": 40, "total": 40}
        assert repeated == {"inserted": 0, "total": 40}
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
def _recycling_fees_database(
    recycling_fees_session_factory: sessionmaker,
) -> None:
    """Ensure lookup and payment tests share the isolated seeded database."""


class TestRecyclingFeesData:
    @pytest.fixture(autouse=True)
    def _db(self, recycling_fees_session_factory: sessionmaker):
        self.db = recycling_fees_session_factory()
        try:
            yield
        finally:
            self.db.close()

    def test_total_entries_is_40(self) -> None:
        total = self.db.execute(text("SELECT COUNT(*) FROM recycling_fees")).scalar()
        assert total == 40

    def test_passenger_cars_12_entries(self) -> None:
        count = self.db.execute(text(
            "SELECT COUNT(*) FROM recycling_fees WHERE hs_prefix = '8703'"
        )).scalar()
        assert count == 12

    def test_trucks_8_entries(self) -> None:
        count = self.db.execute(text(
            "SELECT COUNT(*) FROM recycling_fees WHERE hs_prefix = '8704'"
        )).scalar()
        assert count == 8

    def test_motorcycles_10_entries(self) -> None:
        count = self.db.execute(text(
            "SELECT COUNT(*) FROM recycling_fees WHERE hs_prefix = '8711'"
        )).scalar()
        assert count == 10

    def test_all_have_legal_ref(self) -> None:
        missing = self.db.execute(text(
            "SELECT COUNT(*) FROM recycling_fees WHERE legal_ref IS NULL OR legal_ref = ''"
        )).scalar()
        assert missing == 0

    def test_unique_constraint(self) -> None:
        dupes = self.db.execute(text("""
            SELECT hs_prefix, vehicle_type, is_new, COUNT(*) c
            FROM recycling_fees
            GROUP BY hs_prefix, vehicle_type, is_new
            HAVING c > 1
        """)).fetchall()
        assert len(dupes) == 0


class TestRecyclingFeeLookup:
    def test_lookup_new_car_1500cc(self) -> None:
        results = get_recycling_fee("8703220000", is_new=True, engine_volume=1500)
        assert len(results) >= 1
        best = results[0]
        assert best["coefficient"] == 4.2
        assert best["base_rate"] == 20000
        assert best["fee_amount"] == 84000.0

    def test_lookup_used_car_3200cc(self) -> None:
        results = get_recycling_fee("8703240000", is_new=False, engine_volume=3200)
        assert len(results) >= 1
        best = results[0]
        assert best["coefficient"] == 28.5

    def test_lookup_non_vehicle_returns_empty(self) -> None:
        results = get_recycling_fee("8517120000", is_new=True)
        assert results == []

    def test_lookup_electric_car(self) -> None:
        results = get_recycling_fee("8703800000", is_new=True, engine_volume=None)
        has_electric = any("electric" in r["vehicle_type"] for r in results)
        assert has_electric or len(results) > 0

    def test_motorcycle_small(self) -> None:
        results = get_recycling_fee("8711200000", is_new=True, engine_volume=150)
        assert len(results) >= 1
        best = results[0]
        assert best["base_rate"] == 9000


class TestRecyclingFeeInPaymentEngine:
    def test_car_payment_includes_recycling_fee(self) -> None:
        result = compute_payments({
            "hs_code": "8703220000",
            "customs_value": 1000000,
            "country": "DE",
            "vehicle_is_new": True,
            "engine_volume": 1500,
        })
        assert result["status"] == "OK"
        rf = result.get("recycling_fee", {})
        assert rf.get("applied") is True
        assert rf["fee_amount"] == 84000.0
        assert result["breakdown"]["recycling_fee"] == 84000.0
        assert result["breakdown"]["total_payable"] > result["breakdown"]["duty"] + result["breakdown"]["vat"]

    def test_non_vehicle_no_recycling_fee(self) -> None:
        result = compute_payments({
            "hs_code": "8517120000",
            "customs_value": 100000,
        })
        assert result["status"] == "OK"
        rf = result.get("recycling_fee", {})
        assert rf.get("applied") is False
        assert result["breakdown"]["recycling_fee"] == 0.0

    def test_embargo_response_has_recycling_fee_field(self) -> None:
        result = compute_payments({
            "hs_code": "8517120000",
            "customs_value": 100000,
        })
        if result["status"] == "EMBARGO":
            assert "recycling_fee" in result["breakdown"]
