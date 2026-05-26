"""Сводный анализ нетарифных требований по позиции товара."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Union

from .ntm_enricher import enrich_measures_by_description
from .ntm_triggers import find_measures_by_description
from .non_tariff_rules import (
    _measure_to_permit_type,
    find_measures_for_code,
    find_rules_for_code,
    get_default_cert_form,
    get_sensitive_override,
)
from .normative_store import extract_tr_ts_act_codes, find_normative_notes_for_hs, lookup_tr_ts_acts_by_codes
from .ntm_effective_requirements import build_effective_requirements
from .normative_requirements_block import build_normative_requirements_block
from .sanctions_risk_block import build_sanctions_risk_block
from .permits_service import check_permits
from .regulatory_layer import get_regulatory_documents_for_hs
from .tr_ts_catalog import TR_TS_FULL_NAMES, get_full_ntm_requirements


def _build_broker_required_permits(
    hs_code: str,
    catalog_and_layer_rows: List[Dict[str, Any]],
    trigger_measures: List[Dict[str, Any]],
    sensitive_permit: str | None,
) -> List[Dict[str, Any]]:
    """Каталог ТР ТС + нерегламентные слои + триггеры + чувствительные группы; дедуп по (permit_type, tr_ts)."""
    rows: List[Dict[str, Any]] = [dict(r) for r in catalog_and_layer_rows]
    hc = (hs_code or "").strip().replace(" ", "")
    for m in trigger_measures:
        pt = (m.get("permit_type") or "").strip()
        if not pt:
            continue
        ref = f"{m.get('regulatory_act', '')} {m.get('legal_ref', '')} {m.get('description', '')}"
        tr_ts = (m.get("tr_ts_code") or "").strip()
        if not tr_ts:
            mch = re.search(r"(?:ТР\s*(?:ТС|ЕАЭС)?\s*)?(\d{3}/\d{4})", ref, flags=re.IGNORECASE)
            tr_ts = mch.group(1) if mch else ""
        tr_norm: str | None = tr_ts if tr_ts else None
        fname = TR_TS_FULL_NAMES.get(tr_norm, "") if tr_norm else ""
        rows.append(
            {
                "permit_type": pt,
                "tr_ts": tr_norm,
                "tr_ts_full_name": fname,
                "description": (m.get("description") or "").strip(),
                "legal_ref": (m.get("regulatory_act") or m.get("legal_ref") or "").strip(),
                "matched_prefix": hc[:4] if hc else "",
                "priority": 2,
                "trigger": m.get("trigger"),
            }
        )
    if sensitive_permit:
        rows.append(
            {
                "permit_type": sensitive_permit,
                "tr_ts": None,
                "tr_ts_full_name": "",
                "description": "Чувствительная группа товара (override)",
                "legal_ref": "SENSITIVE_OVERRIDES",
                "matched_prefix": hc[:4] if hc else "",
                "priority": 1,
                "trigger": None,
            }
        )
    seen: set[tuple[str, str | None]] = set()
    deduped: List[Dict[str, Any]] = []
    for r in rows:
        key = (str(r["permit_type"]), r.get("tr_ts"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    return deduped


def _sanitize_ntm_rules_for_position(
    hs_code: str,
    description: str,
    rules: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Подчищает устаревшие комбинации в seed non_tariff_rules (СГР на игрушках/взрослой косметике, СС на 8517/8528)."""
    code = (hs_code or "").strip().replace(" ", "")
    if not code or not rules:
        return rules
    desc_l = (description or "").lower()
    child_cosmetic = any(x in desc_l for x in ("дет", "детск", "младен", "baby"))
    out: List[Dict[str, Any]] = []
    for r in rules:
        rp = [p for p in (r.get("required_permits") or []) if p]
        if code.startswith("9503"):
            rp = [p for p in rp if p != "СГР"]
        if code.startswith("33") and not child_cosmetic:
            rp = [p for p in rp if p != "СГР"]
        if code.startswith("8517") or code.startswith("8528"):
            rp = [p for p in rp if p != "СС"]
        r2 = dict(r)
        r2["required_permits"] = rp
        out.append(r2)
    return out


