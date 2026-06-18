"""Tests for Honest Mark marking requirements."""
from __future__ import annotations

import pytest
from sqlalchemy import text

from app.db import SessionLocal


class TestHonestMarkRequirements:
    @pytest.fixture(autouse=True)
    def _db(self):
        self.db = SessionLocal()
        yield
        self.db.close()

    def _marking_count(self, prefix: str) -> int:
        return self.db.execute(text(
            "SELECT COUNT(*) FROM non_tariff_measures "
            "WHERE measure_type = 'marking' AND quality = 'verified' "
            "AND commodity_code LIKE :pat"
        ), {"pat": f"{prefix}%"}).scalar()

    def test_tobacco_marking_exists(self) -> None:
        count = self._marking_count("2402")
        assert count >= 1, "Tobacco (2402) should have marking entries"

    def test_footwear_marking_exists(self) -> None:
        count = self._marking_count("6403")
        assert count >= 1, "Footwear (6403) should have marking entries"

    def test_medicines_marking_exists(self) -> None:
        count = self._marking_count("3004")
        assert count >= 1, "Medicines (3004) should have marking entries"

    def test_clothing_marking_exists(self) -> None:
        count = self._marking_count("6203")
        assert count >= 1, "Clothing (6203) should have marking entries"

    def test_dairy_marking_exists(self) -> None:
        count = self._marking_count("0401")
        assert count >= 1, "Dairy (0401) should have marking entries"

    def test_tires_marking_exists(self) -> None:
        count = self._marking_count("4011")
        assert count >= 1, "Tires (4011) should have marking entries"

    def test_water_marking_exists(self) -> None:
        count = self._marking_count("2201")
        assert count >= 1, "Packaged water (2201) should have marking entries"

    def test_beer_marking_exists(self) -> None:
        count = self._marking_count("2203")
        assert count >= 1, "Beer (2203) should have marking entries"

    def test_perfumery_marking_exists(self) -> None:
        count = self._marking_count("3303")
        assert count >= 1, "Perfumery (3303) should have marking entries"

    def test_canned_marking_exists(self) -> None:
        count = self._marking_count("1602")
        assert count >= 1, "Canned products (1602) should have marking entries"

    def test_fur_marking_exists(self) -> None:
        count = self._marking_count("4303")
        assert count >= 1, "Fur (4303) should have marking entries"

    def test_total_verified_marking_above_200(self) -> None:
        total = self.db.execute(text(
            "SELECT COUNT(*) FROM non_tariff_measures "
            "WHERE measure_type = 'marking' AND quality = 'verified'"
        )).scalar()
        assert total >= 200, f"Expected >= 200 verified marking entries, got {total}"

    def test_all_entries_have_regulatory_act(self) -> None:
        missing = self.db.execute(text(
            "SELECT COUNT(*) FROM non_tariff_measures "
            "WHERE measure_type = 'marking' AND quality = 'verified' "
            "AND (regulatory_act IS NULL OR regulatory_act = '')"
        )).scalar()
        assert missing == 0, f"Found {missing} marking entries without regulatory_act"
