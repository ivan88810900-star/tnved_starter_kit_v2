"""Импорт legacy ``non_tariff_measures`` в NTM v2 (данные + shadow, без runtime enforcement)."""

from __future__ import annotations

import json
from typing import Any, Iterator

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from .. import db
from ..datetime_util import utc_now_naive
from ..models.ntm_v2 import NtmApplicabilityRuleV2, NtmMeasureV2
from ..models.tnved import NonTariffMeasure
from .hs_matching import get_hs_prefixes, normalize_hs_code
from .non_tariff_rules import (
    _extract_tr_ts_code,
    _measure_to_permit_type,
)
from .ntm_v2_legacy_rules_import import merge_v2_legacy_rules_into_broker
from .tr_ts_catalog import TR_TS_FULL_NAMES

MEASURES_SOURCE_KIND = "legacy_non_tariff_measures"
MEASURES_SOURCE_REF_PREFIX = "non_tariff_measures"

_LEN_TO_SOURCE_LEVEL: dict[int, str] = {
    10: "exact",
    8: "8_digit",
    6: "6_digit",
    4: "4_digit",
    2: "chapter",
}


def measure_type_to_measure_kind(measure_type: str) -> str:
    """Маппинг legacy ``measure_type`` → v2 ``measure_kind``."""
    mtype = (measure_type or "").lower().strip()
    mapping = {
        "license": "license",
        "licence": "license",
        "certificate": "technical_regulation",
        "declaration": "technical_regulation",
        "vet_control": "vet",
        "phyto_control": "phyto",
        "sgr": "sgr",
        "tr_ts": "technical_regulation",
        "ban": "prohibition",
        "marking": "marking",
        "fsetc": "other",
        "radiation_control": "other",
        "other": "other",
    }
    return mapping.get(mtype, "other")


def _legacy_measure_measure_import_key(legacy_measure_id: int) -> str:
    """Одна legacy-строка → одна v2-мера (стабильный id, без семантического merge)."""
    return f"{MEASURES_SOURCE_KIND}|{legacy_measure_id}"


def _legacy_measure_rule_import_key(legacy_measure_id: int, commodity_code: str) -> str:
    return f"{MEASURES_SOURCE_KIND}|measure:{legacy_measure_id}|{commodity_code}"


def _legacy_measure_payload_json(
    *,
    legacy_measure_id: int,
    commodity_code: str,
    measure_type: str,
    permit_type: str | None,
    tr_ts_code: str | None,
    description: str,
    document_required: str,
    legal_ref: str,
    quality: str,
) -> dict[str, Any]:
    return {
        "legacy_payload": {
            "legacy_measure_id": legacy_measure_id,
            "commodity_code": commodity_code,
            "measure_type": measure_type,
            "permit_type": permit_type,
            "tr_ts_code": tr_ts_code,
            "description": description,
            "document_required": document_required,
            "legal_ref": legal_ref,
            "quality": quality,
        }
    }


def _measure_title(measure_type: str, description: str, legal_ref: str) -> str:
    desc = (description or "").strip()
    if desc:
        return desc[:512]
    act = (legal_ref or "").strip()
    if act:
        return f"{measure_type}: {act}"[:512]
    return f"{measure_type} (legacy non_tariff_measures)"[:512]


def _measure_short_description(
    *,
    legacy_measure_id: int,
    commodity_code: str,
    measure_type: str,
    quality: str,
) -> str:
    return json.dumps(
        {
            "legacy_measure_id": legacy_measure_id,
            "commodity_code": commodity_code,
            "measure_type": measure_type,
            "quality": quality,
            "source": MEASURES_SOURCE_REF_PREFIX,
        },
        ensure_ascii=False,
    )


def _derive_permit_and_tr_ts(row: NonTariffMeasure, hs_for_domain: str) -> tuple[str, str]:
    desc = (row.description or "").strip()
    legal_ref = (row.regulatory_act or "").strip()
    doc = (row.document_required or "").strip()
    mtype = (row.measure_type or "").strip()
    permit = _measure_to_permit_type(
        mtype,
        f"{doc} {desc} {legal_ref}",
        hs_code=hs_for_domain,
    )
    tr_ts = _extract_tr_ts_code(desc, legal_ref, doc) or ""
    return permit or "", tr_ts


def measure_compare_key(
    *,
    measure_kind: str,
    permit_type: str | None,
    tr_ts_act_code: str | None,
    legal_ref: str | None,
) -> str:
    """Нормализованный ключ для shadow compare (как в ТЗ)."""
    pt = (permit_type or "").strip()
    tr = (tr_ts_act_code or "").strip()
    lr = (legal_ref or "").strip()
    return f"{measure_kind}|{pt}|{tr}|{lr}"


