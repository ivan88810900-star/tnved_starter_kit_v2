"""Импорт ``tr_ts_catalog`` и ``ntm_layers`` в таблицы NTM v2 (идемпотентно)."""

from __future__ import annotations

import json
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import db
from ..datetime_util import utc_now_naive
from ..models.ntm_v2 import NtmApplicabilityRuleV2, NtmMeasureV2
from . import ntm_layers as ntm_layers_mod
from .tr_ts_catalog import ALL_REGULATIONS, TR_TS_FULL_NAMES

SOURCE_KIND = "legacy_tr_ts_catalog"
SOURCE_REF_CATALOG = "tr_ts_catalog.ALL_REGULATIONS"
MEASURE_KIND = "technical_regulation"

LAYERS_SOURCE_KIND = "legacy_ntm_layers"
LAYERS_SOURCE_REF = "ntm_layers.py"


def _measure_import_key(permit_type: str, tr_ts_act_code: str) -> str:
    """Стабильный ключ меры: один TR + форма документа = одна мера независимо от числа HS-префиксов."""
    return f"{SOURCE_KIND}|{MEASURE_KIND}|{permit_type}|{tr_ts_act_code}"


def _rule_import_key(hs_prefix: str, tr_ts_act_code: str, permit_type: str) -> str:
    return f"{SOURCE_KIND}|{hs_prefix}|{tr_ts_act_code}|{permit_type}"


def _measure_title(tr_ts: str, permit_type: str) -> str:
    name = TR_TS_FULL_NAMES.get(tr_ts, "")
    if name:
        return f"ТР ТС {tr_ts} — {name} ({permit_type})"
    return f"ТР ТС {tr_ts} ({permit_type})"


def _measure_short_description(tr_ts: str, permit_type: str) -> str:
    form_label = "Декларация о соответствии" if permit_type == "ДС" else "Сертификат соответствия"
    return f"{form_label} по ТР ТС {tr_ts}"


