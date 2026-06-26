#!/usr/bin/env python3
"""Аудит ``NTM_V2_RULES_ENFORCEMENT_ENABLED`` (без measures enforcement)."""

from __future__ import annotations

import asyncio
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.services.hs_matching import normalize_hs_code
from app.services.ntm_v2_combined_runtime_diagnostics import build_safe_v2_matrix_cases
from app.services.ntm_v2_legacy_rules_import import (
    LEGACY_RULES_IMPORT_APPLICABILITY,
    RULES_SOURCE_KIND,
    compare_non_tariff_check_rules_enforcement,
    get_legacy_rule_requirements_v2_legacy_shape,
    import_legacy_non_tariff_rules_to_ntm_v2,
    is_legacy_v2_rule_definite,
)


def _clean_types(values: list[str] | None) -> list[str]:
    return sorted({str(v).strip() for v in (values or []) if str(v).strip()})


def _matched_v2_rules_detail(hs_code: str, added_types: set[str]) -> list[dict]:
    from app import db
    from app.models.ntm_v2 import NtmApplicabilityRuleV2, NtmMeasureV2
    from app.services.ntm_v2_legacy_rules_import import _iter_matched_legacy_v2_rules

    out: list[dict] = []
    with db.SessionLocal() as session:
        for rule, measure in _iter_matched_legacy_v2_rules(hs_code, as_of=date.today(), session=session):
            if not is_legacy_v2_rule_definite(rule):
                continue
            pt = (measure.permit_type or "").strip()
            if pt not in added_types:
                continue
            payload = rule.description_match_json if isinstance(rule.description_match_json, dict) else {}
            legacy = payload.get("legacy_payload") if isinstance(payload.get("legacy_payload"), dict) else {}
            out.append(
                {
                    "v2_rule_id": rule.id,
                    "v2_measure_id": measure.id,
                    "legacy_rule_id": legacy.get("legacy_rule_id"),
                    "hs_prefix": rule.hs_code,
                    "permit_type": pt,
                    "tr_ts": measure.tr_ts_act_code or None,
                    "rule_name": legacy.get("rule_name") or measure.title,
                    "exception_note": legacy.get("exception_note") or "",
                    "source_url": legacy.get("source_url") or "",
                    "source_revision": legacy.get("source_revision") or "",
                    "priority": int(rule.priority or 0),
                    "rule_import_key": rule.rule_import_key,
                }
            )
    return out


async def run_audit() -> dict:
    import_report = import_legacy_non_tariff_rules_to_ntm_v2()
    cases = build_safe_v2_matrix_cases()
    results: list[dict] = []
    changed_hs: list[str] = []
    status_flips: list[dict] = []
    added_freq: Counter[str] = Counter()
    only_sgr = 0
    only_ss = 0
    both = 0

    for hs, desc in cases:
        cmp = await compare_non_tariff_check_rules_enforcement(hs, desc)
        added = set(cmp.get("added_permit_types") or [])
        row = {
            "hs_code": cmp["hs_code"],
            "description": desc,
            "baseline": {
                "required_permit_types": _clean_types(cmp.get("baseline_required_permit_types")),
                "missing_permit_types": _clean_types(cmp.get("baseline_missing_permit_types")),
                "status": cmp.get("status_before"),
            },
            "with_rules_enforcement": {
                "required_permit_types": _clean_types(cmp.get("enforced_required_permit_types")),
                "missing_permit_types": _clean_types(cmp.get("enforced_missing_permit_types")),
                "status": cmp.get("status_after"),
            },
            "added_permit_types": sorted(added),
            "added_missing_permit_types": sorted(
                set(cmp.get("enforced_missing_permit_types") or [])
                - set(cmp.get("baseline_missing_permit_types") or [])
            ),
            "status_changed": cmp.get("status_before") != cmp.get("status_after"),
            "changed": cmp.get("changed"),
            "contributing_v2_rules": _matched_v2_rules_detail(hs, added) if added else [],
            "v2_rule_rows_informational": get_legacy_rule_requirements_v2_legacy_shape(hs, desc),
            "v2_rule_rows_enforceable": get_legacy_rule_requirements_v2_legacy_shape(
                hs, desc, enforceable_only=True
            ),
        }
        results.append(row)
        if row["changed"]:
            changed_hs.append(row["hs_code"])
            for pt in added:
                added_freq[pt] += 1
            has_sgr = "СГР" in added
            has_ss = "СС" in added
            if has_sgr and has_ss:
                both += 1
            elif has_sgr:
                only_sgr += 1
            elif has_ss:
                only_ss += 1
        if row["status_changed"]:
            status_flips.append(
                {
                    "hs_code": row["hs_code"],
                    "description": desc,
                    "status_before": row["baseline"]["status"],
                    "status_after": row["with_rules_enforcement"]["status"],
                    "added_permit_types": row["added_permit_types"],
                    "contributing_v2_rules": row["contributing_v2_rules"],
                }
            )

    return {
        "audit": "NTM_V2_RULES_ENFORCEMENT_ENABLED",
        "import_applicability_policy": LEGACY_RULES_IMPORT_APPLICABILITY,
        "import_report": import_report,
        "source_kind": RULES_SOURCE_KIND,
        "total_cases": len(cases),
        "changed_cases": len(changed_hs),
        "unchanged_cases": len(cases) - len(changed_hs),
        "status_flips": len(status_flips),
        "added_permit_type_frequency": dict(added_freq),
        "changed_hs_codes": changed_hs,
        "cases_only_sgr": only_sgr,
        "cases_only_ss": only_ss,
        "cases_sgr_and_ss": both,
        "status_flip_details": status_flips,
        "cases": results,
    }


def main() -> None:
    report = asyncio.run(run_audit())
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
