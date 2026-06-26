"""
Единый слой нормализованных нетарифных требований (effective requirements).

Сводит broker / rules / measures в одну структуру с явным флагом
``used_for_missing_check`` (в текущем PR совпадает с набором ключей из broker).
Не меняет расчёт ``missing_permit_types`` в ``check_position_non_tariff``.
"""
from __future__ import annotations

from typing import Any, TypedDict


class EffectiveRequirement(TypedDict):
    permit_type: str
    tr_ts: str | None
    key: str
    sources: list[str]
    source_details: list[dict[str, Any]]
    used_for_missing_check: bool


def _normalize_tr_ts(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


def _compact_key(permit_type: str, tr_ts: str | None) -> str:
    p = (permit_type or "").strip()
    t = tr_ts or ""
    return f"{p}|{t}"


def _internal_key(permit_type: str, tr_ts: Any) -> tuple[str, str | None]:
    p = (permit_type or "").strip()
    return (p, _normalize_tr_ts(tr_ts))


def _broker_row_source_tag(row: dict[str, Any]) -> str:
    if (row.get("legal_ref") or "").strip() == "SENSITIVE_OVERRIDES":
        return "sensitive_override"
    if row.get("trigger") is not None:
        return "broker_triggers"
    return "broker_catalog_layers"


def _merge_requirement(
    store: dict[tuple[str, str | None], EffectiveRequirement],
    permit_type: str,
    tr_ts: Any,
    source: str,
    detail: dict[str, Any],
    *,
    used_for_missing_check: bool,
) -> None:
    ik = _internal_key(permit_type, tr_ts)
    if not ik[0]:
        return
    key_str = _compact_key(ik[0], ik[1])
    if ik not in store:
        store[ik] = {
            "permit_type": ik[0],
            "tr_ts": ik[1],
            "key": key_str,
            "sources": [],
            "source_details": [],
            "used_for_missing_check": False,
        }
    er = store[ik]
    if source not in er["sources"]:
        er["sources"].append(source)
    er["sources"].sort()
    er["source_details"].append(detail)
    er["used_for_missing_check"] = er["used_for_missing_check"] or used_for_missing_check


def build_effective_requirements(
    *,
    broker_required_permits: list[dict[str, Any]],
    rules: list[dict[str, Any]],
    measures: list[dict[str, Any]],
    trigger_measures: list[dict[str, Any]] | None = None,
    legacy_v2_rules: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Собирает нормализованные требования по ключу ``(permit_type, tr_ts)``.

    * Broker-строки (итог ``_build_broker_required_permits``) → ``used_for_missing_check=True``.
    * Правила БД (декартово ``required_permits`` × ``tr_ts``) → ``rules_db``, ``used_for_missing_check=False``.
    * Меры БД (только непустой ``permit_type``) → ``measures_db``, ``used_for_missing_check=False``.
    * ``trigger_measures`` не добавляют отдельных ключей: они уже учтены в broker; параметр
      зарезервирован для будущего расширения детализации (сейчас может быть пустым).

    Возвращает словарь с полями ``all``, ``used_for_missing_check``, ``informational_only``,
    ``informational_not_used_for_missing_check_count``.
    """
    _ = trigger_measures  # зарезервировано: триггеры уже в broker_required_permits

    store: dict[tuple[str, str | None], EffectiveRequirement] = {}

    for br in broker_required_permits:
        pt = str(br.get("permit_type") or "").strip()
        if not pt:
            continue
        src = _broker_row_source_tag(br)
        detail = {
            "source": src,
            "matched_prefix": br.get("matched_prefix"),
            "legal_ref": (br.get("legal_ref") or "")[:200],
            "description": (br.get("description") or "")[:200],
            "trigger": br.get("trigger"),
        }
        _merge_requirement(store, pt, br.get("tr_ts"), src, detail, used_for_missing_check=True)

    for rule in rules:
        permits = [x for x in (rule.get("required_permits") or []) if x]
        trs = [x for x in (rule.get("tr_ts") or []) if x]
        if not permits:
            continue
        if not trs:
            trs = [""]
        for p in permits:
            for t in trs:
                detail = {
                    "source": "rules_db",
                    "rule_name": rule.get("name"),
                    "hs_prefix": rule.get("hs_prefix"),
                    "tr_ts_fragment": t or None,
                }
                _merge_requirement(
                    store,
                    str(p).strip(),
                    t if t else None,
                    "rules_db",
                    detail,
                    used_for_missing_check=False,
                )

    for m in measures:
        pt = (m.get("permit_type") or "").strip()
        if not pt:
            continue
        ts = (m.get("tr_ts_code") or "").strip() or None
        detail = {
            "source": "measures_db",
            "commodity_code": m.get("commodity_code"),
            "measure_type": m.get("measure_type"),
            "source_level": m.get("source_level"),
            "match_prefix_len": m.get("match_prefix_len"),
        }
        _merge_requirement(store, pt, ts, "measures_db", detail, used_for_missing_check=False)

    for lr in legacy_v2_rules or []:
        pt = str(lr.get("permit_type") or "").strip()
        if not pt:
            continue
        used = bool(lr.get("used_for_missing_check"))
        detail = {
            "source": str(lr.get("source") or "legacy_non_tariff_rules_v2"),
            "applicability": lr.get("applicability"),
            "matched_prefix": lr.get("matched_prefix"),
            "description": (lr.get("description") or "")[:200],
            "legal_ref": (lr.get("legal_ref") or "")[:200],
        }
        _merge_requirement(
            store,
            pt,
            lr.get("tr_ts"),
            "legacy_non_tariff_rules_v2",
            detail,
            used_for_missing_check=used,
        )

    all_items = sorted(
        store.values(),
        key=lambda x: (x["permit_type"], x["key"]),
    )
    used_items = [x for x in all_items if x["used_for_missing_check"]]
    info_items = [x for x in all_items if not x["used_for_missing_check"]]

    return {
        "all": all_items,
        "used_for_missing_check": used_items,
        "informational_only": info_items,
        "informational_not_used_for_missing_check_count": len(info_items),
    }
