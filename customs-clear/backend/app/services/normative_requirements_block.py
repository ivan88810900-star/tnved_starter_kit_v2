"""
Продуктовый блок нормативных требований (MVP).

Агрегирует результат ``check_position_non_tariff`` в структуру для UI:
обязательные / отсутствующие / advisory документы с метками источника и applicability.

Не меняет broker / missing-check семантику — только нормализует уже вычисленный ответ.
"""
from __future__ import annotations

from typing import Any

SOURCE_LABELS: dict[str, str] = {
    "tr_ts_catalog": "ТР ТС каталог",
    "broker_catalog_layers": "Каталог нетарифных требований",
    "runtime_triggers": "Триггер по описанию товара",
    "sensitive_override": "Чувствительная группа товара",
    "legacy_non_tariff_rules": "Историческое правило (подсказка)",
    "legacy_non_tariff_measures": "Legacy меры (справочно)",
    "official_sgr_registry": "Решение ЕЭК №299",
    "domain_default": "Доменная форма подтверждения (ЕЭК №620)",
    "non_tariff_measures": "Нетарифные меры (runtime)",
    "rules_db": "Правила нетарифного контроля",
    "measures_db": "Меры нетарифного регулирования",
}

_EMPTY_MESSAGE = (
    "Для данной позиции не выявлено нормативных требований к разрешительным документам. "
    "Уточните код ТН ВЭД и описание товара."
)


def source_label_for(source: str | None) -> str:
    key = (source or "").strip()
    if not key:
        return "Источник не указан"
    return SOURCE_LABELS.get(key, key)


def _resolve_broker_source(row: dict[str, Any]) -> str:
    explicit = (row.get("source") or "").strip()
    if explicit:
        return explicit
    legal_ref = (row.get("legal_ref") or "").strip()
    if legal_ref == "SENSITIVE_OVERRIDES":
        return "sensitive_override"
    if row.get("trigger"):
        return "runtime_triggers"
    if legal_ref == "get_default_cert_form()":
        return "domain_default"
    if legal_ref in ("catalog", "non_tariff_measures") or row.get("source_level"):
        if legal_ref == "non_tariff_measures":
            return "non_tariff_measures"
        return "tr_ts_catalog"
    return "broker_catalog_layers"


def _broker_evidence(row: dict[str, Any]) -> str | None:
    parts: list[str] = []
    desc = (row.get("description") or "").strip()
    if desc:
        parts.append(desc)
    legal_ref = (row.get("legal_ref") or "").strip()
    skip_refs = {"catalog", "SENSITIVE_OVERRIDES", "get_default_cert_form()", "non_tariff_measures"}
    if legal_ref and legal_ref not in skip_refs:
        parts.append(legal_ref)
    trigger = row.get("trigger")
    if trigger:
        parts.append(f"Триггер: {trigger}")
    if not parts:
        return None
    return " · ".join(parts)


def _required_document_from_broker(row: dict[str, Any]) -> dict[str, Any]:
    source = _resolve_broker_source(row)
    tr_ts = row.get("tr_ts")
    applicability = (row.get("applicability") or "").strip() or "definite"
    return {
        "permit_type": str(row.get("permit_type") or "").strip(),
        "tr_ts": tr_ts,
        "source": source,
        "source_label": source_label_for(source),
        "applicability": applicability,
        "reason": _broker_evidence(row),
        "used_for_missing_check": True,
        "rule_name": (row.get("description") or "").strip()[:200] or None,
    }


def _enrich_advisory_item(item: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(item)
    src = (enriched.get("source") or "").strip()
    if not enriched.get("source_label"):
        enriched["source_label"] = source_label_for(src)
    enriched.setdefault("used_for_missing_check", False)
    return enriched


def build_normative_requirements_block(non_tariff_result: dict[str, Any]) -> dict[str, Any]:
    """
    Собирает продуктовый блок из ответа ``check_position_non_tariff``.

    * ``required_documents`` — broker-строки (``used_for_missing_check=True``).
    * ``missing_documents`` — подмножество по ``missing_permit_types``.
    * ``advisory_requirements`` — possible / needs_clarification / official SGR (advisory-only).
    """
    required_permits: list[dict[str, Any]] = list(non_tariff_result.get("required_permits") or [])
    missing_types = set(non_tariff_result.get("missing_permit_types") or [])
    advisory_raw: list[dict[str, Any]] = list(non_tariff_result.get("advisory_requirements") or [])

    required_documents = [
        doc for doc in (_required_document_from_broker(r) for r in required_permits) if doc["permit_type"]
    ]

    missing_by_type: dict[str, dict[str, Any]] = {}
    for row in required_permits:
        pt = str(row.get("permit_type") or "").strip()
        if pt and pt in missing_types and pt not in missing_by_type:
            missing_by_type[pt] = row

    missing_documents: list[dict[str, Any]] = []
    for pt in sorted(missing_types):
        row = missing_by_type.get(pt, {})
        source = _resolve_broker_source(row) if row else "broker_catalog_layers"
        missing_documents.append(
            {
                "permit_type": pt,
                "tr_ts": row.get("tr_ts") if row else None,
                "source": source,
                "source_label": source_label_for(source),
                "reason": "Документ не указан среди предоставленных разрешений",
                "used_for_missing_check": True,
            }
        )

    advisory_requirements = [_enrich_advisory_item(a) for a in advisory_raw]

    sources_summary = sorted(
        {
            *(d.get("source") for d in required_documents if d.get("source")),
            *(d.get("source") for d in missing_documents if d.get("source")),
            *(a.get("source") for a in advisory_requirements if a.get("source")),
        }
    )

    has_any = bool(required_documents or missing_documents or advisory_requirements)
    empty_message: str | None = _EMPTY_MESSAGE if not has_any else None

    return {
        "status": non_tariff_result.get("status"),
        "hs_code": non_tariff_result.get("hs_code"),
        "description": non_tariff_result.get("description"),
        "required_documents": required_documents,
        "missing_documents": missing_documents,
        "advisory_requirements": advisory_requirements,
        "sources_summary": sources_summary,
        "empty_message": empty_message,
        "tr_ts": list(non_tariff_result.get("tr_ts") or []),
        "notes": list(non_tariff_result.get("notes") or []),
    }