def _drop_spurious_ai_measures(
    hs_code: str,
    description: str,
    measures: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """LLM иногда добавляет СГР/«сертификат» там, где домен и БД уже задают ДС/СС."""
    code = (hs_code or "").strip()
    desc_l = (description or "").lower()
    out: List[Dict[str, Any]] = []
    for m in measures:
        if m.get("source_level") != "ai_enriched":
            out.append(m)
            continue
        mt = (str(m.get("measure_type") or "")).lower()
        if code.startswith("9503") and mt == "sgr":
            continue
        if len(code) >= 2 and code[:2] == "33" and mt == "sgr":
            if "дет" not in desc_l and "детск" not in desc_l and "младен" not in desc_l:
                continue
        if code.startswith("8517") and mt in ("certificate", "sgr"):
            continue
        if code.startswith("8528") and mt in ("certificate", "sgr"):
            continue
        out.append(m)
    return out


def _data_freshness() -> Dict[str, Any]:
    """Возвращает сведения об актуальности нетарифных правил."""
    try:
        from .normative_store import list_source_status
        sources = list_source_status()
        eec = next((s for s in sources if s["source_code"] == "EEC_ETT"), None)
        if eec:
            return {
                "source_name": eec["source_name"],
                "source_code": eec["source_code"],
                "synced_at": eec["synced_at"],
                "is_stale": eec["is_stale"],
                "revision": eec["revision"],
            }
    except Exception:
        pass
    return {
        "source_name": "Локальная база правил",
        "source_code": "LOCAL",
        "synced_at": None,
        "is_stale": False,
        "revision": "seed",
    }


async def check_position_non_tariff(
    hs_code: str,
    description: str,
    country: str | None,
    permits: List[Dict[str, str]],
    *,
    skip_registry_verify: bool = False,
    include_effective_requirements_debug: bool = False,
    rules_enforcement_enabled: bool | None = None,
    measures_enforcement_enabled: bool | None = None,
    official_sgr_advisory_enabled: bool | None = None,
) -> Dict[str, Any]:
    """Проверка нетарифных требований по одной позиции товара."""
    catalog_and_layers = get_full_ntm_requirements(hs_code, description or "")
    rules = _sanitize_ntm_rules_for_position(hs_code, description, find_rules_for_code(hs_code))
    db_measures = find_measures_for_code(hs_code, direction="import")
    measures: List[Dict[str, Any]] = list(db_measures)
    trigger_measures = find_measures_by_description(description, hs_code)
    if trigger_measures:
        measures.extend(trigger_measures)
    # Если есть описание товара — обогащаем через AI.
    if description and len(description) > 10:
        enriched = await enrich_measures_by_description(
            hs_code=hs_code,
            description=description,
            base_measures=measures,
        )
        if enriched:
            measures.extend(_drop_spurious_ai_measures(hs_code, description, enriched))
    if skip_registry_verify:
        permits_result = [
            {
                "type": (p.get("type") or "").strip(),
                "number": (p.get("number") or "").strip(),
                "status": "SKIPPED",
                "holder": None,
                "registry_link": None,
                "note": "Проверка ФСА/СГР отключена в запросе",
            }
            for p in permits
            if (p.get("number") or "").strip()
        ]
    else:
        permits_result = await check_permits(permits, hs_code)

    notes: list[str] = []
    required_types: set[str] = set()
    tr_ts_list: set[str] = set()
    rule_sources: list[Dict[str, Union[str, int, bool, list]]] = []

    seen_rules: set[str] = set()
    for r in rules:
        required_types.update(r.get("required_permits", []))
        tr_ts_list.update(r.get("tr_ts", []))
        # Уникальность: имя + префикс (одно имя может быть на разных hs_prefix)
        key = f"{r.get('name', '')}|{r.get('hs_prefix', '')}"
        if key in seen_rules:
            continue
        seen_rules.add(key)
        tr_ts = r.get("tr_ts", [])
        req_perm = r.get("required_permits", [])
        edition = (r.get("tr_ts_edition") or "").strip()
        exc = (r.get("exception_note") or "").strip()
        data_info = f"ТР ТС {', '.join(tr_ts)}" if tr_ts else "Правило в приложении"
        if edition:
            data_info = f"{data_info}; редакция: {edition[:120]}{'…' if len(edition) > 120 else ''}"
        rs: Dict[str, Union[str, int, bool, list]] = {
            "name": r["name"],
            "integrated": True,
            "data_info": data_info,
            "required_permits": req_perm,
            "revision": r.get("source_revision", "seed"),
            "hs_prefix": r.get("hs_prefix", ""),
            "priority": int(r.get("priority") or 0),
        }
        if edition:
            rs["tr_ts_edition"] = edition
        if exc:
            rs["exception_note"] = exc
            line = f"Исключение / оговорка ({r.get('name', 'правило')}): {exc}"
            if line not in notes:
                notes.append(line)
        rule_sources.append(rs)

    seen_measure_notes: set[str] = set()
    seen_measure_sources: set[str] = set()
    for m in measures:
        mtype = str(m.get("measure_type") or "").strip().lower()
        permit = (m.get("permit_type") or "").strip()
        tr_ts_code = (m.get("tr_ts_code") or "").strip()
        desc = (m.get("description") or "").strip()
        legal_ref = (m.get("legal_ref") or "").strip()
        code = (m.get("commodity_code") or "").strip()
        source_level = m.get("source_level") or ""

        # Для trigger/ai_enriched permit_type должен задаваться источником.
        # Для БД-мер дополнительно пытаемся вычислить, если не пришел.
        if not permit and source_level not in ("trigger", "ai_enriched"):
            permit = _measure_to_permit_type(mtype, f"{desc} {legal_ref}", hs_code=hs_code) or ""

        if permit:
            required_types.add(permit)
        if tr_ts_code:
            tr_ts_list.add(tr_ts_code)
        if "prohibit" in mtype or "запрет" in f"{desc} {legal_ref}".lower():
            line = f"Запретительная мера: {desc or legal_ref or mtype}".strip()
            if line not in seen_measure_notes:
                seen_measure_notes.add(line)
                notes.append(line)
        elif desc:
            line = f"Мера ({mtype or 'ntm'}): {desc}"
            if line not in seen_measure_notes:
                seen_measure_notes.add(line)
                notes.append(line)

        source_key = f"{mtype}|{legal_ref}|{code}|{m.get('source_level', '')}|{m.get('trigger', '')}"
        if source_key in seen_measure_sources:
            continue
        seen_measure_sources.add(source_key)
        rule_sources.append(
            {
                "name": f"NTM/{mtype or 'measure'}",
                "integrated": True,
                "data_info": (legal_ref or "non_tariff_measures"),
                "required_permits": ([permit] if permit else []),
                "revision": "non_tariff_measures",
                "hs_prefix": code[:10],
                "priority": 0,
                "legal_ref": legal_ref,
                "source_level": m.get("source_level"),
                "trigger": m.get("trigger"),
            }
        )

    domain_pt = get_default_cert_form(hs_code)
    if domain_pt:
        required_types.add(domain_pt)
        rule_sources.append(
            {
                "name": "Доменная форма подтверждения (ЕЭК №620)",
                "integrated": True,
                "data_info": "get_default_cert_form()",
                "required_permits": [domain_pt],
                "revision": "domain-default",
                "hs_prefix": (hs_code or "")[:10],
                "priority": -1,
            }
        )

    sensitive_permit = get_sensitive_override(hs_code)
    if sensitive_permit:
        required_types.add(sensitive_permit)

    broker_required_permits = _build_broker_required_permits(
        hs_code,
        catalog_and_layers,
        trigger_measures,
        sensitive_permit,
    )
    from .ntm_v2_legacy_rules_import import (
        get_advisory_legacy_rule_requirements_v2,
        get_legacy_rule_requirements_for_enforcement,
        get_legacy_rule_requirements_v2_legacy_shape,
        merge_v2_legacy_rules_into_broker,
        should_apply_v2_rules_enforcement,
    )

    from .ntm_v2_official_sgr_import import (
        get_advisory_official_sgr_requirements_v2,
        merge_advisory_legacy_and_official,
        should_apply_official_sgr_advisory,
    )

    legacy_advisory = get_advisory_legacy_rule_requirements_v2(
        hs_code,
        description or "",
    )
    official_advisory: list[dict[str, Any]] = []
    if should_apply_official_sgr_advisory(official_sgr_advisory_enabled):
        official_advisory = get_advisory_official_sgr_requirements_v2(
            hs_code,
            description or "",
        )
    advisory_requirements = merge_advisory_legacy_and_official(
        legacy_advisory,
        official_advisory,
    )

    legacy_v2_rules_informational: list[dict[str, Any]] = []
    if should_apply_v2_rules_enforcement(rules_enforcement_enabled):
        v2_rule_rows = get_legacy_rule_requirements_for_enforcement(
            hs_code,
            description or "",
        )
        broker_required_permits = merge_v2_legacy_rules_into_broker(
            broker_required_permits,
            v2_rule_rows,
        )
    elif include_effective_requirements_debug:
        legacy_v2_rules_informational = get_legacy_rule_requirements_v2_legacy_shape(
            hs_code,
            description or "",
        )

    measures_enforcement_audit: Dict[str, Any] | None = None
    from .ntm_v2_legacy_measures_enforcement import (
        apply_v2_measures_enforcement_to_broker,
        should_apply_v2_measures_enforcement,
    )

    if should_apply_v2_measures_enforcement(measures_enforcement_enabled):
        broker_required_permits, measures_enforcement_audit = apply_v2_measures_enforcement_to_broker(
            broker_required_permits,
            hs_code,
            description or "",
        )

    for br in broker_required_permits:
        ts = br.get("tr_ts")
        if ts:
            tr_ts_list.add(str(ts))

    broker_keys = {(str(r.get("permit_type") or ""), r.get("tr_ts")) for r in broker_required_permits}
    advisory_requirements = [
        a
        for a in advisory_requirements
        if (a.get("permit_type"), a.get("tr_ts")) not in broker_keys
    ]

    got_types = {p["type"] for p in permits_result if p.get("type")}
    required_permit_types = sorted({r["permit_type"] for r in broker_required_permits})
    missing_types = set(required_permit_types) - got_types

    if missing_types:
        status = "ERROR"
    elif not broker_required_permits and not rules and not measures:
        status = "WARNING"
    else:
        status = "OK"

    if not rules and not measures and not broker_required_permits:
        notes.append("Для данного кода ТН ВЭД нет настроенных правил нетарифных мер (нетарифные требования могут применяться — уточните вручную).")

    for n in find_normative_notes_for_hs(hs_code):
        if n.get("category") == "non_tariff" and (n.get("body") or n.get("title")):
            line = f"{n.get('title', '')}: {n.get('body', '')}".strip(": ").strip()
            if line and line not in notes:
                notes.append(line)

    tr_ts_codes = extract_tr_ts_act_codes(sorted(tr_ts_list))
    tr_ts_registry = lookup_tr_ts_acts_by_codes(tr_ts_codes)
    regulatory_docs = get_regulatory_documents_for_hs(hs_code, max_results=10)

    result: Dict[str, Any] = {
        "status": status,
        "hs_code": hs_code,
        "description": description,
        "country": country,
        "tr_ts": sorted(tr_ts_list),
        "tr_ts_act_codes": tr_ts_codes,
        "tr_ts_registry": tr_ts_registry,
        "required_permits": broker_required_permits,
        "regulatory_documents": regulatory_docs,
        "required_permit_types": required_permit_types,
        "permits": permits_result,
        "missing_permit_types": sorted(missing_types),
        "advisory_requirements": advisory_requirements,
        "notes": notes,
        "rule_sources": rule_sources,
        "data_freshness": _data_freshness(),
    }
    if measures_enforcement_audit is not None:
        result["measures_enforcement_audit"] = measures_enforcement_audit
    if include_effective_requirements_debug:
        if not legacy_v2_rules_informational and should_apply_v2_rules_enforcement(
            rules_enforcement_enabled
        ):
            legacy_v2_rules_informational = get_legacy_rule_requirements_v2_legacy_shape(
                hs_code,
                description or "",
            )
        result["effective_requirements_debug"] = build_effective_requirements(
            broker_required_permits=broker_required_permits,
            rules=rules,
            measures=db_measures,
            trigger_measures=trigger_measures,
            legacy_v2_rules=legacy_v2_rules_informational,
        )
    result["normative_block"] = build_normative_requirements_block(result)
    result["risk_block"] = build_sanctions_risk_block(
        hs_code=hs_code,
        description=description or "",
        country=country,
    ).model_dump()
    return result
