"""Тесты is_active для trois_registry."""
from __future__ import annotations

import unittest
from datetime import date, timedelta

from app.services.trois_registry_sync import compute_trois_is_active


class TroisIsActiveTests(unittest.TestCase):
    def test_empty_valid_until_is_active(self) -> None:
        self.assertTrue(compute_trois_is_active(""))
        self.assertTrue(compute_trois_is_active(None))

    def test_future_date_is_active(self) -> None:
        future = date.today() + timedelta(days=30)
        vu = future.strftime("%Y.%m.%d")
        self.assertTrue(compute_trois_is_active(vu))

    def test_past_date_is_inactive(self) -> None:
        self.assertFalse(compute_trois_is_active("2010.12.31"))


if __name__ == "__main__":
    unittest.main()
