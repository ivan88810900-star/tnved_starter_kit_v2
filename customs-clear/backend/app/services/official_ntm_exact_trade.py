"""Fail-closed exact/shadow evaluation for selected trade-control rules.

This module is deliberately separate from ``non_tariff_service`` and the broker.
It turns structured transaction facts into explainable Decision-30 and Russian
export-control results, but cannot create a missing-document error by itself.

Two boundaries are intentional:

* a TN VED reference written as a prefix or ``из`` remains
  ``needs_clarification`` even when every supplied fact looks compatible;
* the six Russian export-control HS lists are candidate indexes only.  A bounded
  curated rule may reach ``definite`` only when its exact item, exact code,
  description and structured identification facts all agree.

Curated exact results run in shadow mode by default.  Enabling the flag below
changes only this module's returned applicability; ``used_for_missing_check``
and ``enforcement_enabled`` remain false and no broker integration exists.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from typing import Any

from .hs_matching import normalize_hs_code
from .official_export_control import (
    load_export_control_dataset,
    match_export_control_candidate,
)

SOURCE_KIND = "official_ntm_exact_trade"
SCHEMA_VERSION = "1"

CURATED_ALLOWLIST_FLAG = "NTM_V2_EXACT_TRADE_CURATED_ALLOWLIST_ENABLED"

DECISION_30_OFFICIAL_INDEX_URL = (
    "https://eec.eaeunion.org/comission/department/catr/nontariff/30.php"
)
DECISION_30_UNIFIED_LIST_URL = (
    "https://eec.eaeunion.org/comission/department/catr/nontariff/ep.new.php"
)
DECISION_30_SOURCE_REVISION = (
    "Decision-30/official-EEC; ETT-2022 recoding basis Decision 137/2021; "
    "curated slice checked 2026-08-15"
)

PP_1284_OFFICIAL_URL = "https://publication.pravo.gov.ru/Document/View/0001202207190026"
PP_1284_SOURCE_REVISION = "PP-RF-1284/2022-07-16; official publication 2022-07-19"
FZ_183_PRIMARY_COPY_URL = (
    "https://www.fsb.ru/fsb/npd/more.htm%21id%3D10434786%40fsbNpa.html"
)
FSTEC_CATCH_ALL_FORM_URL = "https://publication.pravo.gov.ru/document/0001202305260014"
FZ_183_SOURCE_REVISION = "Federal-Law-183-FZ/article-20; transaction-level catch-all"

_TRUE_VALUES = {"1", "true", "yes", "on", "да", "истина"}
_FALSE_VALUES = {"0", "false", "no", "off", "нет", "ложь", ""}
_RUSSIA_DESTINATIONS = {"ru", "rus", "russia", "russian federation", "рф", "россия"}

_WASTE_MARKERS = ("отход", "лом", "шлак", "зола", "шлам", "отработан")
_PESTICIDE_MARKERS = (
    "пестицид",
    "гербицид",
    "фунгицид",
    "инсектицид",
    "средство защиты растений",
    "plant protection",
)
_LAB_USE_MARKERS = (
    "лаборатор",
    "лабораторное исследование",
    "laboratory",
    "reference standard",
    "эталон",
    "стандартный образец",
)


def is_exact_trade_curated_allowlist_enabled() -> bool:
    """Return the explicit default-OFF exact-result flag state."""

    raw = os.getenv(CURATED_ALLOWLIST_FLAG)
    return bool(raw and raw.strip().lower() in _TRUE_VALUES)


def _text(value: Any) -> str:
    return str(value or "").strip().lower().replace("ё", "е")


def _direction(value: Any) -> str | None:
    normalized = _text(value)
    aliases = {
        "import": "import",
        "импорт": "import",
        "ввоз": "import",
        "export": "export",
        "экспорт": "export",
        "вывоз": "export",
        "both": "both",
        "оба": "both",
        "transit": "transit",
        "транзит": "transit",
    }
    return aliases.get(normalized)


def _strict_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    normalized = _text(value)
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    return None


def _to_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(str(value).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None


def _flatten_strings(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, Mapping):
        flattened: list[str] = []
        for key, nested in value.items():
            flattened.append(str(key))
            flattened.extend(_flatten_strings(nested))
        return tuple(flattened)
    if isinstance(value, (list, tuple, set, frozenset)):
        flattened = []
        for nested in value:
            flattened.extend(_flatten_strings(nested))
        return tuple(flattened)
    return (str(value),)


def _contains_any(value: Any, markers: tuple[str, ...]) -> bool:
    haystack = " ".join(_text(part) for part in _flatten_strings(value))
    return any(_text(marker) in haystack for marker in markers)


def _normalized_cas_numbers(facts: Mapping[str, Any]) -> set[str]:
    values = list(_flatten_strings(facts.get("cas_numbers")))
    composition = facts.get("composition")
    if isinstance(composition, Mapping):
        for key, value in composition.items():
            if "cas" in _text(key):
                values.extend(_flatten_strings(value))
    else:
        values.extend(_flatten_strings(composition))

    normalized: set[str] = set()
    for value in values:
        match = re.search(r"\b\d{2,7}-\d{2}-\d\b", str(value))
        if match:
            normalized.add(match.group(0))
    return normalized


def _direction_matches(required: str, actual: str | None) -> bool:
    return (
        actual is None
        or required == "both"
        or actual == required
        or (actual == "both" and required in {"import", "export"})
    )


def _missing_direction(required: str, actual: str | None) -> list[str]:
    if actual is None and required != "both":
        return ["direction"]
    return []


def _effective_applicability(
    *,
    exact_ready: bool,
    curated_allowlist_enabled: bool,
) -> tuple[str, str]:
    shadow = "definite" if exact_ready else "needs_clarification"
    effective = shadow if curated_allowlist_enabled else "needs_clarification"
    return effective, shadow


def _matched_rule(
    *,
    rule_id: str,
    hs_mode: str,
    hs_value: str,
    hs_code: str,
    description_condition: str,
    description_matched: bool,
    required_facts: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "hs": {
            "mode": hs_mode,
            "value": hs_value,
            "matched_code": hs_code,
        },
        "description_condition": description_condition,
        "description_matched": description_matched,
        "required_facts": list(required_facts),
    }


def _base_row(
    *,
    rule_id: str,
    family: str,
    direction: str,
    permit_type: str,
    source_url: str,
    source_revision: str,
    rule_name: str,
    missing_facts: list[str],
    exclusions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "source": SOURCE_KIND,
        "source_kind": SOURCE_KIND,
        "schema_version": SCHEMA_VERSION,
        "rule_id": rule_id,
        "family": family,
        "direction": direction,
        "permit_type": permit_type,
        "rule_name": rule_name,
        "source_url": source_url,
        "source_revision": source_revision,
        "missing_facts": sorted(set(missing_facts)),
        "exclusions": exclusions or [],
        "requires_manual_review": True,
        "used_for_missing_check": False,
        "enforcement_enabled": False,
    }


def _decision_30_pesticide_candidate(
    hs_code: str,
    description: str,
    facts: Mapping[str, Any],
    actual_direction: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rule_id = "D30-2.2-PESTICIDES-FROM-3808"
    if not hs_code.startswith("3808"):
        return [], []
    if hs_code.startswith("380894"):
        return [], [
            {
                "kind": "rule_exclusion",
                "rule_id": rule_id,
                "section": "2.2",
                "reason": "The official 'из 3808' row expressly excludes heading 3808 94.",
                "matched_hs": hs_code,
                "source_url": DECISION_30_UNIFIED_LIST_URL,
                "source_revision": DECISION_30_SOURCE_REVISION,
            }
        ]
    if not _direction_matches("import", actual_direction):
        return [], [
            {
                "kind": "direction_exclusion",
                "rule_id": rule_id,
                "section": "2.2",
                "required_direction": "import",
                "actual_direction": actual_direction,
            }
        ]

    purpose = facts.get("intended_use")
    description_matched = _contains_any(description, _PESTICIDE_MARKERS)
    purpose_matched = _contains_any(purpose, _PESTICIDE_MARKERS)
    missing = _missing_direction("import", actual_direction)
    if not (description_matched or purpose_matched):
        missing.append("intended_use:plant_protection")

    row = _base_row(
        rule_id=rule_id,
        family="licensing",
        direction="import",
        permit_type="ЛЗ/заключение",
        source_url=DECISION_30_UNIFIED_LIST_URL,
        source_revision=DECISION_30_SOURCE_REVISION,
        rule_name="Decision 30, section 2.2 — plant-protection products (from 3808)",
        missing_facts=missing,
    )
    row.update(
        {
            "section": "2.2",
            "applicability": "needs_clarification",
            "shadow_applicability": "needs_clarification",
            "match_precision": "prefix_from",
            "candidate_only": True,
            "curated_allowlist_eligible": False,
            "matched_rule": _matched_rule(
                rule_id=rule_id,
                hs_mode="prefix_from",
                hs_value="3808 (except 380894)",
                hs_code=hs_code,
                description_condition="plant-protection product / pesticide",
                description_matched=description_matched or purpose_matched,
                required_facts=("direction", "intended_use"),
            ),
            "reason": "The legal row is written as 'из 3808'; code and facts cannot make it exact.",
        }
    )
    return [row], []


def _decision_30_waste_candidates(
    hs_code: str,
    description: str,
    facts: Mapping[str, Any],
    actual_direction: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not hs_code.startswith("7204"):
        return [], []

    rows: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    description_matched = _contains_any(description, _WASTE_MARKERS)
    is_waste = _strict_bool(facts.get("is_waste"))
    hazardous = _strict_bool(facts.get("hazardous_waste"))
    contamination_present = bool(_flatten_strings(facts.get("contamination")))
    waste_class_present = bool(_flatten_strings(facts.get("waste_class")))

    specifications = (
        (
            "D30-1.2-WASTE-FROM-7204",
            "1.2",
            "import",
            "prohibitions_restrictions",
            "ЗАПРЕТ",
            "Decision 30, section 1.2 — prohibited hazardous waste (from 7204)",
        ),
        (
            "D30-2.3-WASTE-FROM-7204",
            "2.3",
            "both",
            "licensing",
            "ЗАКЛЮЧЕНИЕ/ЛЗ",
            "Decision 30, section 2.3 — controlled hazardous waste (from 7204)",
        ),
    )
    for (
        rule_id,
        section,
        required_direction,
        family,
        permit_type,
        rule_name,
    ) in specifications:
        if not _direction_matches(required_direction, actual_direction):
            diagnostics.append(
                {
                    "kind": "direction_exclusion",
                    "rule_id": rule_id,
                    "section": section,
                    "required_direction": required_direction,
                    "actual_direction": actual_direction,
                }
            )
            continue
        missing = _missing_direction(required_direction, actual_direction)
        if not description_matched:
            missing.append("description:waste")
        if is_waste is not True:
            missing.append("is_waste")
        if hazardous is not True:
            missing.append("hazardous_waste")
        if not (contamination_present or waste_class_present):
            missing.append("contamination_or_waste_class")

        row = _base_row(
            rule_id=rule_id,
            family=family,
            direction=required_direction,
            permit_type=permit_type,
            source_url=DECISION_30_UNIFIED_LIST_URL,
            source_revision=DECISION_30_SOURCE_REVISION,
            rule_name=rule_name,
            missing_facts=missing,
        )
        row.update(
            {
                "section": section,
                "applicability": "needs_clarification",
                "shadow_applicability": "needs_clarification",
                "match_precision": "prefix_from",
                "candidate_only": True,
                "curated_allowlist_eligible": False,
                "matched_rule": _matched_rule(
                    rule_id=rule_id,
                    hs_mode="prefix_from",
                    hs_value="7204",
                    hs_code=hs_code,
                    description_condition="waste with listed composition/contaminant",
                    description_matched=description_matched,
                    required_facts=(
                        "direction",
                        "is_waste",
                        "hazardous_waste",
                        "contamination_or_waste_class",
                    ),
                ),
                "reason": "The official row is 'из 7204'; generic ferrous scrap is never definite.",
            }
        )
        rows.append(row)
    return rows, diagnostics


def _decision_30_hexachlorobenzene_exact(
    hs_code: str,
    description: str,
    facts: Mapping[str, Any],
    actual_direction: str | None,
    curated_allowlist_enabled: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Bounded exact row from Decision 30 section 2.30 (CAS 118-74-1)."""

    rule_id = "D30-2.30-HCB-2903920000"
    if hs_code != "2903920000":
        return [], []
    if not _direction_matches("import", actual_direction):
        return [], [
            {
                "kind": "direction_exclusion",
                "rule_id": rule_id,
                "section": "2.30",
                "required_direction": "import",
                "actual_direction": actual_direction,
                "reason": "Section 2.30 regulates import only.",
            }
        ]

    description_matched = _contains_any(
        description,
        ("гексахлорбензол", "hexachlorobenzene", "hcb"),
    )
    cas_matched = "118-74-1" in _normalized_cas_numbers(facts)
    intended_use_matched = _contains_any(facts.get("intended_use"), _LAB_USE_MARKERS)
    technical_confirmed = (
        _strict_bool(facts.get("technical_parameters_confirmed")) is True
    )
    official_name_confirmed = (
        _strict_bool(facts.get("product_name_matches_official_row")) is True
    )
    manufacturer_documents_verified = (
        _strict_bool(facts.get("manufacturer_documents_verified")) is True
    )
    sealed_container = _strict_bool(facts.get("sealed_container")) is True
    package_volume_ml = _to_float(facts.get("package_volume_ml"))
    package_mass_g = _to_float(facts.get("package_mass_g"))
    presentation_quantity_confirmed = any(
        quantity is not None and 1.0 <= quantity <= 10.0
        for quantity in (package_volume_ml, package_mass_g)
    )
    missing = _missing_direction("import", actual_direction)
    if not description_matched:
        missing.append("description:hexachlorobenzene")
    if not cas_matched:
        missing.append("cas_numbers:118-74-1")
    if not intended_use_matched:
        missing.append("intended_use:laboratory_or_reference_standard")
    if not technical_confirmed:
        missing.append("technical_parameters_confirmed")
    if not official_name_confirmed:
        missing.append("product_name_matches_official_row")
    if not manufacturer_documents_verified:
        missing.append("manufacturer_documents_verified")
    if not sealed_container:
        missing.append("sealed_container")
    if not presentation_quantity_confirmed:
        missing.append("package_volume_ml_or_package_mass_g:1_to_10")

    exact_ready = not missing
    applicability, shadow_applicability = _effective_applicability(
        exact_ready=exact_ready,
        curated_allowlist_enabled=curated_allowlist_enabled,
    )
    row = _base_row(
        rule_id=rule_id,
        family="licensing",
        direction="import",
        permit_type="ЛЗ/заключение",
        source_url=DECISION_30_UNIFIED_LIST_URL,
        source_revision=DECISION_30_SOURCE_REVISION,
        rule_name="Decision 30, section 2.30 — hexachlorobenzene (CAS 118-74-1)",
        missing_facts=missing,
    )
    row.update(
        {
            "section": "2.30",
            "applicability": applicability,
            "shadow_applicability": shadow_applicability,
            "match_precision": "exact",
            "candidate_only": False,
            "curated_allowlist_eligible": exact_ready,
            "curated_allowlist_enabled": curated_allowlist_enabled,
            "matched_rule": _matched_rule(
                rule_id=rule_id,
                hs_mode="exact",
                hs_value="2903920000",
                hs_code=hs_code,
                description_condition="hexachlorobenzene / HCB",
                description_matched=description_matched,
                required_facts=(
                    "direction=import",
                    "cas_numbers contains 118-74-1",
                    "intended_use is laboratory research or reference standard",
                    "technical_parameters_confirmed",
                    "product_name_matches_official_row",
                    "manufacturer_documents_verified",
                    "sealed_container",
                    "package_volume_ml_or_package_mass_g is 1–10",
                ),
            ),
            "reason": (
                "Exact status requires code, substance identity/CAS, permitted purpose and confirmation "
                "of the section's physical, chemical and sealed 1–10 ml(g) presentation conditions."
            ),
        }
    )
    return [row], []


