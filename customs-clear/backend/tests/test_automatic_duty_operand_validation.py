"""Automatic duty operands must fail closed before payment arithmetic."""

from __future__ import annotations

import math
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

from app.models.tnved import HsDutyRule
from app.services.payment_engine import _compute_structured_duty, compute_payments


@contextmanager
def _isolated_legacy_rate(raw_value: object):
    """Run compute_payments without relying on seeded or external lookup state."""
    rate = AutomaticDutyOperandValidationTests._legacy_rate(raw_value)
    patches = (
        patch("app.services.payment_engine.find_rate_for_hs", return_value=(rate, 10)),
        patch("app.services.payment_engine._find_duty_rule_for_hs", return_value=(None, 0)),
        patch("app.services.rate_display.resolve_excise_for_hs", return_value=("none", 0.0, "")),
        patch("app.services.payment_engine._resolve_special_duties", return_value=(0.0, [])),
        patch("app.services.payment_engine.get_recycling_fee", return_value=[]),
        patch("app.services.payment_engine._find_vat_preference", return_value=(None, 0)),
        patch(
            "app.services.payment_engine.get_integrated_data_stats",
            return_value={"hs_rates_count": 1},
        ),
        patch("app.services.payment_engine.get_tnved_context_for_hs", return_value={}),
    )
    entered = []
    try:
        for item in patches:
            item.start()
            entered.append(item)
        yield
    finally:
        for item in reversed(entered):
            item.stop()


def _compute(
    *,
    rule_type: str = "ad_valorem",
    ad_valorem_pct: object | None = 5.0,
    specific_amount: object | None = None,
    auto_duty_rate: object = 7.0,
):
    rule = HsDutyRule(
        commodity_code="9999999999",
        type=rule_type,
        ad_valorem_pct=ad_valorem_pct,
        specific_amount=specific_amount,
        specific_currency="RUB",
        specific_uom="kg",
    )
    return _compute_structured_duty(
        customs_value=100_000.0,
        quantity=10.0,
        net_weight_kg=10.0,
        extra_quantity=None,
        duty_rule=rule,
        manual_duty_rate=None,
        auto_duty_rate=auto_duty_rate,
        fx_rates={"RUB": 1.0},
    )


