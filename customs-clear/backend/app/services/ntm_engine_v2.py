"""Движок NTM v2: оценка по БД и опциональная подмена каталога ТР ТС / ntm_layers в пайплайне."""

from __future__ import annotations

import json
import logging
import os
from datetime import date
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import joinedload

from .. import db
from ..models.ntm_v2 import NtmApplicabilityRuleV2, NtmMeasureV2
from .hs_matching import match_hs_prefix, normalize_hs_code
from .tr_ts_catalog import TR_TS_FULL_NAMES, get_tr_ts_requirements

logger = logging.getLogger(__name__)

MEASURE_KIND_TR = "technical_regulation"
LAYER_KINDS = frozenset({"vet", "phyto", "sgr", "notification", "license"})
LAYER_LEGACY_ORDER = ("vet", "phyto", "notification", "license", "sgr")

TR_TS_SOURCE_KIND = "legacy_tr_ts_catalog"
LAYERS_SOURCE_KIND = "legacy_ntm_layers"

# Канонические меры v2: ntm_layers + каталог ТР ТС (+ official SGR contour).
# Исключает TKS-зеркала non_tariff_measures:* и legacy non_tariff_rules:*.
_CANONICAL_MEASURE_SOURCE_REF = or_(
    NtmMeasureV2.source_ref.like("ntm_layers.py:%"),
    NtmMeasureV2.source_ref.like("tr_ts_catalog.%"),
    NtmMeasureV2.source_kind == "official_sgr_registry",
)


def _env_truthy(name: str) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def is_ntm_v2_tr_ts_enabled() -> bool:
    """
    Feature flag ``NTM_V2_TR_TS_ENABLED``: подмена слоя ТР ТС в ``get_full_ntm_requirements``.

    По умолчанию — ``tr_ts_catalog.NTM_V2_TR_TS_ENABLED`` (True).
    Явное выключение: ``0``, ``false``, ``no``, ``off``.
    Явное включение: ``1``, ``true``, ``yes``, ``on``.
    """
    raw = os.environ.get("NTM_V2_TR_TS_ENABLED")
    if raw is None or not raw.strip():
        from .tr_ts_catalog import NTM_V2_TR_TS_ENABLED

        return bool(NTM_V2_TR_TS_ENABLED)
    if raw.strip().lower() in ("0", "false", "no", "off"):
        return False
    return _env_truthy("NTM_V2_TR_TS_ENABLED")


def is_ntm_v2_layers_enabled() -> bool:
    """``NTM_V2_LAYERS_ENABLED``: подмена ``ntm_layers`` в ``get_full_ntm_requirements``."""
    return _env_truthy("NTM_V2_LAYERS_ENABLED")


def _parse_layer_measure_meta(measure: NtmMeasureV2) -> dict[str, Any]:
    raw = measure.short_description or ""
    if raw.strip().startswith("{"):
        try:
            d = json.loads(raw)
            return {
                "legal_ref": str(d.get("legal_ref") or ""),
                "consumer": str(d.get("consumer") or ""),
                "label": str(d.get("label") or measure.title),
                "sgr_description_triggers": list(d.get("sgr_description_triggers") or []),
                "sgr_water_hints": list(d.get("sgr_water_hints") or []),
            }
        except json.JSONDecodeError:
            pass
    return {
        "legal_ref": "",
        "consumer": raw,
        "label": measure.title,
        "sgr_description_triggers": [],
        "sgr_water_hints": [],
    }


def _rule_description_matches(description_match_json: Any, description: str) -> bool:
    if not description_match_json:
        return True
    if not isinstance(description_match_json, dict):
        return True
    dm = description_match_json
    mode = dm.get("mode")
    contains = dm.get("description_contains_any") or dm.get("substrings")
    requires = dm.get("description_requires_any")
    excludes = dm.get("exclude_if_contains_any")
    if mode in ("official_sgr", "official_sgr_and") or requires or excludes:
        from .ntm_v2_official_sgr_import import official_sgr_description_matches

        return official_sgr_description_matches(
            description,
            description_contains_any=contains if isinstance(contains, list) else None,
            description_requires_any=requires if isinstance(requires, list) else None,
            exclude_if_contains_any=excludes if isinstance(excludes, list) else None,
        )
    if mode == "any_substring":
        subs = dm.get("substrings") or []
        dl = (description or "").lower()
        return any(str(s).lower() in dl for s in subs)
    return True