def measure_compare_key_from_legacy_dict(m: dict[str, Any]) -> str:
    mk = measure_type_to_measure_kind(str(m.get("measure_type") or ""))
    return measure_compare_key(
        measure_kind=mk,
        permit_type=m.get("permit_type"),
        tr_ts_act_code=m.get("tr_ts_code"),
        legal_ref=m.get("legal_ref"),
    )


def legacy_measure_dict_to_broker_row(m: dict[str, Any]) -> dict[str, Any]:
    """Строка imported measure в формате broker layer (runtime + диагностика)."""
    tr_raw = m.get("tr_ts_code")
    tr_norm: str | None = (str(tr_raw).strip() if tr_raw else None) or None
    pt = (m.get("permit_type") or "").strip()
    mtype = str(m.get("measure_type") or "")
    mk = str(m.get("measure_kind") or measure_type_to_measure_kind(mtype))
    legal_ref = str(m.get("legal_ref") or "")
    return {
        "permit_type": pt,
        "tr_ts": tr_norm,
        "tr_ts_full_name": TR_TS_FULL_NAMES.get(tr_norm or "", "") if tr_norm else "",
        "description": str(m.get("description") or "")[:500],
        "legal_ref": legal_ref[:500],
        "matched_prefix": str(m.get("commodity_code") or "")[:16],
        "priority": 0,
        "trigger": None,
        "source_level": "measures_v2",
        "source_kind": MEASURES_SOURCE_KIND,
        "measure_kind": mk,
        "measure_key": measure_compare_key(
            measure_kind=mk,
            permit_type=pt or None,
            tr_ts_act_code=tr_norm,
            legal_ref=legal_ref,
        ),
    }


def get_v2_legacy_measures_broker_rows(
    hs_code: str,
    description: str = "",
    *,
    session: Session | None = None,
) -> list[dict[str, Any]]:
    """Matched v2 legacy measures для HS в формате broker rows."""
    _ = description
    close_session = False
    if session is None:
        session = db.SessionLocal()
        close_session = True
    try:
        raw = _find_v2_legacy_measures_for_code(hs_code, session=session)
        return [legacy_measure_dict_to_broker_row(m) for m in raw]
    finally:
        if close_session:
            session.close()


