"""Tests for invoice batch and scenario compare."""

from __future__ import annotations

import io
import unittest

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

try:
    from app.services.invoice_batch_service import parse_invoice_file
    from app.services.scenario_compare_service import compare_scenarios_extended

    _OK = True
except ImportError:
    _OK = False


@pytest.fixture
def isolated_scenario_db(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Run the scenario calculator against a complete disposable schema.

    The service modules keep local references to ``SessionLocal``.  Patching
    every reader used by this end-to-end path keeps this test independent of
    an ambient development database without changing the calculator's
    fail-closed behaviour when a normative table is genuinely unavailable.
    """
    if not _OK:
        yield
        return

    from app import db as app_db
    from app.models.core import (
        CountryRisk,
        CustomsCalculationHistory,
        ExchangeRate,
        GeoSpecialDuty,
        HsRate,
        IngestedDocument,
        NonTariffRule,
        NormativeNote,
        TnvedEntry,
        TnvedEntryEmbedding,
        TrTsAct,
    )
    from app.models.rop import RopGoodsRate, RopPackagingDefault, RopPackagingRate
    from app.models.tnved import (
        Chapter,
        Commodity,
        CountryTariffPreference,
        HsDutyRule,
        RecyclingFee,
        Section,
        SpecialDuty,
        VatPreference,
    )
    from app.services import (
        exchange_rates,
        invoice_analyzer,
        normative_store,
        payment_engine,
        rate_display,
        scenario_compare_service,
    )

    engine = create_engine(
        f"sqlite:///{tmp_path / 'scenario.sqlite'}",
        connect_args={"check_same_thread": False},
    )
    tables = [
        ExchangeRate.__table__,
        CountryRisk.__table__,
        GeoSpecialDuty.__table__,
        HsRate.__table__,
        HsDutyRule.__table__,
        CountryTariffPreference.__table__,
        SpecialDuty.__table__,
        RecyclingFee.__table__,
        VatPreference.__table__,
        NonTariffRule.__table__,
        TnvedEntry.__table__,
        NormativeNote.__table__,
        TrTsAct.__table__,
        IngestedDocument.__table__,
        TnvedEntryEmbedding.__table__,
        CustomsCalculationHistory.__table__,
        Section.__table__,
        Chapter.__table__,
        Commodity.__table__,
        RopGoodsRate.__table__,
        RopPackagingDefault.__table__,
        RopPackagingRate.__table__,
    ]
    app_db.Base.metadata.create_all(bind=engine, tables=tables)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    monkeypatch.setattr(app_db, "engine", engine)
    monkeypatch.setattr(app_db, "SessionLocal", session_factory)
    monkeypatch.setattr(normative_store, "engine", engine)
    for module in (
        exchange_rates,
        invoice_analyzer,
        normative_store,
        payment_engine,
        rate_display,
        scenario_compare_service,
    ):
        monkeypatch.setattr(module, "SessionLocal", session_factory)

    try:
        yield
    finally:
        engine.dispose()


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
@pytest.mark.usefixtures("isolated_scenario_db")
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
        self.assertEqual(len(out["scenarios"]), 2)
        self.assertIn("best_scenario", out)


if __name__ == "__main__":
    unittest.main()
