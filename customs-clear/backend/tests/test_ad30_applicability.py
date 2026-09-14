"""Source-bound product candidate tests; none grants legal applicability."""

from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal, localcontext

import pytest

from app.services.ad30_applicability import assess_ad30_candidate
from app.services.ad30_source_facts import load_ad30_source_facts


DAY = date(2026, 9, 14)


def product(**changes):
    result = {
        "direction": "import",
        "destination": "RU",
        "origin_country": "CN",
        "commodity_code": "7306402009",
        "tubular_product": True,
        "welded": True,
        "corrosion_resistant_steel": True,
        "cross_section": "round",
        "wall_thickness_mm": "1",
        "outer_diameter_mm": "20",
    }
    result.update(changes)
    return result


def assess(facts=None, **kwargs):
    return assess_ad30_candidate(as_of=DAY, facts=product() if facts is None else facts, **kwargs)


def assert_unavailable_legal(result):
    assert result["legal_applicability"] == "unavailable"
    assert result["requires_manual_review"] is True
    assert result["producer_row_selected"] is None
    for key in (
        "legal_review_verified", "effective_dates_verified", "final_payable",
        "can_promote", "db_mutated", "source_evidence_verified",
        "original_artifacts_verified", "source_text_verified",
    ):
        assert result[key] is False
    assert "effective_dates_unverified" in result["review_blockers"]
    assert "complete_amendment_history_unverified" in result["review_blockers"]
    assert "producer_identity_and_succession_unverified" in result["review_blockers"]


@pytest.mark.parametrize("code", ["7306402009", "7306408001", "7306408008", "7306611009"])
@pytest.mark.parametrize("shape,measurements", [
    ("round", {"outer_diameter_mm": "20"}),
    ("square", {"perimeter_mm": "400"}),
    ("rectangular", {"perimeter_mm": "400", "max_side_mm": "120"}),
])
def test_source_code_and_declared_shape_predicates_are_independent(code, shape, measurements):
    # This is NOT a code-to-shape nomenclature mapping. That missing audit is
    # always carried by the legal blockers, including all these literal matches.
    facts = product(commodity_code=code, cross_section=shape)
    facts.pop("outer_diameter_mm")
    facts.update(measurements)
    result = assess(facts)
    assert result["candidate_scope"] == "matches_source_candidate"
    assert result["missing_facts"] == result["invalid_facts"] == result["contradictory_facts"] == []
    assert "historical_nomenclature_mapping_unverified" in result["review_blockers"]
    assert_unavailable_legal(result)


@pytest.mark.parametrize("destination", ["RU", "AM", "BY", "KG", "KZ"])
def test_all_explicit_eaeu_destination_identities(destination):
    assert assess(product(destination=destination))["candidate_scope"] == "matches_source_candidate"


@pytest.mark.parametrize("changes,scope", [
    ({"wall_thickness_mm": "0.4"}, "matches_source_candidate"),
    ({"wall_thickness_mm": "0.3999"}, "outside_source_candidate"),
    ({"wall_thickness_mm": "6", "outer_diameter_mm": "115"}, "matches_source_candidate"),
    ({"wall_thickness_mm": "6.0001"}, "outside_source_candidate"),
    ({"outer_diameter_mm": "6"}, "matches_source_candidate"),
    ({"outer_diameter_mm": "5.9999"}, "outside_source_candidate"),
    ({"outer_diameter_mm": "115"}, "matches_source_candidate"),
    ({"outer_diameter_mm": "115.0001"}, "outside_source_candidate"),
    ({"cross_section": "square", "perimeter_mm": "400"}, "matches_source_candidate"),
    ({"cross_section": "square", "perimeter_mm": "400.0001"}, "outside_source_candidate"),
    ({"cross_section": "rectangular", "perimeter_mm": "400", "max_side_mm": "120"}, "matches_source_candidate"),
    ({"cross_section": "rectangular", "perimeter_mm": "400.0001", "max_side_mm": "120"}, "outside_source_candidate"),
    ({"cross_section": "rectangular", "perimeter_mm": "400", "max_side_mm": "120.0001"}, "outside_source_candidate"),
])
def test_each_printed_dimension_boundary(changes, scope):
    result = assess(product(**changes))
    assert result["candidate_scope"] == scope
    assert_unavailable_legal(result)


@pytest.mark.parametrize("field,value", [
    ("direction", "export"), ("direction", "transit"),
    ("destination", "CN"), ("origin_country", "DE"),
    ("commodity_code", "8501100000"), ("tubular_product", False),
    ("welded", False), ("corrosion_resistant_steel", False),
    ("cross_section", "other"),
])
def test_known_false_conjunct_is_only_outside_this_candidate(field, value):
    result = assess(product(**{field: value}))
    assert result["candidate_scope"] == "outside_source_candidate"
    assert_unavailable_legal(result)


@pytest.mark.parametrize("field", list(product()))
@pytest.mark.parametrize("absent", [True, False])
def test_missing_or_null_each_required_round_fact_never_matches(field, absent):
    facts = product()
    if absent:
        facts.pop(field)
    else:
        facts[field] = None
    result = assess(facts)
    assert result["candidate_scope"] == "needs_clarification"
    assert field in result["missing_facts"]
    assert_unavailable_legal(result)


@pytest.mark.parametrize("shape,field", [
    ("square", "perimeter_mm"), ("rectangular", "perimeter_mm"),
    ("rectangular", "max_side_mm"),
])
def test_shape_specific_measurement_is_never_derived(shape, field):
    facts = product(cross_section=shape, perimeter_mm="400", max_side_mm="120")
    facts.pop(field)
    result = assess(facts)
    assert result["candidate_scope"] == "needs_clarification"
    assert field in result["missing_facts"]


