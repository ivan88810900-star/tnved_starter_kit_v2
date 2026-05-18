"""Combined diff: legacy baseline vs safe v2 runtime (все четыре NTM v2 flags)."""

from __future__ import annotations

import os
from collections import Counter
from contextlib import contextmanager
from typing import Any, Iterator

from .hs_matching import normalize_hs_code

_EXTRA_MATRIX_HS: list[tuple[str, str]] = [
    ("1301900000", ""),
    ("1211300000", ""),
    ("1211400000", ""),
    ("1211500000", ""),
    ("1211908608", ""),
]

_ENV_TR_TS = "NTM_V2_TR_TS_ENABLED"
_ENV_LAYERS = "NTM_V2_LAYERS_ENABLED"


@contextmanager
def _ntm_v2_catalog_flags(
    *,
    tr_ts_v2: bool,
    layers_v2: bool,
) -> Iterator[None]:
    """Временно выставляет env для TR TS / layers (только diagnostics)."""
    saved = {
        _ENV_TR_TS: os.environ.get(_ENV_TR_TS),
        _ENV_LAYERS: os.environ.get(_ENV_LAYERS),
    }
    for name, enabled in ((_ENV_TR_TS, tr_ts_v2), (_ENV_LAYERS, layers_v2)):
        if enabled:
            os.environ[name] = "true"
        else:
            os.environ.pop(name, None)
    try:
        yield
    finally:
        for name, prev in saved.items():
            if prev is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = prev


def _clean_permit_types(values: list[str] | None) -> list[str]:
    return sorted({str(v).strip() for v in (values or []) if str(v).strip()})


def _snapshot(check_result: dict[str, Any]) -> dict[str, Any]:
    permits = [
        r
        for r in (check_result.get("required_permits") or [])
        if (r.get("permit_type") or "").strip()
    ]
    return {
        "status": check_result.get("status"),
        "required_permit_types": _clean_permit_types(check_result.get("required_permit_types")),
        "missing_permit_types": _clean_permit_types(check_result.get("missing_permit_types")),
        "required_permits": permits,
    }


def _diff_types(before: list[str], after: list[str]) -> tuple[list[str], list[str]]:
    b, a = set(before), set(after)
    return sorted(a - b), sorted(b - a)


def _status_transition(before: str | None, after: str | None) -> str:
    return f"{before or '?'}→{after or '?'}"


async def _check_with_runtime(
    hs_code: str,
    description: str,
    permits: list[dict[str, str]] | None,
    country: str | None,
    *,
    tr_ts_v2: bool,
    layers_v2: bool,
    rules_enforcement: bool,
    measures_enforcement: bool,
    skip_registry_verify: bool,
) -> dict[str, Any]:
    from .non_tariff_service import check_position_non_tariff

    permit_list = permits if permits is not None else []
    with _ntm_v2_catalog_flags(tr_ts_v2=tr_ts_v2, layers_v2=layers_v2):
        return await check_position_non_tariff(
            hs_code=hs_code,
            description=description,
            country=country,
            permits=permit_list,
            skip_registry_verify=skip_registry_verify,
            rules_enforcement_enabled=rules_enforcement,
            measures_enforcement_enabled=measures_enforcement,
        )


def _compute_contribution(
    baseline_types: set[str],
    replacement_types: set[str],
    with_rules_types: set[str],
    safe_v2_types: set[str],
) -> dict[str, Any]:
    replacement_added = sorted(replacement_types - baseline_types)
    rules_added = sorted(with_rules_types - replacement_types)
    measures_added = sorted(safe_v2_types - with_rules_types)

    total_added = sorted(safe_v2_types - baseline_types)
    attributed = set(replacement_added) | set(rules_added) | set(measures_added)
    unexplained = sorted(set(total_added) - attributed)

    replacement_only = (
        replacement_types == baseline_types
        and not replacement_added
        and not rules_added
        and not measures_added
    )

    return {
        "rules_enforcement_added": rules_added,
        "measures_enforcement_added": measures_added,
        "replacement_catalog_added": replacement_added,
        "replacement_only_no_semantic_change": replacement_only,
        "requires_manual_attribution": bool(unexplained),
        "unexplained_added_permit_types": unexplained,
    }


