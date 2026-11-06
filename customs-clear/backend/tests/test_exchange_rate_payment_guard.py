"""Fail-closed FX provenance checks for payment calculations."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.core import ExchangeRate, SourceStatus
from app.api.calculator import CalculatorRequest, compute
from app.services.exchange_rates import CBRF_SOURCE_CODE, FALLBACK, TRACKED, get_rates_map
from app.services.payment_quote_service import build_payment_quote
from app.services.scenario_compare_service import compare_scenarios_extended


def _memory_sessionmaker():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        bind=engine,
        tables=[ExchangeRate.__table__, SourceStatus.__table__],
    )
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


class PaymentFxProvenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _memory_sessionmaker()
        self.now = datetime(2026, 9, 27, 5, 0, 0)
        with self.sm() as db:
            db.add_all(
                [
                    ExchangeRate(
                        currency_code=code,
                        rate=80.0 + index,
                        nominal=1.0,
                        updated_at=self.now,
                    )
                    for index, code in enumerate(TRACKED)
                ]
            )
            db.commit()
        self.session_patch = patch("app.services.exchange_rates.SessionLocal", self.sm)
        self.session_patch.start()

    def tearDown(self) -> None:
        self.session_patch.stop()

    def _add_status(
        self,
        *,
        revision: str = "cbrf:2026-09-25",
        synced_at: datetime | None = None,
        is_stale: bool = False,
    ) -> None:
        with self.sm() as db:
            db.add(
                SourceStatus(
                    source_code=CBRF_SOURCE_CODE,
                    source_name="CBRF test",
                    source_url="https://www.cbr.ru/scripts/XML_daily.asp",
                    revision=revision,
                    synced_at=synced_at or self.now,
                    is_stale=is_stale,
                    note="test",
                )
            )
            db.commit()

    def test_foreign_currency_rates_require_cbrf_provenance(self) -> None:
        with self.assertRaisesRegex(ValueError, "не подтверждены"):
            get_rates_map(require_cbrf_provenance=True)

    def test_fallback_or_stale_status_is_rejected(self) -> None:
        self._add_status(revision="fallback", is_stale=True)
        with self.assertRaisesRegex(ValueError, "требует проверки"):
            get_rates_map(require_cbrf_provenance=True)

    def test_malformed_cbrf_revision_is_rejected(self) -> None:
        self._add_status(revision="cbrf:not-a-date")
        with self.assertRaisesRegex(ValueError, "не подтверждены"):
            get_rates_map(require_cbrf_provenance=True)

    def test_future_cbrf_revision_is_rejected(self) -> None:
        self._add_status(revision="cbrf:2999-01-01")
        with self.assertRaisesRegex(ValueError, "не подтверждены"):
            get_rates_map(require_cbrf_provenance=True)

    def test_old_provenance_cannot_approve_newer_rate_rows(self) -> None:
        self._add_status(synced_at=self.now - timedelta(minutes=1))
        with self.assertRaisesRegex(ValueError, "не подтверждены"):
            get_rates_map(require_cbrf_provenance=True)

    def test_complete_positive_rows_with_covering_cbrf_status_are_accepted(self) -> None:
        self._add_status()
        rates = get_rates_map(require_cbrf_provenance=True)
        self.assertEqual(set(rates), set(TRACKED) | {"RUB"})
        self.assertEqual(rates["RUB"], 1.0)
        self.assertEqual(rates["USD"], 80.0)

    def test_missing_or_nonpositive_tracked_rate_is_rejected(self) -> None:
        self._add_status()
        with self.sm() as db:
            row = db.query(ExchangeRate).filter(ExchangeRate.currency_code == "EUR").one()
            row.rate = 0.0
            db.commit()
        with self.assertRaisesRegex(ValueError, "не подтверждены"):
            get_rates_map(require_cbrf_provenance=True)

    def test_unverified_map_keeps_legacy_fallback_for_non_payment_consumers(self) -> None:
        with self.sm() as db:
            db.query(ExchangeRate).filter(ExchangeRate.currency_code == "EUR").delete()
            db.commit()
        rates = get_rates_map()
        self.assertEqual(rates["EUR"], FALLBACK["EUR"])

    def test_quote_foreign_currency_requests_verified_map(self) -> None:
        with patch(
            "app.services.payment_quote_service.get_rates_map",
            side_effect=ValueError("unverified FX"),
        ) as rates:
            with self.assertRaisesRegex(ValueError, "unverified FX"):
                build_payment_quote(
                    {
                        "hs_code": "8509400000",
                        "customs_value": 1_000,
                        "invoice_currency": "USD",
                    }
                )
        rates.assert_called_once_with(require_cbrf_provenance=True)

    def test_scenario_compare_foreign_currency_requests_verified_map(self) -> None:
        with patch(
            "app.services.scenario_compare_service.get_rates_map",
            side_effect=ValueError("unverified FX"),
        ) as rates:
            with self.assertRaisesRegex(ValueError, "unverified FX"):
                compare_scenarios_extended(
                    {
                        "base": {
                            "hs_code": "8509400000",
                            "customs_value": 1_000,
                            "currency": "USD",
                        },
                        "scenarios": [{"name": "A"}, {"name": "B"}],
                    }
                )
        rates.assert_called_once_with(require_cbrf_provenance=True)

    def test_calculator_rejects_foreign_currency_before_computation(self) -> None:
        request = CalculatorRequest(
            hs_code="8509400000",
            customs_value=1_000,
            invoice_currency="USD",
            save_history=False,
        )
        with (
            patch("app.api.calculator.is_leaf_hs_code", return_value=True),
            patch(
                "app.api.calculator.get_rates_map",
                side_effect=ValueError("unverified FX"),
            ) as rates,
            patch("app.api.calculator.compute_payments") as engine,
        ):
            with self.assertRaises(HTTPException) as error:
                asyncio.run(compute(request))
        self.assertEqual(error.exception.status_code, 400)
        self.assertIn("unverified FX", str(error.exception.detail))
        rates.assert_called_once_with(require_cbrf_provenance=True)
        engine.assert_not_called()


if __name__ == "__main__":
    unittest.main()
