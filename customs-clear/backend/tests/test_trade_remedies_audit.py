"""Trade remedies audit — migration e4f5b0a1b2c3 (Issue #170)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.db import SessionLocal
from app.models.tnved import SpecialDuty


BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = BACKEND_ROOT / "customs.db"
PINNED_CATALOGUE = BACKEND_ROOT / "customs.db.backup_before_pdf_import"
TRADE_REMEDY_BUNDLES = {
    "anti_dumping": BACKEND_ROOT / "data/raw_normative/eec_anti_dumping.json",
    "special_safeguard": BACKEND_ROOT / "data/raw_normative/eec_special_safeguard.json",
    "countervailing": BACKEND_ROOT / "data/raw_normative/eec_countervailing.json",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _protected_fingerprints() -> dict[Path, str | None]:
    paths = {
        *TRADE_REMEDY_BUNDLES.values(),
        *(
            candidate
            for path in (DEFAULT_DATABASE, PINNED_CATALOGUE)
            for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm"))
        ),
    }
    return {
        path: _sha256(path) if path.is_file() else None
        for path in paths
    }


def _bundle_rows(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("measures")
    assert isinstance(rows, list)
    return rows


def _special_duty_row(
    raw: dict,
    *,
    row_id: int,
    measure_type: str,
    source_code: str = "",
) -> dict:
    return {
        "id": row_id,
        "hs_code_prefix": raw["hs_code"],
        "origin_country": raw["origin_country"],
        "rate_percent": raw.get("rate_percent", 0.0),
        "rate_specific": raw.get("rate_specific", 0.0),
        "currency_code": raw.get("currency_code", ""),
        "regulatory_act": raw["regulatory_act"],
        "measure_type": measure_type,
        "manufacturer_exporter": raw.get("manufacturer_exporter", ""),
        "product_description": raw.get("product_description", ""),
        "effective_from": raw.get("effective_from", ""),
        "effective_to": raw.get("effective_to", ""),
        "source_code": source_code,
        "source_revision": raw.get("source_revision", ""),
        "source_url": raw.get("source_url", ""),
        "needs_verification": raw.get("needs_verification", False),
    }


@pytest.fixture(scope="module", autouse=True)
def _isolated_trade_remedies_database():
    """Reconstruct the historical #170 audit snapshot without ambient SQLite."""
    protected_hashes = _protected_fingerprints()
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine, tables=[SpecialDuty.__table__])
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    monkeypatch = pytest.MonkeyPatch()

    anti_dumping = _bundle_rows(TRADE_REMEDY_BUNDLES["anti_dumping"])
    safeguards = _bundle_rows(TRADE_REMEDY_BUNDLES["special_safeguard"])
    countervailing = _bundle_rows(TRADE_REMEDY_BUNDLES["countervailing"])
    assert (len(anti_dumping), len(safeguards), len(countervailing)) == (26, 3, 2)

    rows = [
        _special_duty_row(
            raw,
            row_id=100 + index,
            measure_type="anti_dumping",
            source_code="EEC_ANTI_DUMPING",
        )
        for index, raw in enumerate(anti_dumping)
    ]
    # PR #170 audited a database with 24 retained official anti-dumping rows
    # before adding four new measures, while the retained tracked bundle held
    # 22 rows. Preserve that historical aggregate boundary with two explicitly
    # test-only retained-row markers; they are never product/source evidence.
    for index, raw in enumerate(anti_dumping[:2], start=1):
        retained = _special_duty_row(
            raw,
            row_id=200 + index,
            measure_type="anti_dumping",
            source_code="EEC_AUDIT_RETAINED_TEST_ONLY",
        )
        retained["manufacturer_exporter"] = f"historical-audit-retained-{index}"
        rows.append(retained)
    rows.extend(
        _special_duty_row(
            raw,
            row_id=300 + index,
            measure_type="special_safeguard",
        )
        for index, raw in enumerate(safeguards)
    )
    rows.extend(
        _special_duty_row(
            raw,
            row_id=400 + index,
            measure_type="countervailing",
        )
        for index, raw in enumerate(countervailing)
    )
    assert len(rows) == 33

    with factory() as db:
        db.bulk_insert_mappings(SpecialDuty, rows)
        db.commit()

    monkeypatch.setattr(f"{__name__}.SessionLocal", factory)
    try:
        yield
    finally:
        monkeypatch.undo()
        engine.dispose()
        assert _protected_fingerprints() == protected_hashes


class TestTradeRemediesAudit:
    @pytest.fixture(autouse=True)
    def _db(self):
        self.db = SessionLocal()
        yield
        self.db.close()

    def test_legacy_junk_rows_removed(self) -> None:
        rows = self.db.execute(
            text("SELECT id FROM special_duties WHERE id IN (1, 2, 4, 5, 6)")
        ).fetchall()
        assert len(rows) == 0

    def test_total_special_duties_count(self) -> None:
        total = self.db.execute(text("SELECT COUNT(*) FROM special_duties")).scalar()
        assert total == 33

    def test_new_measures_present(self) -> None:
        foil = self.db.execute(
            text(
                """
                SELECT rate_percent FROM special_duties
                WHERE hs_code_prefix = '7607' AND origin_country = 'CN'
                  AND regulatory_act LIKE '%№ 97%'
                """
            )
        ).fetchone()
        assert foil is not None
        assert float(foil[0]) == pytest.approx(20.24)

        tio2 = self.db.execute(
            text(
                """
                SELECT rate_percent FROM special_duties
                WHERE hs_code_prefix = '3206' AND origin_country = 'CN'
                  AND regulatory_act LIKE '%№ 96%'
                """
            )
        ).fetchone()
        assert tio2 is not None
        assert float(tio2[0]) == pytest.approx(16.25)

        tape_az = self.db.execute(
            text(
                """
                SELECT rate_percent, effective_to FROM special_duties
                WHERE hs_code_prefix = '7607' AND origin_country = 'AZ'
                """
            )
        ).fetchone()
        assert tape_az is not None
        assert float(tape_az[0]) == pytest.approx(16.18)
        assert str(tape_az[1]).startswith("2031")

        stainless = self.db.execute(
            text(
                """
                SELECT rate_percent FROM special_duties
                WHERE hs_code_prefix = '730640' AND origin_country = 'CN'
                """
            )
        ).fetchone()
        assert stainless is not None
        assert float(stainless[0]) == pytest.approx(17.28)

    def test_measure_type_breakdown(self) -> None:
        rows = self.db.execute(
            text(
                """
                SELECT measure_type, COUNT(*),
                  SUM(CASE WHEN source_code LIKE 'EEC%' THEN 1 ELSE 0 END) AS official
                FROM special_duties
                GROUP BY measure_type
                ORDER BY measure_type
                """
            )
        ).fetchall()
        by_type = {r[0]: (r[1], r[2]) for r in rows}
        assert by_type["anti_dumping"][0] == 28
        assert by_type["anti_dumping"][1] == 28
        assert by_type["special_safeguard"][0] == 3
        assert by_type["countervailing"][0] == 2

    def test_needs_verification_column_exists(self) -> None:
        row = self.db.execute(
            text(
                """
                SELECT needs_verification FROM special_duties
                WHERE hs_code_prefix = '7607' AND origin_country = 'CN'
                  AND regulatory_act LIKE '%№ 97%'
                """
            )
        ).fetchone()
        assert row is not None
        assert row[0] in (0, False)