def import_tr_ts_catalog_to_ntm_v2(session: Session | None = None) -> dict[str, Any]:
    """
    Переносит весь ``ALL_REGULATIONS`` в ``ntm_measures_v2`` + ``ntm_applicability_rules_v2``.

    Идемпотентность: уникальные ``import_key`` / ``rule_import_key``; повторный импорт
    не создаёт новых строк, обновляет ``priority`` у правил и ``updated_at``.
    """
    close_session = False
    if session is None:
        session = db.SessionLocal()
        close_session = True
    now = utc_now_naive()
    measures_created = 0
    measures_skipped_duplicates = 0
    rules_created = 0
    rules_skipped_duplicates = 0
    unique_pairs = sorted({(tr_ts, form) for _, tr_ts, form in ALL_REGULATIONS})

    try:
        measure_by_key: dict[str, NtmMeasureV2] = {
            m.import_key: m for m in session.scalars(select(NtmMeasureV2)).all()
        }
        for tr_ts, permit_type in unique_pairs:
            ik = _measure_import_key(permit_type, tr_ts)
            if ik in measure_by_key:
                measures_skipped_duplicates += 1
                continue
            row = NtmMeasureV2(
                measure_kind=MEASURE_KIND,
                permit_type=permit_type,
                title=_measure_title(tr_ts, permit_type),
                short_description=_measure_short_description(tr_ts, permit_type),
                tr_ts_act_code=tr_ts,
                regulatory_document_id=None,
                valid_from=None,
                valid_to=None,
                status="active",
                source_kind=SOURCE_KIND,
                source_ref=SOURCE_REF_CATALOG,
                import_key=ik,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            session.flush()
            measure_by_key[ik] = row
            measures_created += 1

        for idx, (prefix, tr_ts, permit_type) in enumerate(ALL_REGULATIONS):
            ik = _measure_import_key(permit_type, tr_ts)
            measure = measure_by_key[ik]
            rk = _rule_import_key(prefix, tr_ts, permit_type)
            existing_rule = session.scalar(
                select(NtmApplicabilityRuleV2).where(NtmApplicabilityRuleV2.rule_import_key == rk)
            )
            if existing_rule is None:
                session.add(
                    NtmApplicabilityRuleV2(
                        measure_id=measure.id,
                        direction="import",
                        country_iso=None,
                        hs_scope_mode="prefix",
                        hs_code=prefix,
                        excluded_hs_json=None,
                        description_match_json=None,
                        applicability="definite",
                        requires_manual_review=False,
                        priority=idx,
                        valid_from=None,
                        valid_to=None,
                        source_kind=SOURCE_KIND,
                        source_ref=SOURCE_REF_CATALOG,
                        rule_import_key=rk,
                        created_at=now,
                        updated_at=now,
                    )
                )
                rules_created += 1
            else:
                existing_rule.priority = idx
                existing_rule.measure_id = measure.id
                existing_rule.updated_at = now
                rules_skipped_duplicates += 1

        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        if close_session:
            session.close()

    return {
        "measures_created": measures_created,
        "rules_created": rules_created,
        "measures_skipped_duplicates": measures_skipped_duplicates,
        "rules_skipped_duplicates": rules_skipped_duplicates,
        "catalog_rows": len(ALL_REGULATIONS),
        "unique_measures": len(unique_pairs),
    }


def _layer_measure_import_key(measure_kind: str, permit_type: str) -> str:
    return f"{LAYERS_SOURCE_KIND}|{measure_kind}|{permit_type}"


def _layer_rule_import_key(layer: str, suffix: str) -> str:
    return f"{LAYERS_SOURCE_KIND}|{layer}|{suffix}"


def _layer_meta_json(*, legal_ref: str, consumer: str, label: str, **extra: Any) -> str:
    payload: dict[str, Any] = {"legal_ref": legal_ref, "consumer": consumer, "label": label}
    payload.update(extra)
    return json.dumps(payload, ensure_ascii=False)


# Снимок констант СГР на момент импорта (runtime v2 читает из JSON меры, не из ntm_layers).
SGR_WATER_HINTS: tuple[str, ...] = (
    "минеральн",
    "лечеб",
    "столов",
    "бутилир",
    "детск",
    "газирован",
)


def _desc_match_any_substrings(substrings: tuple[str, ...] | list[str]) -> dict[str, Any]:
    return {"mode": "any_substring", "substrings": list(substrings)}


def import_ntm_layers_to_ntm_v2(session: Session | None = None) -> dict[str, Any]:
    """
    Импортирует HS-правила и условия по описанию из ``ntm_layers`` в v2.

    Не удаляет и не пересоздаёт меры/правила ТР ТС (другой ``source_kind``).
    """
    close_session = False
    if session is None:
        session = db.SessionLocal()
        close_session = True
    now = utc_now_naive()
    measures_created = 0
    measures_skipped = 0
    rules_created = 0
    rules_skipped = 0

    samples: list[tuple[str, str, Callable[[], dict[str, Any] | None]]] = [
        ("vet", "ВС", lambda: ntm_layers_mod.get_vet_requirement("0101000000")),
        ("phyto", "ФСС", lambda: ntm_layers_mod.get_phyto_requirement("0601000000")),
        ("notification", "НФ", lambda: ntm_layers_mod.get_nf_requirement("8525600000")),
        ("license", "ЛЗ", lambda: ntm_layers_mod.get_licence_requirement("2203000000")),
        ("sgr", "СГР", lambda: ntm_layers_mod.get_sgr_requirement("1901000000", "")),
    ]

    try:
        measure_by_key: dict[str, NtmMeasureV2] = {
            m.import_key: m for m in session.scalars(select(NtmMeasureV2)).all()
        }

        sgr_desc_triggers = list(ntm_layers_mod.SGR_DESCRIPTION_TRIGGERS)

        for measure_kind, permit_type, sample_fn in samples:
            sample = sample_fn()
            if not sample:
                raise RuntimeError(f"ntm_layers sample empty for {measure_kind}/{permit_type}")
            ik = _layer_measure_import_key(measure_kind, permit_type)
            meta_extra: dict[str, Any] = {}
            if measure_kind == "sgr":
                meta_extra = {
                    "sgr_description_triggers": sgr_desc_triggers,
                    "sgr_water_hints": list(SGR_WATER_HINTS),
                }
            meta_json = _layer_meta_json(
                legal_ref=str(sample.get("legal_ref") or ""),
                consumer=str(sample.get("description") or ""),
                label=str(sample.get("tr_ts_full_name") or permit_type),
                **meta_extra,
            )
            if ik in measure_by_key:
                measures_skipped += 1
                measure = measure_by_key[ik]
                measure.short_description = meta_json
                measure.title = str(sample.get("tr_ts_full_name") or permit_type)[:512]
                measure.updated_at = now
            else:
                measure = NtmMeasureV2(
                    measure_kind=measure_kind,
                    permit_type=permit_type,
                    title=str(sample.get("tr_ts_full_name") or permit_type)[:512],
                    short_description=meta_json,
                    tr_ts_act_code="",
                    regulatory_document_id=None,
                    valid_from=None,
                    valid_to=None,
                    status="active",
                    source_kind=LAYERS_SOURCE_KIND,
                    source_ref=f"{LAYERS_SOURCE_REF}:{measure_kind}",
                    import_key=ik,
                    created_at=now,
                    updated_at=now,
                )
                session.add(measure)
                session.flush()
                measure_by_key[ik] = measure
                measures_created += 1

        def _ensure_measure(mk: str, pt: str) -> NtmMeasureV2:
            ik2 = _layer_measure_import_key(mk, pt)
            m2 = measure_by_key.get(ik2)
            if m2 is None:
                raise KeyError(ik2)
            return m2

        pri = 10_000

        vet_m = _ensure_measure("vet", "ВС")
        for p in sorted(set(ntm_layers_mod.VET_DOMAINS), key=lambda x: (-len(x), x)):
            rk = _layer_rule_import_key("vet", f"hs|{p}")
            pri += 1
            ex = session.scalar(select(NtmApplicabilityRuleV2).where(NtmApplicabilityRuleV2.rule_import_key == rk))
            if ex is None:
                session.add(
                    NtmApplicabilityRuleV2(
                        measure_id=vet_m.id,
                        direction="import",
                        country_iso=None,
                        hs_scope_mode="prefix",
                        hs_code=p,
                        excluded_hs_json=None,
                        description_match_json=None,
                        applicability="definite",
                        requires_manual_review=False,
                        priority=pri,
                        valid_from=None,
                        valid_to=None,
                        source_kind=LAYERS_SOURCE_KIND,
                        source_ref=f"{LAYERS_SOURCE_REF}:get_vet_requirement:{p}",
                        rule_import_key=rk,
                        created_at=now,
                        updated_at=now,
                    )
                )
                rules_created += 1
            else:
                ex.priority = pri
                ex.updated_at = now
                rules_skipped += 1

        phy_m = _ensure_measure("phyto", "ФСС")
        for p in sorted(set(ntm_layers_mod.PHYTO_DOMAINS), key=lambda x: (-len(x), x)):
            rk = _layer_rule_import_key("phyto", f"hs|{p}")
            pri += 1
            ex = session.scalar(select(NtmApplicabilityRuleV2).where(NtmApplicabilityRuleV2.rule_import_key == rk))
            if ex is None:
                session.add(
                    NtmApplicabilityRuleV2(
                        measure_id=phy_m.id,
                        direction="import",
                        country_iso=None,
                        hs_scope_mode="prefix",
                        hs_code=p,
                        excluded_hs_json=None,
                        description_match_json=None,
                        applicability="definite",
                        requires_manual_review=False,
                        priority=pri,
                        valid_from=None,
                        valid_to=None,
                        source_kind=LAYERS_SOURCE_KIND,
                        source_ref=f"{LAYERS_SOURCE_REF}:get_phyto_requirement:{p}",
                        rule_import_key=rk,
                        created_at=now,
                        updated_at=now,
                    )
                )
                rules_created += 1
            else:
                ex.priority = pri
                ex.updated_at = now
                rules_skipped += 1

        nf_m = _ensure_measure("notification", "НФ")
        for p in sorted(set(ntm_layers_mod.NF_DOMAINS), key=lambda x: (-len(x), x)):
            rk = _layer_rule_import_key("nf", f"hs|{p}")
            pri += 1
            ex = session.scalar(select(NtmApplicabilityRuleV2).where(NtmApplicabilityRuleV2.rule_import_key == rk))
            if ex is None:
                session.add(
                    NtmApplicabilityRuleV2(
                        measure_id=nf_m.id,
                        direction="import",
                        country_iso=None,
                        hs_scope_mode="prefix",
                        hs_code=p,
                        excluded_hs_json=None,
                        description_match_json=None,
                        applicability="definite",
                        requires_manual_review=False,
                        priority=pri,
                        valid_from=None,
                        valid_to=None,
                        source_kind=LAYERS_SOURCE_KIND,
                        source_ref=f"{LAYERS_SOURCE_REF}:get_nf_requirement:{p}",
                        rule_import_key=rk,
                        created_at=now,
                        updated_at=now,
                    )
                )
                rules_created += 1
            else:
                ex.priority = pri
                ex.updated_at = now
                rules_skipped += 1

        lz_m = _ensure_measure("license", "ЛЗ")
        for p in sorted(set(ntm_layers_mod.LICENCE_DOMAINS), key=lambda x: (-len(x), x)):
            rk = _layer_rule_import_key("lz", f"hs|{p}")
            pri += 1
            ex = session.scalar(select(NtmApplicabilityRuleV2).where(NtmApplicabilityRuleV2.rule_import_key == rk))
            if ex is None:
                session.add(
                    NtmApplicabilityRuleV2(
                        measure_id=lz_m.id,
                        direction="import",
                        country_iso=None,
                        hs_scope_mode="prefix",
                        hs_code=p,
                        excluded_hs_json=None,
                        description_match_json=None,
                        applicability="definite",
                        requires_manual_review=False,
                        priority=pri,
                        valid_from=None,
                        valid_to=None,
                        source_kind=LAYERS_SOURCE_KIND,
                        source_ref=f"{LAYERS_SOURCE_REF}:get_licence_requirement:{p}",
                        rule_import_key=rk,
                        created_at=now,
                        updated_at=now,
                    )
                )
                rules_created += 1
            else:
                ex.priority = pri
                ex.updated_at = now
                rules_skipped += 1

        sgr_m = _ensure_measure("sgr", "СГР")
        sgr_subs = tuple(sgr_desc_triggers) + SGR_WATER_HINTS
        for p in sorted(set(ntm_layers_mod.SGR_DOMAINS) - {"2201"}, key=lambda x: (-len(x), x)):
            rk = _layer_rule_import_key("sgr", f"hs|{p}")
            pri += 1
            ex = session.scalar(select(NtmApplicabilityRuleV2).where(NtmApplicabilityRuleV2.rule_import_key == rk))
            if ex is None:
                session.add(
                    NtmApplicabilityRuleV2(
                        measure_id=sgr_m.id,
                        direction="import",
                        country_iso=None,
                        hs_scope_mode="prefix",
                        hs_code=p,
                        excluded_hs_json=None,
                        description_match_json=None,
                        applicability="definite",
                        requires_manual_review=False,
                        priority=pri,
                        valid_from=None,
                        valid_to=None,
                        source_kind=LAYERS_SOURCE_KIND,
                        source_ref=f"{LAYERS_SOURCE_REF}:get_sgr_requirement:hs:{p}",
                        rule_import_key=rk,
                        created_at=now,
                        updated_at=now,
                    )
                )
                rules_created += 1
            else:
                ex.priority = pri
                ex.updated_at = now
                rules_skipped += 1

        rk2201 = _layer_rule_import_key("sgr", "hs|2201|desc")
        pri += 1
        ex2201 = session.scalar(select(NtmApplicabilityRuleV2).where(NtmApplicabilityRuleV2.rule_import_key == rk2201))
        if ex2201 is None:
            session.add(
                NtmApplicabilityRuleV2(
                    measure_id=sgr_m.id,
                    direction="import",
                    country_iso=None,
                    hs_scope_mode="prefix",
                    hs_code="2201",
                    excluded_hs_json=None,
                    description_match_json=_desc_match_any_substrings(sgr_subs),
                    applicability="definite",
                    requires_manual_review=False,
                    priority=pri,
                    valid_from=None,
                    valid_to=None,
                    source_kind=LAYERS_SOURCE_KIND,
                    source_ref=f"{LAYERS_SOURCE_REF}:get_sgr_requirement:2201",
                    rule_import_key=rk2201,
                    created_at=now,
                    updated_at=now,
                )
            )
            rules_created += 1
        else:
            ex2201.priority = pri
            ex2201.description_match_json = _desc_match_any_substrings(sgr_subs)
            ex2201.updated_at = now
            rules_skipped += 1

        rk_desc = _layer_rule_import_key("sgr", "desc_any")
        pri += 1
        exd = session.scalar(select(NtmApplicabilityRuleV2).where(NtmApplicabilityRuleV2.rule_import_key == rk_desc))
        desc_only_subs = tuple(ntm_layers_mod.SGR_DESCRIPTION_TRIGGERS)
        if exd is None:
            session.add(
                NtmApplicabilityRuleV2(
                    measure_id=sgr_m.id,
                    direction="import",
                    country_iso=None,
                    hs_scope_mode="prefix",
                    hs_code="",
                    excluded_hs_json=None,
                    description_match_json=_desc_match_any_substrings(desc_only_subs),
                    applicability="definite",
                    requires_manual_review=False,
                    priority=pri,
                    valid_from=None,
                    valid_to=None,
                    source_kind=LAYERS_SOURCE_KIND,
                    source_ref=f"{LAYERS_SOURCE_REF}:get_sgr_requirement:desc_any",
                    rule_import_key=rk_desc,
                    created_at=now,
                    updated_at=now,
                )
            )
            rules_created += 1
        else:
            exd.priority = pri
            exd.description_match_json = _desc_match_any_substrings(desc_only_subs)
            exd.updated_at = now
            rules_skipped += 1

        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        if close_session:
            session.close()

    return {
        "layers_measures_created": measures_created,
        "layers_measures_skipped": measures_skipped,
        "layers_rules_created": rules_created,
        "layers_rules_skipped": rules_skipped,
    }
