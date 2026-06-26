"""Узкий enforcement imported legacy ``non_tariff_measures`` (vet/phyto only)."""

from __future__ import annotations

import os
from datetime import date
from typing import Any, Literal

from .ntm_v2_legacy_measures_import import (
    MEASURES_SOURCE_KIND,
    get_v2_legacy_measures_broker_rows,
    merge_v2_legacy_measures_into_broker,
)

EnforcementDecision = Literal["allow", "skip", "manual_review"]

_VET_PERMIT = "ВС"
_PHYTO_PERMIT = "ФСС"
_ALLOWED_KIND_PERMIT: frozenset[tuple[str, str]] = frozenset(
    {
        ("vet", _VET_PERMIT),
        ("phyto", _PHYTO_PERMIT),
    }
)


def _env_truthy(name: str) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def is_ntm_v2_measures_enforcement_enabled() -> bool:
    """``NTM_V2_MEASURES_ENFORCEMENT_ENABLED``: vet/phyto v2 measures в broker missing-check."""
    return _env_truthy("NTM_V2_MEASURES_ENFORCEMENT_ENABLED")


def should_apply_v2_measures_enforcement(explicit: bool | None = None) -> bool:
    if explicit is not None:
        return explicit
    return is_ntm_v2_measures_enforcement_enabled()


def _baseline_permit_types(baseline_broker: list[dict[str, Any]]) -> set[str]:
    return {str(r["permit_type"]).strip() for r in baseline_broker if (r.get("permit_type") or "").strip()}


def _baseline_pairs(baseline_broker: list[dict[str, Any]]) -> set[tuple[str, str | None]]:
    out: set[tuple[str, str | None]] = set()
    for r in baseline_broker:
        pt = (r.get("permit_type") or "").strip()
        if not pt:
            continue
        tr = r.get("tr_ts")
        tr_norm: str | None = (str(tr).strip() if tr else None) or None
        out.add((pt, tr_norm))
    return out


def classify_v2_measure_for_enforcement(
    measure_row: dict[str, Any],
    baseline_broker_required_permits: list[dict[str, Any]],
) -> EnforcementDecision:
    """
    Suitability gate для enforcement v2 measures.

    ``allow`` — только vet+ВС или phyto+ФСС, ``truly_new`` permit_type для позиции.
    """
    source_kind = str(measure_row.get("source_kind") or MEASURES_SOURCE_KIND)
    measure_kind = str(measure_row.get("measure_kind") or "").strip()
    permit_type = (measure_row.get("permit_type") or "").strip()

    if source_kind != MEASURES_SOURCE_KIND:
        return "manual_review"

    if not permit_type:
        return "skip"

    pair = (measure_kind, permit_type)
    if pair not in _ALLOWED_KIND_PERMIT:
        if measure_kind in ("vet", "phyto") or permit_type in (_VET_PERMIT, _PHYTO_PERMIT):
            return "manual_review"
        return "skip"

    baseline_types = _baseline_permit_types(baseline_broker_required_permits)
    if permit_type in baseline_types:
        return "skip"

    tr = measure_row.get("tr_ts")
    tr_norm: str | None = (str(tr).strip() if tr else None) or None
    if (permit_type, tr_norm) in _baseline_pairs(baseline_broker_required_permits):
        return "skip"

    return "allow"


def filter_v2_measures_for_enforcement(
    measure_rows: list[dict[str, Any]],
    baseline_broker_required_permits: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    """Разбивает candidate rows по решению gate; возвращает только ``allow`` rows."""
    allowed: list[dict[str, Any]] = []
    audit: dict[str, list[str]] = {
        "allowed_measure_keys": [],
        "skipped_measure_keys": [],
        "manual_review_measure_keys": [],
    }
    for row in measure_rows:
        key = str(row.get("measure_key") or "")
        decision = classify_v2_measure_for_enforcement(row, baseline_broker_required_permits)
        bucket = {
            "allow": "allowed_measure_keys",
            "skip": "skipped_measure_keys",
            "manual_review": "manual_review_measure_keys",
        }[decision]
        audit[bucket].append(key)
        if decision == "allow":
            allowed.append(row)
    return allowed, audit


def apply_v2_measures_enforcement_to_broker(
    broker_rows: list[dict[str, Any]],
    hs_code: str,
    description: str = "",
    *,
    as_of: date | None = None,
) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    """Добавляет в broker только vet/phyto measures, прошедшие gate."""
    _ = as_of
    candidates = get_v2_legacy_measures_broker_rows(hs_code, description)
    allowed, audit = filter_v2_measures_for_enforcement(candidates, broker_rows)
    merged = merge_v2_legacy_measures_into_broker(broker_rows, allowed)
    return merged, audit


async def compare_non_tariff_check_measures_enforcement(
    hs_code: str,
    description: str = "",
    permits: list[dict[str, str]] | None = None,
    country: str | None = None,
    *,
    skip_registry_verify: bool = True,
) -> dict[str, Any]:
    """Сравнение ``check_position_non_tariff`` без и с measures enforcement (без смены env)."""
    from .non_tariff_service import check_position_non_tariff

    permit_list = permits if permits is not None else []
    baseline = await check_position_non_tariff(
        hs_code=hs_code,
        description=description,
        country=country,
        permits=permit_list,
        skip_registry_verify=skip_registry_verify,
        measures_enforcement_enabled=False,
    )
    enforced = await check_position_non_tariff(
        hs_code=hs_code,
        description=description,
        country=country,
        permits=permit_list,
        skip_registry_verify=skip_registry_verify,
        measures_enforcement_enabled=True,
    )

    base_types = set(baseline.get("required_permit_types") or [])
    enf_types = set(enforced.get("required_permit_types") or [])
    base_missing = set(baseline.get("missing_permit_types") or [])
    enf_missing = set(enforced.get("missing_permit_types") or [])

    diag = enforced.get("measures_enforcement_audit") or {}

    return {
        "hs_code": hs_code,
        "baseline_required_permit_types": sorted(base_types),
        "enforced_required_permit_types": sorted(enf_types),
        "added_permit_types": sorted(enf_types - base_types),
        "baseline_missing_permit_types": sorted(base_missing),
        "enforced_missing_permit_types": sorted(enf_missing),
        "added_missing_permit_types": sorted(enf_missing - base_missing),
        "status_before": baseline.get("status"),
        "status_after": enforced.get("status"),
        "changed": (
            base_types != enf_types
            or base_missing != enf_missing
            or baseline.get("status") != enforced.get("status")
        ),
        "allowed_measure_keys": list(diag.get("allowed_measure_keys") or []),
        "skipped_measure_keys": list(diag.get("skipped_measure_keys") or []),
        "manual_review_measure_keys": list(diag.get("manual_review_measure_keys") or []),
    }