def _rule_hs_matches(norm_hs: str, rule: NtmApplicabilityRuleV2) -> bool:
    hp = normalize_hs_code(rule.hs_code)
    if not hp:
        return True
    return match_hs_prefix(norm_hs, hp)


def _rule_and_measure_active(rule: NtmApplicabilityRuleV2, as_of: date) -> bool:
    m = rule.measure
    if rule.valid_from is not None and as_of < rule.valid_from:
        return False
    if rule.valid_to is not None and as_of > rule.valid_to:
        return False
    if m.valid_from is not None and as_of < m.valid_from:
        return False
    if m.valid_to is not None and as_of > m.valid_to:
        return False
    return True


def _rule_matches_runtime(
    rule: NtmApplicabilityRuleV2,
    *,
    norm_hs: str,
    description: str,
    country: str | None,
    as_of: date,
) -> bool:
    m = rule.measure
    if not _rule_and_measure_active(rule, as_of):
        return False
    if country is not None and rule.country_iso is not None and rule.country_iso != country:
        return False
    if not _rule_hs_matches(norm_hs, rule):
        return False
    return _rule_description_matches(rule.description_match_json, description)


def _first_sgr_trigger(description: str, triggers: list[str]) -> str | None:
    desc_lower = (description or "").lower()
    for trigger in triggers:
        if trigger in desc_lower:
            return trigger
    return None


def _pick_sgr_rule_for_output(matched: list[NtmApplicabilityRuleV2], matched_prefix: str | None) -> NtmApplicabilityRuleV2:
    mp_norm = normalize_hs_code(matched_prefix or "")
    if mp_norm:
        for r in matched:
            if normalize_hs_code(r.hs_code) == mp_norm:
                return r
    hs_rules = [r for r in matched if normalize_hs_code(r.hs_code)]
    if hs_rules:
        return max(hs_rules, key=lambda x: len(normalize_hs_code(x.hs_code)))
    return matched[0]


def _compute_sgr_public_dict(
    hs_code: str,
    description: str,
    matched_sgr_rules: list[NtmApplicabilityRuleV2],
) -> dict[str, Any] | None:
    """
    Публичные поля СГР только из v2 (логика как ``get_sgr_requirement``, без вызова legacy).
    """
    if not matched_sgr_rules:
        return None

    code = normalize_hs_code(hs_code)
    desc_lower = (description or "").lower()
    meta = _parse_layer_measure_meta(matched_sgr_rules[0].measure)
    triggers: list[str] = meta.get("sgr_description_triggers") or []
    water_hints: list[str] = meta.get("sgr_water_hints") or []

    hs_prefixes = sorted(
        {normalize_hs_code(r.hs_code) for r in matched_sgr_rules if normalize_hs_code(r.hs_code)},
        key=len,
        reverse=True,
    )
    matched_prefix = hs_prefixes[0] if hs_prefixes else None
    matched_trigger = _first_sgr_trigger(description, triggers)

    if matched_prefix == "2201" and not matched_trigger:
        if not any(h in desc_lower for h in water_hints):
            matched_prefix = None

    if not matched_prefix and not matched_trigger:
        return None

    fallback_prefix = code[:4] if len(code) >= 4 else code
    public = {
        "permit_type": "СГР",
        "tr_ts": None,
        "tr_ts_full_name": meta["label"],
        "description": meta["consumer"],
        "legal_ref": meta["legal_ref"],
        "matched_prefix": matched_prefix or fallback_prefix,
        "priority": 1,
        "trigger": matched_trigger,
    }
    pick = _pick_sgr_rule_for_output(matched_sgr_rules, matched_prefix)
    return {**public, "_rule_pick": pick}


