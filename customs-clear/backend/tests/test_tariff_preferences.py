"""Tests for country tariff preferences and payment engine integration."""
from __future__ import annotations

import pytest
from sqlalchemy import text

from app.db import SessionLocal
from app.services.normative_store import get_tariff_preference


class TestCountryTariffPreferencesData:
    @pytest.fixture(autouse=True)
    def _db(self):
        self.db = SessionLocal()
        yield
        self.db.close()

    def test_total_countries_above_150(self) -> None:
        count = self.db.execute(
            text("SELECT COUNT(*) FROM country_tariff_preferences")
        ).scalar()
        assert count >= 150, f"Expected >= 150 country preferences, got {count}"

    def test_eaeu_members_have_zero_coefficient(self) -> None:
        for iso in ("BY", "KZ", "AM", "KG"):
            pref = get_tariff_preference(iso)
            assert pref is not None, f"EAEU member {iso} not found"
            assert pref.duty_coefficient == 0.0, f"{iso} should have 0.0 coefficient"
            assert pref.preference_type == "eaeu"

    def test_sng_countries_have_zero_coefficient(self) -> None:
        for iso in ("UZ", "TJ", "MD"):
            pref = get_tariff_preference(iso)
            assert pref is not None, f"CIS country {iso} not found"
            assert pref.duty_coefficient == 0.0

    def test_gsp_countries_have_075_coefficient(self) -> None:
        for iso in ("CN", "BR", "IN", "TR"):
            pref = get_tariff_preference(iso)
            assert pref is not None, f"GSP country {iso} not found"
            assert pref.duty_coefficient == 0.75, f"{iso} should have 0.75 coefficient"
            assert pref.preference_type == "gsp"

    def test_ldc_countries_have_zero_coefficient(self) -> None:
        for iso in ("AF", "BD", "ET"):
            pref = get_tariff_preference(iso)
            assert pref is not None, f"LDC country {iso} not found"
            assert pref.duty_coefficient == 0.0

    def test_mfn_countries_have_full_coefficient(self) -> None:
        for iso in ("US", "DE", "JP", "KR"):
            pref = get_tariff_preference(iso)
            assert pref is not None, f"MFN country {iso} not found"
            assert pref.duty_coefficient == 1.0

    def test_non_mfn_has_double_coefficient(self) -> None:
        pref = get_tariff_preference("KP")
        assert pref is not None, "DPRK not found"
        assert pref.duty_coefficient == 2.0
        assert pref.preference_type == "non_mfn"

    def test_all_entries_have_legal_ref(self) -> None:
        missing = self.db.execute(text(
            "SELECT COUNT(*) FROM country_tariff_preferences "
            "WHERE legal_ref IS NULL OR legal_ref = ''"
        )).scalar()
        assert missing == 0, f"Found {missing} entries without legal_ref"

    def test_all_entries_have_effective_from(self) -> None:
        missing = self.db.execute(text(
            "SELECT COUNT(*) FROM country_tariff_preferences "
            "WHERE effective_from IS NULL OR effective_from = ''"
        )).scalar()
        assert missing == 0, f"Found {missing} entries without effective_from"

    def test_lookup_returns_none_for_unknown_country(self) -> None:
        pref = get_tariff_preference("XX")
        assert pref is None

    def test_lookup_case_insensitive(self) -> None:
        pref = get_tariff_preference("cn")
        assert pref is not None
        assert pref.preference_type == "gsp"


class TestTariffPreferencePaymentIntegration:
    def test_gsp_reduces_duty(self) -> None:
        from app.services.payment_engine import compute_payments

        base_result = compute_payments({
            "hs_code": "8509100000",
            "customs_value": 100000,
            "country": "US",
        })
        gsp_result = compute_payments({
            "hs_code": "8509100000",
            "customs_value": 100000,
            "country": "CN",
        })
        base_duty = base_result["breakdown"]["duty"]
        gsp_duty = gsp_result["breakdown"]["duty"]
        if base_duty > 0:
            assert gsp_duty < base_duty, (
                f"GSP duty ({gsp_duty}) should be less than MFN duty ({base_duty})"
            )

    def test_eaeu_zeroes_duty(self) -> None:
        from app.services.payment_engine import compute_payments

        result = compute_payments({
            "hs_code": "8509100000",
            "customs_value": 100000,
            "country": "BY",
        })
        assert result["breakdown"]["duty"] == 0.0, "EAEU member should have zero duty"
        assert result["tariff_preference"]["applied"] is True
        assert result["tariff_preference"]["duty_coefficient"] == 0.0

    def test_manual_duty_rate_overrides_preference(self) -> None:
        from app.services.payment_engine import compute_payments

        result = compute_payments({
            "hs_code": "8509100000",
            "customs_value": 100000,
            "country": "BY",
            "duty_rate": 10.0,
        })
        assert result["breakdown"]["duty"] == 10000.0, "Manual rate should override preference"
        assert result["tariff_preference"]["applied"] is False

    def test_tariff_pref_meta_in_response(self) -> None:
        from app.services.payment_engine import compute_payments

        result = compute_payments({
            "hs_code": "8509100000",
            "customs_value": 100000,
            "country": "CN",
        })
        assert "tariff_preference" in result
        pref = result["tariff_preference"]
        assert pref["applied"] is True
        assert pref["preference_type"] == "gsp"
        assert pref["duty_coefficient"] == 0.75

    def test_no_country_no_preference(self) -> None:
        from app.services.payment_engine import compute_payments

        result = compute_payments({
            "hs_code": "8509100000",
            "customs_value": 100000,
        })
        assert result["tariff_preference"]["applied"] is False
