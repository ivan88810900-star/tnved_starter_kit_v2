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
    Синхронизирует HS-правила и условия из ``ntm_layers`` с v2.

    Удаляет устаревшие правила только из своего generated namespace;
    меры/правила ТР ТС и официальных контуров не затрагивает.
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
    rules_removed = 0

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
                measure.measure_kind = measure_kind
                measure.permit_type = permit_type
                measure.short_description = meta_json
                measure.title = str(sample.get("tr_ts_full_name") or permit_type)[:512]
                measure.tr_ts_act_code = ""
                measure.regulatory_document_id = None
                measure.valid_from = None
                measure.valid_to = None
                measure.status = "active"
                measure.source_kind = LAYERS_SOURCE_KIND
                measure.source_ref = f"{LAYERS_SOURCE_REF}:{measure_kind}"
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

        desired_rules: list[dict[str, Any]] = []
        pri = 10_000

        def _plan_rule(
            *,
            measure: NtmMeasureV2,
            layer_key: str,
            suffix: str,
            hs_code: str,
            source_ref: str,
            description_match_json: dict[str, Any] | None = None,
        ) -> None:
            nonlocal pri
            pri += 1
            desired_rules.append({
                "measure_id": measure.id,
                "direction": "import",
                "country_iso": None,
                "hs_scope_mode": "prefix",
                "hs_code": hs_code,
                "excluded_hs_json": None,
                "description_match_json": description_match_json,
                "applicability": "definite",
                "requires_manual_review": False,
                "priority": pri,
                "valid_from": None,
                "valid_to": None,
                "source_kind": LAYERS_SOURCE_KIND,
                "source_ref": source_ref,
                "rule_import_key": _layer_rule_import_key(layer_key, suffix),
            })

        vet_m = _ensure_measure("vet", "ВС")
        for p in sorted(set(ntm_layers_mod.VET_DOMAINS), key=lambda x: (-len(x), x)):
            _plan_rule(
                measure=vet_m,
                layer_key="vet",
                suffix=f"hs|{p}",
                hs_code=p,
                source_ref=f"{LAYERS_SOURCE_REF}:get_vet_requirement:{p}",
            )

        phy_m = _ensure_measure("phyto", "ФСС")
        for p in sorted(set(ntm_layers_mod.PHYTO_DOMAINS), key=lambda x: (-len(x), x)):
            _plan_rule(
                measure=phy_m,
                layer_key="phyto",
                suffix=f"hs|{p}",
                hs_code=p,
                source_ref=f"{LAYERS_SOURCE_REF}:get_phyto_requirement:{p}",
            )

        nf_m = _ensure_measure("notification", "НФ")
        for p in sorted(set(ntm_layers_mod.NF_DOMAINS), key=lambda x: (-len(x), x)):
            _plan_rule(
                measure=nf_m,
                layer_key="nf",
                suffix=f"hs|{p}",
                hs_code=p,
                source_ref=f"{LAYERS_SOURCE_REF}:get_nf_requirement:{p}",
            )

        lz_m = _ensure_measure("license", "ЛЗ")
        for p in sorted(set(ntm_layers_mod.LICENCE_DOMAINS), key=lambda x: (-len(x), x)):
            _plan_rule(
                measure=lz_m,
                layer_key="lz",
                suffix=f"hs|{p}",
                hs_code=p,
                source_ref=f"{LAYERS_SOURCE_REF}:get_licence_requirement:{p}",
            )

        sgr_m = _ensure_measure("sgr", "СГР")
        sgr_subs = tuple(sgr_desc_triggers) + SGR_WATER_HINTS
        for p in sorted(
            set(ntm_layers_mod.SGR_DOMAINS) - {"2201"},
            key=lambda x: (-len(x), x),
        ):
            _plan_rule(
                measure=sgr_m,
                layer_key="sgr",
                suffix=f"hs|{p}",
                hs_code=p,
                source_ref=f"{LAYERS_SOURCE_REF}:get_sgr_requirement:hs:{p}",
            )
        _plan_rule(
            measure=sgr_m,
            layer_key="sgr",
            suffix="hs|2201|desc",
            hs_code="2201",
            source_ref=f"{LAYERS_SOURCE_REF}:get_sgr_requirement:2201",
            description_match_json=_desc_match_any_substrings(sgr_subs),
        )
        _plan_rule(
            measure=sgr_m,
            layer_key="sgr",
            suffix="desc_any",
            hs_code="",
            source_ref=f"{LAYERS_SOURCE_REF}:get_sgr_requirement:desc_any",
            description_match_json=_desc_match_any_substrings(
                tuple(ntm_layers_mod.SGR_DESCRIPTION_TRIGGERS)
            ),
        )

        existing_generated = {
            rule.rule_import_key: rule
            for rule in session.scalars(
                select(NtmApplicabilityRuleV2).where(
                    NtmApplicabilityRuleV2.source_kind == LAYERS_SOURCE_KIND,
                    NtmApplicabilityRuleV2.rule_import_key.like(
                        f"{LAYERS_SOURCE_KIND}|%"
                    ),
                )
            ).all()
        }
        desired_keys = {str(spec["rule_import_key"]) for spec in desired_rules}
        for spec in desired_rules:
            rule_import_key = str(spec["rule_import_key"])
            existing = existing_generated.get(rule_import_key)
            if existing is None:
                session.add(
                    NtmApplicabilityRuleV2(
                        **spec,
                        created_at=now,
                        updated_at=now,
                    )
                )
                rules_created += 1
                continue
            for field, value in spec.items():
                setattr(existing, field, value)
            existing.updated_at = now
            rules_skipped += 1

        # Это generated snapshot одного импортера. Удаляем только его собственные
        # ключи и source_kind; official/legacy-rules/TR-TS контуры не затрагиваются.
        for rule_import_key, stale_rule in existing_generated.items():
            if rule_import_key in desired_keys:
                continue
            session.delete(stale_rule)
            rules_removed += 1

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
        "layers_rules_removed": rules_removed,
    }
