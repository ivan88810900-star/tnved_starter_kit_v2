"""Диагностика imported legacy ``non_tariff_measures`` (v2): роль, дубли, impact на missing-check."""

from __future__ import annotations

from collections import Counter
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from .. import db
from ..models.ntm_v2 import NtmApplicabilityRuleV2, NtmMeasureV2
from .hs_matching import normalize_hs_code
from .non_tariff_rules import get_sensitive_override
from .ntm_triggers import find_measures_by_description
from .non_tariff_service import _build_broker_required_permits
from .ntm_v2_legacy_measures_import import (
    MEASURES_SOURCE_KIND,
    _find_v2_legacy_measures_for_code,
    get_v2_legacy_measures_broker_rows,
    measure_compare_key,
    measure_type_to_measure_kind,
    merge_v2_legacy_measures_into_broker,
)
from .tr_ts_catalog import get_full_ntm_requirements

ENFORCEMENT_CANDIDATE_KINDS: frozenset[str] = frozenset(
    {
        "technical_regulation",
        "sgr",
        "license",
        "registration",
        "vet",
        "phyto",
        "notification",
    }
)

INFORMATIONAL_KINDS: frozenset[str] = frozenset(
    {
        "prohibition",
        "marking",
        "other",
    }
)


def _legacy_payload(rule: NtmApplicabilityRuleV2) -> dict[str, Any]:
    dm = rule.description_match_json if isinstance(rule.description_match_json, dict) else {}
    legacy = dm.get("legacy_payload")
    return legacy if isinstance(legacy, dict) else {}


def _classify_imported_measure(measure: NtmMeasureV2, legacy: dict[str, Any]) -> str:
    """
    Группа пригодности: ``enforcement_candidate`` | ``informational_only_candidate`` | ``ambiguous_candidate``.
    """
    pt = (measure.permit_type or "").strip()
    mk = (measure.measure_kind or "").strip()
    legal_ref = str(legacy.get("legal_ref") or "").strip()
    description = str(legacy.get("description") or "").strip()
    legacy_mtype = str(legacy.get("measure_type") or "").strip()

    if not pt:
        return "informational_only_candidate"

    if mk in INFORMATIONAL_KINDS or legacy_mtype in ("ban", "marking", "fsetc"):
        return "informational_only_candidate"

    if mk in ENFORCEMENT_CANDIDATE_KINDS:
        if mk == "other" or (not legal_ref and not description):
            return "ambiguous_candidate"
        return "enforcement_candidate"

    return "ambiguous_candidate"


def _broker_pair_key(permit_type: str, tr_ts: str | None) -> tuple[str, str | None]:
    tr = (tr_ts or "").strip() or None
    return (permit_type.strip(), tr)


def _baseline_broker_rows(hs_code: str, description: str) -> list[dict[str, Any]]:
    catalog = get_full_ntm_requirements(hs_code, description or "")
    triggers = find_measures_by_description(description, hs_code)
    sensitive = get_sensitive_override(hs_code)
    return _build_broker_required_permits(hs_code, catalog, triggers, sensitive)


def _status_from_broker(
    broker_rows: list[dict[str, Any]],
    permits_result: list[dict[str, Any]],
    *,
    has_rules_or_measures: bool,
) -> str:
    required_types = sorted({r["permit_type"] for r in broker_rows if r.get("permit_type")})
    got_types = {p.get("type") for p in permits_result if p.get("type")}
    missing = set(required_types) - got_types
    if missing:
        return "ERROR"
    if not broker_rows and not has_rules_or_measures:
        return "WARNING"
    return "OK"


def _classify_measure_impact(
    row: dict[str, Any],
    baseline_pairs: set[tuple[str, str | None]],
    baseline_types: set[str],
) -> str:
    pt = (row.get("permit_type") or "").strip()
    if not pt:
        return "informational_only"
    key = _broker_pair_key(pt, row.get("tr_ts"))
    if key in baseline_pairs:
        return "exactly_already_covered"
    if pt in baseline_types:
        return "permit_type_already_covered_different_tr_ts"
    return "truly_new_permit_type"