def _export_control_item(facts: Mapping[str, Any]) -> tuple[int | None, str | None]:
    value = facts.get("export_control_list_item")
    if isinstance(value, Mapping):
        number_raw = value.get("source_number", value.get("list_number"))
        try:
            source_number = int(number_raw) if number_raw is not None else None
        except (TypeError, ValueError):
            source_number = None
        item = _text(value.get("item_id", value.get("item"))) or None
        return source_number, item
    normalized = _text(value).replace("пп-рф-", "pp-").replace("pp-rf-", "pp-")
    match = re.search(
        r"(?:pp-)?(1284|1285|1286|1287|1288|1299)\s*[:/#-]\s*([0-9.]+)", normalized
    )
    if not match:
        return None, None
    return int(match.group(1)), match.group(2).rstrip(".")


def _matched_export_sources(hs_code: str) -> list[dict[str, Any]]:
    payload = load_export_control_dataset()
    sources: list[dict[str, Any]] = []
    for source in payload.get("source_lists") or []:
        if not isinstance(source, Mapping):
            continue
        prefixes = tuple(
            normalize_hs_code(str(candidate))
            for candidate in (source.get("hs_candidates") or [])
        )
        if any(prefix and hs_code.startswith(prefix) for prefix in prefixes):
            sources.append(
                {
                    "number": source.get("number"),
                    "title": source.get("title"),
                    "official_url": source.get("official_url"),
                }
            )
    return sources


