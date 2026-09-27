"""Fail-closed tests for FX used in customs payment calculations."""

from __future__ import annotations

import math
import unittest
from datetime import date, datetime, timedelta
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.core import ExchangeRate, SourceStatus
from app.models.tnved import HsDutyRule
from app.services.exchange_rates import CBRF_SOURCE_CODE, _parse_cbr_xml, get_rates_map
from app.services.payment_engine import _compute_structured_duty
from app.services.scenario_compare_service import compare_scenarios_extended


def _memory_sessionmaker():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        bind=engine,
        tables=[SourceStatus.__table__, ExchangeRate.__table__],
    )
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


def _specific_eur_rule() -> HsDutyRule:
    return HsDutyRule(
        commodity_code="9999999999",
        type="specific",
        specific_amount=2.0,
        specific_currency="EUR",
        specific_uom="kg",
    )


def _compute(rule: HsDutyRule, fx_rates: dict[str, float] | None):
    return _compute_structured_duty(
        customs_value=100_000.0,
        quantity=10.0,
        net_weight_kg=10.0,
        extra_quantity=None,
        duty_rule=rule,
        manual_duty_rate=None,
        auto_duty_rate=5.0,
        fx_rates=fx_rates,
    )


class PaymentFxFailClosedTests(unittest.TestCase):
    def test_foreign_specific_duty_requires_explicit_verified_rate(self) -> None:
        with self.assertRaisesRegex(ValueError, "подтвержденного курса"):
            _compute(_specific_eur_rule(), None)

    def test_foreign_specific_duty_uses_explicit_rate(self) -> None:
        result = _compute(_specific_eur_rule(), {"EUR": 101.25})
        self.assertEqual(result[0], 2025.0)
        self.assertEqual(result[3], 2025.0)
        self.assertEqual(result[5], 101.25)

    def test_rub_specific_duty_needs_no_external_rate(self) -> None:
        rule = _specific_eur_rule()
        rule.specific_currency = "RUB"
        result = _compute(rule, None)
        self.assertEqual(result[0], 20.0)
        self.assertEqual(result[5], 1.0)

    def test_non_positive_non_finite_and_boolean_rates_are_rejected(self) -> None:
        for invalid in (0.0, -1.0, math.nan, math.inf, True):
            with self.subTest(rate=invalid):
                with self.assertRaisesRegex(ValueError, "Некорректный курс"):
                    _compute(_specific_eur_rule(), {"EUR": invalid})


class ExchangeRateProvenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self.session_patch = patch("app.services.exchange_rates.SessionLocal", self.sm)
        self.session_patch.start()

    def tearDown(self) -> None:
        self.session_patch.stop()

    def _add_rate(self, *, updated_at: datetime | None = None) -> None:
        with self.sm() as db:
            db.add(
                ExchangeRate(
                    currency_code="EUR",
                    rate=101.25,
                    nominal=1.0,
                    updated_at=updated_at or datetime.now(),
                )
            )
            db.commit()

    def _add_status(
        self,
        *,
        revision: str,
        is_stale: bool,
        synced_at: datetime | None = None,
    ) -> None:
        with self.sm() as db:
            db.add(
                SourceStatus(
                    source_code=CBRF_SOURCE_CODE,
                    source_name="CBRF test",
                    source_url="https://www.cbr.ru/",
                    revision=revision,
                    synced_at=synced_at or datetime.now(),
                    is_stale=is_stale,
                    note="test",
                )
            )
            db.commit()

    def test_persisted_rate_without_verified_source_is_hidden(self) -> None:
        self._add_rate()
        self.assertEqual(get_rates_map(), {"RUB": 1.0})

    def test_fallback_status_hides_persisted_rate(self) -> None:
        self._add_rate()
        self._add_status(revision="fallback", is_stale=True)
        self.assertEqual(get_rates_map(), {"RUB": 1.0})

    def test_verified_cbr_status_exposes_bound_persisted_rate(self) -> None:
        synced_at = datetime.now()
        self._add_rate(updated_at=synced_at - timedelta(seconds=1))
        self._add_status(
            revision=f"cbrf:{date.today().isoformat()}",
            is_stale=False,
            synced_at=synced_at,
        )
        self.assertEqual(get_rates_map(), {"EUR": 101.25, "RUB": 1.0})

    def test_rate_newer_than_provenance_is_hidden(self) -> None:
        synced_at = datetime.now()
        self._add_rate(updated_at=synced_at + timedelta(seconds=1))
        self._add_status(
            revision=f"cbrf:{date.today().isoformat()}",
            is_stale=False,
            synced_at=synced_at,
        )
        self.assertEqual(get_rates_map(), {"RUB": 1.0})


class CbrXmlDateTests(unittest.TestCase):
    def test_malformed_source_date_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            _parse_cbr_xml('<ValCurs Date="bad"></ValCurs>')

    def test_future_source_date_fails_closed(self) -> None:
        tomorrow = date.today() + timedelta(days=1)
        xml_date = tomorrow.strftime("%d.%m.%Y")
        with self.assertRaisesRegex(ValueError, "future rate date"):
            _parse_cbr_xml(f'<ValCurs Date="{xml_date}"></ValCurs>')


class ScenarioFxFailClosedTests(unittest.TestCase):
    def test_foreign_scenario_does_not_fall_back_to_one(self) -> None:
        payload = {
            "base": {
                "hs_code": "8471300000",
                "customs_value": 1000,
                "currency": "USD",
            },
            "scenarios": [{"name": "A"}, {"name": "B"}],
        }
        with patch(
            "app.services.scenario_compare_service.get_rates_map",
            return_value={"RUB": 1.0},
        ):
            with self.assertRaisesRegex(ValueError, "подтвержденного курса"):
                compare_scenarios_extended(payload)


if __name__ == "__main__":
    unittest.main()
