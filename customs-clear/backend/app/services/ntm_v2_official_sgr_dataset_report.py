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

# Префиксы целевой curated-партии (issue #3 / Section II batch).
SECTION_II_BATCH_ISSUE3_PREFIXES: tuple[str, ...] = ("7306", "5910", "3926")


def _hs_prefixes_from_rules(rules: list[dict[str, Any]]) -> list[str]:
    prefixes: set[str] = set()
    for r in rules:
        hs = str(r.get("hs_scope") or "").strip()
        if hs:
            prefixes.add(hs)
    return sorted(prefixes)


def _rule_ids_for_hs_prefix(rules: list[dict[str, Any]], prefix: str) -> list[str]:
    out: list[str] = []
    for row in rules:
        hs = str(row.get("hs_scope") or "").strip()
        if hs.startswith(prefix):
            rid = str(row.get("rule_id") or "").strip()
            if rid:
                out.append(rid)
    return sorted(out)


def _coverage_issue3_batch(rules: list[dict[str, Any]]) -> dict[str, Any]:
    all_prefixes = _hs_prefixes_from_rules(rules)
    covered: list[str] = []
    missing: list[str] = []
    rule_ids_by_prefix: dict[str, list[str]] = {}
    for prefix in SECTION_II_BATCH_ISSUE3_PREFIXES:
        ids = _rule_ids_for_hs_prefix(rules, prefix)
        rule_ids_by_prefix[prefix] = ids
        if any(p == prefix or p.startswith(prefix) for p in all_prefixes):
            covered.append(prefix)
        else:
            missing.append(prefix)
    return {
        "target_prefixes": list(SECTION_II_BATCH_ISSUE3_PREFIXES),
        "covered_prefixes": covered,
        "missing_prefixes": missing,
        "rule_ids_by_prefix": rule_ids_by_prefix,
        "complete": not missing,
    }


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
            "id": "adult_diapers_9619_no_child_clarify",
            "hs_code": "9619000000",
            "description": "Подгузники для взрослых",
            "expect": {"needs_clarification": False},
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
        {
            "id": "drinking_water_pipe_7306_possible",
            "hs_code": "7306100000",
            "description": "Труба стальная для хозпитьевого водоснабжения",
            "expect": {"has_possible": True, "rule_id": "eec299-7306-drinking-water-pipes"},
        },
        {
            "id": "industrial_pipe_7306_no_match",
            "hs_code": "7306100000",
            "description": "Труба стальная для нефтепровода",
            "expect": {"has_any_match": False},
        },
        {
            "id": "industrial_water_supply_7306_no_match",
            "hs_code": "7306100000",
            "description": "Труба стальная для промышленного водоснабжения",
            "expect": {"has_any_match": False},
        },
        {
            "id": "hvs_pipe_with_industrial_context_7306_possible",
            "hs_code": "7306100000",
            "description": "Труба для хозпитьевого водоснабжения промышленного объекта",
            "expect": {"has_possible": True, "rule_id": "eec299-7306-drinking-water-pipes"},
        },
        {
            "id": "food_conveyor_belt_5910_possible",
            "hs_code": "5910000000",
            "description": "Лента конвейерная для контакта с пищевыми продуктами",
            "expect": {"has_possible": True, "rule_id": "eec299-5910-food-conveyor-belts"},
        },
        {
            "id": "technical_fabric_5910_no_match",
            "hs_code": "5910000000",
            "description": "Ткань прорезиненная техническая",
            "expect": {"has_any_match": False},
        },
        {
            "id": "industrial_conveyor_belt_5910_no_match",
            "hs_code": "5910000000",
            "description": "Лента конвейерная промышленная для угольного транспорта",
            "expect": {"has_any_match": False},
        },
        {
            "id": "technical_food_contact_belt_5910_possible",
            "hs_code": "5910000000",
            "description": "Лента конвейерная техническая для контакта с пищевыми продуктами",
            "expect": {"has_possible": True, "rule_id": "eec299-5910-food-conveyor-belts"},
        },
        {
            "id": "plastic_food_contact_3926_clarify",
            "hs_code": "3926909709",
            "description": "Изделие пластмассовое для контакта с пищевыми продуктами",
            "expect": {"needs_clarification": True, "rule_id": "eec299-3926-section-ii-related"},
        },
        {
            "id": "plastic_technical_3926_no_match",
            "hs_code": "3926909709",
            "description": "Пластиковая заглушка техническая",
            "expect": {"has_any_match": False},
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
        if "rule_id" in exp:
            rid = exp["rule_id"]
            checks["rule_id"] = any(str(m.get("rule_id")) == rid for m in matched)
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
        "section_ii_batch_issue3": _coverage_issue3_batch(rules),
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
