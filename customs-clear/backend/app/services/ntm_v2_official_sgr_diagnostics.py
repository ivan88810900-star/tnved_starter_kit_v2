"""Диагностика: official SGR contour vs legacy СГР (без production broker)."""

from __future__ import annotations

from datetime import date
from typing import Any

from .hs_matching import normalize_hs_code
from .ntm_layers import get_sgr_requirement
from .ntm_v2_legacy_rules_import import (
    get_advisory_legacy_rule_requirements_v2,
    get_legacy_rule_requirements_for_enforcement,
)
from .ntm_v2_official_sgr_import import (
    OFFICIAL_SGR_SOURCE_KIND,
    evaluate_official_sgr_for_position,
)


def _legacy_layers_sgr(hs_code: str, description: str) -> dict[str, Any] | None:
    row = get_sgr_requirement(hs_code, description)
    if not row:
        return None
    return {
        "source": "ntm_layers.get_sgr_requirement",
        "permit_type": row.get("permit_type"),
        "matched_prefix": row.get("matched_prefix"),
        "trigger": row.get("trigger"),
        "legal_ref": row.get("legal_ref"),
        "applicability_implied": "definite",
    }


def _legacy_rules_sgr(hs_code: str, description: str) -> dict[str, Any]:
    advisory = [
        r
        for r in get_advisory_legacy_rule_requirements_v2(hs_code, description)
        if (r.get("permit_type") or "") == "СГР"
    ]
    definite_rows = [
        r
        for r in get_legacy_rule_requirements_for_enforcement(hs_code, description)
        if (r.get("permit_type") or "") == "СГР"
    ]
    return {
        "advisory": advisory,
        "definite_enforcement_rows": definite_rows,
        "has_advisory_sgr": bool(advisory),
        "has_definite_sgr": bool(definite_rows),
    }


def _sgr_keys_from_legacy_layers(row: dict[str, Any] | None) -> set[str]:
    if not row:
        return set()
    return {f"СГР|{row.get('matched_prefix') or ''}|layers"}


def _sgr_keys_from_rules(rows: list[dict[str, Any]], *, tag: str) -> set[str]:
    out: set[str] = set()
    for r in rows:
        pt = r.get("permit_type") or "СГР"
        hp = r.get("matched_prefix") or r.get("hs_prefix") or ""
        tr = r.get("tr_ts") or ""
        app = r.get("applicability") or tag
        out.add(f"{pt}|{hp}|{tr}|{app}")
    return out


def _sgr_keys_from_official(eval_result: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for r in eval_result.get("matched_rules") or []:
        hp = r.get("hs_prefix") or ""
        app = r.get("applicability") or ""
        rid = r.get("rule_import_key") or r.get("title") or ""
        out.add(f"СГР|{hp}|official|{app}|{rid}")
    return out


def compare_official_sgr_rules_vs_legacy_sgr(
    hs_code: str,
    description: str = "",
    *,
    as_of: date | None = None,
) -> dict[str, Any]:
    """
    Сравнение legacy СГР (layers + legacy rules) с official v2 contour.

    Не меняет runtime check; только диагностика для миграции нормативной базы.
    """
    _ = as_of
    norm = normalize_hs_code(hs_code)
    layers = _legacy_layers_sgr(norm, description)
    legacy_rules = _legacy_rules_sgr(norm, description)
    official = evaluate_official_sgr_for_position(norm, description)

    legacy_keys = _sgr_keys_from_legacy_layers(layers)
    legacy_keys |= _sgr_keys_from_rules(legacy_rules.get("advisory") or [], tag="possible")
    legacy_keys |= _sgr_keys_from_rules(legacy_rules.get("definite_enforcement_rows") or [], tag="definite")

    official_keys = _sgr_keys_from_official(official)

    legacy_implied_definite = layers is not None
    legacy_advisory = legacy_rules.get("has_advisory_sgr", False)

    return {
        "hs_code": norm,
        "description": description,
        "legacy": {
            "layers": layers,
            "rules": legacy_rules,
            "implies_definite_via_layers": legacy_implied_definite,
            "implies_sgr_via_rules_advisory": legacy_advisory,
        },
        "official_v2": {
            "source_kind": OFFICIAL_SGR_SOURCE_KIND,
            "evaluation": official,
            "has_definite_sgr": official.get("has_definite_sgr"),
            "has_advisory_sgr": official.get("has_advisory_sgr"),
        },
        "legacy_only_sgr": sorted(legacy_keys - official_keys),
        "official_only_sgr": sorted(official_keys - legacy_keys),
        "overlap_keys": sorted(legacy_keys & official_keys),
        "legacy_extra_sgr": {
            "layers_definite_without_official": legacy_implied_definite
            and not official.get("has_definite_sgr")
            and not official.get("has_advisory_sgr"),
            "rules_advisory_sgr": legacy_rules.get("advisory") or [],
            "note": (
                "legacy_extra: широкие legacy_non_tariff_rules (possible) или layers definite "
                "без соответствия в official contour"
            ),
        },
        "official_extra_sgr": {
            "rules": (official.get("advisory_rules") or []) + (official.get("definite_rules") or []),
            "note": "official contour без аналога в legacy layers/rules",
        },
    }
