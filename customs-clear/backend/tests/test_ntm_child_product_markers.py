"""Child-product description gates must not match unrelated ``дет*`` words."""

from __future__ import annotations

import copy

import pytest

from app.services.non_tariff_service import (
    _drop_spurious_ai_measures,
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