def evaluate_ntm_v2(
    *,
    hs_code: str,
    description: str = "",
    country: str | None = None,
    as_of: date | None = None,
    source_kinds: frozenset[str] | set[str] | None = None,
) -> dict[str, Any]:
    """
    Активные правила v2: ТР ТС (``technical_regulation``) + слои (vet/phyto/…).

    ``source_kinds`` ограничивает ``NtmMeasureV2.source_kind`` (иначе все источники в БД).
    Адаптеры пайплайна передают только свой ``source_kind``.
    """
    norm = normalize_hs_code(hs_code)
    if not norm:
        return {"requirements": []}
    ref = as_of or date.today()

    with db.SessionLocal() as session:
        stmt = (
            select(NtmApplicabilityRuleV2)
            .join(NtmMeasureV2, NtmApplicabilityRuleV2.measure_id == NtmMeasureV2.id)
            .options(joinedload(NtmApplicabilityRuleV2.measure))
            .where(
                NtmMeasureV2.status == "active",
                NtmApplicabilityRuleV2.direction.in_(("import", "both")),
                _CANONICAL_MEASURE_SOURCE_REF,
            )
        )
        if source_kinds is not None:
            kinds = frozenset(source_kinds)
            stmt = stmt.where(
                NtmMeasureV2.source_kind.in_(kinds),
                NtmApplicabilityRuleV2.source_kind.in_(kinds),
            )
        all_rules = session.scalars(stmt).unique().all()

        matched: list[NtmApplicabilityRuleV2] = []
        for rule in all_rules:
            if _rule_matches_runtime(rule, norm_hs=norm, description=description, country=country, as_of=ref):
                matched.append(rule)

        tr_rules = [r for r in matched if r.measure.measure_kind == MEASURE_KIND_TR]
        tr_rules.sort(key=lambda r: r.priority)
        seen_tr: set[tuple[str, str]] = set()
        tr_out: list[dict[str, Any]] = []
        for rule in tr_rules:
            m = rule.measure
            key = (m.permit_type, m.tr_ts_act_code)
            if key in seen_tr:
                continue
            seen_tr.add(key)
            tr_out.append(
                {
                    "measure_kind": m.measure_kind,
                    "permit_type": m.permit_type,
                    "tr_ts": m.tr_ts_act_code,
                    "measure_id": m.id,
                    "rule_id": rule.id,
                    "matched_hs_scope": rule.hs_code,
                    "applicability": rule.applicability,
                    "used_for_document_check": True,
                }
            )

        layer_out: list[dict[str, Any]] = []
        for kind in LAYER_LEGACY_ORDER:
            sub = [r for r in matched if r.measure.measure_kind == kind]
            if not sub:
                continue
            if kind == "sgr":
                pub = _compute_sgr_public_dict(hs_code, description, sub)
                if not pub:
                    continue
                pick = pub.pop("_rule_pick")
                m = pick.measure
                layer_out.append(
                    {
                        "measure_kind": kind,
                        "permit_type": m.permit_type,
                        "tr_ts": None,
                        "measure_id": m.id,
                        "rule_id": pick.id,
                        "matched_hs_scope": str(pub["matched_prefix"]),
                        "applicability": pick.applicability,
                        "used_for_document_check": True,
                        "layer_trigger": pub.get("trigger"),
                        "layer_public": pub,
                    }
                )
                continue
            best = max(sub, key=lambda r: (len(normalize_hs_code(r.hs_code)), -r.priority))
            m = best.measure
            layer_out.append(
                {
                    "measure_kind": kind,
                    "permit_type": m.permit_type,
                    "tr_ts": None,
                    "measure_id": m.id,
                    "rule_id": best.id,
                    "matched_hs_scope": best.hs_code,
                    "applicability": best.applicability,
                    "used_for_document_check": True,
                    "layer_trigger": None,
                    "layer_public": None,
                }
            )

    return {"requirements": [*tr_out, *layer_out]}