def analyze_legacy_measures_v2_distribution(session: Session | None = None) -> dict[str, Any]:
    """Агрегаты по всей базе imported ``legacy_non_tariff_measures``."""
    close_session = False
    if session is None:
        session = db.SessionLocal()
        close_session = True

    try:
        measures = session.scalars(
            select(NtmMeasureV2)
            .where(NtmMeasureV2.source_kind == MEASURES_SOURCE_KIND)
            .options(joinedload(NtmMeasureV2.applicability_rules))
        ).unique().all()

        rules = session.scalars(
            select(NtmApplicabilityRuleV2).where(
                NtmApplicabilityRuleV2.source_kind == MEASURES_SOURCE_KIND
            )
        ).all()

        by_measure_kind: Counter[str] = Counter()
        by_permit_type: Counter[str] = Counter()
        by_tr_ts: Counter[str] = Counter()
        by_legacy_measure_type: Counter[str] = Counter()
        by_quality: Counter[str] = Counter()
        by_suitability: Counter[str] = Counter()

        empty_permit = 0
        nonempty_permit = 0
        empty_tr_ts = 0

        for m in measures:
            by_measure_kind[m.measure_kind] += 1
            pt = (m.permit_type or "").strip()
            if pt:
                nonempty_permit += 1
                by_permit_type[pt] += 1
            else:
                empty_permit += 1
            tr = (m.tr_ts_act_code or "").strip()
            if tr:
                by_tr_ts[tr] += 1
            else:
                empty_tr_ts += 1

            legacy: dict[str, Any] = {}
            if m.applicability_rules:
                legacy = _legacy_payload(m.applicability_rules[0])
            by_legacy_measure_type[str(legacy.get("measure_type") or "—")] += 1
            by_quality[str(legacy.get("quality") or "normal")] += 1
            by_suitability[_classify_imported_measure(m, legacy)] += 1

        by_hs_len: Counter[str] = Counter()
        by_prefix_bucket: Counter[str] = Counter()
        with_valid_from = 0
        with_valid_to = 0

        for rule in rules:
            hs = normalize_hs_code(rule.hs_code)
            ln = len(hs)
            by_hs_len[str(ln)] += 1
            if ln in (2, 4, 6, 8, 10):
                by_prefix_bucket[str(ln)] += 1
            else:
                by_prefix_bucket["other"] += 1
            if rule.valid_from:
                with_valid_from += 1
            if rule.valid_to:
                with_valid_to += 1

        total_measures = len(measures)
        enforcement = by_suitability.get("enforcement_candidate", 0)
        informational = by_suitability.get("informational_only_candidate", 0)
        ambiguous = by_suitability.get("ambiguous_candidate", 0)

        return {
            "measures": {
                "total_imported": total_measures,
                "by_measure_kind": dict(by_measure_kind.most_common()),
                "by_permit_type": dict(by_permit_type.most_common(30)),
                "by_tr_ts_act_code": dict(by_tr_ts.most_common(20)),
                "empty_permit_type": empty_permit,
                "nonempty_permit_type": nonempty_permit,
                "empty_tr_ts_act_code": empty_tr_ts,
                "by_legacy_measure_type": dict(by_legacy_measure_type.most_common(20)),
                "by_quality": dict(by_quality),
                "suitability": {
                    "enforcement_candidate": enforcement,
                    "informational_only_candidate": informational,
                    "ambiguous_candidate": ambiguous,
                    "enforcement_candidate_pct": round(
                        100.0 * enforcement / total_measures, 2
                    )
                    if total_measures
                    else 0.0,
                },
            },
            "rules": {
                "total_imported": len(rules),
                "by_hs_code_length": dict(by_hs_len.most_common()),
                "by_prefix_bucket_2_4_6_8_10": dict(by_prefix_bucket),
                "with_valid_from": with_valid_from,
                "with_valid_to": with_valid_to,
                "without_dates": len(rules) - max(with_valid_from, with_valid_to),
            },
        }
    finally:
        if close_session:
            session.close()


