"""Regression tests for vat_preferences audit #161 fix."""

from __future__ import annotations

import unittest

from app.db import SessionLocal
from app.models.tnved import VatPreference
from app.services.payment_engine import get_effective_vat_rate


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