def get_tr_ts_requirements_v2_legacy_shape(hs_code: str, description: str = "") -> list[dict[str, Any]]:
    """
    Адаптер v2 → формат ``get_tr_ts_requirements`` (только ``measure_kind=technical_regulation``).
    """
    evaluated = evaluate_ntm_v2(
        hs_code=hs_code,
        description=description,
        source_kinds=frozenset({TR_TS_SOURCE_KIND}),
    )
    legacy = get_tr_ts_requirements(hs_code)
    legacy_keys = {(str(x.get("permit_type") or ""), str(x.get("tr_ts") or "")) for x in legacy}

    raw_reqs = [r for r in evaluated.get("requirements") or [] if r.get("measure_kind") == MEASURE_KIND_TR]
    if not raw_reqs:
        if legacy:
            logger.warning(
                "NTM_V2_TR_TS: v2 вернул пустой список ТР ТС, fallback на legacy-каталог "
                "(%s строк(и)) для hs_code=%r — проверьте импорт в ntm_*_v2.",
                len(legacy),
                hs_code,
            )
            return legacy
        return []

    out: list[dict[str, Any]] = []
    for r in raw_reqs:
        form = str(r.get("permit_type") or "")
        tr_ts = str(r.get("tr_ts") or "")
        if (form, tr_ts) not in legacy_keys:
            continue
        matched = str(r.get("matched_hs_scope") or "")
        out.append(
            {
                "permit_type": form,
                "tr_ts": tr_ts,
                "tr_ts_full_name": TR_TS_FULL_NAMES.get(tr_ts, ""),
                "description": (
                    f"{'Декларация о соответствии' if form == 'ДС' else 'Сертификат соответствия'} "
                    f"по ТР ТС {tr_ts}"
                ),
                "legal_ref": f"ТР ТС {tr_ts}",
                "matched_prefix": matched,
                "priority": 1,
                "trigger": None,
            }
        )
    if not out and legacy:
        logger.warning(
            "NTM_V2_TR_TS: v2 не дал совпадений с legacy-каталогом, fallback "
            "(%s строк(и)) для hs_code=%r.",
            len(legacy),
            hs_code,
        )
        return legacy
    return out


def get_layer_requirements_v2_legacy_shape(hs_code: str, description: str = "") -> list[dict[str, Any]]:
    """Адаптер v2 → формат ``ntm_layers.get_all_layer_requirements``."""
    evaluated = evaluate_ntm_v2(
        hs_code=hs_code,
        description=description,
        source_kinds=frozenset({LAYERS_SOURCE_KIND}),
    )
    rows = [r for r in evaluated.get("requirements") or [] if r.get("measure_kind") in LAYER_KINDS]
    if not rows:
        logger.warning(
            "NTM_V2_LAYERS: v2 не вернул слоёв для hs_code=%r — проверьте импорт ``import_ntm_layers_to_ntm_v2``.",
            hs_code,
        )
        return []

    out: list[dict[str, Any]] = []
    with db.SessionLocal() as session:
        for r in rows:
            mid = int(r["measure_id"])
            m = session.get(NtmMeasureV2, mid)
            if m is None:
                continue
            meta = _parse_layer_measure_meta(m)
            pub = r.get("layer_public")
            if isinstance(pub, dict):
                out.append(
                    {
                        "permit_type": pub["permit_type"],
                        "tr_ts": pub.get("tr_ts"),
                        "tr_ts_full_name": pub["tr_ts_full_name"],
                        "description": pub["description"],
                        "legal_ref": pub["legal_ref"],
                        "matched_prefix": pub["matched_prefix"],
                        "priority": pub.get("priority", 1),
                        "trigger": pub.get("trigger"),
                        "measure_kind": str(r.get("measure_kind") or "sgr"),
                        "short_description": m.short_description,
                    }
                )
            else:
                out.append(
                    {
                        "permit_type": m.permit_type,
                        "tr_ts": None,
                        "tr_ts_full_name": meta["label"],
                        "description": meta["consumer"],
                        "legal_ref": meta["legal_ref"],
                        "matched_prefix": str(r.get("matched_hs_scope") or ""),
                        "priority": 1,
                        "trigger": r.get("layer_trigger"),
                        "measure_kind": str(r.get("measure_kind") or ""),
                        "short_description": m.short_description,
                    }
                )
    return out


def get_tr_ts_requirements_for_pipeline(hs_code: str, description: str = "") -> list[dict[str, Any]]:
    """Источник строк ТР ТС для ``get_full_ntm_requirements``: legacy или v2 по флагу."""
    if not is_ntm_v2_tr_ts_enabled():
        return get_tr_ts_requirements(hs_code)
    return get_tr_ts_requirements_v2_legacy_shape(hs_code, description)