async def compare_legacy_measures_enforcement_impact(
    hs_code: str,
    description: str = "",
    country: str | None = None,
    *,
    as_of: date | None = None,
) -> dict[str, Any]:
    """
    Baseline: ``check_position_non_tariff`` (measures не в broker).
    Hypothetical: тот же broker + merge imported v2 measures (только диагностика).
    """
    from .non_tariff_service import check_position_non_tariff

    _ = as_of
    baseline = await check_position_non_tariff(
        hs_code=hs_code,
        description=description,
        country=country,
        permits=[],
        skip_registry_verify=True,
        rules_enforcement_enabled=False,
    )

    baseline_broker = _baseline_broker_rows(hs_code, description)
    _ = as_of
    measure_rows = get_v2_legacy_measures_broker_rows(hs_code, description)
    hypothetical_broker = merge_v2_legacy_measures_into_broker(baseline_broker, measure_rows)

    baseline_types = sorted({r["permit_type"] for r in baseline_broker if r.get("permit_type")})
    hypothetical_types = sorted({r["permit_type"] for r in hypothetical_broker if r.get("permit_type")})
    baseline_pairs = {_broker_pair_key(r["permit_type"], r.get("tr_ts")) for r in baseline_broker}
    baseline_type_set = set(baseline_types)

    permits_result = baseline.get("permits") or []
    got_types = {p.get("type") for p in permits_result if p.get("type")}
    baseline_missing = sorted(set(baseline_types) - got_types)
    hypothetical_missing = sorted(set(hypothetical_types) - got_types)

    has_rules_or_measures = bool(
        baseline.get("rule_sources") or baseline.get("notes")
    )
    status_before = baseline.get("status")
    status_after = _status_from_broker(
        hypothetical_broker,
        permits_result,
        has_rules_or_measures=has_rules_or_measures,
    )

    impact_by_measure: list[dict[str, Any]] = []
    for row in measure_rows:
        impact_by_measure.append(
            {
                "measure_key": row.get("measure_key"),
                "permit_type": row.get("permit_type"),
                "tr_ts": row.get("tr_ts"),
                "classification": _classify_measure_impact(row, baseline_pairs, baseline_type_set),
            }
        )

    added_types = sorted(set(hypothetical_types) - set(baseline_types))
    keys_for_change = [
        str(r["measure_key"])
        for r in impact_by_measure
        if r["classification"] == "truly_new_permit_type"
        and (r.get("permit_type") or "") in added_types
    ]

    classification_counts = Counter(r["classification"] for r in impact_by_measure)

    return {
        "hs_code": normalize_hs_code(hs_code),
        "description": description,
        "baseline_required_permit_types": baseline_types,
        "hypothetical_required_permit_types": hypothetical_types,
        "added_permit_types": added_types,
        "baseline_missing_permit_types": baseline_missing,
        "hypothetical_missing_permit_types": hypothetical_missing,
        "added_missing_permit_types": sorted(set(hypothetical_missing) - set(baseline_missing)),
        "status_before": status_before,
        "status_after": status_after,
        "changed": (
            baseline_types != hypothetical_types
            or baseline_missing != hypothetical_missing
            or status_before != status_after
        ),
        "measure_keys_responsible_for_change": keys_for_change,
        "measures_matched_count": len(measure_rows),
        "classification_counts": dict(classification_counts),
        "impact_by_measure": impact_by_measure,
    }