class AutomaticDutyOperandValidationTests(unittest.TestCase):
    def test_invalid_ad_valorem_operands_fail_closed(self) -> None:
        for value in (-1.0, math.nan, math.inf, -math.inf, True, "bad"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "адвалорной ставки"):
                    _compute(ad_valorem_pct=value)

    def test_invalid_specific_operands_fail_closed(self) -> None:
        for value in (-1.0, math.nan, math.inf, -math.inf, True, "bad"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "специфической ставки"):
                    _compute(
                        rule_type="specific",
                        ad_valorem_pct=None,
                        specific_amount=value,
                    )

    def test_invalid_legacy_auto_rate_fails_closed(self) -> None:
        for value in (-1.0, math.nan, math.inf, -math.inf, True, "bad"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "ставки пошлины"):
                    _compute(auto_duty_rate=value)

    def test_zero_and_positive_operands_remain_valid(self) -> None:
        zero = _compute(ad_valorem_pct=0.0, auto_duty_rate=0.0)
        self.assertEqual(zero[0], 0.0)
        self.assertEqual(zero[1], 0.0)

        ad_valorem = _compute(ad_valorem_pct=5.0)
        self.assertEqual(ad_valorem[0], 5_000.0)
        self.assertEqual(ad_valorem[1], 5.0)

        specific = _compute(
            rule_type="specific",
            ad_valorem_pct=None,
            specific_amount=2.0,
        )
        self.assertEqual(specific[0], 20.0)
        self.assertEqual(specific[3], 20.0)

    def test_manual_override_does_not_admit_or_read_automatic_operands(self) -> None:
        rule = HsDutyRule(
            commodity_code="9999999998",
            type="combined_max",
            ad_valorem_pct=math.nan,
            specific_amount=math.inf,
            specific_currency="RUB",
            specific_uom="kg",
        )
        result = _compute_structured_duty(
            customs_value=100_000.0,
            quantity=10.0,
            net_weight_kg=10.0,
            extra_quantity=None,
            duty_rule=rule,
            manual_duty_rate=4.0,
            auto_duty_rate=math.nan,
            fx_rates={"RUB": 1.0},
        )
        self.assertEqual(result[0], 4_000.0)
        self.assertEqual(result[4], "manual_rate")

    def test_finite_operands_that_overflow_results_fail_closed_on_every_path(self) -> None:
        cases = (
            {"rule": None, "auto": 1e308},
            {"rule_type": "ad_valorem", "ad": 1e308},
            {"rule_type": "specific", "ad": None, "specific": 1e308},
            {"rule_type": "combined_max", "ad": 5.0, "specific": 1e308},
            # The infinite component must not be hidden by min(finite, inf).
            {"rule_type": "combined_min", "ad": 5.0, "specific": 1e308},
        )
        for case in cases:
            with self.subTest(case=case):
                if case.get("rule", "present") is None:
                    with self.assertRaisesRegex(ValueError, "результат автоматического расчета"):
                        _compute_structured_duty(
                            customs_value=100_000.0,
                            quantity=10.0,
                            net_weight_kg=10.0,
                            extra_quantity=None,
                            duty_rule=None,
                            manual_duty_rate=None,
                            auto_duty_rate=case["auto"],
                            fx_rates={"RUB": 1.0},
                        )
                else:
                    with self.assertRaisesRegex(ValueError, "результат автоматического расчета"):
                        _compute(
                            rule_type=case["rule_type"],
                            ad_valorem_pct=case["ad"],
                            specific_amount=case.get("specific"),
                        )

    @staticmethod
    def _legacy_rate(raw_value: object) -> SimpleNamespace:
        return SimpleNamespace(
            hs_code="9998000000",
            hs_prefix="9998",
            duty_rate=raw_value,
            vat_rule="none",
            vat_rule_basis="",
            vat_import_rate=22.0,
            excise_type="none",
            excise_value=0.0,
            excise_basis="",
            antidumping_type="none",
            antidumping_value=0.0,
            antidumping_condition="",
            antidumping_countries="",
            source_revision="test",
        )

    def test_compute_payments_rejects_corrupt_raw_legacy_rates(self) -> None:
        for value in (
            -5,
            "-5",
            "-5%",
            "−5%",
            "–5%",
            "—5%",
            math.nan,
            math.inf,
            -math.inf,
            True,
            "bad",
            b"5%",
            ["5%"],
            {"rate": "5%"},
        ):
            with self.subTest(value=value):
                with _isolated_legacy_rate(value):
                    with self.assertRaisesRegex(ValueError, "hs_rates"):
                        compute_payments({"hs_code": "9998000000", "customs_value": 100_000.0})

    def test_compute_payments_rejects_legacy_result_overflow_before_vat(self) -> None:
        huge_but_finite_decimal = "1" + ("0" * 307)
        with _isolated_legacy_rate(huge_but_finite_decimal):
            with self.assertRaisesRegex(ValueError, "результат автоматического расчета"):
                compute_payments({"hs_code": "9998000000", "customs_value": 100_000.0})

    def test_compute_payments_preserves_valid_legacy_formats(self) -> None:
        for value in ("0", "0%", "5", "5%", "10%, но не менее 0.2 евро/кг"):
            with self.subTest(value=value):
                with _isolated_legacy_rate(value):
                    result = compute_payments({"hs_code": "9998000000", "customs_value": 100_000.0})
                    self.assertEqual(result["status"], "OK")

    def test_compute_payments_manual_override_skips_corrupt_legacy_source(self) -> None:
        with _isolated_legacy_rate("bad"):
            result = compute_payments(
                {"hs_code": "9998000000", "customs_value": 100_000.0, "duty_rate": 4.0}
            )
        self.assertEqual(result["breakdown"]["duty"], 4_000.0)
        self.assertEqual(result["breakdown"]["selected_rule"], "manual_rate")


if __name__ == "__main__":
    unittest.main()
