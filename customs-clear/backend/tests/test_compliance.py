"""Тесты объединённого комплаенс-результата: платежи + нетарифка + документы + риски."""
import unittest
import unittest.mock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import HsRate
from app.models.tnved import Commodity, HsDutyRule, SpecialDuty, VatPreference
from app.services.normative_store import SEED_RATES
from app.services.payment_engine import compute_payments


class ComplianceLogicTests(unittest.TestCase):
    """Комплаенс-логика без HTTP: проверка структуры ответа payment + риски."""

    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(
            bind=cls.engine,
            tables=[
                Commodity.__table__,
                HsDutyRule.__table__,
                HsRate.__table__,
                SpecialDuty.__table__,
                VatPreference.__table__,
            ],
        )
        cls.SessionLocal = sessionmaker(
            bind=cls.engine,
            autocommit=False,
            autoflush=False,
        )
        cls._patchers = [
            unittest.mock.patch(
                "app.services.payment_engine.SessionLocal", cls.SessionLocal
            ),
            unittest.mock.patch(
                "app.services.normative_store.SessionLocal", cls.SessionLocal
            ),
            unittest.mock.patch(
                "app.services.rate_display.SessionLocal", cls.SessionLocal
            ),
            unittest.mock.patch(
                "app.services.payment_engine.get_country_risk_by_iso",
                return_value=None,
            ),
            unittest.mock.patch(
                "app.services.payment_engine.find_geo_embargo_match",
                return_value=None,
            ),
            unittest.mock.patch(
                "app.services.payment_engine.find_geo_duty_override_row",
                return_value=None,
            ),
            unittest.mock.patch(
                "app.services.payment_engine.get_tariff_preference",
                return_value=None,
            ),
            unittest.mock.patch(
                "app.services.payment_engine.get_recycling_fee",
                return_value=[],
            ),
            unittest.mock.patch(
                "app.services.payment_engine.get_integrated_data_stats",
                return_value={"hs_rates_count": len(SEED_RATES)},
            ),
            unittest.mock.patch(
                "app.services.payment_engine.get_tnved_context_for_hs",
                return_value={},
            ),
        ]
        for patcher in cls._patchers:
            patcher.start()
        with cls.SessionLocal() as db:
            db.add_all(
                HsRate(hs_code=row["hs_prefix"], **row)
                for row in SEED_RATES
            )
            db.commit()

    @classmethod
    def tearDownClass(cls):
        for patcher in reversed(cls._patchers):
            patcher.stop()
        cls.engine.dispose()

    def test_payment_breakdown_has_all_fields(self):
        """Breakdown содержит все обязательные поля."""
        res = compute_payments({
            "hs_code": "8509400000",
            "customs_value": 100_000,
            "freight": 10_000,
        })
        b = res["breakdown"]
        self.assertIn("duty", b)
        self.assertIn("vat", b)
        self.assertIn("excise", b)
        self.assertIn("antidumping", b)
        self.assertIn("total_payable", b)
        self.assertIn("vat_reason", b)
        self.assertIn("excise_reason", b)
        self.assertIn("antidumping_reason", b)

    def test_antidumping_manual_review_no_country(self):
        """Код 7214 без страны → antidumping_status = manual_review."""
        res = compute_payments({
            "hs_code": "7214990000",
            "customs_value": 100_000,
            "freight": 0,
        })
        self.assertEqual(res["data_quality"]["antidumping_status"], "manual_review")

    def test_sources_present(self):
        """В ответе есть sources с integrated и data_info."""
        res = compute_payments({
            "hs_code": "8509400000",
            "customs_value": 100_000,
        })
        self.assertGreater(len(res["sources"]), 0)
        for s in res["sources"]:
            self.assertIn("name", s)
            self.assertIn("integrated", s)
            self.assertIn("data_info", s)

    def test_quantity_affects_excise(self):
        """quantity влияет на расчёт акциза (fixed). Для combined_max по литрам нужен extra_quantity."""
        res1 = compute_payments({
            "hs_code": "2208201200",
            "customs_value": 100_000,
            "quantity": 5,
            "extra_quantity": 100.0,
        })
        res2 = compute_payments({
            "hs_code": "2208201200",
            "customs_value": 100_000,
            "quantity": 10,
            "extra_quantity": 100.0,
        })
        self.assertAlmostEqual(res1["breakdown"]["excise"] * 2, res2["breakdown"]["excise"], places=0)


if __name__ == "__main__":
    unittest.main()