async def run_legacy_measures_impact_matrix(
    cases: list[tuple[str, str]],
    *,
    country: str | None = None,
) -> dict[str, Any]:
    """Batch-диагностика по списку ``(hs_code, description)``."""
    results: list[dict[str, Any]] = []
    unchanged = 0
    changed = 0
    added_type_counter: Counter[str] = Counter()
    status_flip_cases: list[dict[str, Any]] = []

    for hs, desc in cases:
        cmp = await compare_legacy_measures_enforcement_impact(
            hs,
            desc,
            country,
        )
        results.append(cmp)
        if cmp["changed"]:
            changed += 1
            for pt in cmp.get("added_permit_types") or []:
                added_type_counter[pt] += 1
            if cmp.get("status_before") != cmp.get("status_after"):
                status_flip_cases.append(
                    {
                        "hs_code": cmp["hs_code"],
                        "description": desc,
                        "status_before": cmp["status_before"],
                        "status_after": cmp["status_after"],
                        "added_permit_types": cmp["added_permit_types"],
                    }
                )
        else:
            unchanged += 1

    top_growth = sorted(
        (
            {
                "hs_code": r["hs_code"],
                "description": r.get("description", ""),
                "added_count": len(r.get("added_permit_types") or []),
                "added_permit_types": r.get("added_permit_types"),
            }
            for r in results
            if r.get("added_permit_types")
        ),
        key=lambda x: x["added_count"],
        reverse=True,
    )[:10]

    return {
        "total_cases": len(cases),
        "unchanged_cases": unchanged,
        "changed_cases": changed,
        "added_permit_type_frequency": dict(added_type_counter.most_common(20)),
        "status_flip_cases": status_flip_cases,
        "top_hs_by_new_permit_types": top_growth,
        "cases": results,
    }


def build_regression_matrix_cases() -> list[tuple[str, str]]:
    """Уникальные HS из ``REGRESSION_MATRIX``."""
    from tests.test_ntm_pipeline import REGRESSION_MATRIX

    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for hs, desc, _exp in REGRESSION_MATRIX:
        norm = normalize_hs_code(hs)
        if norm in seen:
            continue
        seen.add(norm)
        out.append((hs, desc))
    return out


def sample_hs_with_legacy_measures(limit: int = 12) -> list[tuple[str, str]]:
    """HS, где ``find_measures_for_code`` возвращает много записей (для расширения матрицы)."""
    from .non_tariff_rules import find_measures_for_code

    with db.SessionLocal() as session:
        rows = session.execute(
            select(
                NtmApplicabilityRuleV2.hs_code,
                func.count(NtmApplicabilityRuleV2.id).label("cnt"),
            )
            .where(NtmApplicabilityRuleV2.source_kind == MEASURES_SOURCE_KIND)
            .group_by(NtmApplicabilityRuleV2.hs_code)
            .order_by(func.count(NtmApplicabilityRuleV2.id).desc())
            .limit(limit * 3)
        ).all()

    out: list[tuple[str, str]] = []
    for hs_code, _cnt in rows:
        norm = normalize_hs_code(hs_code)
        if len(norm) < 6:
            continue
        padded = norm.ljust(10, "0")[:10]
        if find_measures_for_code(padded):
            out.append((padded, ""))
        if len(out) >= limit:
            break
    return out


async def run_full_legacy_measures_diagnostics_report() -> dict[str, Any]:
    """Сводный отчёт: distribution + матрица регрессии + сэмпл HS с мерами."""
    distribution = analyze_legacy_measures_v2_distribution()
    matrix_cases = build_regression_matrix_cases()
    matrix_cases.extend(sample_hs_with_legacy_measures(limit=8))
    matrix = await run_legacy_measures_impact_matrix(matrix_cases)
    return {
        "distribution": distribution,
        "impact_matrix": {
            "total_cases": matrix["total_cases"],
            "unchanged_cases": matrix["unchanged_cases"],
            "changed_cases": matrix["changed_cases"],
            "added_permit_type_frequency": matrix["added_permit_type_frequency"],
            "status_flip_cases": matrix["status_flip_cases"],
            "top_hs_by_new_permit_types": matrix["top_hs_by_new_permit_types"],
        },
    }