def merge_v2_legacy_measures_into_broker(
    broker_rows: list[dict[str, Any]],
    measure_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Дедуп по ``(permit_type, tr_ts)``; пустой ``permit_type`` не добавляется."""
    filtered = [r for r in measure_rows if (r.get("permit_type") or "").strip()]
    return merge_v2_legacy_rules_into_broker(broker_rows, filtered)


def measure_compare_key_from_v2_measure(measure: NtmMeasureV2, legal_ref: str = "") -> str:
    payload = {}
    if measure.applicability_rules:
        rule = measure.applicability_rules[0]
        dm = rule.description_match_json if isinstance(rule.description_match_json, dict) else {}
        legacy = dm.get("legacy_payload") if isinstance(dm.get("legacy_payload"), dict) else {}
        legal_ref = str(legacy.get("legal_ref") or legal_ref)
    return measure_compare_key(
        measure_kind=measure.measure_kind,
        permit_type=measure.permit_type,
        tr_ts_act_code=measure.tr_ts_act_code or None,
        legal_ref=legal_ref,
    )


def _iter_v2_legacy_measure_rules(session: Session) -> Iterator[NtmApplicabilityRuleV2]:
    stmt = (
        select(NtmApplicabilityRuleV2)
        .join(NtmMeasureV2, NtmApplicabilityRuleV2.measure_id == NtmMeasureV2.id)
        .options(joinedload(NtmApplicabilityRuleV2.measure))
        .where(
            NtmApplicabilityRuleV2.source_kind == MEASURES_SOURCE_KIND,
            NtmMeasureV2.source_kind == MEASURES_SOURCE_KIND,
            NtmMeasureV2.status == "active",
        )
    )
    yield from session.scalars(stmt).unique().all()


def _find_v2_legacy_measures_for_code(
    hs_code: str,
    direction: str = "import",
    *,
    session: Session,
) -> list[dict[str, Any]]:
    """
    Тот же алгоритм, что ``find_measures_for_code``: префиксы 10→2, стоп на первом уровне,
    дедуп по ``row.id`` и ``compact_key`` на уровне.
    """
    _ = direction  # legacy ORM без direction; v2 rules — import
    code = normalize_hs_code(hs_code)
    if not code:
        return []

    prefixes: list[tuple[str, str, int]] = []
    for pref in get_hs_prefixes(code, levels=(10, 8, 6, 4, 2)):
        ln = len(pref)
        prefixes.append((pref, _LEN_TO_SOURCE_LEVEL[ln], ln))
    if not prefixes:
        return []

    all_rules = list(_iter_v2_legacy_measure_rules(session))
    level_order = {
        "exact": 0,
        "8_digit": 1,
        "6_digit": 2,
        "4_digit": 3,
        "chapter": 4,
    }
    results: list[dict[str, Any]] = []
    seen_import_keys: set[str] = set()

    for pref, source_level, pref_len in prefixes:
        level_seen: set[tuple[str, str, str, str]] = set()
        level_rows: list[dict[str, Any]] = []
        for rule in all_rules:
            measure = rule.measure
            # Эквивалент legacy SQL: commodity_code LIKE '{pref}%'
            rule_hs = normalize_hs_code(rule.hs_code)
            if not rule_hs.startswith(pref):
                continue
            ik = measure.import_key
            if ik in seen_import_keys:
                continue
            payload = rule.description_match_json if isinstance(rule.description_match_json, dict) else {}
            legacy = payload.get("legacy_payload") if isinstance(payload.get("legacy_payload"), dict) else {}
            mtype = str(legacy.get("measure_type") or measure.measure_kind)
            legal_ref = str(legacy.get("legal_ref") or "")
            desc = str(legacy.get("description") or measure.title)
            doc = str(legacy.get("document_required") or "")
            permit_type = legacy.get("permit_type") if legacy.get("permit_type") is not None else measure.permit_type
            tr_ts = legacy.get("tr_ts_code") if legacy.get("tr_ts_code") is not None else (measure.tr_ts_act_code or None)
            measure_kind = measure.measure_kind or measure_type_to_measure_kind(mtype)
            compact_key = (
                mtype.lower(),
                legal_ref.lower(),
                str(permit_type or ""),
                str(tr_ts or ""),
            )
            if compact_key in level_seen:
                continue
            level_seen.add(compact_key)
            seen_import_keys.add(ik)
            level_rows.append(
                {
                    "commodity_code": legacy.get("commodity_code") or rule.hs_code,
                    "measure_type": mtype,
                    "description": desc,
                    "document_required": doc,
                    "legal_ref": legal_ref,
                    "permit_type": permit_type,
                    "tr_ts_code": tr_ts,
                    "measure_kind": measure_kind,
                    "match_prefix_len": pref_len,
                    "source_level": source_level,
                }
            )
        if level_rows:
            results.extend(level_rows)
            break

    results.sort(
        key=lambda m: (
            level_order.get(str(m.get("source_level") or ""), 99),
            -int(m.get("match_prefix_len") or 0),
            str(m.get("commodity_code") or ""),
        )
    )
    return results


def import_legacy_non_tariff_measures_to_ntm_v2(
    session: Session | None = None,
) -> dict[str, Any]:
    """
    Импортирует все строки ``non_tariff_measures`` в v2 (идемпотентно).

    Строки с ``quality='noise'`` не импортируются (как фильтр в ``find_measures_for_code``).
    """
    close_session = False
    if session is None:
        session = db.SessionLocal()
        close_session = True
    now = utc_now_naive()
    legacy_measures_processed = 0
    measures_created = 0
    measures_updated = 0
    applicability_rules_created = 0
    applicability_rules_updated = 0
    skipped_noise = 0
    skipped_invalid_hs = 0
    duplicates_skipped = 0

    try:
        measure_by_key: dict[str, NtmMeasureV2] = {
            m.import_key: m
            for m in session.scalars(
                select(NtmMeasureV2).where(NtmMeasureV2.source_kind == MEASURES_SOURCE_KIND)
            ).all()
        }

        legacy_rows = session.scalars(
            select(NonTariffMeasure).order_by(NonTariffMeasure.id)
        ).all()

        for row in legacy_rows:
            legacy_measures_processed += 1
            if (row.quality or "").strip().lower() == "noise":
                skipped_noise += 1
                continue

            commodity_code = normalize_hs_code(row.commodity_code)
            if not commodity_code:
                skipped_invalid_hs += 1
                continue

            permit_type, tr_ts = _derive_permit_and_tr_ts(row, commodity_code)
            mtype = (row.measure_type or "").strip()
            mk = measure_type_to_measure_kind(mtype)
            desc = (row.description or "").strip()
            legal_ref = (row.regulatory_act or "").strip()
            doc = (row.document_required or "").strip()
            quality = (row.quality or "normal").strip()

            payload = _legacy_measure_payload_json(
                legacy_measure_id=row.id,
                commodity_code=commodity_code,
                measure_type=mtype,
                permit_type=permit_type or None,
                tr_ts_code=tr_ts or None,
                description=desc,
                document_required=doc,
                legal_ref=legal_ref,
                quality=quality,
            )

            mik = _legacy_measure_measure_import_key(row.id)
            if mik not in measure_by_key:
                measure = NtmMeasureV2(
                    measure_kind=mk,
                    permit_type=permit_type,
                    title=_measure_title(mtype, desc, legal_ref),
                    short_description=_measure_short_description(
                        legacy_measure_id=row.id,
                        commodity_code=commodity_code,
                        measure_type=mtype,
                        quality=quality,
                    ),
                    tr_ts_act_code=tr_ts,
                    regulatory_document_id=None,
                    valid_from=None,
                    valid_to=None,
                    status="active",
                    source_kind=MEASURES_SOURCE_KIND,
                    source_ref=f"{MEASURES_SOURCE_REF_PREFIX}:id:{row.id}",
                    import_key=mik,
                    created_at=now,
                    updated_at=now,
                )
                session.add(measure)
                session.flush()
                measure_by_key[mik] = measure
                measures_created += 1
            else:
                measure = measure_by_key[mik]
                measure.measure_kind = mk
                measure.permit_type = permit_type
                measure.title = _measure_title(mtype, desc, legal_ref)
                measure.short_description = _measure_short_description(
                    legacy_measure_id=row.id,
                    commodity_code=commodity_code,
                    measure_type=mtype,
                    quality=quality,
                )
                measure.tr_ts_act_code = tr_ts
                measure.updated_at = now
                measures_updated += 1

            rk = _legacy_measure_rule_import_key(row.id, commodity_code)
            existing = session.scalar(
                select(NtmApplicabilityRuleV2).where(NtmApplicabilityRuleV2.rule_import_key == rk)
            )
            if existing is None:
                session.add(
                    NtmApplicabilityRuleV2(
                        measure_id=measure.id,
                        direction="import",
                        country_iso=None,
                        hs_scope_mode="prefix",
                        hs_code=commodity_code,
                        excluded_hs_json=None,
                        description_match_json=payload,
                        applicability="definite",
                        requires_manual_review=False,
                        priority=0,
                        valid_from=None,
                        valid_to=None,
                        source_kind=MEASURES_SOURCE_KIND,
                        source_ref=f"{MEASURES_SOURCE_REF_PREFIX}:measure_id:{row.id}",
                        rule_import_key=rk,
                        created_at=now,
                        updated_at=now,
                    )
                )
                applicability_rules_created += 1
            else:
                existing.measure_id = measure.id
                existing.hs_code = commodity_code
                existing.hs_scope_mode = "prefix"
                existing.description_match_json = payload
                existing.updated_at = now
                applicability_rules_updated += 1
                duplicates_skipped += 1

        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        if close_session:
            session.close()

    return {
        "legacy_measures_processed": legacy_measures_processed,
        "measures_created": measures_created,
        "measures_updated": measures_updated,
        "applicability_rules_created": applicability_rules_created,
        "applicability_rules_updated": applicability_rules_updated,
        "skipped_noise": skipped_noise,
        "skipped_invalid_hs": skipped_invalid_hs,
        "duplicates_skipped": duplicates_skipped,
    }


def compare_legacy_non_tariff_measures_vs_ntm_v2(
    hs_code: str,
    *,
    description: str = "",
    direction: str = "import",
) -> dict[str, Any]:
    """
    Shadow: ``find_measures_for_code`` vs v2 (``source_kind=legacy_non_tariff_measures``).

    Ключ сравнения: ``measure_kind|permit_type|tr_ts_act_code|legal_ref``.
    """
    _ = description
    from .non_tariff_rules import find_measures_for_code

    legacy_rows = find_measures_for_code(hs_code, direction=direction)
    legacy_keys = {measure_compare_key_from_legacy_dict(m) for m in legacy_rows}

    with db.SessionLocal() as session:
        v2_rows = _find_v2_legacy_measures_for_code(hs_code, direction, session=session)
        v2_keys: set[str] = set()
        for m in v2_rows:
            mk = measure_type_to_measure_kind(str(m.get("measure_type") or ""))
            v2_keys.add(
                measure_compare_key(
                    measure_kind=mk,
                    permit_type=m.get("permit_type"),
                    tr_ts_act_code=m.get("tr_ts_code"),
                    legal_ref=m.get("legal_ref"),
                )
            )

    return {
        "hs_code": normalize_hs_code(hs_code),
        "direction": (direction or "import").strip().lower(),
        "legacy_only": sorted(legacy_keys - v2_keys),
        "v2_only": sorted(v2_keys - legacy_keys),
        "overlap": sorted(legacy_keys & v2_keys),
        "is_full_match": legacy_keys == v2_keys,
        "legacy_count": len(legacy_keys),
        "v2_count": len(v2_keys),
    }
