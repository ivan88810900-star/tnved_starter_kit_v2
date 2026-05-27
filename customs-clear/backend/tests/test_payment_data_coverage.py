"""Тесты диагностики покрытия ТН ВЭД и платёжных данных."""

from __future__ import annotations

import unittest
import unittest.mock
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.main import app
from app.models.core import ExchangeRate, GeoSpecialDuty, HsRate, SourceStatus, SyncLog, TnvedEntry
from app.models.tnved import Chapter, Commodity, HsDutyRule, Section, SpecialDuty, VatPreference
from app.services.normative_store import init_db
from app.services.payment_data_coverage import (
    diagnose_duty_rates,
    diagnose_excise,
    diagnose_trade_remedies,
    run_payment_data_coverage_report,
)

try:
    from fastapi.testclient import TestClient

    _API_OK = True
except ImportError:
    _API_OK = False


_COVERAGE_TABLES = [
    Section.__table__,
    Chapter.__table__,
    Commodity.__table__,
    HsDutyRule.__table__,
    SpecialDuty.__table__,
    VatPreference.__table__,
    TnvedEntry.__table__,
    HsRate.__table__,
    ExchangeRate.__table__,
    GeoSpecialDuty.__table__,
    SourceStatus.__table__,
    SyncLog.__table__,
]


def _memory_sessionmaker():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine, tables=_COVERAGE_TABLES)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


class TestPaymentDataCoverageEmptyDb(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self._patch_session = unittest.mock.patch(
            "app.services.payment_data_coverage.SessionLocal",
            self.sm,
        )
        self._patch_session.start()

    def tearDown(self) -> None:
        self._patch_session.stop()

    def test_empty_db_summary_is_missing_or_not_configured(self) -> None:
        report = run_payment_data_coverage_report()
        self.assertEqual(report["status"], "OK")
        summary = report["summary"]
        self.assertIn(summary["tnved_entries"]["status"], ("missing", "partial"))
        self.assertEqual(summary["duty_rates"]["status"], "missing")
        self.assertEqual(summary["customs_fees"]["status"], "present")
        self.assertEqual(summary["excise"]["status"], "not_configured")
        self.assertEqual(summary["trade_remedies"]["status"], "not_configured")
        self.assertIn(summary["exchange_rates"]["status"], ("missing", "partial"))
        self.assertFalse(report["smart_payments"]["can_produce_final_total"])
        self.assertTrue(summary["excise"]["manual_review_required"])
        self.assertTrue(len(report["next_actions"]) >= 1)


class TestPaymentDataCoveragePartialRates(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        with self.sm() as db:
            db.add(
                HsRate(
                    hs_code="8471300000",
                    hs_prefix="8471",
                    duty_rate="0%",
                    vat_import_rate=22.0,
                )
            )
            db.add(
                HsRate(
                    hs_code="2203009900",
                    hs_prefix="2203",
                    duty_rate="0%",
                    vat_import_rate=22.0,
                    excise_type="percent",
                    excise_value=12.0,
                    source_revision="seed",
                )
            )
            db.commit()

        self._patch = unittest.mock.patch(
            "app.services.payment_data_coverage.SessionLocal",
            self.sm,
        )
        self._patch.start()

    def tearDown(self) -> None:
        self._patch.stop()

    def test_partial_duty_rates_with_gaps(self) -> None:
        duty = diagnose_duty_rates()
        self.assertEqual(duty.status, "partial")
        self.assertEqual(duty.count, 2)
        self.assertTrue(duty.manual_review_required)
        self.assertGreater(len(duty.gaps), 0)

    def test_excise_seed_rows_not_full_coverage(self) -> None:
        excise = diagnose_excise()
        self.assertIn(excise.status, ("not_configured", "partial"))
        self.assertTrue(excise.manual_review_required)
        self.assertNotEqual(excise.status, "present")


class TestPaymentDataCoverageUnknownTradeRemedySources(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        with self.sm() as db:
            db.add(
                SpecialDuty(
                    hs_code_prefix="8517",
                    origin_country="CN",
                    rate_percent=15.0,
                    regulatory_act="TEST-UNKNOWN-SOURCE",
                )
            )
            db.add(
                HsRate(
                    hs_code="7214990000",
                    hs_prefix="7214",
                    duty_rate="5%",
                    vat_import_rate=22.0,
                    has_antidumping=True,
                    antidumping_type="percent",
                    antidumping_value=34.0,
                )
            )
            db.commit()

        self._patch = unittest.mock.patch(
            "app.services.payment_data_coverage.SessionLocal",
            self.sm,
        )
        self._patch.start()

    def tearDown(self) -> None:
        self._patch.stop()

    def test_unknown_trade_remedy_source_not_present(self) -> None:
        trade = diagnose_trade_remedies()
        self.assertIn(trade.status, ("not_configured", "partial"))
        self.assertNotEqual(trade.status, "present")
        self.assertTrue(trade.manual_review_required)
        self.assertGreater(trade.count or 0, 0)


class TestPaymentDataCoverageFreshExchangeRates(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        now = datetime.utcnow()
        with self.sm() as db:
            for code in ("USD", "EUR", "CNY", "BYN", "KZT"):
                db.add(
                    ExchangeRate(
                        currency_code=code,
                        rate=90.0,
                        nominal=1.0,
                        updated_at=now,
                    )
                )
            db.commit()

        self._patch = unittest.mock.patch(
            "app.services.payment_data_coverage.SessionLocal",
            self.sm,
        )
        self._patch.start()

    def tearDown(self) -> None:
        self._patch.stop()

    def test_fresh_exchange_rates_present(self) -> None:
        from app.services.payment_data_coverage import diagnose_exchange_rates

        fx = diagnose_exchange_rates()
        self.assertEqual(fx.status, "present")
        self.assertIsNotNone(fx.last_successful_sync_at)


@unittest.skipUnless(_API_OK, "fastapi not installed")
class TestPaymentDataCoverageApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_db()
        cls.client = TestClient(app)

    def test_payment_coverage_endpoint(self) -> None:
        r = self.client.get("/api/sources/payment-coverage")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "OK")
        self.assertIn("summary", body)
        self.assertIn("smart_payments", body)
        self.assertIn("next_actions", body)
        self.assertIn("tnved_entries", body["summary"])
        self.assertIn("duty_rates", body["summary"])
        self.assertIn("excise", body["summary"])