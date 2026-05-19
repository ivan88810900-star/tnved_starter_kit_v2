"""Валидация curated-датасета official SGR (``official_sgr_rules.seed.json``)."""

from __future__ import annotations

from typing import Any

from .hs_matching import normalize_hs_code

VALID_APPLICABILITIES = frozenset({"definite", "possible", "needs_clarification"})
VALID_HS_SCOPE_MODES = frozenset({"prefix", "exact", "description_only"})
REQUIRED_RULE_FIELDS = ("rule_id", "permit_type", "applicability", "title", "evidence")

# Заведомо неверные обобщения для ``definite`` без description-условий (п. 5 ТЗ).
PROHIBITED_DEFINITE_HS_PREFIXES = frozenset(
    {"9503", "9504", "8508", "8509", "8517", "8471", "9401", "9403"}
)

WIDE_HS_LEN_WARNING = 4

# Узкие товарные позиции Перечня II, где ``definite`` по HS допустим без description-маркеров.
DEFINITE_NARROW_HS_ALLOWLIST = frozenset({"3808"})


def _rule_signature(row: dict[str, Any]) -> tuple[Any, ...]:
    desc = tuple(sorted(str(x).lower() for x in (row.get("description_contains_any") or [])))
    req = tuple(sorted(str(x).lower() for x in (row.get("description_requires_any") or [])))
    excl = tuple(sorted(str(x).lower() for x in (row.get("exclude_if_contains_any") or [])))
    return (
        normalize_hs_code(str(row.get("hs_scope") or "")),
        str(row.get("hs_scope_mode") or "prefix"),
        str(row.get("applicability") or ""),
        desc,
        req,
        excl,
    )


