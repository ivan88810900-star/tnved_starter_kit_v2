"""Сроки действия non_tariff_rules (valid_from / valid_to)."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest

from app.services.normative_store import (
    _non_tariff_rule_active_on,
    _parse_non_tariff_rule_date,
    find_non_tariff_rules_for_hs,
)


class TestParseNonTariffRuleDate:
    def test_empty(self) -> None:
        assert _parse_non_tariff_rule_date("") == ("open", None)
        assert _parse_non_tariff_rule_date("   ") == ("open", None)
        assert _parse_non_tariff_rule_date(None) == ("open", None)

    def test_iso(self) -> None:
        assert _parse_non_tariff_rule_date("2024-06-15") == ("ok", date(2024, 6, 15))

    def test_iso_prefix_only(self) -> None:
        assert _parse_non_tariff_rule_date("2024-06-15T12:00:00Z") == ("ok", date(2024, 6, 15))

    def test_invalid(self) -> None:
        assert _parse_non_tariff_rule_date("not-a-date") == ("invalid", None)
        assert _parse_non_tariff_rule_date("2024-13-40") == ("invalid", None)


class TestNonTariffRuleActiveOn:
    ref = date(2026, 5, 14)

    def test_no_bounds(self) -> None:
        assert _non_tariff_rule_active_on("", "", self.ref) is True
        assert _non_tariff_rule_active_on("  ", "  ", self.ref) is True

    def test_valid_from_past(self) -> None:
        assert _non_tariff_rule_active_on("2020-01-01", "", self.ref) is True

    def test_valid_from_future(self) -> None:
        assert _non_tariff_rule_active_on("2099-01-01", "", self.ref) is False

    def test_valid_to_future(self) -> None:
        assert _non_tariff_rule_active_on("", "2099-12-31", self.ref) is True

    def test_valid_to_past(self) -> None:
        assert _non_tariff_rule_active_on("", "2020-12-31", self.ref) is False

    def test_range_includes_as_of(self) -> None:
        assert _non_tariff_rule_active_on("2024-01-01", "2028-12-31", self.ref) is True

    def test_range_excludes_as_of_before(self) -> None:
        assert _non_tariff_rule_active_on("2030-01-01", "2031-12-31", self.ref) is False

    def test_range_excludes_as_of_after(self) -> None:
        assert _non_tariff_rule_active_on("2010-01-01", "2015-12-31", self.ref) is False

    def test_inclusive_bounds(self) -> None:
        assert _non_tariff_rule_active_on("2026-05-14", "2026-05-14", self.ref) is True

    @patch("app.services.normative_store.logger.warning")
    def test_invalid_valid_from_excludes_and_logs(self, mock_warn: object) -> None:
        assert _non_tariff_rule_active_on("nope", "", self.ref, rule_id=1, rule_name="t", hs_prefix="85") is False
        assert mock_warn.called

    @patch("app.services.normative_store.logger.warning")
    def test_invalid_valid_to_excludes_and_logs(self, mock_warn: object) -> None:
        assert _non_tariff_rule_active_on("", "bad-date", self.ref, rule_id=2, rule_name="t", hs_prefix="85") is False
        assert mock_warn.called


class TestFindNonTariffRulesAsOf:
    """Интеграция: параметр as_of не ломает вызов с пустым кодом."""

    def test_empty_hs(self) -> None:
        assert find_non_tariff_rules_for_hs("", as_of=date(2020, 1, 1)) == []
