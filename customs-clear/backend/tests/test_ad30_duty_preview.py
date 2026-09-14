"""Hypothetical source-row operands are not legally applicable AD30 rates."""
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal, Inexact, Rounded, localcontext

import pytest

from app.services.ad30_duty_preview import preview_ad30_duty
from app.services.ad30_source_facts import load_ad30_source_facts


def candidate_facts(**changes):
    facts = {
        "direction": "import", "destination": "RU", "origin_country": "CN",
        "commodity_code": "7306402009", "tubular_product": True,
        "welded": True, "corrosion_resistant_steel": True,
        "cross_section": "round", "wall_thickness_mm": "0.4",
        "outer_diameter_mm": "6",
    }
    facts.update(changes)
    return facts


def preview(**changes):
    values = dict(as_of=date(2026, 9, 14), facts=candidate_facts(),
                  source_row_id="foshan_vinmay", customs_value="1000", currency="RUB")
    values.update(changes)
    return preview_ad30_duty(**values)


def assert_non_admitted(result):
    assert result["legal_applicability"] == "unavailable"
    assert result["temporal_applicability"] == "unavailable"
    assert result["review_required"] is True
    assert result["final_payable_amount"] is None
    for field in (
        "original_artifacts_verified", "source_text_verified", "producer_identity_verified",
        "amendment_history_verified", "durable_legal_retention_attested", "legal_review_verified",
        "legal_approval", "applied", "final_payable", "production_ready", "can_promote",
        "active_rates_written", "db_mutated", "rounding_applied",
    ):
        assert result[field] is False, field


@pytest.mark.parametrize("row,literal,expected", [
    ("foshan_vinmay", "14,62", "146.20"),
    ("guangdong_sumwin", "17,28", "172.80"),
    ("other_producers", "17,28", "172.80"),
])
def test_each_explicit_source_row_is_hypothetical_exact_arithmetic(row, literal, expected):
    result = preview(source_row_id=row)
    assert result["status"] == "calculated"
    assert result["assessment"]["candidate_scope"] == "matches_source_candidate"
    assert result["amount"] == Decimal(expected)
    assert result["selected_source_row"]["row_id"] == row
    assert result["selected_source_row"]["rate_percent_literal"] == literal
    assert result["selected_source_row"]["evidence_ids"]
    assert result["row_selection_kind"] == "hypothetical_source_row"
    calculation = result["calculation"]
    assert calculation.trace[0].operands == (Decimal(1000), Decimal(literal.replace(",", ".")), Decimal(100))
    assert calculation.amount == result["amount"]
    assert calculation.source_evidence_verified is False
    assert result["source_record_integrity_verified"] is True
    assert result["source_dossier_sha256"] == result["assessment"]["source_dossier_sha256"]
    assert_non_admitted(result)


@pytest.mark.parametrize("as_of", [date(2020, 1, 1), date(2026, 3, 14), date(2026, 9, 14), date(2032, 1, 1)])
def test_date_is_retained_without_creating_a_historical_legal_interval(as_of):
    result = preview(as_of=as_of)
    assert result["as_of"] == as_of.isoformat()
    assert result["calculation"].as_of == as_of
    assert_non_admitted(result)


@pytest.mark.parametrize("changes", [
    {"wall_thickness_mm": "6", "outer_diameter_mm": "115"},
    {"cross_section": "square", "wall_thickness_mm": "6", "perimeter_mm": "400"},
    {"cross_section": "rectangular", "wall_thickness_mm": "6", "perimeter_mm": "400", "max_side_mm": "120"},
])
def test_all_three_shapes_use_their_explicit_source_bounds(changes):
    result = preview(facts=candidate_facts(**changes))
    assert result["status"] == "calculated"
    assert result["amount"] == Decimal("146.20")
    assert_non_admitted(result)


@pytest.mark.parametrize("as_of", [None, "2026-09-14", datetime(2026, 9, 14), True, 20260914])
def test_no_current_date_default_or_date_coercion(as_of):
    with pytest.raises(ValueError):
        preview(as_of=as_of)