@pytest.mark.parametrize("value", [
    True, False, 1.0, float("nan"), float("inf"), Decimal("NaN"),
    Decimal("Infinity"), Decimal("1e100000"), 10**100, "1e1", "1,5",
    "1 mm", "0.1 cm", " 1", "+1", "01", "1\n", "١", {}, [],
    "0", 0, -1, "-1", "0.0000000000001",
])
@pytest.mark.parametrize("field", ["wall_thickness_mm", "max_side_mm"])
def test_malformed_even_unused_measurement_has_priority_over_known_mismatch(field, value):
    result = assess(product(origin_country="DE", **{field: value}))
    assert result["candidate_scope"] == "needs_clarification"
    assert {item["field"] for item in result["invalid_facts"]} == {field}
    assert_unavailable_legal(result)


@pytest.mark.parametrize("field,value", [
    ("origin_country", "ZZ"), ("origin_country", "FR"),
    ("origin_country", "EU"), ("origin_country", "cn"),
    ("origin_country", ["CN"]), ("destination", "EAEU"),
    ("destination", "ZZ"), ("destination", {}),
    ("direction", "IMPORT"), ("direction", []),
    ("cross_section", "oval"), ("cross_section", {}),
    ("commodity_code", "7306"), ("commodity_code", 7306402009),
    ("commodity_code", "7306 40 200 9"), ("commodity_code", "７３０６４０２００９"),
    ("welded", 1), ("tubular_product", "true"), ("corrosion_resistant_steel", {}),
    ("producer_name", "Foshan Vinmay Stainless Steel Co., Ltd."),
    ("legal_review_verified", True),
])
def test_unverified_identity_and_wrong_types_are_not_negative_or_positive_legal_facts(field, value):
    result = assess(product(**{field: value}))
    assert result["candidate_scope"] == "needs_clarification"
    assert field in {item["field"] for item in result["invalid_facts"]}
    assert_unavailable_legal(result)


@pytest.mark.parametrize("changes,reason", [
    ({"cross_section": "rectangular", "perimeter_mm": "240", "max_side_mm": "120"}, "perimeter_conflicts_with_max_side"),
    ({"cross_section": "rectangular", "perimeter_mm": "401", "max_side_mm": "100"}, "perimeter_conflicts_with_max_side"),
])
def test_contradictory_supplied_geometry_stays_unresolved(changes, reason):
    result = assess(product(**changes))
    assert result["candidate_scope"] == "needs_clarification"
    assert reason in {item["reason"] for item in result["contradictory_facts"]}
    assert_unavailable_legal(result)


def test_missing_facts_do_not_hide_known_false_conjunct_but_no_legal_exclusion_is_issued():
    result = assess({"welded": False})
    assert result["candidate_scope"] == "outside_source_candidate"
    assert result["missing_facts"]
    assert_unavailable_legal(result)


@pytest.mark.parametrize("bad_date", [None, "2026-09-14", 20260914, True, datetime(2026, 9, 14)])
def test_no_date_default_or_datetime_coercion(bad_date):
    with pytest.raises(ValueError, match="explicit date"):
        assess_ad30_candidate(as_of=bad_date, facts=product())


@pytest.mark.parametrize("day", [date(2021, 3, 13), date(2021, 3, 14), date(2026, 3, 14), date(2026, 9, 8), date(2026, 10, 11), date(2031, 9, 8)])
def test_explicit_dates_are_recorded_without_claiming_effective_intervals(day):
    result = assess_ad30_candidate(as_of=day, facts=product())
    assert result["as_of"] == day.isoformat()
    assert result["candidate_scope"] == "matches_source_candidate"
    assert_unavailable_legal(result)


def test_result_binds_each_predicate_to_the_validated_source_dossier():
    source = load_ad30_source_facts()
    result = assess(source_facts=source)
    assert result["source_dossier_sha256"] == source.dossier_sha256
    evidence = {item["fact_id"]: item for item in result["source_evidence"]}
    for criterion in result["criteria"]:
        assert criterion["source_fact_ids"]
        for fact_id in criterion["source_fact_ids"]:
            reference = evidence[fact_id]
            original = next(item for item in source.facts if item.fact_id == fact_id)
            assert reference["body_sha256"] == original.body_sha256
            assert reference["json_pointer"] == original.json_pointer
            assert reference["page"] == original.page
            assert reference["evidence_file_sha256"] == original.evidence_file_sha256


def test_forged_source_bundle_is_revalidated():
    source = load_ad30_source_facts()
    with pytest.raises(ValueError):
        assess(source_facts=replace(source, dossier_sha256="0" * 64))


def test_assessment_does_not_mutate_inputs_or_depend_on_decimal_precision():
    facts = product(wall_thickness_mm=Decimal("0.4"), outer_diameter_mm=115)
    before = deepcopy(facts)
    expected = assess(facts)
    with localcontext() as context:
        context.prec = 2
        actual = assess(facts)
    assert actual == expected
    assert facts == before


@pytest.mark.parametrize("facts", [None, [], "CN", {1: True}, {"x" * 81: True}, {str(i): True for i in range(33)}])
def test_unbounded_or_invalid_fact_container_rejected(facts):
    with pytest.raises(ValueError):
        assess_ad30_candidate(as_of=DAY, facts=facts)
