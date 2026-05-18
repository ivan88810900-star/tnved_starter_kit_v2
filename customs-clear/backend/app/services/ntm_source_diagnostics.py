"""
Диагностика пересечений источников нетарифных требований для `/api/non_tariff/check`.

Не используется в production-пайплайне; только сравнение наборов ключей
``(permit_type, tr_ts_or_empty)`` между правилами БД, каталогом ТР ТС, слоями ntm_layers,
мерой БД и брокерским dedupe (как в ``_build_broker_required_permits``).
"""
from __future__ import annotations

from typing import Any, Iterable

from .non_tariff_rules import (
    find_measures_for_code,
    find_rules_for_code,
    get_sensitive_override,
)
from .ntm_layers import get_all_layer_requirements
from .ntm_triggers import find_measures_by_description
from .tr_ts_catalog import get_full_ntm_requirements, get_tr_ts_requirements


ReqKey = tuple[str, str]


def _norm_key(permit: str | None, tr_ts: str | None) -> ReqKey:
    p = (permit or "").strip()
    t = (tr_ts or "").strip() if tr_ts is not None else ""
    return (p, t)


def _key_to_str(k: ReqKey) -> str:
    return f"{k[0]}|{k[1]}"


def _rows_to_keys(rows: Iterable[dict[str, Any]]) -> set[ReqKey]:
    out: set[ReqKey] = set()
    for r in rows:
        pt = r.get("permit_type")
        ts = r.get("tr_ts")
        if ts is not None:
            ts = str(ts).strip()
        else:
            ts = ""
        out.add(_norm_key(str(pt or ""), ts))
    return out


def _rules_to_keys(rules: Iterable[dict[str, Any]]) -> set[ReqKey]:
    """
    Разворачивает ``non_tariff_rules``: декартово произведение required_permits × tr_ts;
    если ``tr_ts`` пуст, используется один пустой код регламента.
    """
    out: set[ReqKey] = set()
    for r in rules:
        permits = [x for x in (r.get("required_permits") or []) if x]
        trs = [x for x in (r.get("tr_ts") or []) if x]
        if not permits:
            continue
        if not trs:
            trs = [""]
        for p in permits:
            for t in trs:
                out.add(_norm_key(p, t))
    return out


def _measures_to_keys(measures: Iterable[dict[str, Any]]) -> tuple[set[ReqKey], int]:
    """Ключи (permit_type, tr_ts_code); счётчик строк без permit_type."""
    keys: set[ReqKey] = set()
    no_permit = 0
    for m in measures:
        pt = (m.get("permit_type") or "").strip()
        ts = (m.get("tr_ts_code") or "").strip()
        if not pt:
            no_permit += 1
            continue
        keys.add(_norm_key(pt, ts or ""))
    return keys, no_permit


def _broker_rows_to_keys(rows: Iterable[dict[str, Any]]) -> set[ReqKey]:
    return _rows_to_keys(rows)


def _sorted_key_strings(keys: set[ReqKey]) -> list[str]:
    return sorted(_key_to_str(k) for k in keys if k[0])


def _suspected_duplicate_keys(r: set[ReqKey], c: set[ReqKey], l: set[ReqKey]) -> list[str]:
    dup: set[ReqKey] = set()
    for k in r & c:
        dup.add(k)
    for k in r & l:
        dup.add(k)
    for k in c & l:
        dup.add(k)
    return sorted(_key_to_str(k) for k in dup)