def get_layer_requirements_for_pipeline(hs_code: str, description: str = "") -> list[dict[str, Any]]:
    """Источник нерегламентных слоёв для ``get_full_ntm_requirements``."""
    if not is_ntm_v2_layers_enabled():
        from . import ntm_layers as ntm_layers_mod

        return ntm_layers_mod.get_all_layer_requirements(hs_code, description)
    return get_layer_requirements_v2_legacy_shape(hs_code, description)


def _norm_key(permit_type: str, tr_ts: str | None) -> str:
    return f"{permit_type}|{tr_ts or ''}"


def _layer_cmp_key(permit_type: str, tr_ts: str | None, measure_kind: str) -> str:
    return f"{permit_type}|{tr_ts or ''}|{measure_kind}"


def compare_legacy_tr_ts_catalog_vs_ntm_v2(hs_code: str, description: str = "") -> dict[str, Any]:
    """Shadow: legacy ``get_tr_ts_requirements`` vs v2 (только ТР ТС)."""
    _ = description
    legacy = get_tr_ts_requirements(hs_code)
    v2 = evaluate_ntm_v2(
        hs_code=hs_code,
        description=description,
        source_kinds=frozenset({TR_TS_SOURCE_KIND}),
    )
    v2_tr = [r for r in v2["requirements"] if r.get("measure_kind") == MEASURE_KIND_TR]

    legacy_keys = {_norm_key(x.get("permit_type", ""), x.get("tr_ts")) for x in legacy}
    v2_keys = {_norm_key(r["permit_type"], r.get("tr_ts")) for r in v2_tr}

    return {
        "legacy_only": sorted(legacy_keys - v2_keys),
        "v2_only": sorted(v2_keys - legacy_keys),
        "overlap": sorted(legacy_keys & v2_keys),
        "is_full_match": legacy_keys == v2_keys,
    }


def compare_pipeline_tr_ts_vs_legacy_catalog(hs_code: str, description: str = "") -> dict[str, Any]:
    """Диагностика runtime ТР ТС vs legacy-каталог."""
    legacy = get_tr_ts_requirements(hs_code)
    runtime = get_tr_ts_requirements_for_pipeline(hs_code, description)
    legacy_keys = {_norm_key(x.get("permit_type", ""), x.get("tr_ts")) for x in legacy}
    runtime_keys = {_norm_key(x.get("permit_type", ""), x.get("tr_ts")) for x in runtime}
    return {
        "ntm_v2_tr_ts_enabled": is_ntm_v2_tr_ts_enabled(),
        "legacy_only": sorted(legacy_keys - runtime_keys),
        "runtime_only": sorted(runtime_keys - legacy_keys),
        "overlap": sorted(legacy_keys & runtime_keys),
        "is_full_match": legacy_keys == runtime_keys,
    }


def compare_pipeline_layers_vs_legacy(hs_code: str, description: str = "") -> dict[str, Any]:
    """Диагностика runtime слоёв vs ``get_all_layer_requirements``."""
    from . import ntm_layers as ntm_layers_mod

    legacy = ntm_layers_mod.get_all_layer_requirements(hs_code, description)
    runtime = get_layer_requirements_for_pipeline(hs_code, description)

    def _row_key(d: dict[str, Any]) -> str:
        mk = str(d.get("measure_kind") or "")
        if not mk:
            pt = str(d.get("permit_type") or "")
            if pt == "ВС":
                mk = "vet"
            elif pt == "ФСС":
                mk = "phyto"
            elif pt == "СГР":
                mk = "sgr"
            elif pt == "НФ":
                mk = "notification"
            elif pt == "ЛЗ":
                mk = "license"
        return _layer_cmp_key(str(d.get("permit_type") or ""), d.get("tr_ts"), mk)

    legacy_keys = {_row_key(x) for x in legacy}
    runtime_keys = {_row_key(x) for x in runtime}
    return {
        "ntm_v2_layers_enabled": is_ntm_v2_layers_enabled(),
        "legacy_only": sorted(legacy_keys - runtime_keys),
        "runtime_only": sorted(runtime_keys - legacy_keys),
        "overlap": sorted(legacy_keys & runtime_keys),
        "is_full_match": legacy_keys == runtime_keys,
    }