async def compare_non_tariff_check_legacy_vs_safe_v2(
    hs_code: str,
    description: str = "",
    permits: list[dict[str, str]] | None = None,
    country: str | None = None,
    *,
    skip_registry_verify: bool = True,
) -> dict[str, Any]:
    """
    Baseline: legacy TR TS + legacy layers, rules/measures enforcement OFF.
    Safe v2: v2 TR TS + v2 layers, rules + narrow measures enforcement ON.
    """
    raw_baseline = await _check_with_runtime(
        hs_code,
        description,
        permits,
        country,
        tr_ts_v2=False,
        layers_v2=False,
        rules_enforcement=False,
        measures_enforcement=False,
        skip_registry_verify=skip_registry_verify,
    )
    raw_replacement = await _check_with_runtime(
        hs_code,
        description,
        permits,
        country,
        tr_ts_v2=True,
        layers_v2=True,
        rules_enforcement=False,
        measures_enforcement=False,
        skip_registry_verify=skip_registry_verify,
    )
    raw_with_rules = await _check_with_runtime(
        hs_code,
        description,
        permits,
        country,
        tr_ts_v2=True,
        layers_v2=True,
        rules_enforcement=True,
        measures_enforcement=False,
        skip_registry_verify=skip_registry_verify,
    )
    raw_safe = await _check_with_runtime(
        hs_code,
        description,
        permits,
        country,
        tr_ts_v2=True,
        layers_v2=True,
        rules_enforcement=True,
        measures_enforcement=True,
        skip_registry_verify=skip_registry_verify,
    )

    baseline = _snapshot(raw_baseline)
    safe_v2 = _snapshot(raw_safe)

    added_pt, removed_pt = _diff_types(
        baseline["required_permit_types"],
        safe_v2["required_permit_types"],
    )
    added_miss, removed_miss = _diff_types(
        baseline["missing_permit_types"],
        safe_v2["missing_permit_types"],
    )

    contribution = _compute_contribution(
        set(baseline["required_permit_types"]),
        set(_snapshot(raw_replacement)["required_permit_types"]),
        set(_snapshot(raw_with_rules)["required_permit_types"]),
        set(safe_v2["required_permit_types"]),
    )

    status_before = baseline["status"]
    status_after = safe_v2["status"]

    return {
        "hs_code": normalize_hs_code(hs_code),
        "description": description,
        "baseline": baseline,
        "safe_v2": safe_v2,
        "diff": {
            "added_permit_types": added_pt,
            "removed_permit_types": removed_pt,
            "added_missing_permit_types": added_miss,
            "removed_missing_permit_types": removed_miss,
            "status_before": status_before,
            "status_after": status_after,
            "status_changed": status_before != status_after,
            "changed": bool(
                added_pt
                or removed_pt
                or added_miss
                or removed_miss
                or status_before != status_after
            ),
        },
        "contribution": contribution,
        "intermediate": {
            "replacement_v2": _snapshot(raw_replacement),
            "with_rules_enforcement": _snapshot(raw_with_rules),
        },
    }


def build_safe_v2_matrix_cases() -> list[tuple[str, str]]:
    """Уникальные HS: REGRESSION_MATRIX + дополнительные показательные коды."""
    from tests.test_ntm_pipeline import REGRESSION_MATRIX

    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for hs, desc, _exp in REGRESSION_MATRIX:
        norm = normalize_hs_code(hs)
        if norm in seen:
            continue
        seen.add(norm)
        out.append((hs, desc))
    for hs, desc in _EXTRA_MATRIX_HS:
        norm = normalize_hs_code(hs)
        if norm in seen:
            continue
        seen.add(norm)
        out.append((hs, desc))
    return out


async def run_safe_v2_combined_impact_matrix(
    cases: list[tuple[str, str]],
    *,
    country: str | None = None,
    skip_registry_verify: bool = True,
) -> dict[str, Any]:
    """Batch combined legacy vs safe v2 по списку ``(hs_code, description)``."""
    results: list[dict[str, Any]] = []
    unchanged = 0
    changed = 0
    status_flips = 0
    status_transitions: Counter[str] = Counter()
    added_pt_freq: Counter[str] = Counter()
    added_miss_freq: Counter[str] = Counter()
    rules_only_cases: list[str] = []
    measures_only_cases: list[str] = []
    both_cases: list[str] = []
    replacement_only_cases: list[str] = []
    top_growth: list[dict[str, Any]] = []

    for hs, desc in cases:
        row = await compare_non_tariff_check_legacy_vs_safe_v2(
            hs,
            desc,
            country=country,
            skip_registry_verify=skip_registry_verify,
        )
        results.append(row)
        diff = row["diff"]
        contrib = row["contribution"]

        if diff["changed"]:
            changed += 1
            for pt in diff["added_permit_types"]:
                added_pt_freq[pt] += 1
            for pt in diff["added_missing_permit_types"]:
                added_miss_freq[pt] += 1
            top_growth.append(
                {
                    "hs_code": row["hs_code"],
                    "description": desc,
                    "added_count": len(diff["added_permit_types"]),
                    "added_permit_types": diff["added_permit_types"],
                }
            )
        else:
            unchanged += 1

        if diff["status_changed"]:
            status_flips += 1
            status_transitions[_status_transition(diff["status_before"], diff["status_after"])] += 1

        rules_added = set(contrib.get("rules_enforcement_added") or [])
        measures_added = set(contrib.get("measures_enforcement_added") or [])
        repl_added = set(contrib.get("replacement_catalog_added") or [])

        if rules_added and measures_added:
            both_cases.append(row["hs_code"])
        elif rules_added:
            rules_only_cases.append(row["hs_code"])
        elif measures_added:
            measures_only_cases.append(row["hs_code"])
        elif contrib.get("replacement_only_no_semantic_change") and not diff["changed"]:
            replacement_only_cases.append(row["hs_code"])

        _ = repl_added

    top_growth.sort(key=lambda x: x["added_count"], reverse=True)

    rules_freq: Counter[str] = Counter()
    measures_freq: Counter[str] = Counter()
    for row in results:
        for pt in row["contribution"].get("rules_enforcement_added") or []:
            rules_freq[pt] += 1
        for pt in row["contribution"].get("measures_enforcement_added") or []:
            measures_freq[pt] += 1

    return {
        "total_cases": len(cases),
        "unchanged_cases": unchanged,
        "changed_cases": changed,
        "status_flips": status_flips,
        "status_transition_counts": dict(status_transitions),
        "added_permit_type_frequency": dict(added_pt_freq.most_common()),
        "added_missing_permit_type_frequency": dict(added_miss_freq.most_common()),
        "rules_enforcement_permit_frequency": dict(rules_freq.most_common()),
        "measures_enforcement_permit_frequency": dict(measures_freq.most_common()),
        "cases_rules_only": rules_only_cases,
        "cases_measures_only": measures_only_cases,
        "cases_both_rules_and_measures": both_cases,
        "cases_replacement_only_unchanged": replacement_only_cases,
        "top_hs_by_added_permit_types": top_growth[:10],
        "cases": results,
    }