def compare_ntm_requirement_sources(
    hs_code: str,
    description: str = "",
    *,
    include_triggers: bool = True,
) -> dict[str, Any]:
    """
    Сравнивает наборы ``(permit_type, tr_ts)`` между источниками.

    * **rules** — ``find_rules_for_code`` + ``_sanitize_ntm_rules_for_position`` (как в check).
    * **catalog** — только ``get_tr_ts_requirements``.
    * **layers** — только ``get_all_layer_requirements`` (без каталога ТР ТС).
    * **measures** — ``find_measures_for_code`` (import), только строки с непустым ``permit_type``.
    * **broker_static** — ``_build_broker_required_permits`` без триггеров по описанию.
    * **broker_full** — с триггерами (если ``include_triggers``), плюс ``get_sensitive_override``.

    Возвращает множества в виде отсортированных строк ``perm|tr_ts`` для стабильных тестов/логов.
    """
    from .non_tariff_service import (
        _build_broker_required_permits,
        _sanitize_ntm_rules_for_position,
    )

    rules = _sanitize_ntm_rules_for_position(hs_code, description, find_rules_for_code(hs_code))
    catalog_rows = get_tr_ts_requirements(hs_code)
    layer_rows = get_all_layer_requirements(hs_code, description)
    measures = find_measures_for_code(hs_code, direction="import")

    r_keys = _rules_to_keys(rules)
    c_keys = _rows_to_keys(catalog_rows)
    l_keys = _rows_to_keys(layer_rows)
    m_keys, measures_no_permit_count = _measures_to_keys(measures)

    sensitive = get_sensitive_override(hs_code)
    triggers: list[dict[str, Any]] = []
    if include_triggers:
        triggers = find_measures_by_description(description, hs_code)

    catalog_and_layers_rows = [*catalog_rows, *layer_rows]
    broker_static = _build_broker_required_permits(
        hs_code, catalog_and_layers_rows, [], sensitive
    )
    broker_full = _build_broker_required_permits(
        hs_code, get_full_ntm_requirements(hs_code, description), triggers, sensitive
    )

    b_static_keys = _broker_rows_to_keys(broker_static)
    b_full_keys = _broker_rows_to_keys(broker_full)

    union_rcl = r_keys | c_keys | l_keys

    only_in_rules = r_keys - c_keys - l_keys
    only_in_catalog = c_keys - r_keys - l_keys
    only_in_layers = l_keys - r_keys - c_keys
    rules_and_catalog_overlap = r_keys & c_keys
    catalog_and_layers_overlap = c_keys & l_keys
    all_sources_overlap = r_keys & c_keys & l_keys

    measures_only = m_keys - union_rcl

    suspected_duplicates = _suspected_duplicate_keys(r_keys, c_keys, l_keys)

    broker_only_not_in_union_static = b_static_keys - union_rcl
    broker_full_not_in_union = b_full_keys - union_rcl

    return {
        "hs_code": hs_code,
        "description": description,
        "include_triggers": include_triggers,
        "counts": {
            "rules": len(rules),
            "catalog_rows": len(catalog_rows),
            "layer_rows": len(layer_rows),
            "measure_rows": len(measures),
            "measure_rows_without_permit_type": measures_no_permit_count,
            "keys_rules": len(r_keys),
            "keys_catalog": len(c_keys),
            "keys_layers": len(l_keys),
            "keys_measures_permit_like": len(m_keys),
            "keys_broker_static": len(b_static_keys),
            "keys_broker_full": len(b_full_keys),
        },
        "only_in_rules": _sorted_key_strings(only_in_rules),
        "only_in_catalog": _sorted_key_strings(only_in_catalog),
        "only_in_layers": _sorted_key_strings(only_in_layers),
        "rules_and_catalog_overlap": _sorted_key_strings(rules_and_catalog_overlap),
        "catalog_and_layers_overlap": _sorted_key_strings(catalog_and_layers_overlap),
        "all_sources_overlap": _sorted_key_strings(all_sources_overlap),
        "measures_only": _sorted_key_strings(measures_only),
        "suspected_duplicates": suspected_duplicates,
        "broker_static_keys": _sorted_key_strings(b_static_keys),
        "broker_full_keys": _sorted_key_strings(b_full_keys),
        "broker_static_not_in_rules_catalog_layers": _sorted_key_strings(
            broker_only_not_in_union_static
        ),
        "broker_full_not_in_rules_catalog_layers": _sorted_key_strings(broker_full_not_in_union),
        "notes": {
            "rules_encoding": "Пары (permit, tr_ts) из декартова произведения списков правила; пустой tr_ts — ключ с пустой второй частью.",
            "broker_vs_check": (
                "В ``check_position_non_tariff`` список ``required_permit_types`` / ``missing_types`` "
                "строится только из ``broker_required_permits`` (каталог+слои+триггеры+sensitive), "
                "а не из полного объединения с ``non_tariff_rules`` — см. non_tariff_service.py."
            ),
        },
    }


def run_ntm_source_matrix(
    cases: list[tuple[str, str]],
    *,
    include_triggers: bool = False,
) -> list[dict[str, Any]]:
    """Пакетный прогон диагностики по списку (hs_code, description)."""
    out: list[dict[str, Any]] = []
    for hs, desc in cases:
        row = compare_ntm_requirement_sources(hs, desc, include_triggers=include_triggers)
        out.append(
            {
                "hs_code": hs,
                "description": desc,
                "counts": row["counts"],
                "only_in_rules": row["only_in_rules"],
                "only_in_catalog": row["only_in_catalog"],
                "only_in_layers": row["only_in_layers"],
                "rules_and_catalog_overlap": row["rules_and_catalog_overlap"],
                "catalog_and_layers_overlap": row["catalog_and_layers_overlap"],
                "all_sources_overlap": row["all_sources_overlap"],
                "measures_only": row["measures_only"],
                "suspected_duplicates": row["suspected_duplicates"],
                "broker_static_not_in_union": row["broker_static_not_in_rules_catalog_layers"],
            }
        )
    return out
