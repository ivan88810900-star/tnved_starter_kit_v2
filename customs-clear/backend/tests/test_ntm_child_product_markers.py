"""Child-product description gates must not match unrelated ``дет*`` words."""

from __future__ import annotations

import copy

import pytest

from app.services.non_tariff_service import (
    _drop_spurious_ai_measures,
    _is_child_product_description,
    _sanitize_ntm_rules_for_position,
)
from app.services.ntm_v2_official_sgr_dataset_validation import validate_official_sgr_dataset
from app.services.ntm_v2_official_sgr_import import (
    evaluate_official_sgr_from_seed_payload,
    load_official_sgr_payload,
)


@pytest.mark.parametrize(
    "description",
    [
        "Детокс-крем для взрослых",
        "Деталь косметического набора",
        "Крем с детоксицирующим эффектом",
    ],
)
def test_unrelated_det_prefix_does_not_keep_legacy_sgr(description: str) -> None:
    rules = [{"required_permits": ["СГР", "ДС"]}]

    sanitized = _sanitize_ntm_rules_for_position("3304990000", description, rules)

    assert sanitized[0]["required_permits"] == ["ДС"]


@pytest.mark.parametrize(
    "description",
    [
        "Детский крем",
        "Крем для детей",
        "Крем для младенцев",
        "Baby cream",
    ],
)
def test_explicit_child_description_keeps_legacy_sgr(description: str) -> None:
    rules = [{"required_permits": ["СГР", "ДС"]}]

    sanitized = _sanitize_ntm_rules_for_position("3304990000", description, rules)

    assert sanitized[0]["required_permits"] == ["СГР", "ДС"]


@pytest.mark.parametrize(
    "description",
    [
        "недетский крем",
        "не детский крем",
        "НЕ-ДЕТСКИЙ крем",
        "крем не\u00a0для детей",
        "крем без детских отдушек",
    ],
)
def test_negated_child_audience_fails_closed_at_service_gate(description: str) -> None:
    assert _is_child_product_description(description) is False


@pytest.mark.parametrize(
    "description",
    [
        "детский крем",
        "крем для детей",
        "крем для взрослых и детей",
        "крем не только для детей, но и для взрослых",
    ],
)
def test_explicit_or_mixed_child_audience_remains_true(description: str) -> None:
    assert _is_child_product_description(description) is True


def test_mixed_adult_and_child_audience_keeps_legacy_and_ai_sgr() -> None:
    description = "Крем универсальный для взрослых и детей"
    rules = [{"required_permits": ["СГР", "ДС"]}]
    measures = [
        {"source_level": "ai_enriched", "measure_type": "sgr", "description": "СГР"},
        {"source_level": "ai_enriched", "measure_type": "declaration", "description": "ДС"},
    ]

    sanitized = _sanitize_ntm_rules_for_position("3304990000", description, rules)
    filtered = _drop_spurious_ai_measures("3304990000", description, measures)

    assert sanitized[0]["required_permits"] == ["СГР", "ДС"]
    assert [row["measure_type"] for row in filtered] == ["sgr", "declaration"]


@pytest.mark.parametrize(
    "description",
    [
        "Крем универсальный для взрослых",
        "Крем 18+",
        "Крем не для детей",
    ],
)
def test_adult_only_or_explicitly_excluded_audience_drops_legacy_sgr(description: str) -> None:
    rules = [{"required_permits": ["СГР", "ДС"]}]

    sanitized = _sanitize_ntm_rules_for_position("3304990000", description, rules)

    assert sanitized[0]["required_permits"] == ["ДС"]


def test_unrelated_det_prefix_drops_ai_sgr() -> None:
    measures = [
        {"source_level": "ai_enriched", "measure_type": "sgr", "description": "СГР"},
        {"source_level": "ai_enriched", "measure_type": "declaration", "description": "ДС"},
    ]

    filtered = _drop_spurious_ai_measures("3304990000", "Детокс-крем для взрослых", measures)

    assert [row["measure_type"] for row in filtered] == ["declaration"]


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        ("Детокс-крем для взрослых", False),
        ("Деталь косметического набора", False),
        ("Детский крем", True),
        ("Крем для детей", True),
        ("Крем для младенцев", True),
        ("Baby cream", True),
        ("Крем универсальный для взрослых и детей", True),
        ("Крем 18+", False),
        ("Крем не для детей", False),
        ("недетский крем", False),
        ("не детский крем", False),
        ("крем без детских отдушек", False),
        ("крем для взрослых и детей", True),
    ],
)
def test_official_3304_child_rule_uses_explicit_child_markers(
    description: str,
    expected: bool,
) -> None:
    result = evaluate_official_sgr_from_seed_payload(
        load_official_sgr_payload(),
        "3304990000",
        description,
    )

    assert result["has_definite_sgr"] is expected


def test_validator_rejects_ambiguous_det_marker_for_definite_3304() -> None:
    payload = copy.deepcopy(load_official_sgr_payload())
    rule = next(row for row in payload["rules"] if row["rule_id"] == "eec299-3304-cosmetics-child-definite")
    rule["description_contains_any"] = ["дет"]

    result = validate_official_sgr_dataset(payload)

    assert result["valid"] is False
    assert any(error["code"] == "ambiguous_3304_child_marker" for error in result["errors"])
