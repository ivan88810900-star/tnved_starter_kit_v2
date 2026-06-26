"""Диагностика official SGR → advisory (флаг ``NTM_V2_OFFICIAL_SGR_ADVISORY_ENABLED``)."""

from __future__ import annotations

import asyncio
from typing import Any

from .ntm_v2_legacy_rules_import import get_advisory_legacy_rule_requirements_v2
from .ntm_v2_official_sgr_import import (
    OFFICIAL_SGR_SOURCE_KIND,
    OFFICIAL_SGR_SOURCE_LABEL,
    get_advisory_official_sgr_requirements_v2,
    merge_advisory_legacy_and_official,
)


def build_official_sgr_advisory_matrix_cases() -> list[dict[str, str]]:
    return [
        {"hs_code": "3808990000", "description": "Дезинфицирующее средство", "note": "definite official"},
        {"hs_code": "2201900000", "description": "минеральная вода лечебная", "note": "needs_clarification"},
        {"hs_code": "2201900000", "description": "Питьевая вода", "note": "no official SGR"},
        {"hs_code": "9503007500", "description": "Кукла пластиковая", "note": "legacy toy SGR"},
        {"hs_code": "3304990000", "description": "Косметика для взрослых", "note": "legacy adult cosmetics"},
        {"hs_code": "3304990000", "description": "Детский крем для лица", "note": "official child definite"},
        {"hs_code": "9999999999", "description": "БАД витаминный комплекс", "note": "needs_clarification BAD"},
    ]


def _count_applicability(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"definite": 0, "possible": 0, "needs_clarification": 0, "other": 0}
    for r in rows:
        app = str(r.get("applicability") or "").strip()
        if app in counts:
            counts[app] += 1
        else:
            counts["other"] += 1
    return counts


async def run_official_sgr_advisory_matrix(
    cases: list[dict[str, str]] | None = None,
    *,
    official_advisory_enabled: bool = True,
) -> dict[str, Any]:
    from .non_tariff_service import check_position_non_tariff

    cases = cases or build_official_sgr_advisory_matrix_cases()
    rows: list[dict[str, Any]] = []
    totals = {
        "official": {"definite": 0, "possible": 0, "needs_clarification": 0, "other": 0},
        "legacy": {"definite": 0, "possible": 0, "needs_clarification": 0, "other": 0},
        "merged": {"definite": 0, "possible": 0, "needs_clarification": 0, "other": 0},
    }

    for case in cases:
        hs = case["hs_code"]
        desc = case.get("description") or ""
        legacy = get_advisory_legacy_rule_requirements_v2(hs, desc)
        official = (
            get_advisory_official_sgr_requirements_v2(hs, desc)
            if official_advisory_enabled
            else []
        )
        merged = merge_advisory_legacy_and_official(legacy, official)
        check = await check_position_non_tariff(
            hs,
            desc,
            "DE",
            [],
            skip_registry_verify=True,
            official_sgr_advisory_enabled=official_advisory_enabled,
        )
        advisory = check.get("advisory_requirements") or []
        official_in_response = [a for a in advisory if a.get("source") == OFFICIAL_SGR_SOURCE_KIND]
        legacy_in_response = [a for a in advisory if a.get("source") != OFFICIAL_SGR_SOURCE_KIND]

        for bucket, items in (
            ("official", official),
            ("legacy", legacy),
            ("merged", merged),
        ):
            c = _count_applicability(items)
            for k, v in c.items():
                totals[bucket][k] += v

        rows.append(
            {
                "hs_code": hs,
                "description": desc,
                "note": case.get("note"),
                "legacy_advisory_count": len(legacy),
                "official_advisory_count": len(official),
                "merged_advisory_count": len(merged),
                "response_advisory_count": len(advisory),
                "response_official_count": len(official_in_response),
                "response_legacy_count": len(legacy_in_response),
                "required_permit_types": check.get("required_permit_types"),
                "missing_permit_types": check.get("missing_permit_types"),
                "status": check.get("status"),
                "official_sgr_in_required": "СГР" in (check.get("required_permit_types") or []),
                "official_applicability_counts": _count_applicability(official),
                "merged_applicability_counts": _count_applicability(merged),
                "response_official_samples": [
                    {
                        "permit_type": a.get("permit_type"),
                        "applicability": a.get("applicability"),
                        "source_label": a.get("source_label"),
                    }
                    for a in official_in_response[:3]
                ],
            }
        )

    return {
        "official_sgr_advisory_enabled": official_advisory_enabled,
        "official_source_kind": OFFICIAL_SGR_SOURCE_KIND,
        "official_source_label": OFFICIAL_SGR_SOURCE_LABEL,
        "case_count": len(rows),
        "totals": totals,
        "cases": rows,
    }


def run_official_sgr_advisory_matrix_sync(
    *,
    official_advisory_enabled: bool = True,
) -> dict[str, Any]:
    return asyncio.run(
        run_official_sgr_advisory_matrix(official_advisory_enabled=official_advisory_enabled)
    )
