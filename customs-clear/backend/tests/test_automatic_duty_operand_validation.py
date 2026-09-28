"""Automatic duty operands must fail closed before payment arithmetic."""

from __future__ import annotations

import math
import unittest

from app.models.tnved import HsDutyRule
from app.services.payment_engine import _compute_structured_duty


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


if __name__ == "__main__":
    unittest.main()
