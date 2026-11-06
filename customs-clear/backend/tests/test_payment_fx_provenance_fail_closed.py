"""Fail-closed tests for FX used in customs payment calculations."""

from __future__ import annotations

import math
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.core import ExchangeRate, SourceStatus
from app.models.tnved import HsDutyRule
from app.services.exchange_rates import CBRF_SOURCE_CODE, _parse_cbr_xml, get_rates_map
from app.services.invoice_batch_service import calculate_line_payments
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
                    updated_at=updated_at or datetime.now(timezone.utc).replace(tzinfo=None),
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
                    synced_at=synced_at or datetime.now(timezone.utc).replace(tzinfo=None),
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
        synced_at = datetime.now(timezone.utc).replace(tzinfo=None)
        self._add_rate(updated_at=synced_at)
        self._add_status(
            revision=f"cbrf:{datetime.now(timezone.utc).date().isoformat()}",
            is_stale=False,
            synced_at=synced_at,
        )
        self.assertEqual(get_rates_map(), {"EUR": 101.25, "RUB": 1.0})

    def test_rate_not_from_exact_same_sync_is_hidden(self) -> None:
        synced_at = datetime.now(timezone.utc).replace(tzinfo=None)
        for row_time in (
            synced_at - timedelta(days=30),
            synced_at - timedelta(seconds=1),
            synced_at + timedelta(seconds=1),
        ):
            with self.subTest(row_time=row_time):
                with self.sm() as db:
                    db.query(ExchangeRate).delete()
                    db.query(SourceStatus).delete()
                    db.commit()
                self._add_rate(updated_at=row_time)
                self._add_status(
                    revision=f"cbrf:{datetime.now(timezone.utc).date().isoformat()}",
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

    def test_verified_map_reaches_each_scenario_payment(self) -> None:
        payload = {
            "base": {
                "hs_code": "9999999999",
                "customs_value": 1000,
                "currency": "USD",
            },
            "scenarios": [{"name": "A"}, {"name": "B"}],
        }
        rates = {"USD": 92.0, "EUR": 101.25, "RUB": 1.0}
        seen: list[dict[str, float]] = []

        def fake_compute(pay_payload):
            supplied = pay_payload.get("_fx_rates")
            seen.append(supplied)
            duty = _compute(_specific_eur_rule(), supplied)[0]
            return {
                "status": "OK",
                "breakdown": {
                    "duty": duty,
                    "vat": 0.0,
                    "customs_fee": 0.0,
                    "excise": 0.0,
                    "total_payable": duty,
                },
                "recycling_fee": {"fee_amount": 0.0},
            }

        with (
            patch(
                "app.services.scenario_compare_service.get_rates_map",
                return_value=rates,
            ),
            patch(
                "app.services.scenario_compare_service.compute_payments",
                side_effect=fake_compute,
            ),
        ):
            result = compare_scenarios_extended(payload)

        self.assertEqual(result["status"], "OK")
        self.assertEqual(seen, [rates, rates])
        self.assertEqual(
            [scenario["total"] for scenario in result["scenarios"]],
            [2025.0, 2025.0],
        )


class InvoiceBatchFxFailClosedTests(unittest.TestCase):
    @staticmethod
    def _line(currency: str) -> dict[str, object]:
        return {
            "description": "test",
            "hs_code": "8471300000",
            "quantity": 2,
            "unit_price": 50,
            "currency": currency,
            "country_of_origin": "CN",
        }

    @staticmethod
    def _echo_payment(payload):
        value = float(payload["customs_value"])
        return {
            "status": "OK",
            "breakdown": {
                "duty": 0.0,
                "vat": 0.0,
                "excise": 0.0,
                "customs_fee": 0.0,
                "total_payable": value,
            },
            "recycling_fee": {"fee_amount": 0.0},
        }

    def test_foreign_invoice_is_converted_and_passes_same_verified_map(self) -> None:
        rates = {"USD": 92.0, "EUR": 101.25, "RUB": 1.0}
        with (
            patch(
                "app.services.invoice_batch_service.get_rates_map",
                return_value=rates,
            ),
            patch(
                "app.services.invoice_batch_service.compute_payments",
                side_effect=self._echo_payment,
            ) as compute,
        ):
            result = calculate_line_payments(self._line("USD"))

        payment_input = compute.call_args.args[0]
        self.assertEqual(payment_input["customs_value"], 9200.0)
        self.assertEqual(payment_input["invoice_currency"], "RUB")
        self.assertEqual(payment_input["_fx_rates"], rates)
        self.assertEqual(result["customs_value_original"], 100.0)
        self.assertEqual(result["customs_value"], 9200.0)
        self.assertEqual(result["total_payable"], 9200.0)
        self.assertEqual(result["fx_rate"], 92.0)

    def test_foreign_invoice_missing_or_invalid_rate_never_computes_final(self) -> None:
        for rates in (
            {"RUB": 1.0},
            {"USD": 0.0, "RUB": 1.0},
            {"USD": math.nan, "RUB": 1.0},
            {"USD": True, "RUB": 1.0},
        ):
            with self.subTest(rates=rates):
                with (
                    patch(
                        "app.services.invoice_batch_service.get_rates_map",
                        return_value=rates,
                    ),
                    patch(
                        "app.services.invoice_batch_service.compute_payments",
                    ) as compute,
                ):
                    with self.assertRaises(ValueError):
                        calculate_line_payments(self._line("USD"))
                    compute.assert_not_called()

    def test_rub_invoice_uses_identity_without_foreign_rate(self) -> None:
        with (
            patch(
                "app.services.invoice_batch_service.get_rates_map",
                return_value={"RUB": 1.0},
            ),
            patch(
                "app.services.invoice_batch_service.compute_payments",
                side_effect=self._echo_payment,
            ) as compute,
        ):
            result = calculate_line_payments(self._line("RUB"))

        self.assertEqual(compute.call_args.args[0]["customs_value"], 100.0)
        self.assertEqual(result["customs_value"], 100.0)
        self.assertEqual(result["total_payable"], 100.0)
        self.assertEqual(result["fx_rate"], 1.0)


if __name__ == "__main__":
    unittest.main()