def validate_official_sgr_dataset(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Проверка JSON-датасета official SGR.

    Returns:
        ``{"valid": bool, "errors": [...], "warnings": [...], "summary": {...}}``
    """
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    rules = payload.get("rules")
    if not isinstance(payload, dict):
        return _result(False, ["payload must be a JSON object"], [], {})
    if not isinstance(rules, list):
        errors.append({"code": "rules_not_array", "message": "поле rules должно быть массивом"})
        return _result(False, errors, warnings, {})

    seen_ids: set[str] = set()
    seen_signatures: dict[tuple[Any, ...], str] = {}
    applicability_counts = {"definite": 0, "possible": 0, "needs_clarification": 0}
    hs_modes: dict[str, int] = {}
    description_based = 0
    hs_only = 0
    categories: dict[str, int] = {}

    for idx, row in enumerate(rules):
        if not isinstance(row, dict):
            errors.append({"code": "rule_not_object", "index": idx})
            continue
        path = f"rules[{idx}]"
        rule_id = str(row.get("rule_id") or "").strip()
        if not rule_id:
            errors.append({"code": "missing_rule_id", "path": path})
        elif rule_id in seen_ids:
            errors.append({"code": "duplicate_rule_id", "path": path, "rule_id": rule_id})
        else:
            seen_ids.add(rule_id)

        for field in REQUIRED_RULE_FIELDS:
            if not str(row.get(field) or "").strip():
                errors.append({"code": "missing_required", "path": path, "field": field})

        permit = str(row.get("permit_type") or "").strip()
        if permit and permit != "СГР":
            errors.append({"code": "invalid_permit_type", "path": path, "permit_type": permit})

        app = str(row.get("applicability") or "").strip()
        if app not in VALID_APPLICABILITIES:
            errors.append({"code": "invalid_applicability", "path": path, "applicability": app})
        elif app in applicability_counts:
            applicability_counts[app] += 1

        hs_mode = str(row.get("hs_scope_mode") or "prefix").strip() or "prefix"
        if hs_mode not in VALID_HS_SCOPE_MODES:
            errors.append({"code": "invalid_hs_scope_mode", "path": path, "hs_scope_mode": hs_mode})
        hs_modes[hs_mode] = hs_modes.get(hs_mode, 0) + 1

        hs_scope = normalize_hs_code(str(row.get("hs_scope") or ""))
        if hs_mode == "description_only" and hs_scope:
            errors.append(
                {
                    "code": "description_only_with_hs",
                    "path": path,
                    "rule_id": rule_id,
                    "message": "при hs_scope_mode=description_only hs_scope должен быть пустым",
                }
            )
        if hs_mode in ("prefix", "exact") and not hs_scope and not row.get("description_contains_any") and not row.get(
            "description_requires_any"
        ):
            errors.append(
                {
                    "code": "empty_rule",
                    "path": path,
                    "rule_id": rule_id,
                    "message": "правило без hs_scope и без description-маркеров",
                }
            )

        contains = [str(x).strip() for x in (row.get("description_contains_any") or []) if str(x).strip()]
        requires = [str(x).strip() for x in (row.get("description_requires_any") or []) if str(x).strip()]
        excludes = [str(x).strip() for x in (row.get("exclude_if_contains_any") or []) if str(x).strip()]
        if contains or requires:
            description_based += 1
        elif hs_scope:
            hs_only += 1

        sig = _rule_signature(row)
        if sig in seen_signatures:
            errors.append(
                {
                    "code": "duplicate_signature",
                    "path": path,
                    "rule_id": rule_id,
                    "duplicate_of": seen_signatures[sig],
                }
            )
        else:
            seen_signatures[sig] = rule_id

        cat = str(row.get("category") or "uncategorized").strip()
        categories[cat] = categories.get(cat, 0) + 1

        if app == "definite":
            for banned in PROHIBITED_DEFINITE_HS_PREFIXES:
                if hs_scope.startswith(banned):
                    errors.append(
                        {
                            "code": "prohibited_definite_hs",
                            "path": path,
                            "rule_id": rule_id,
                            "hs_scope": hs_scope,
                            "message": f"definite запрещён для префикса {banned}",
                        }
                    )
            if hs_scope == "3304" and not contains:
                errors.append(
                    {
                        "code": "prohibited_definite_3304",
                        "path": path,
                        "rule_id": rule_id,
                        "message": "3304 definite только с детскими маркерами в description",
                    }
                )
            if (
                hs_scope
                and len(hs_scope) <= WIDE_HS_LEN_WARNING
                and not contains
                and hs_mode != "description_only"
                and hs_scope not in DEFINITE_NARROW_HS_ALLOWLIST
            ):
                warnings.append(
                    {
                        "code": "wide_definite_without_description",
                        "path": path,
                        "rule_id": rule_id,
                        "hs_scope": hs_scope,
                        "message": "definite на широком HS без description-условий",
                    }
                )

        if app == "possible" and hs_scope in ("3808",) and not contains:
            pass

    summary = {
        "total_rules": len(rules),
        "unique_rule_ids": len(seen_ids),
        "by_applicability": applicability_counts,
        "by_hs_scope_mode": hs_modes,
        "description_based_rules": description_based,
        "hs_only_rules": hs_only,
        "by_category": dict(sorted(categories.items())),
        "warnings_by_code": _count_warning_codes(warnings),
        "definite_narrow_hs_allowlist": sorted(DEFINITE_NARROW_HS_ALLOWLIST),
        "source_document": str(payload.get("source_document") or ""),
        "source_revision": str(payload.get("source_revision") or ""),
        "dataset_version": str(payload.get("dataset_version") or ""),
        "curation_note": str(payload.get("curation_note") or ""),
    }
    valid = not errors
    return _result(valid, errors, warnings, summary)


def _count_warning_codes(warnings: list[Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for w in warnings:
        code = str(w.get("code") or "other")
        out[code] = out.get(code, 0) + 1
    return out


def _result(
    valid: bool,
    errors: list[Any],
    warnings: list[Any],
    summary: dict[str, Any],
) -> dict[str, Any]:
    return {
        "valid": valid,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
        "summary": summary,
    }
