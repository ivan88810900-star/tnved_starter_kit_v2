"""Pure, non-serving preview of a versioned ETT candidate.

Selecting an expression is not approval of its legal correctness.  This module
does not read databases, infer the current date/country, calculate VAT, or change
the active calculator.  Numeric product facts may be exact ``Decimal``/``int``
values or bounded plain decimal strings (the lossless JSON representation).
Binary floats, non-finite numbers and implicit boolean coercions are rejected.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Literal

from .ett_manifest import (
    ETTCondition,
    ETTDuty,
    ETTEvidence,
    ETTFootnote,
    ETTManifest,
    ETTRateRule,
    manifest_sha256,
    validate_manifest,
)


_CODE = re.compile(r"[0-9]{10}\Z", re.ASCII)
_DECIMAL = re.compile(r"-?(?:0|[1-9][0-9]{0,23})(?:\.[0-9]{1,12})?\Z", re.ASCII)
_DESTINATIONS = frozenset({"AM", "BY", "KZ", "KG", "RU"})
_MAX_FACTS = 256
_MAX_DECIMAL_LENGTH = 38


@dataclass(frozen=True)
class ETTResolution:
    """An explainable selection, permanently labelled as candidate preview."""

    status: Literal["resolved", "needs_clarification", "unavailable"]
    code: str
    as_of: date
    destination: str
    snapshot_id: str
    manifest_sha256: str
    reason: str
    rule_ids: tuple[str, ...] = ()
    duty: ETTDuty | None = None
    missing_facts: tuple[str, ...] = ()
    evidence: tuple[ETTEvidence, ...] = ()
    effective_evidence: tuple[ETTEvidence, ...] = ()
    footnotes: tuple[ETTFootnote, ...] = ()
    mode: Literal["candidate_preview"] = field(default="candidate_preview", init=False)


def _numeric_fact(value: object, fact_name: str) -> Decimal:
    """Parse only exact, bounded numeric representations; never float -> str."""
    if type(value) is int:
        # Bound before string conversion (and do not let bool enter this branch).
        if value.bit_length() > 80:
            raise ValueError(f"numeric fact {fact_name!r} exceeds the size limit")
        text = str(value)
    elif type(value) is str:
        text = value
    elif type(value) is Decimal:
        if not value.is_finite():
            raise ValueError(f"numeric fact {fact_name!r} must be finite")
        _sign, digits, exponent = value.as_tuple()
        if len(digits) > 36 or not -12 <= exponent <= 24:
            raise ValueError(f"numeric fact {fact_name!r} exceeds the size limit")
        text = format(value, "f")
    else:
        raise ValueError(f"numeric fact {fact_name!r} requires an exact decimal")
    if len(text) > _MAX_DECIMAL_LENGTH or _DECIMAL.fullmatch(text) is None:
        raise ValueError(f"numeric fact {fact_name!r} requires a bounded plain decimal")
    number = Decimal(text)
    if number < 0:
        raise ValueError(f"numeric fact {fact_name!r} must be nonnegative")
    return number


def _condition_matches(condition: ETTCondition, value: object) -> bool:
    if condition.op == "eq":
        expected = condition.value
        if type(value) is not type(expected):
            raise ValueError(f"fact {condition.field!r} has an incorrect type")
        return value == expected
    if condition.op != "numeric_interval":
        raise ValueError("unsupported ETT condition")
    number = _numeric_fact(value, condition.field)
    lower = condition.minimum
    upper = condition.maximum
    if lower is not None:
        if number < lower or (number == lower and not condition.minimum_inclusive):
            return False
    if upper is not None:
        if number > upper or (number == upper and not condition.maximum_inclusive):
            return False
    return True


def _evaluate_rule(rule: ETTRateRule, facts: Mapping[str, object]) -> tuple[bool, set[str]]:
    """Conjunction: a known false predicate excludes the whole candidate.

    Collect failures before returning so manifest condition order cannot change
    which supplied malformed values are rejected. Missing facts on an excluded
    rule must not create questions for the caller.
    """
    missing: set[str] = set()
    excluded = False
    for condition in rule.conditions:
        if condition.field not in facts or facts[condition.field] is None:
            missing.add(condition.field)
        elif not _condition_matches(condition, facts[condition.field]):
            excluded = True
    return (False, set()) if excluded else (not missing, missing)


def _unique_evidence(values: list[ETTEvidence]) -> tuple[ETTEvidence, ...]:
    # Evidence models are immutable; canonical JSON provides a stable key even
    # where multiple rules cite the same source row in a different order.
    unique = {item.model_dump_json(): item for item in values}
    return tuple(unique[key] for key in sorted(unique))


def resolve_rate(
    manifest: ETTManifest,
    code: str,
    as_of: date,
    destination: str,
    facts: Mapping[str, object] | None = None,
) -> ETTResolution:
    """Resolve a candidate expression for an explicit day and destination.

    All effective intervals are half-open: ``valid_from <= as_of < valid_to``.
    A missing fact can never turn a potentially applicable rule into an excluded
    one. Multiple matches are unavailable even if their numerical duties agree;
    there is no last-wins, broad-prefix, current-date or zero-duty fallback.
    Invalid request representations raise ``ValueError``.
    """
    if not isinstance(manifest, ETTManifest):
        raise ValueError("manifest must be a validated ETTManifest")
    if type(code) is not str or _CODE.fullmatch(code) is None:
        raise ValueError("code must contain exactly ten ASCII digits")
    if type(as_of) is not date:
        raise ValueError("as_of must be an explicit date, not a datetime or string")
    if type(destination) is not str or destination not in _DESTINATIONS:
        raise ValueError("destination must be an explicit EAEU member code")
    if facts is None:
        supplied: dict[str, object] = {}
    elif not isinstance(facts, Mapping) or len(facts) > _MAX_FACTS:
        raise ValueError("facts must be a bounded mapping")
    else:
        supplied = dict(facts)
        if any(type(key) is not str for key in supplied):
            raise ValueError("fact names must be strings")

    # Resolve the actual revalidated representation. model_copy/model_construct
    # can bypass Pydantic validation and otherwise leave strings where the hash
    # validator normalized them to dates/Decimals, splitting evidence from use.
    manifest = validate_manifest(manifest)
    base = dict(
        code=code,
        as_of=as_of,
        destination=destination,
        snapshot_id=manifest.snapshot_id,
        manifest_sha256=manifest_sha256(manifest),
    )
    if not (manifest.coverage_from <= as_of < manifest.coverage_to):
        return ETTResolution(status="unavailable", reason="outside_snapshot_coverage", **base)

    codes = [entry for entry in manifest.codes if entry.code == code]
    if not codes:
        return ETTResolution(status="unavailable", reason="code_not_present", **base)
    current_codes = [entry for entry in codes if entry.valid_from <= as_of < entry.valid_to]
    if len(current_codes) != 1:
        reason = "code_not_effective" if not current_codes else "ambiguous_code_versions"
        return ETTResolution(status="unavailable", reason=reason, **base)

    candidates = sorted(
        (
            rule for rule in manifest.rate_rules
            if rule.code == code
            and rule.valid_from <= as_of < rule.valid_to
            and destination in rule.destinations
        ),
        key=lambda rule: rule.rule_id,
    )
    matched: list[ETTRateRule] = []
    unknown: list[ETTRateRule] = []
    missing: set[str] = set()
    for rule in candidates:
        matches, absent = _evaluate_rule(rule, supplied)
        if matches:
            matched.append(rule)
        elif absent:
            unknown.append(rule)
            missing.update(absent)

    relevant = sorted(matched + unknown, key=lambda rule: rule.rule_id)
    footnote_ids = {item for rule in relevant for item in rule.footnote_ids}
    footnotes = tuple(sorted(
        (item for item in manifest.footnotes if item.footnote_id in footnote_ids),
        key=lambda item: item.footnote_id,
    ))
    detail = dict(
        rule_ids=tuple(rule.rule_id for rule in relevant),
        missing_facts=tuple(sorted(missing)),
        evidence=_unique_evidence([item for rule in relevant for item in rule.evidence]),
        effective_evidence=_unique_evidence([
            item for rule in relevant for item in rule.effective_evidence
        ]),
        footnotes=footnotes,
    )
    if len(matched) > 1:
        return ETTResolution(status="unavailable", reason="ambiguous_rate_rules", **detail, **base)
    if unknown:
        return ETTResolution(
            status="needs_clarification", reason="incomplete_product_facts", **detail, **base
        )
    if not matched:
        return ETTResolution(status="unavailable", reason="no_applicable_rate", **detail, **base)
    return ETTResolution(
        status="resolved", reason="matching_rate", duty=matched[0].duty, **detail, **base
    )
