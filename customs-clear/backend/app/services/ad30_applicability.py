"""Pure assessment of the retained Decision 12 product wording for review.

This is an interpretation candidate, not a legal-applicability service. It never
chooses a producer row, establishes an effective interval, or returns a duty.
Even a complete literal-scope match leaves legal applicability unavailable.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from fractions import Fraction

from .ad30_source_facts import (
    AD30SourceFacts,
    load_ad30_source_facts,
    validate_ad30_source_facts,
)
from .ett_manifest import EAEU_DESTINATIONS


_KNOWN_COUNTRIES = EAEU_DESTINATIONS | frozenset({
    "CN", "US", "DE", "GB", "JP", "KR", "IN", "TR",
})
# This deliberately bounded identity set is not a country/origin registry.
# A valid but unlisted identity is unresolved, never a known country mismatch.
_BOOLEANS = ("tubular_product", "welded", "corrosion_resistant_steel")
_MEASUREMENTS = (
    "wall_thickness_mm", "outer_diameter_mm", "perimeter_mm", "max_side_mm",
)
_FIELDS = frozenset({
    "direction", "destination", "origin_country", "commodity_code",
    "cross_section", *_BOOLEANS, *_MEASUREMENTS,
})
_SHAPES = frozenset({"round", "square", "rectangular", "other"})
_DECIMAL = re.compile(r"(?:0|[1-9][0-9]{0,23})(?:\.[0-9]{1,12})?\Z", re.ASCII)
_CODE = re.compile(r"[0-9]{10}\Z", re.ASCII)
_REVIEW_BLOCKERS = (
    "complete_amendment_history_unverified",
    "effective_dates_unverified",
    "historical_nomenclature_mapping_unverified",
    "producer_identity_and_succession_unverified",
    "product_facts_caller_supplied",
    "original_artifacts_not_reverified_by_this_assessment",
    "source_text_not_reverified_by_this_assessment",
    "manifest_bound_human_review_required",
    "separate_admission_approval_required",
    "durable_versioning_retention_and_legal_hold_unattested",
)


def _positive_mm(value: object) -> Decimal:
    """Require bounded, exact millimetres; do not coerce float/bool or units."""
    if type(value) is int:
        if value.bit_length() > 80:
            raise ValueError("measurement exceeds the precision bound")
        text = str(value)
    elif type(value) is str:
        text = value
    elif type(value) is Decimal:
        if not value.is_finite():
            raise ValueError("measurement must be finite")
        _, digits, exponent = value.as_tuple()
        if len(digits) > 36 or not -12 <= exponent <= 24:
            raise ValueError("measurement exceeds the precision bound")
        text = format(value, "f")
    else:
        raise ValueError("measurement requires an exact decimal")
    if len(text) > 37 or _DECIMAL.fullmatch(text) is None:
        raise ValueError("measurement requires a bounded plain decimal")
    number = Decimal(text)
    if number <= 0:
        raise ValueError("physical measurement must be positive")
    return number


def assess_ad30_candidate(
    *,
    as_of: date,
    facts: Mapping[str, object],
    source_facts: AD30SourceFacts | None = None,
) -> dict:
    """Assess a literal product candidate; every legal result stays unavailable.

    Missing data produces questions. Malformed or physically contradictory
    supplied data takes priority over any known predicate mismatch. Otherwise a
    known false conjunct is outside this bounded source candidate, even when
    other facts are missing. Neither result establishes absence of a legal duty.
    The explicit date is recorded only; no law/date selection or clock is used.
    """
    if type(as_of) is not date:
        raise ValueError("as_of requires an explicit date, not a datetime or string")
    if not isinstance(facts, Mapping) or len(facts) > 32:
        raise ValueError("facts requires a bounded mapping")
    if any(type(key) is not str or len(key) > 80 for key in facts):
        raise ValueError("fact keys require bounded strings")
    source = validate_ad30_source_facts(
        load_ad30_source_facts() if source_facts is None else source_facts
    )
    by_id = {item.fact_id: item for item in source.facts}
    codes = frozenset(
        code.replace(" ", "") for code in json.loads(by_id["d12.codes"].value_json)
    )
    supplied = dict(facts)
    invalid: dict[str, str] = {
        key: "unsupported_fact" for key in supplied if key not in _FIELDS
    }
    missing: set[str] = set()
    numbers: dict[str, Decimal] = {}
    criteria: list[dict] = []
    contradictions: list[dict] = []

    # Validate every supplied measurement before evaluating any exclusion.
    # A wrong shape or country cannot conceal malformed unused numeric inputs.
    for key in _MEASUREMENTS:
        value = supplied.get(key)
        if value is not None:
            try:
                numbers[key] = _positive_mm(value)
            except ValueError:
                invalid[key] = "requires_positive_exact_millimetres"
    for key in _BOOLEANS:
        if supplied.get(key) is not None and type(supplied[key]) is not bool:
            invalid[key] = "requires_boolean"
    for key in ("origin_country", "destination"):
        value = supplied.get(key)
        if value is not None and (type(value) is not str or value not in _KNOWN_COUNTRIES):
            invalid[key] = "country_identity_unverified"
    direction = supplied.get("direction")
    if direction is not None and (type(direction) is not str or direction not in {"import", "export", "transit"}):
        invalid["direction"] = "unsupported_direction"
    shape = supplied.get("cross_section")
    if shape is not None and (type(shape) is not str or shape not in _SHAPES):
        invalid["cross_section"] = "cross_section_unverified"
    code = supplied.get("commodity_code")
    if code is not None and (type(code) is not str or _CODE.fullmatch(code) is None):
        invalid["commodity_code"] = "requires_exact_ten_ascii_digits"

    def criterion(name: str, keys: tuple[str, ...], source_ids: tuple[str, ...], predicate) -> None:
        absent = [key for key in keys if supplied.get(key) is None]
        missing.update(absent)
        if any(key in invalid for key in keys):
            outcome, reason = "needs_clarification", "invalid_fact"
        elif absent:
            outcome, reason = "needs_clarification", "missing_fact"
        else:
            outcome = "match" if predicate() else "mismatch"
            reason = "supplied_facts_match_source_candidate" if outcome == "match" else "supplied_facts_outside_source_candidate"
        criteria.append({
            "criterion": name,
            "fact_keys": list(keys),
            "outcome": outcome,
            "reason": reason,
            "source_fact_ids": list(source_ids),
        })

    criterion("import_direction", ("direction",), ("d12.product",), lambda: direction == "import")
    criterion("eaeu_destination", ("destination",), ("d12.product",), lambda: supplied["destination"] in EAEU_DESTINATIONS)
    criterion("china_origin", ("origin_country",), ("d12.origin",), lambda: supplied["origin_country"] == "CN")
    criterion("printed_code", ("commodity_code",), ("d12.codes", "d12.joint_code_description"), lambda: code in codes)
    for key in _BOOLEANS:
        criterion(key, (key,), ("d12.product", "d12.joint_code_description"), lambda key=key: supplied[key] is True)
    criterion("wall_thickness", ("wall_thickness_mm",), ("d12.wall",), lambda: Decimal("0.4") <= numbers["wall_thickness_mm"] <= Decimal("6"))
    criterion("named_cross_section", ("cross_section",), ("d12.round_diameter", "d12.square_perimeter", "d12.rectangle_dimensions"), lambda: shape in {"round", "square", "rectangular"})
    if shape == "round":
        criterion("round_outer_diameter", ("outer_diameter_mm",), ("d12.round_diameter",), lambda: Decimal("6") <= numbers["outer_diameter_mm"] <= Decimal("115"))
    elif shape == "square":
        criterion("square_perimeter", ("perimeter_mm",), ("d12.square_perimeter",), lambda: numbers["perimeter_mm"] <= Decimal("400"))
    elif shape == "rectangular":
        criterion("rectangular_perimeter", ("perimeter_mm",), ("d12.rectangle_dimensions",), lambda: numbers["perimeter_mm"] <= Decimal("400"))
        criterion("rectangular_max_side", ("max_side_mm",), ("d12.rectangle_dimensions",), lambda: numbers["max_side_mm"] <= Decimal("120"))

    def contradiction(reason: str, keys: tuple[str, ...]) -> None:
        contradictions.append({
            "reason": reason,
            "fact_keys": list(keys),
            "basis": "physical_consistency_of_supplied_dimensions_only",
        })

    # Exact rational comparisons do not depend on Decimal's ambient precision.
    # These checks reject contradictory inputs; they never fill missing facts.
    perimeter = Fraction(numbers["perimeter_mm"]) if "perimeter_mm" in numbers else None
    side = Fraction(numbers["max_side_mm"]) if "max_side_mm" in numbers else None
    if shape == "rectangular" and perimeter is not None and side is not None:
        if not 2 * side < perimeter <= 4 * side:
            contradiction("perimeter_conflicts_with_max_side", ("perimeter_mm", "max_side_mm"))

    if invalid or contradictions:
        scope, reason = "needs_clarification", "invalid_or_contradictory_supplied_facts"
    elif any(item["outcome"] == "mismatch" for item in criteria):
        scope, reason = "outside_source_candidate", "known_literal_candidate_mismatch"
    elif missing:
        scope, reason = "needs_clarification", "missing_product_facts"
    else:
        scope, reason = "matches_source_candidate", "all_literal_product_predicates_match"
    evidence_ids = sorted({fact_id for item in criteria for fact_id in item["source_fact_ids"]})
    return {
        "mode": "offline_source_candidate_review",
        "as_of": as_of.isoformat(),
        "source_dossier_sha256": source.dossier_sha256,
        "candidate_scope": scope,
        "reason": reason,
        "criteria": criteria,
        "missing_facts": sorted(missing),
        "invalid_facts": [{"field": key, "reason": invalid[key]} for key in sorted(invalid)],
        "contradictory_facts": contradictions,
        "source_evidence": [{
            "fact_id": by_id[fact_id].fact_id,
            "evidence_path": by_id[fact_id].evidence_path,
            "evidence_file_sha256": by_id[fact_id].evidence_file_sha256,
            "json_pointer": by_id[fact_id].json_pointer,
            "body_sha256": by_id[fact_id].body_sha256,
            "source_url": by_id[fact_id].source_url,
            "page": by_id[fact_id].page,
            "locator": by_id[fact_id].locator,
            "observation_kind": by_id[fact_id].observation_kind,
        } for fact_id in evidence_ids],
        "review_blockers": list(_REVIEW_BLOCKERS),
        "legal_applicability": "unavailable",
        "requires_manual_review": True,
        "source_record_integrity_verified": True,
        "source_evidence_verified": False,
        "original_artifacts_verified": False,
        "source_text_verified": False,
        "producer_row_selected": None,
        "legal_review_verified": False,
        "effective_dates_verified": False,
        "can_promote": False,
        "final_payable": False,
        "db_mutated": False,
    }
