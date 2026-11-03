"""Regression tests for vat_preferences audit #161 fix."""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.db import SessionLocal
from app.models.core import HsRate
from app.models.tnved import VatPreference
from app.services.payment_engine import get_effective_vat_rate


BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = BACKEND_ROOT / "customs.db"
PINNED_CATALOGUE = BACKEND_ROOT / "customs.db.backup_before_pdf_import"
VAT_RATE_BUNDLE = BACKEND_ROOT / "data/raw_normative/eec_ett_vat.json"
VAT_PREFERENCE_BUNDLE = BACKEND_ROOT / "data/vat_preferences_164p2_expansion.json"
CONTROL_CODES = {
    "2710191100",
    "9018908401",
    "9503007500",
    "9206000000",
    "0201100001",
    "8471300000",
    "3004900001",
    "4901990000",
    "9504200000",
    "9506110000",
    "9508100000",
    "9506000000",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _protected_fingerprints() -> dict[Path, str | None]:
    paths = {
        VAT_RATE_BUNDLE,
        VAT_PREFERENCE_BUNDLE,
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


@pytest.fixture(scope="module", autouse=True)
def _isolated_vat_preferences_database():
    """Run the audit against tracked VAT bundles, never ambient SQLite."""
    protected_hashes = _protected_fingerprints()
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        bind=engine,
        tables=[HsRate.__table__, VatPreference.__table__],
    )
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    monkeypatch = pytest.MonkeyPatch()

    rate_payload = json.loads(VAT_RATE_BUNDLE.read_text(encoding="utf-8"))
    preference_payload = json.loads(VAT_PREFERENCE_BUNDLE.read_text(encoding="utf-8"))
    rate_rows = [
        row
        for row in rate_payload["rates"]
        if row.get("hs_code") in CONTROL_CODES
    ]
    assert {row["hs_code"] for row in rate_rows} == {
        "2710191100",
        "9018908401",
        "9503007500",
        "9206000000",
        "0201100001",
        "8471300000",
        "3004900001",
        "4901990000",
        "9508100000",
    }

    with factory() as db:
        db.add_all(
            HsRate(
                hs_code=row["hs_code"],
                hs_prefix=row["hs_code"],
                duty_rate="0",
                vat_import_rate=row["vat_import_rate"],
                vat_rule=row["vat_rule"],
                vat_rule_basis=row["vat_rule_basis"],
                source_revision=row["source_revision"],
                source_url=row["source_url"],
            )
            for row in rate_rows
        )
        db.add_all(
            VatPreference(**row)
            for row in preference_payload["items"]
        )
        db.commit()

    monkeypatch.setattr("app.services.normative_store.SessionLocal", factory)
    monkeypatch.setattr("app.services.payment_engine.SessionLocal", factory)
    monkeypatch.setattr(f"{__name__}.SessionLocal", factory)
    try:
        yield
    finally:
        monkeypatch.undo()
        engine.dispose()
        assert _protected_fingerprints() == protected_hashes


class VatPreferencesAudit161Tests(unittest.TestCase):
    def test_no_bad_broad_prefixes(self) -> None:
        with SessionLocal() as db:
            bad = (
                db.query(VatPreference)
                .filter(VatPreference.hs_code_prefix.in_(("27", "92", "95")))
                .count()
            )
            self.assertEqual(bad, 0, "Broad tamdoc prefixes 27/92/95 must be removed")

    def test_950300_not_9503_heading_prefix(self) -> None:
        with SessionLocal() as db:
            old = (
                db.query(VatPreference)
                .filter(VatPreference.hs_code_prefix == "9503")
                .count()
            )
            new = (
                db.query(VatPreference)
                .filter(VatPreference.hs_code_prefix == "950300", VatPreference.vat_rate == 10)
                .count()
            )
            self.assertEqual(old, 0, "4-digit prefix 9503 must not remain")
            self.assertGreaterEqual(new, 1, "6-digit prefix 950300 required per PP908")

    def test_9018_is_10_not_zero(self) -> None:
        with SessionLocal() as db:
            row = (
                db.query(VatPreference)
                .filter(VatPreference.hs_code_prefix == "9018")
                .order_by(VatPreference.id.desc())
                .first()
            )
            self.assertIsNotNone(row)
            assert row is not None
            self.assertEqual(int(row.vat_rate), 10)

    def test_effective_vat_control_codes(self) -> None:
        checks: list[tuple[str, int, str]] = [
            ("2710191100", 22, "нефтепродукты"),
            ("9018908401", 10, "медизделия ПП688"),
            ("9503007500", 10, "игрушки ПП908"),
            ("9206000000", 22, "муз.инструменты"),
            ("0201100001", 10, "говядина ПП908"),
            ("8471300000", 22, "ноутбук"),
            ("3004900001", 10, "лекарства"),
            ("4901990000", 10, "книги"),
            ("9504200000", 22, "9504 настольные игры"),
            ("9506110000", 22, "9506 спорт"),
            ("9508100000", 22, "9508 цирки"),
            ("9506000000", 22, "спортинвентарь 9506"),
        ]
        for code, expected, desc in checks:
            actual = int(get_effective_vat_rate(code))
            self.assertEqual(
                actual,
                expected,
                f"{code} ({desc}): expected {expected}%, got {actual}%",
            )


if __name__ == "__main__":
    unittest.main()