def _retired_export_row(hs_code: str) -> dict[str, Any] | None:
    metadata = load_export_control_dataset().get("retired_exact_codes") or {}
    for row in metadata.get("codes") or []:
        if normalize_hs_code(str(row.get("hs_code") or "")) == hs_code:
            return {
                "kind": "retired_export_control_code",
                "rule_id": "RF-EXPORT-HS-CANDIDATE",
                "matched_hs": hs_code,
                "replacement_code": normalize_hs_code(
                    str(row.get("replacement_code") or "")
                ),
                "catalog_revision": metadata.get("catalog_revision"),
                "effective_from": metadata.get("effective_from"),
                "basis": metadata.get("basis"),
                "source_url": metadata.get("basis_url"),
                "reason": "The exact code is retired and cannot inherit candidate status by prefix.",
            }
    return None


def _export_control_rows(
    hs_code: str,
    description: str,
    facts: Mapping[str, Any],
    actual_direction: str | None,
    curated_allowlist_enabled: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    retired = _retired_export_row(hs_code)
    if retired:
        return [], [retired]
    matched_prefix = match_export_control_candidate(hs_code)
    if not matched_prefix:
        return [], []
    if not _direction_matches("export", actual_direction):
        return [], [
            {
                "kind": "direction_exclusion",
                "rule_id": "RF-EXPORT-HS-CANDIDATE",
                "required_direction": "export",
                "actual_direction": actual_direction,
            }
        ]

    source_documents = _matched_export_sources(hs_code)
    if hs_code == "2930909508":
        rule_id = "RF-PP1284-2.1.1-AMITON"
        description_matched = _contains_any(
            description,
            ("амитон", "amiton", "o,o-диэтил-s", "о,о-диэтил-s"),
        )
        cas_matched = "78-53-5" in _normalized_cas_numbers(facts)
        source_number, item_id = _export_control_item(facts)
        item_matched = source_number == 1284 and item_id == "2.1.1"
        technical_confirmed = (
            _strict_bool(facts.get("technical_parameters_confirmed")) is True
        )
        official_name_confirmed = (
            _strict_bool(facts.get("product_name_matches_official_row")) is True
        )
        manufacturer_documents_verified = (
            _strict_bool(facts.get("manufacturer_documents_verified")) is True
        )
        destination = _text(facts.get("destination_country"))
        destination_matched = bool(
            destination and destination not in _RUSSIA_DESTINATIONS
        )
        end_user_present = bool(_flatten_strings(facts.get("end_user")))
        missing = _missing_direction("export", actual_direction)
        if not description_matched:
            missing.append("description:amiton")
        if not cas_matched:
            missing.append("cas_numbers:78-53-5")
        if not item_matched:
            missing.append("export_control_list_item:PP-1284:2.1.1")
        if not technical_confirmed:
            missing.append("technical_parameters_confirmed")
        if not destination_matched:
            missing.append("destination_country:foreign")
        if not end_user_present:
            missing.append("end_user")
        if not official_name_confirmed:
            missing.append("product_name_matches_official_row")
        if not manufacturer_documents_verified:
            missing.append("manufacturer_documents_verified")

        exact_ready = not missing
        applicability, shadow_applicability = _effective_applicability(
            exact_ready=exact_ready,
            curated_allowlist_enabled=curated_allowlist_enabled,
        )
        row = _base_row(
            rule_id=rule_id,
            family="export_control_dual_use",
            direction="export",
            permit_type="ЛЗ/разрешение ФСТЭК",
            source_url=PP_1284_OFFICIAL_URL,
            source_revision=PP_1284_SOURCE_REVISION,
            rule_name="PP RF 1284, item 2.1.1 — amiton (CAS 78-53-5)",
            missing_facts=missing,
        )
        row.update(
            {
                "applicability": applicability,
                "shadow_applicability": shadow_applicability,
                "match_precision": "exact",
                "candidate_only": False,
                "curated_allowlist_eligible": exact_ready,
                "curated_allowlist_enabled": curated_allowlist_enabled,
                "hs_candidate_prefix": matched_prefix,
                "source_documents": source_documents,
                "matched_rule": _matched_rule(
                    rule_id=rule_id,
                    hs_mode="exact",
                    hs_value="2930909508",
                    hs_code=hs_code,
                    description_condition="amiton / exact CAS 78-53-5",
                    description_matched=description_matched,
                    required_facts=(
                        "direction=export",
                        "destination_country is foreign",
                        "export_control_list_item=PP-1284:2.1.1",
                        "cas_numbers contains 78-53-5",
                        "technical_parameters_confirmed",
                        "end_user",
                        "product_name_matches_official_row",
                        "manufacturer_documents_verified",
                    ),
                ),
                "reason": "The HS candidate becomes exact only for the curated identified list item.",
            }
        )
        return [row], []

    missing = _missing_direction("export", actual_direction)
    missing.extend(("export_control_list_item", "technical_parameters_confirmed"))
    row = _base_row(
        rule_id="RF-EXPORT-HS-CANDIDATE",
        family="export_control_dual_use",
        direction="export",
        permit_type="ЛЗ/разрешение ФСТЭК",
        source_url=str(
            (source_documents[0].get("official_url") if source_documents else None)
            or load_export_control_dataset().get("source_url")
        ),
        source_revision=str(
            load_export_control_dataset().get("dataset_id") or "candidate-index"
        ),
        rule_name="Russian export-control lists — HS candidate only",
        missing_facts=missing,
    )
    row.update(
        {
            "applicability": "needs_clarification",
            "shadow_applicability": "needs_clarification",
            "match_precision": "candidate_prefix",
            "candidate_only": True,
            "curated_allowlist_eligible": False,
            "hs_candidate_prefix": matched_prefix,
            "source_documents": source_documents,
            "matched_rule": _matched_rule(
                rule_id="RF-EXPORT-HS-CANDIDATE",
                hs_mode="candidate_prefix",
                hs_value=matched_prefix,
                hs_code=hs_code,
                description_condition="not encoded in the HS candidate index",
                description_matched=False,
                required_facts=(
                    "export_control_list_item",
                    "technical_parameters_confirmed",
                ),
            ),
            "reason": (
                "HS codes in the six lists are reference candidates. Name, purpose and list-specific "
                "technical thresholds require identification."
            ),
        }
    )
    return [row], []


def _risk_signal(value: Any) -> bool:
    parsed = _strict_bool(value)
    if parsed is not None:
        return parsed
    if isinstance(value, Mapping):
        return any(_risk_signal(nested) for nested in value.values())
    return _text(value) in {
        "risk",
        "high",
        "confirmed",
        "match",
        "yes",
        "indicators_present",
        "indicators present",
        "индикаторы",
        "есть индикаторы",
    }


def _evaluate_catch_all(
    facts: Mapping[str, Any],
    actual_direction: str | None,
) -> dict[str, Any]:
    end_user = facts.get("end_user")
    wmd = _risk_signal(facts.get("wmd_end_use"))
    military = _risk_signal(facts.get("military_end_use"))
    sanctioned = _risk_signal(facts.get("sanctioned_end_user"))
    explicit_risk = _risk_signal(facts.get("catch_all_risk"))
    if isinstance(end_user, Mapping):
        wmd = wmd or _risk_signal(end_user.get("wmd_end_use"))
        military = military or _risk_signal(end_user.get("military_end_use"))
        sanctioned = sanctioned or _risk_signal(end_user.get("sanctioned"))

    result: dict[str, Any] = {
        "rule_id": "RF-183-FZ-ARTICLE-20-CATCH-ALL",
        "family": "export_control_catch_all",
        "scope": "transaction",
        "source_url": FZ_183_PRIMARY_COPY_URL,
        "operational_form_source_url": FSTEC_CATCH_ALL_FORM_URL,
        "source_revision": FZ_183_SOURCE_REVISION,
        "automatic_document_requirement": False,
        "document_type": None,
        "permit_type": None,
        "used_for_missing_check": False,
        "enforcement_enabled": False,
        "evidence": {
            "catch_all_risk": explicit_risk,
            "military_end_use": military,
            "wmd_end_use": wmd,
            "sanctioned_end_user": sanctioned,
        },
    }
    if actual_direction in {"import", "transit"}:
        result.update(
            {
                "status": "not_applicable_direction",
                "applicability": "not_applicable",
                "missing_facts": [],
                "reason": (
                    "Article 20 catch-all is evaluated for an export/foreign-transfer "
                    "transaction, not the supplied movement direction."
                ),
            }
        )
        return result

    missing = [] if actual_direction == "export" else ["direction"]
    if wmd:
        result.update(
            {
                "status": "prohibited_transaction_risk",
                "applicability": "transaction_risk",
                "missing_facts": missing,
                "reason": (
                    "Structured transaction evidence indicates WMD/end-use knowledge. Article 20(1) "
                    "is a transaction prohibition risk, not an HS-code document requirement."
                ),
                "recommended_action": "stop_transaction_and_escalate_to_export_control_counsel",
            }
        )
    elif explicit_risk or military or sanctioned:
        result.update(
            {
                "status": "permission_review_required",
                "applicability": "transaction_risk",
                "missing_facts": missing,
                "reason": (
                    "End-use/end-user evidence triggers Article 20 transaction review even when the "
                    "item is absent from a control-list HS candidate index."
                ),
                "recommended_action": "obtain_identification_and_check_commission_permission",
            }
        )
    else:
        result.update(
            {
                "status": "not_detected",
                "applicability": "not_detected",
                "missing_facts": missing,
                "reason": (
                    "No catch-all risk fact was supplied. This is not a clean-party or end-use clearance."
                ),
                "recommended_action": "collect_end_use_and_end_user_evidence",
            }
        )
    return result


def evaluate_exact_trade_measures(
    hs_code: str,
    description: str = "",
    facts: Mapping[str, Any] | None = None,
    *,
    curated_allowlist_enabled: bool | None = None,
) -> dict[str, Any]:
    """Evaluate a bounded exact Decision-30/export-control slice.

    ``facts`` stays a generic mapping so callers can add source-specific evidence.
    Canonical keys currently consumed are ``direction``, ``origin_country``,
    ``destination_country``, ``intended_use``, ``end_user``, ``composition``,
    ``cas_numbers``, ``is_waste``, ``hazardous_waste``, ``waste_class``,
    ``contamination``, ``export_control_list_item``,
    ``technical_parameters_confirmed``, ``catch_all_risk``, ``military_end_use``,
    ``wmd_end_use`` and ``sanctioned_end_user``.  Cultural age/value facts are
    accepted but intentionally not converted into a definite rule in this bounded
    slice because section 2.20 criteria are not curated here.
    """

    fact_map: Mapping[str, Any] = facts if isinstance(facts, Mapping) else {}
    code = normalize_hs_code(hs_code)
    actual_direction = _direction(fact_map.get("direction"))
    allowlist_enabled = (
        is_exact_trade_curated_allowlist_enabled()
        if curated_allowlist_enabled is None
        else bool(curated_allowlist_enabled)
    )

    rows: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    if len(code) != 10:
        diagnostics.append(
            {
                "kind": "invalid_or_non_declarable_hs_code",
                "provided_hs": str(hs_code or ""),
                "normalized_hs": code,
                "reason": "Exact evaluation requires a 10-digit TN VED EAEU code.",
            }
        )
    else:
        evaluators = (
            lambda: _decision_30_pesticide_candidate(
                code, description, fact_map, actual_direction
            ),
            lambda: _decision_30_waste_candidates(
                code, description, fact_map, actual_direction
            ),
            lambda: _decision_30_hexachlorobenzene_exact(
                code,
                description,
                fact_map,
                actual_direction,
                allowlist_enabled,
            ),
            lambda: _export_control_rows(
                code,
                description,
                fact_map,
                actual_direction,
                allowlist_enabled,
            ),
        )
        for evaluator in evaluators:
            new_rows, new_diagnostics = evaluator()
            rows.extend(new_rows)
            diagnostics.extend(new_diagnostics)

    raw_direction = fact_map.get("direction")
    if raw_direction not in (None, "") and actual_direction is None:
        diagnostics.append(
            {
                "kind": "invalid_direction",
                "provided_direction": str(raw_direction),
                "accepted_values": [
                    "import",
                    "export",
                    "transit",
                    "ввоз",
                    "вывоз",
                    "транзит",
                ],
            }
        )

    return {
        "source_kind": SOURCE_KIND,
        "schema_version": SCHEMA_VERSION,
        "hs_code": code,
        "direction": actual_direction,
        "rows": rows,
        "catch_all": _evaluate_catch_all(fact_map, actual_direction),
        "diagnostics": diagnostics,
        "curated_allowlist": {
            "flag": CURATED_ALLOWLIST_FLAG,
            "enabled": allowlist_enabled,
            "default": False,
            "broker_integrated": False,
            "used_for_missing_check": False,
        },
        "coverage": {
            "decision_30_sections": ["1.2", "2.2", "2.3", "2.30"],
            "decision_30_exact_rule_ids": ["D30-2.30-HCB-2903920000"],
            "export_control_hs_dataset": "six_lists_candidate_only",
            "export_control_exact_rule_ids": ["RF-PP1284-2.1.1-AMITON"],
            "catch_all_scope": "transaction_not_hs_document",
        },
        "provided_fact_keys": sorted(str(key) for key in fact_map),
        "disclaimer": (
            "Bounded exact/shadow evaluator; it is not complete Decision-30 legal coverage, "
            "does not perform party screening and cannot enforce or mark a document missing."
        ),
    }


__all__ = [
    "CURATED_ALLOWLIST_FLAG",
    "DECISION_30_OFFICIAL_INDEX_URL",
    "DECISION_30_UNIFIED_LIST_URL",
    "evaluate_exact_trade_measures",
    "is_exact_trade_curated_allowlist_enabled",
]
