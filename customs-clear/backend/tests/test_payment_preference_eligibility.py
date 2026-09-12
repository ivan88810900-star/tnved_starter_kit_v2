"""Country seeds cannot establish commodity- and shipment-specific eligibility.

These tests use no local customs data, clock assumptions, external calls or DB
writes. The deliberately fictitious country guards against a country blacklist.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import payment_engine as engine
from app.services import payment_quote_service as quotes


@pytest.fixture
def payment_data(monkeypatch):
    rate = SimpleNamespace(
        duty_rate="10%", vat_import_rate=22.0, vat_rule="none", vat_rule_basis="",
        excise_type="none", excise_value=0.0, excise_basis="",
        antidumping_type="none", antidumping_value=0.0,
        antidumping_condition="", antidumping_countries="", source_revision="test",
    )
    data = SimpleNamespace(coefficient=0.75, duty_rule=engine._FallbackDutyRule(
        commodity_code="8509400000", type="ad_valorem", ad_valorem_pct=10.0,
        specific_amount=None, specific_currency="", specific_uom="",
    ), geo_override=None)
    monkeypatch.setattr(engine, "SessionLocal", lambda: pytest.fail("Unexpected database access"))
    monkeypatch.setattr(engine, "find_rate_for_hs", lambda _: (rate, 10))
    monkeypatch.setattr(engine, "_find_duty_rule_for_hs", lambda _: (data.duty_rule, 10 if data.duty_rule else 0))
    monkeypatch.setattr(engine, "_find_vat_preference", lambda _: (None, 0))
    monkeypatch.setattr(engine, "get_country_risk_by_iso", lambda _: None)
    monkeypatch.setattr(engine, "find_geo_embargo_match", lambda *a, **k: None)
    monkeypatch.setattr(engine, "find_geo_duty_override_row", lambda *a, **k: data.geo_override)
    monkeypatch.setattr(engine, "get_tariff_preference", lambda country: SimpleNamespace(
        duty_coefficient=1.0 if country == "CN" else data.coefficient,
        preference_type="legacy_seed", legal_ref="Historical country seed",
    ))
    monkeypatch.setattr(engine, "_resolve_special_duties", lambda **k: (0.0, []))
    monkeypatch.setattr(engine, "get_recycling_fee", lambda *a, **k: [])
    monkeypatch.setattr(engine, "calculate_customs_fee", lambda _: 1_000.0)
    monkeypatch.setattr(engine, "get_integrated_data_stats", lambda: {"hs_rates_count": 1})
    monkeypatch.setattr(engine, "get_tnved_context_for_hs", lambda _: {"title": "Test goods"})
    monkeypatch.setattr("app.services.rate_display.resolve_excise_for_hs", lambda _: ("none", 0.0, ""))
    monkeypatch.setattr(quotes, "compute_payments", engine.compute_payments)
    monkeypatch.setattr(quotes, "get_rates_map", lambda: {"RUB": 1.0})
    monkeypatch.setattr(quotes, "canonical_anchor_for_hs", lambda _: None)
    monkeypatch.setattr(quotes, "_special_duties_configured_for_hs", lambda _: True)
    return data


def _payload(**extra):
    return {"hs_code": "8509400000", "country": "BR", "customs_value": 100_000,
            "insurance": 0, **extra}


@pytest.mark.parametrize("country", ["BR", "IN", "TR", "ZZ"])
@pytest.mark.parametrize("coefficient", [0.0, 0.5, 0.75])
def test_legacy_country_discount_remains_undiscounted_estimate(payment_data, country, coefficient):
    payment_data.coefficient = coefficient
    result = engine.compute_payments(_payload(country=country))
    assert result["status"] == "REVIEW_REQUIRED"
    assert result["amounts_provisional"] is True
    assert result["breakdown"]["duty"] == 10_000
    assert result["breakdown"]["ad_valorem_amount"] == 10_000
    assert result["breakdown"]["vat_base"] == 110_000
    assert result["breakdown"]["vat"] == 24_200
    assert result["breakdown"]["total_payable"] == 35_200
    pref = result["tariff_preference"]
    assert pref["applied"] is False
    assert pref["eligibility_verified"] is False
    assert pref["status"] == "needs_review"
    assert pref["candidate_duty_coefficient"] == coefficient
    assert pref["duty_coefficient"] == 1
    assert pref["source_kind"] == "legacy_country_tariff_preferences"
    assert set(pref["missing_eligibility"]) == {
        "current_regime", "exact_code_and_date", "origin_and_goods_status",
        "origin_evidence", "shipment_conditions_and_exceptions",
    }
    assert pref["reason"] in result["legal_basis"]["duty"]
    assert result["data_quality"]["tariff_preference_warning"] == pref["reason"]
    assert result["data_quality"]["amounts_provisional"] is True


@pytest.mark.parametrize("claims", [
    {"eligibility_verified": True, "apply_tariff_preference": True},
    {"certificate_of_origin": "FORM_A", "origin_confirmed": True, "direct_shipment": True},
    {"as_of": "2026-09-10", "preferential_goods": True, "regime_verified": True},
    {"tariff_preference": {"applied": True, "eligibility_verified": True, "duty_coefficient": 0}},
    {"amounts_provisional": False, "status": "OK", "_tariff_preference_verified": True},
])
def test_caller_claims_do_not_bypass_review(payment_data, claims):
    if "as_of" in claims:
        with pytest.raises(ValueError, match="as_of"):
            engine.compute_payments(_payload(**claims))
        return
    result = engine.compute_payments(_payload(**claims))
    assert result["status"] == "REVIEW_REQUIRED"
    assert result["tariff_preference"]["applied"] is False
    assert result["breakdown"]["duty"] == 10_000


@pytest.mark.parametrize("coefficient, expected_duty, applied", [(1.0, 10_000, False), (2.0, 20_000, True)])
def test_mfn_and_increased_coefficients_are_unchanged(payment_data, coefficient, expected_duty, applied):
    payment_data.coefficient = coefficient
    result = engine.compute_payments(_payload())
    assert result["status"] == "OK"
    assert result["amounts_provisional"] is False
    assert result["breakdown"]["duty"] == expected_duty
    assert result["tariff_preference"]["applied"] is applied


@pytest.mark.parametrize("manual_rate", [0.0, 5.0, 17.0])
def test_explicit_manual_duty_is_not_replaced_or_discounted(payment_data, manual_rate):
    result = engine.compute_payments(_payload(duty_rate=manual_rate))
    assert result["status"] == "OK"
    assert result["amounts_provisional"] is False
    assert result["tariff_preference"]["applied"] is False
    assert result["breakdown"]["selected_rule"] == "manual_rate"
    assert result["breakdown"]["duty"] == 1_000 * manual_rate


def test_geo_override_path_is_unchanged(payment_data):
    payment_data.duty_rule = None
    payment_data.geo_override = SimpleNamespace(duty_rate="35%", document_basis="Geo fixture", document_link="")
    result = engine.compute_payments(_payload())
    assert result["status"] == "OK"
    assert result["amounts_provisional"] is False
    assert result["geo"]["duty_override_rate"] == 35
    assert result["breakdown"]["duty"] == 35_000
    assert result["tariff_preference"]["applied"] is False


def test_structured_specific_amount_is_not_discounted(payment_data):
    payment_data.duty_rule = engine._FallbackDutyRule(
        commodity_code="8509400000", type="specific", ad_valorem_pct=None,
        specific_amount=2.0, specific_currency="EUR", specific_uom="kg",
    )
    result = engine.compute_payments(_payload(net_weight_kg=100, _fx_rates={"EUR": 100}))
    assert result["status"] == "REVIEW_REQUIRED"
    assert result["breakdown"]["duty"] == 20_000
    assert result["breakdown"]["specific_amount_rub"] == 20_000


@pytest.mark.parametrize("overrides, expected_reasons", [
    ({}, {"duty_source_missing", "vat_source_missing"}),
    ({"duty_rate": 5.0}, {"vat_source_missing"}),
    ({"vat_rate": 10.0}, {"duty_source_missing"}),
    ({"duty_rate": 0.0, "vat_rate": 0.0}, set()),
    ({"duty_rate": 5.0, "vat_rate": 10.0}, set()),
])
def test_raw_missing_sources_are_provisional_unless_explicitly_overridden(
    payment_data, monkeypatch, overrides, expected_reasons,
):
    payment_data.duty_rule = None
    monkeypatch.setattr(engine, "find_rate_for_hs", lambda _: (None, 0))
    result = engine.compute_payments(_payload(country="CN", **overrides))
    assert set(result["payment_review_reasons"]) == expected_reasons
    assert result["amounts_provisional"] is bool(expected_reasons)
    assert result["status"] == ("REVIEW_REQUIRED" if expected_reasons else "OK")
    assert result["tariff_preference"] == {"applied": False}
    assert "tariff_preference_warning" not in result["data_quality"]
    if expected_reasons:
        assert result["payment_review_reason"] == result["data_quality"]["payment_review_reason"]
        assert "преференц" not in result["payment_review_reason"].lower()
    if "duty_source_missing" in expected_reasons:
        assert result["breakdown"]["duty"] == 0
        assert "не подтверждает нулевую ставку" in result["legal_basis"]["duty"]
        assert "применена ставка 0" not in result["legal_basis"]["duty"]


def test_structured_duty_does_not_establish_missing_vat_rate(payment_data, monkeypatch):
    monkeypatch.setattr(engine, "find_rate_for_hs", lambda _: (None, 0))
    result = engine.compute_payments(_payload(country="CN"))
    assert result["breakdown"]["duty"] == 10_000
    assert result["payment_review_reasons"] == ["vat_source_missing"]
    assert result["status"] == "REVIEW_REQUIRED"
    quote = quotes.build_payment_quote(_payload(country="CN"))
    lines = {line.code: line for line in quote.line_items}
    assert lines["duty"].status == "applied"
    assert lines["duty"].amount_rub == 10_000
    assert lines["vat"].status == "manual_review_required"
    assert lines["vat"].amount_rub is None
    assert quote.total_payable_rub is None


def test_vat_preference_is_an_independent_source_but_duty_stays_unknown(payment_data, monkeypatch):
    payment_data.duty_rule = None
    monkeypatch.setattr(engine, "find_rate_for_hs", lambda _: (None, 0))
    monkeypatch.setattr(engine, "_find_vat_preference", lambda _: (
        SimpleNamespace(vat_rate=10, decree_info="Fixture VAT source", comment=""), 10,
    ))
    result = engine.compute_payments(_payload(country="CN"))
    assert result["payment_review_reasons"] == ["duty_source_missing"]
    assert result["breakdown"]["vat_rate"] == 10
    assert result["status"] == "REVIEW_REQUIRED"


def test_geo_duty_and_explicit_vat_do_not_require_missing_rate_fallback(payment_data, monkeypatch):
    payment_data.duty_rule = None
    payment_data.geo_override = SimpleNamespace(duty_rate="35%", document_basis="Geo fixture", document_link="")
    monkeypatch.setattr(engine, "find_rate_for_hs", lambda _: (None, 0))
    result = engine.compute_payments(_payload(country="CN", vat_rate=10))
    assert result["status"] == "OK"
    assert result["payment_review_reasons"] == []
    assert result["breakdown"]["duty"] == 35_000
    assert "geo_special_duties" in result["legal_basis"]["duty"]
    quote = quotes.build_payment_quote(_payload(country="CN", vat_rate=10))
    lines = {line.code: line for line in quote.line_items}
    assert lines["duty"].status == "applied"
    assert lines["duty"].amount_rub == 35_000
    # The explicit VAT percentage cannot determine a base with unknown excise/AD.
    assert lines["vat"].status == "manual_review_required"
    assert lines["vat"].amount_rub is None


def test_known_zero_duty_is_distinct_from_missing_zero_fallback(payment_data):
    payment_data.duty_rule.ad_valorem_pct = 0.0
    result = engine.compute_payments(_payload(country="CN"))
    assert result["breakdown"]["duty"] == 0
    assert result["breakdown"]["duty_rate"] == 0
    assert result["status"] == "OK"
    assert result["amounts_provisional"] is False
    assert result["payment_review_reasons"] == []


def test_caller_source_claims_and_reduced_vat_flag_do_not_verify_missing_sources(payment_data, monkeypatch):
    payment_data.duty_rule = None
    monkeypatch.setattr(engine, "find_rate_for_hs", lambda _: (None, 0))
    result = engine.compute_payments(_payload(
        country="CN", apply_reduced_vat=True, amounts_provisional=False,
        status="OK", duty_source_verified=True, vat_source_verified=True,
        data_quality={"match_length": 10}, payment_review_reasons=[],
    ))
    assert result["status"] == "REVIEW_REQUIRED"
    assert result["payment_review_reasons"] == ["duty_source_missing", "vat_source_missing"]
    assert result["breakdown"]["vat_rate"] == 10  # Existing arithmetic remains an estimate.


def test_pending_quote_excludes_provisional_duty_and_vat_from_known_amounts(payment_data):
    quote = quotes.build_payment_quote(_payload())
    lines = {line.code: line for line in quote.line_items}
    assert quote.status == "REVIEW_REQUIRED"
    for code in ("duty", "vat"):
        assert lines[code].status == "manual_review_required"
        assert lines[code].amount_rub is None
        assert any(w.code == f"{code}_manual_review" for w in quote.warnings)
    assert lines["vat"].basis_amount_rub is None
    assert quote.total_payable_rub is None
    assert quote.total_partial_rub == 1_000
    assumptions = {item.key: item for item in quote.assumptions}
    assert assumptions["provisional_duty_rub"].value == "10 000.00 RUB"
    assert assumptions["provisional_vat_rub"].value == "24 200.00 RUB"
    assert assumptions["provisional_total_payable_rub"].value == "35 200.00 RUB"
    assert "Предварительная" in assumptions["provisional_total_payable_rub"].label


def test_normal_quote_retains_known_total(payment_data):
    quote = quotes.build_payment_quote(_payload(country="CN"))
    assert quote.status == "OK"
    assert quote.total_payable_rub == 35_200
    assert quote.total_partial_rub == 35_200
    assert not any(item.key.startswith("provisional_") for item in quote.assumptions)


def test_unknown_duty_and_dependent_vat_are_not_known_partial_amounts(payment_data, monkeypatch):
    payment_data.duty_rule = None
    monkeypatch.setattr(engine, "find_rate_for_hs", lambda _: (None, 0))
    quote = quotes.build_payment_quote(_payload(country="CN"))
    lines = {line.code: line for line in quote.line_items}
    assert lines["duty"].status == "unknown"
    assert lines["duty"].amount_rub is None
    assert lines["vat"].status == "manual_review_required"
    assert lines["vat"].amount_rub is None
    assert lines["vat"].basis_amount_rub is None
    assert quote.total_payable_rub is None
    assert quote.total_partial_rub == 1_000
    assumptions = {item.key: item for item in quote.assumptions}
    assert "payment_source_review" in assumptions
    assert "tariff_preference_review" not in assumptions
    assert all("без преференции" not in item.label for item in quote.assumptions)
    assert all("преференц" not in item.message.lower() for item in quote.warnings)


def test_manual_duty_for_unknown_code_is_preserved_but_unknown_vat_is_blocked(payment_data, monkeypatch):
    payment_data.duty_rule = None
    monkeypatch.setattr(engine, "find_rate_for_hs", lambda _: (None, 0))
    quote = quotes.build_payment_quote(_payload(country="CN", duty_rate=5))
    lines = {line.code: line for line in quote.line_items}
    assert lines["duty"].status == "manual_override"
    assert lines["duty"].amount_rub == 5_000
    assert lines["vat"].status == "manual_review_required"
    assert lines["vat"].amount_rub is None
    assert quote.total_payable_rub is None
    assert quote.total_partial_rub == 6_000


def test_manual_vat_percentage_cannot_resolve_unknown_excise_and_antidumping_base(payment_data, monkeypatch):
    payment_data.duty_rule = None
    monkeypatch.setattr(engine, "find_rate_for_hs", lambda _: (None, 0))
    quote = quotes.build_payment_quote(_payload(country="CN", duty_rate=5, vat_rate=10))
    lines = {line.code: line for line in quote.line_items}
    assert lines["duty"].status == "manual_override"
    assert lines["duty"].amount_rub == 5_000
    assert lines["vat"].status == "manual_review_required"
    assert lines["vat"].amount_rub is None
    assert quote.total_partial_rub == 6_000
    # Explicit duty/VAT do not resolve the other unknown charges for this code.
    assert quote.total_payable_rub is None


@pytest.mark.parametrize("countries", [("BR", "CN"), ("CN", "BR")])
def test_pending_comparison_never_reports_savings(payment_data, countries):
    result = engine.compare_payment_scenarios({
        "shared": {"customs_value": 100_000},
        "scenarios": [{"hs_code": "8509400000", "country": country} for country in countries],
    })
    assert result["status"] == "REVIEW_REQUIRED"
    assert result["amounts_provisional"] is True
    assert all(row["delta_total_vs_first_rub"] is None for row in result["scenarios"])
    assert all(row["total_payable"] == 35_200 for row in result["scenarios"])
    pending = next(row for row in result["scenarios"] if row["country"] == "BR")
    assert pending["payment_result"]["tariff_preference"]["status"] == "needs_review"
    assert pending["tariff_preference"]["applied"] is False


def test_comparison_preserves_manual_result_and_effective_inputs(payment_data):
    result = engine.compare_payment_scenarios({
        "shared": {"customs_value": 100_000, "net_weight_kg": 15, "extra_quantity": 4,
                   "invoice_currency": "RUB", "apply_reduced_vat": False},
        "scenarios": [
            {"hs_code": "8509400000", "country": "CN"},
            {"hs_code": "8509400000", "country": "BR", "duty_rate": 5},
        ],
    })
    assert result["status"] == "OK"
    assert result["amounts_provisional"] is False
    manual = result["scenarios"][1]
    assert manual["delta_total_vs_first_rub"] == -6_100
    assert manual["payment_result"]["breakdown"]["selected_rule"] == "manual_rate"
    assert manual["calculation_payload"]["duty_rate"] == 5
    assert manual["calculation_payload"]["net_weight_kg"] == 15
    assert manual["calculation_payload"]["extra_quantity"] == 4


def test_missing_source_comparison_preserves_reason_and_suppresses_savings(payment_data, monkeypatch):
    payment_data.duty_rule = None
    monkeypatch.setattr(engine, "find_rate_for_hs", lambda _: (None, 0))
    result = engine.compare_payment_scenarios({
        "shared": {"customs_value": 100_000, "country": "CN"},
        "scenarios": [
            {"hs_code": "8509400000"},
            {"hs_code": "8509400000", "duty_rate": 5, "vat_rate": 10},
        ],
    })
    assert result["status"] == "REVIEW_REQUIRED"
    assert result["amounts_provisional"] is True
    assert all(row["delta_total_vs_first_rub"] is None for row in result["scenarios"])
    unknown = result["scenarios"][0]
    assert unknown["payment_review_reason"] == unknown["payment_result"]["payment_review_reason"]
    assert set(unknown["payment_review_reasons"]) == {"duty_source_missing", "vat_source_missing"}
    assert "reason" not in unknown["tariff_preference"]