@pytest.mark.parametrize("changes,missing", [
    ({"source_row_id": None}, ["source_row_id"]),
    ({"customs_value": None}, ["customs_value"]),
    ({"source_row_id": None, "customs_value": None}, ["source_row_id", "customs_value"]),
])
def test_missing_operands_never_pick_other_producers_or_zero(changes, missing):
    result = preview(**changes)
    assert result["status"] == "needs_clarification"
    assert result["missing_inputs"] == missing
    assert result["amount"] is None and result["calculation"] is None
    assert_non_admitted(result)


@pytest.mark.parametrize("row", ["Foshan Vinmay Stainless Steel Co., Ltd.", "unknown", "", 1, True, [], "x" * 65])
def test_producer_names_unknown_rows_and_bad_types_never_select_a_rate(row):
    with pytest.raises(ValueError):
        preview(source_row_id=row)


@pytest.mark.parametrize("facts", [
    {}, candidate_facts(wall_thickness_mm=None), candidate_facts(outer_diameter_mm=None),
    candidate_facts(origin_country=None), candidate_facts(welded=None),
])
def test_incomplete_product_inputs_withhold_all_hypothetical_money(facts):
    result = preview(facts=facts)
    assert result["assessment"]["candidate_scope"] == "needs_clarification"
    assert result["status"] == "needs_clarification"
    assert result["amount"] is None and result["calculation"] is None
    assert_non_admitted(result)


@pytest.mark.parametrize("facts", [
    candidate_facts(origin_country="DE"), candidate_facts(welded=False),
    candidate_facts(commodity_code="8501100000"), candidate_facts(wall_thickness_mm="6.01", outer_diameter_mm="100"),
    candidate_facts(outer_diameter_mm="115.01"), candidate_facts(direction="export"),
])
def test_outside_literal_scope_is_never_interpreted_as_zero_liability(facts):
    result = preview(facts=facts)
    assert result["status"] == "unavailable"
    assert result["assessment"]["candidate_scope"] == "outside_source_candidate"
    assert result["amount"] is None and result["calculation"] is None
    assert_non_admitted(result)


@pytest.mark.parametrize("value", [True, 1.5, "-1", "NaN", "Infinity", "1e3", Decimal("NaN"), Decimal("1e999999"), "9" * 25, [], {}])
def test_invalid_money_is_rejected_even_before_scope_exclusion(value):
    with pytest.raises(ValueError):
        preview(customs_value=value, facts=candidate_facts(origin_country="DE"))


@pytest.mark.parametrize("currency", [None, "rub", "CNY", "", True])
def test_unsupported_currency_is_not_converted(currency):
    with pytest.raises(ValueError):
        preview(currency=currency)


def test_explicit_zero_is_distinct_from_missing_customs_value():
    result = preview(customs_value="0")
    assert result["status"] == "calculated" and result["amount"] == Decimal(0)
    assert_non_admitted(result)


def test_subcent_and_low_decimal_context_are_exact_without_rounding():
    ordinary = preview(customs_value="0.01")
    assert ordinary["amount"] == Decimal("0.001462")
    with localcontext() as context:
        context.prec = 2
        context.Emax = 2
        context.Emin = -2
        context.traps[Inexact] = True
        context.traps[Rounded] = True
        stressed = preview(customs_value="0.01")
    assert stressed == ordinary
    assert_non_admitted(stressed)


def test_source_row_mutation_cannot_create_hypothetical_money():
    source = load_ad30_source_facts()
    changed = replace(source.rate_rows[0], rate_percent_literal="0")
    forged = replace(source, rate_rows=(changed,) + source.rate_rows[1:])
    with pytest.raises(ValueError):
        preview(source_facts=forged)


@pytest.mark.parametrize("key", ["assessment", "legal_approval", "producer_identity_verified", "can_promote"])
def test_caller_assessments_and_approval_markers_are_not_arguments(key):
    with pytest.raises(TypeError):
        preview(**{key: True})
