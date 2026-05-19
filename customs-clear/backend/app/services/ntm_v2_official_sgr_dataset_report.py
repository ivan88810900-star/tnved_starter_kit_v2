"""Отчёт качества и sanity-check official SGR dataset."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .ntm_v2_official_sgr_dataset_validation import validate_official_sgr_dataset
from .ntm_v2_official_sgr_import import (
    DEFAULT_SEED_PATH,
    evaluate_official_sgr_from_seed_payload,
    load_official_sgr_payload,
)


def _hs_prefixes_from_rules(rules: list[dict[str, Any]]) -> list[str]:
    prefixes: set[str] = set()
    for r in rules:
        hs = str(r.get("hs_scope") or "").strip()
        if hs:
            prefixes.add(hs)
    return sorted(prefixes)


def _run_sanity_checks(payload: dict[str, Any]) -> list[dict[str, Any]]:
    cases = [
        {
            "id": "disinfectant_3808_definite",
            "hs_code": "3808990000",
            "description": "Дезинфицирующее средство для поверхностей",
            "expect": {"has_definite_sgr": True, "has_any_match": True},
        },
        {
            "id": "toy_9503_no_official",
            "hs_code": "9503007500",
            "description": "Кукла пластиковая",
            "expect": {"has_definite_sgr": False, "has_any_match": False},
        },
        {
            "id": "vacuum_8508_no_official",
            "hs_code": "8508110000",
            "description": "Пылесос бытовой",
            "expect": {"has_definite_sgr": False, "has_any_match": False},
        },
        {
            "id": "adult_cosmetics_3304_no_definite",
            "hs_code": "3304990000",
            "description": "Косметика для взрослых",
            "expect": {"has_definite_sgr": False},
        },
        {
            "id": "child_cosmetics_3304_definite",
            "hs_code": "3304990000",
            "description": "Детский крем для лица",
            "expect": {"has_definite_sgr": True},
        },
        {
            "id": "plain_water_2201_no_match",
            "hs_code": "2201900000",
            "description": "Питьевая вода",
            "expect": {"has_any_match": False},
        },
        {
            "id": "mineral_water_2201_clarify",
            "hs_code": "2201900000",
            "description": "минеральная вода лечебная",
            "expect": {"needs_clarification": True},
        },
        {
            "id": "bad_description_clarify",
            "hs_code": "2106900000",
            "description": "БАД витаминный комплекс",
            "expect": {"needs_clarification": True},
        },
        {
            "id": "child_nutrition_definite",
            "hs_code": "1901100000",
            "description": "детское питание молочная смесь",
            "expect": {"has_definite_sgr": True},
        },
        {
            "id": "household_chem_3402_possible",
            "hs_code": "3402500000",
            "description": "Средство моющее для посуды",
            "expect": {"has_possible": True},
        },
        {
            "id": "antifreeze_3820_possible",
            "hs_code": "3820000000",
            "description": "Антифриз готовый",
            "expect": {"has_possible": True},
        },
        {
            "id": "child_diapers_9619_clarify",
            "hs_code": "9619000000",
            "description": "Подгузники детские одноразовые",
            "expect": {"needs_clarification": True},
        },
        {
            "id": "solvent_3814_clarify",
            "hs_code": "3814000000",
            "description": "Растворитель для удаления краски",
            "expect": {"needs_clarification": True},
        },
        {
            "id": "intimate_cosmetics_3304_clarify",
            "hs_code": "3304990000",
            "description": "Средство интимной гигиены",
            "expect": {"needs_clarification": True, "has_definite_sgr": False},
        },
    ]
    out: list[dict[str, Any]] = []
    for case in cases:
        ev = evaluate_official_sgr_from_seed_payload(payload, case["hs_code"], case["description"])
        matched = ev.get("matched_rules") or []
        row = {
            "id": case["id"],
            "hs_code": case["hs_code"],
            "description": case["description"],
            "has_definite_sgr": ev.get("has_definite_sgr"),
            "has_advisory_sgr": ev.get("has_advisory_sgr"),
            "matched_count": len(matched),
            "applicabilities": sorted({str(m.get("applicability")) for m in matched}),
        }
        exp = case["expect"]
        checks: dict[str, bool] = {}
        if "has_definite_sgr" in exp:
            checks["has_definite_sgr"] = bool(ev.get("has_definite_sgr")) == exp["has_definite_sgr"]
        if "has_any_match" in exp:
            any_match = bool(matched)
            checks["has_any_match"] = any_match == exp["has_any_match"]
        if "needs_clarification" in exp:
            nc = any(m.get("applicability") == "needs_clarification" for m in matched)
            checks["needs_clarification"] = nc == exp["needs_clarification"]
        if "has_possible" in exp:
            poss = any(m.get("applicability") == "possible" for m in matched)
            checks["has_possible"] = poss == exp["has_possible"]
        row["checks"] = checks
        row["passed"] = all(checks.values()) if checks else True
        out.append(row)
    return out


def build_official_sgr_dataset_report(
    payload: dict[str, Any] | None = None,
    *,
    seed_path: Path | None = None,
    run_sanity: bool = True,
) -> dict[str, Any]:
    data = payload if payload is not None else load_official_sgr_payload(seed_path)
    validation = validate_official_sgr_dataset(data)
    rules = data.get("rules") or []
    coverage = {
        "hs_prefixes": _hs_prefixes_from_rules(rules),
        "hs_prefix_count": len(_hs_prefixes_from_rules(rules)),
        "categories": validation["summary"].get("by_category") or {},
        "warnings_by_code": validation["summary"].get("warnings_by_code") or {},
        "validation_warning_count": validation.get("warning_count", 0),
    }
    report: dict[str, Any] = {
        "validation": validation,
        "summary": validation["summary"],
        "coverage": coverage,
        "quality": {
            "valid": validation.get("valid"),
            "error_count": validation.get("error_count"),
            "warning_count": validation.get("warning_count"),
            "warnings": validation.get("warnings") or [],
        },
    }
    if run_sanity:
        report["sanity_examples"] = _run_sanity_checks(data)
        report["sanity_passed"] = all(r.get("passed") for r in report["sanity_examples"])
    return report


def build_official_sgr_dataset_report_from_seed(
    seed_path: Path | None = None,
    *,
    run_sanity: bool = True,
) -> dict[str, Any]:
    path = seed_path or DEFAULT_SEED_PATH
    payload = load_official_sgr_payload(path)
    report = build_official_sgr_dataset_report(payload, run_sanity=run_sanity)
    report["seed_path"] = str(path)
    return report
