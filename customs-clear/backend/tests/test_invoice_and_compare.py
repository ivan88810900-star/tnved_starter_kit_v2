"""Tests for invoice batch and scenario compare."""

from __future__ import annotations

import hashlib
import io
import os
import subprocess
import sys
import unittest
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

try:
    from app import db as app_db
    from app.models.core import ExchangeRate, HsRate
    from app.models.rop import RopGoodsRate, RopPackagingDefault, RopPackagingRate
    from app.models.tnved import CountryTariffPreference
    from app.services.invoice_batch_service import parse_invoice_file
    from app.services.scenario_compare_service import compare_scenarios_extended

    _OK = True
except ImportError:
    _OK = False


BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = BACKEND_ROOT / "customs.db"
PINNED_CATALOGUE = BACKEND_ROOT / "customs.db.backup_before_pdf_import"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _protected_fingerprints() -> dict[Path, str | None]:
    paths = {
        candidate
        for path in (DEFAULT_DATABASE, PINNED_CATALOGUE)
        for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm"))
    }
    return {
        path: _sha256(path) if path.is_file() else None
        for path in paths
    }


@pytest.fixture(scope="module", autouse=True)
def _isolated_invoice_compare_database(tmp_path_factory: pytest.TempPathFactory):
    """Keep FX, payment and ROP lookups on a disposable scenario database."""
    if not _OK:
        yield
        return

    protected_hashes = _protected_fingerprints()
    original_session = app_db.SessionLocal
    original_engine = app_db.engine
    database = tmp_path_factory.mktemp("invoice-compare") / "invoice-compare.db"
    database_url = f"sqlite:///{database}"
    bootstrap_env = os.environ.copy()
    bootstrap_env["DATABASE_URL"] = database_url
    bootstrap_env.pop("TNVED_SOURCE_DB", None)
    bootstrap = subprocess.run(
        [
            sys.executable,
            "-c",
            "from app.services.normative_store import init_db; init_db()",
        ],
        cwd=BACKEND_ROOT,
        env=bootstrap_env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert bootstrap.returncode == 0, bootstrap.stdout + bootstrap.stderr
    assert _protected_fingerprints() == protected_hashes
    engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False},
    )
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    patches = pytest.MonkeyPatch()
    try:
        patches.setenv("DATABASE_URL", database_url)
        patches.delenv("TNVED_SOURCE_DB", raising=False)

        for module_name, module in tuple(sys.modules.items()):
            if module is None or not (module_name == "app" or module_name.startswith("app.")):
                continue
            if getattr(module, "SessionLocal", None) is original_session:
                patches.setattr(module, "SessionLocal", factory)
            if getattr(module, "engine", None) is original_engine:
                patches.setattr(module, "engine", engine)

        year = date.today().year
        with factory() as db:
            db.add_all(
                [
                    ExchangeRate(currency_code="USD", rate=90.0, nominal=1.0),
                    HsRate(
                        hs_code="8471300000",
                        hs_prefix="8471",
                        duty_rate="10",
                        vat_import_rate=22.0,
                        source_revision="test-invoice-compare",
                    ),
                    CountryTariffPreference(
                        country_code="DE",
                        preference_type="test-reduced-duty",
                        duty_coefficient=0.5,
                        legal_ref="Test fixture",
                        effective_from="2026-01-01",
                    ),
                    RopGoodsRate(
                        category_code="TEST-GOODS",
                        pp2414_group=1,
                        category_name="Test goods",
                        hs_prefixes_json='["8471"]',
                        base_rate_per_ton=1000.0,
                        ke_coefficient=1.0,
                        rate_per_ton=1000.0,
                        recycling_norm=0.5,
                        calendar_year=year,
                        legal_ref="Test fixture",
                    ),
                    RopPackagingDefault(
                        hs_prefix="8471",
                        packaging_type="carton",
                        pp2414_group=46,
                        is_default_rule=False,
                        reason="Test fixture",
                        priority=10,
                    ),
                    RopPackagingRate(
                        category_code="TEST-PACKAGING",
                        pp2414_group=46,
                        category_name="Test carton",
                        packaging_type="carton",
                        base_rate_per_ton=2000.0,
                        ke_coefficient=1.0,
                        rate_per_ton=2000.0,
                        recycling_norm=0.25,
                        calendar_year=year,
                        legal_ref="Test fixture",
                    ),
                ]
            )
            db.commit()

        yield
    finally:
        patches.undo()
        for module_name, module in tuple(sys.modules.items()):
            if module is None or not (module_name == "app" or module_name.startswith("app.")):
                continue
            if getattr(module, "SessionLocal", None) is factory:
                setattr(module, "SessionLocal", original_session)
            if getattr(module, "engine", None) is engine:
                setattr(module, "engine", original_engine)
        engine.dispose()
        assert _protected_fingerprints() == protected_hashes


@unittest.skipIf(not _OK, "deps missing")
class InvoiceBatchTests(unittest.TestCase):
    def test_parse_csv(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "description": "Shoes",
                    "hs_code": "6403990000",
                    "quantity": 2,
                    "unit_price": 50,
                    "currency": "USD",
                    "weight_gross_kg": 3,
                    "weight_net_kg": 2.5,
                    "country_of_origin": "CN",
                }
            ]
        )
        buf = io.BytesIO()
        df.to_csv(buf, index=False)
        lines = parse_invoice_file(buf.getvalue(), "test.csv")
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["description"], "Shoes")


@unittest.skipIf(not _OK, "deps missing")
class ScenarioCompareTests(unittest.TestCase):
    def test_compare_two_countries(self) -> None:
        payload = {
            "base": {
                "hs_code": "8471300000",
                "customs_value": 1000,
                "currency": "USD",
                "weight_gross_kg": 110,
                "weight_net_kg": 100,
            },
            "scenarios": [
                {"name": "CN", "country_of_origin": "CN"},
                {"name": "DE", "country_of_origin": "DE"},
            ],
        }
        out = compare_scenarios_extended(payload)
        self.assertEqual(out["status"], "OK")
        self.assertEqual(out["base"]["customs_value_rub"], 90_000.0)
        self.assertEqual(len(out["scenarios"]), 2)
        by_name = {scenario["name"]: scenario for scenario in out["scenarios"]}
        self.assertEqual(by_name["CN"]["country_of_origin"], "CN")
        self.assertEqual(by_name["DE"]["country_of_origin"], "DE")
        self.assertEqual(by_name["CN"]["payments_status"], "OK")
        self.assertEqual(by_name["DE"]["payments_status"], "OK")
        self.assertEqual(by_name["CN"]["rop"], 55.0)
        self.assertEqual(by_name["DE"]["rop"], 55.0)
        self.assertFalse(by_name["CN"]["preference"]["applied"])
        self.assertTrue(by_name["DE"]["preference"]["applied"])
        self.assertLess(by_name["DE"]["total"], by_name["CN"]["total"])
        self.assertEqual(out["best_scenario"], "DE")
        self.assertGreater(out["savings_vs_worst"], 0)


if __name__ == "__main__":
    unittest.main()
