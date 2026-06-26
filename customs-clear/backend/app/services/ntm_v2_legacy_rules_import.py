"""Импорт legacy ``non_tariff_rules`` в NTM v2 (данные, shadow, опциональный enforcement)."""

from __future__ import annotations

import json
import os
from datetime import date
from typing import Any, Iterator

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from .. import db
from ..datetime_util import utc_now_naive
from ..models.core import NonTariffRule
from ..models.ntm_v2 import NtmApplicabilityRuleV2, NtmMeasureV2
from .hs_matching import match_hs_prefix, normalize_hs_code
from .normative_store import _non_tariff_rule_active_on, _parse_non_tariff_rule_date
from .tr_ts_catalog import TR_TS_FULL_NAMES

RULES_SOURCE_KIND = "legacy_non_tariff_rules"
RULES_SOURCE_REF_PREFIX = "non_tariff_rules"
# Широкие HS-prefix legacy rules — только информационный слой до ручной валидации.
LEGACY_RULES_IMPORT_APPLICABILITY = "possible"
ADVISORY_APPLICABILITIES = frozenset({"possible", "needs_clarification"})

_ADVISORY_REASON_POSSIBLE = (
    "Возможно требуется дополнительный разрешительный документ. "
    "Правило найдено по товарной группе и требует проверки характеристик товара."
)
_ADVISORY_REASON_NEEDS_CLARIFICATION = (
    "Требование может применяться, но для вывода недостаточно характеристик товара. "
    "Уточните состав, назначение или категорию продукции."
)


def _env_truthy(name: str) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def is_ntm_v2_rules_enforcement_enabled() -> bool:
    """``NTM_V2_RULES_ENFORCEMENT_ENABLED``: v2 legacy rules влияют на missing-check."""
    return _env_truthy("NTM_V2_RULES_ENFORCEMENT_ENABLED")


def should_apply_v2_rules_enforcement(explicit: bool | None = None) -> bool:
    if explicit is not None:
        return explicit
    return is_ntm_v2_rules_enforcement_enabled()


def is_legacy_v2_rule_definite(rule: NtmApplicabilityRuleV2) -> bool:
    """Только ``definite`` v2 rules влияют на broker / missing-check."""
    return (rule.applicability or "").strip() == "definite"


def _v2_rule_active_on(rule: NtmApplicabilityRuleV2, measure: NtmMeasureV2, as_of: date) -> bool:
    if measure.status != "active":
        return False
    vf_s = rule.valid_from.isoformat() if rule.valid_from else ""
    vt_s = rule.valid_to.isoformat() if rule.valid_to else ""
    payload = rule.description_match_json if isinstance(rule.description_match_json, dict) else {}
    rule_name = str((payload.get("legacy_payload") or {}).get("rule_name", ""))
    return _non_tariff_rule_active_on(
        vf_s,
        vt_s,
        as_of,
        rule_id=rule.id,
        rule_name=rule_name,
        hs_prefix=rule.hs_code,
    )


def _iter_matched_legacy_v2_rules(
    hs_code: str,
    *,
    as_of: date,
    session: Session,
) -> Iterator[tuple[NtmApplicabilityRuleV2, NtmMeasureV2]]:
    norm = normalize_hs_code(hs_code)
    if not norm:
        return
    stmt = (
        select(NtmApplicabilityRuleV2)
        .join(NtmMeasureV2, NtmApplicabilityRuleV2.measure_id == NtmMeasureV2.id)
        .options(joinedload(NtmApplicabilityRuleV2.measure))
        .where(
            NtmApplicabilityRuleV2.source_kind == RULES_SOURCE_KIND,
            NtmMeasureV2.source_kind == RULES_SOURCE_KIND,
        )
    )
    for rule in session.scalars(stmt).unique().all():
        m = rule.measure
        if not match_hs_prefix(norm, rule.hs_code):
            continue
        if not _v2_rule_active_on(rule, m, as_of):
            continue
        yield rule, m


def get_legacy_rule_requirements_v2_legacy_shape(
    hs_code: str,
    description: str = "",
    as_of: date | None = None,
    *,
    enforceable_only: bool = False,
) -> list[dict[str, Any]]:
    """
    Требования из v2 (``legacy_non_tariff_rules``) в формате строк broker layer.

    * ``enforceable_only=False`` (по умолчанию) — все активные правила + метаданные
      ``applicability`` / ``used_for_missing_check`` для диагностики.
    * ``enforceable_only=True`` — только ``applicability=definite`` (broker enforcement).

    ``description`` зарезервировано (правила v2 не используют текст позиции на этом этапе).
    """
    _ = description
    ref = as_of or date.today()
    rows: list[dict[str, Any]] = []
    with db.SessionLocal() as session:
        for rule, measure in _iter_matched_legacy_v2_rules(hs_code, as_of=ref, session=session):
            definite = is_legacy_v2_rule_definite(rule)
            if enforceable_only and not definite:
                continue
            tr_raw = (measure.tr_ts_act_code or "").strip()
            tr_norm: str | None = tr_raw if tr_raw else None
            payload = rule.description_match_json if isinstance(rule.description_match_json, dict) else {}
            legacy = payload.get("legacy_payload") if isinstance(payload.get("legacy_payload"), dict) else {}
            rule_name = str(legacy.get("rule_name") or measure.title)
            legal_ref = str(legacy.get("source_url") or legacy.get("tr_ts_edition") or RULES_SOURCE_REF_PREFIX)
            if legacy.get("exception_note"):
                legal_ref = f"{legal_ref}; {legacy['exception_note']}"[:500]
            rows.append(
                {
                    "permit_type": measure.permit_type,
                    "tr_ts": tr_norm,
                    "tr_ts_full_name": TR_TS_FULL_NAMES.get(tr_raw, "") if tr_raw else "",
                    "description": rule_name[:500],
                    "legal_ref": legal_ref[:500],
                    "matched_prefix": rule.hs_code,
                    "priority": int(rule.priority or 0),
                    "trigger": None,
                    "source_level": "rules_v2",
                    "applicability": (rule.applicability or "").strip() or LEGACY_RULES_IMPORT_APPLICABILITY,
                    "used_for_missing_check": definite,
                    "source": RULES_SOURCE_KIND,
                }
            )
    return rows


def get_legacy_rule_requirements_for_enforcement(
    hs_code: str,
    description: str = "",
    as_of: date | None = None,
) -> list[dict[str, Any]]:
    """Строки v2 legacy rules, допустимые в broker при ``NTM_V2_RULES_ENFORCEMENT_ENABLED``."""
    return get_legacy_rule_requirements_v2_legacy_shape(
        hs_code,
        description,
        as_of,
        enforceable_only=True,
    )


def advisory_reason_for_applicability(applicability: str) -> str:
    """Нейтральный текст подсказки для advisory-блока."""
    app = (applicability or "").strip()
    if app == "needs_clarification":
        return _ADVISORY_REASON_NEEDS_CLARIFICATION
    return _ADVISORY_REASON_POSSIBLE


def get_advisory_legacy_rule_requirements_v2(
    hs_code: str,
    description: str = "",
    as_of: date | None = None,
) -> list[dict[str, Any]]:
    """
    Потенциальные требования v2 (``possible`` / ``needs_clarification``) для UI.

    Не влияют на broker, ``missing_permit_types`` и ``status``.
    """
    _ = description
    ref = as_of or date.today()
    seen: set[tuple[str, str | None, str]] = set()
    rows: list[dict[str, Any]] = []
    with db.SessionLocal() as session:
        for rule, measure in _iter_matched_legacy_v2_rules(hs_code, as_of=ref, session=session):
            app = (rule.applicability or "").strip()
            if app not in ADVISORY_APPLICABILITIES:
                continue
            pt = (measure.permit_type or "").strip()
            if not pt:
                continue
            tr_raw = (measure.tr_ts_act_code or "").strip()
            tr_norm: str | None = tr_raw if tr_raw else None
            dedup_key = (pt, tr_norm, app)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            payload = rule.description_match_json if isinstance(rule.description_match_json, dict) else {}
            legacy = payload.get("legacy_payload") if isinstance(payload.get("legacy_payload"), dict) else {}
            rule_name = str(legacy.get("rule_name") or measure.title or "").strip()
            exception_note = str(legacy.get("exception_note") or "").strip()

            item: dict[str, Any] = {
                "permit_type": pt,
                "tr_ts": tr_norm,
                "applicability": app,
                "source": RULES_SOURCE_KIND,
                "used_for_missing_check": False,
                "requires_manual_review": bool(rule.requires_manual_review),
                "hs_prefix": rule.hs_code or None,
                "rule_name": rule_name[:200] if rule_name else None,
                "reason": advisory_reason_for_applicability(app),
            }
            if exception_note:
                item["note"] = exception_note[:500]
            rows.append(item)

    rows.sort(key=lambda r: (r.get("permit_type") or "", r.get("tr_ts") or "", r.get("applicability") or ""))
    return rows


def merge_v2_legacy_rules_into_broker(
    broker_rows: list[dict[str, Any]],
    v2_rule_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Добавляет v2 rule rows после существующих broker entries; дедуп по ``(permit_type, tr_ts)``.
    """
    seen: set[tuple[str, str | None]] = {
        (str(r.get("permit_type") or ""), r.get("tr_ts")) for r in broker_rows
    }
    out = [dict(r) for r in broker_rows]
    for r in v2_rule_rows:
        key = (str(r.get("permit_type") or ""), r.get("tr_ts"))
        if not key[0] or key in seen:
            continue
        seen.add(key)
        out.append(dict(r))
    return out


def _parse_csv_field(raw: str | None) -> list[str]:
    return [x.strip() for x in (raw or "").split(",") if x.strip()]


def permit_type_to_measure_kind(permit_type: str) -> str:
    """Маппинг permit_type → measure_kind для v2."""
    pt = (permit_type or "").strip()
    if pt in ("СС", "ДС"):
        return "technical_regulation"
    if pt == "СГР":
        return "sgr"
    if pt == "ЛЗ":
        return "license"
    if pt == "РУ":
        return "registration"
    if pt == "ВС":
        return "vet"
    if pt == "ФСС":
        return "phyto"
    if pt == "НФ":
        return "notification"
    if pt == "КВ":
        return "other"
    return "other"


def _legacy_rules_measure_import_key(measure_kind: str, permit_type: str, tr_ts_act_code: str) -> str:
    """Одна мера на (measure_kind, permit_type, tr_ts) — общая для всех legacy-правил с той же парой."""
    return f"{RULES_SOURCE_KIND}|{measure_kind}|{permit_type}|{tr_ts_act_code or ''}"


def _legacy_rules_rule_import_key(
    legacy_rule_id: int,
    permit_type: str,
    tr_ts_act_code: str,
    hs_prefix: str,
) -> str:
    return f"{RULES_SOURCE_KIND}|rule:{legacy_rule_id}|{permit_type}|{tr_ts_act_code or ''}|{hs_prefix}"


def _legacy_rule_payload_json(
    *,
    legacy_rule_id: int,
    rule_name: str,
    exception_note: str,
    tr_ts_edition: str,
    source_url: str,
    source_revision: str,
) -> dict[str, Any]:
    return {
        "legacy_payload": {
            "legacy_rule_id": legacy_rule_id,
            "rule_name": rule_name,
            "exception_note": exception_note,
            "tr_ts_edition": tr_ts_edition,
            "source_url": source_url,
            "source_revision": source_revision,
        }
    }


def _parse_legacy_rule_dates(
    valid_from: str | None,
    valid_to: str | None,
) -> tuple[date | None, date | None, bool]:
    """Возвращает (valid_from, valid_to, dates_valid)."""
    lo_kind, lo = _parse_non_tariff_rule_date(valid_from)
    hi_kind, hi = _parse_non_tariff_rule_date(valid_to)
    if lo_kind == "invalid" or hi_kind == "invalid":
        return None, None, False
    return lo, hi, True


def _measure_title(permit_type: str, tr_ts_act_code: str) -> str:
    tr = tr_ts_act_code or "—"
    return f"{permit_type} / ТР {tr} (legacy non_tariff_rules)"[:512]


def _measure_short_description(permit_type: str, tr_ts_act_code: str) -> str:
    return json.dumps(
        {
            "permit_type": permit_type,
            "tr_ts_act_code": tr_ts_act_code,
            "source": RULES_SOURCE_REF_PREFIX,
        },
        ensure_ascii=False,
    )


def _expand_legacy_rule_pairs(rule: NonTariffRule) -> list[tuple[str, str]] | None:
    """Декартово произведение required_permits × tr_ts; ``None`` если permits пуст."""
    permits = _parse_csv_field(rule.required_permits)
    if not permits:
        return None
    trs = _parse_csv_field(rule.tr_ts)
    if not trs:
        trs = [""]
    return [(p, t) for p in permits for t in trs]


def import_legacy_non_tariff_rules_to_ntm_v2(
    session: Session | None = None,
    *,
    as_of: date | None = None,
) -> dict[str, Any]:
    """
    Импортирует все строки ``non_tariff_rules`` в v2 (идемпотентно).

    ``as_of`` в отчёте не фильтрует импорт — все правила переносятся; даты сохраняются на rule.
    """
    _ = as_of
    close_session = False
    if session is None:
        session = db.SessionLocal()
        close_session = True
    now = utc_now_naive()
    measures_created = 0
    measures_skipped = 0
    rules_created = 0
    rules_skipped = 0
    rules_applicability_updated = 0
    legacy_rules_processed = 0
    legacy_rules_skipped_no_permits = 0
    legacy_rules_with_invalid_dates = 0
    pairs_created = 0

    try:
        measure_by_key: dict[str, NtmMeasureV2] = {
            m.import_key: m
            for m in session.scalars(
                select(NtmMeasureV2).where(NtmMeasureV2.source_kind == RULES_SOURCE_KIND)
            ).all()
        }

        legacy_rows = session.scalars(select(NonTariffRule).order_by(NonTariffRule.id)).all()

        for rule in legacy_rows:
            legacy_rules_processed += 1
            pairs = _expand_legacy_rule_pairs(rule)
            if pairs is None:
                legacy_rules_skipped_no_permits += 1
                continue

            vf, vt, dates_valid = _parse_legacy_rule_dates(rule.valid_from, rule.valid_to)
            if not dates_valid:
                legacy_rules_with_invalid_dates += 1

            hs_prefix = normalize_hs_code(rule.hs_prefix)
            payload = _legacy_rule_payload_json(
                legacy_rule_id=rule.id,
                rule_name=rule.name or "",
                exception_note=rule.exception_note or "",
                tr_ts_edition=rule.tr_ts_edition or "",
                source_url=rule.source_url or "",
                source_revision=rule.source_revision or "",
            )

            for permit_type, tr_ts in pairs:
                mk = permit_type_to_measure_kind(permit_type)
                tr_norm = tr_ts.strip()
                mik = _legacy_rules_measure_import_key(mk, permit_type, tr_norm)
                if mik not in measure_by_key:
                    measure = NtmMeasureV2(
                        measure_kind=mk,
                        permit_type=permit_type,
                        title=_measure_title(permit_type, tr_norm),
                        short_description=_measure_short_description(permit_type, tr_norm),
                        tr_ts_act_code=tr_norm,
                        regulatory_document_id=None,
                        valid_from=None,
                        valid_to=None,
                        status="active",
                        source_kind=RULES_SOURCE_KIND,
                        source_ref=f"{RULES_SOURCE_REF_PREFIX}:id:{rule.id}",
                        import_key=mik,
                        created_at=now,
                        updated_at=now,
                    )
                    session.add(measure)
                    session.flush()
                    measure_by_key[mik] = measure
                    measures_created += 1
                else:
                    measures_skipped += 1
                    measure = measure_by_key[mik]

                rk = _legacy_rules_rule_import_key(rule.id, permit_type, tr_norm, hs_prefix)
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
                            hs_code=hs_prefix,
                            excluded_hs_json=None,
                            description_match_json=payload,
                            applicability=LEGACY_RULES_IMPORT_APPLICABILITY,
                            requires_manual_review=True,
                            priority=int(rule.priority or 0),
                            valid_from=vf,
                            valid_to=vt,
                            source_kind=RULES_SOURCE_KIND,
                            source_ref=f"{RULES_SOURCE_REF_PREFIX}:rule_id:{rule.id}",
                            rule_import_key=rk,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                    rules_created += 1
                    pairs_created += 1
                else:
                    existing.measure_id = measure.id
                    existing.priority = int(rule.priority or 0)
                    existing.valid_from = vf
                    existing.valid_to = vt
                    existing.description_match_json = payload
                    if existing.applicability != LEGACY_RULES_IMPORT_APPLICABILITY:
                        existing.applicability = LEGACY_RULES_IMPORT_APPLICABILITY
                        rules_applicability_updated += 1
                    existing.requires_manual_review = True
                    existing.updated_at = now
                    rules_skipped += 1

        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        if close_session:
            session.close()

    return {
        "legacy_rules_processed": legacy_rules_processed,
        "legacy_rules_skipped_no_permits": legacy_rules_skipped_no_permits,
        "legacy_rules_with_invalid_dates": legacy_rules_with_invalid_dates,
        "measures_created": measures_created,
        "measures_skipped_duplicates": measures_skipped,
        "rules_created": rules_created,
        "rules_skipped_duplicates": rules_skipped,
        "rules_applicability_updated": rules_applicability_updated,
        "import_applicability": LEGACY_RULES_IMPORT_APPLICABILITY,
        "pairs_materialized": pairs_created,
    }


def _legacy_keys_for_hs(hs_code: str, *, as_of: date | None) -> set[str]:
    from .normative_store import find_non_tariff_rules_for_hs

    keys: set[str] = set()
    for rule in find_non_tariff_rules_for_hs(hs_code, as_of=as_of):
        permits = rule.get("required_permits") or []
        trs = rule.get("tr_ts") or []
        if not permits:
            continue
        if not trs:
            trs = [""]
        for p in permits:
            for t in trs:
                keys.add(f"{p}|{t or ''}")
    return keys


def _v2_legacy_rules_keys_for_hs(
    hs_code: str,
    *,
    as_of: date | None,
    session: Session,
) -> set[str]:
    norm = normalize_hs_code(hs_code)
    if not norm:
        return set()
    ref = as_of or date.today()

    stmt = (
        select(NtmApplicabilityRuleV2)
        .join(NtmMeasureV2, NtmApplicabilityRuleV2.measure_id == NtmMeasureV2.id)
        .where(
            NtmApplicabilityRuleV2.source_kind == RULES_SOURCE_KIND,
            NtmMeasureV2.source_kind == RULES_SOURCE_KIND,
        )
    )
    keys: set[str] = set()
    for rule in session.scalars(stmt).unique().all():
        m = rule.measure
        if not match_hs_prefix(norm, rule.hs_code):
            continue
        vf_s = rule.valid_from.isoformat() if rule.valid_from else ""
        vt_s = rule.valid_to.isoformat() if rule.valid_to else ""
        payload = rule.description_match_json if isinstance(rule.description_match_json, dict) else {}
        rule_name = str((payload.get("legacy_payload") or {}).get("rule_name", ""))
        if not _non_tariff_rule_active_on(
            vf_s,
            vt_s,
            ref,
            rule_id=rule.id,
            rule_name=rule_name,
            hs_prefix=rule.hs_code,
        ):
            continue
        keys.add(f"{m.permit_type}|{m.tr_ts_act_code or ''}")
    return keys


async def compare_non_tariff_check_rules_enforcement(
    hs_code: str,
    description: str = "",
    permits: list[dict[str, str]] | None = None,
    country: str | None = None,
    *,
    skip_registry_verify: bool = True,
) -> dict[str, Any]:
    """
    Сравнение ``check_position_non_tariff`` без и с enforcement v2 rules (без смены глобального env).
    """
    from .non_tariff_service import check_position_non_tariff

    permit_list = permits if permits is not None else []
    baseline = await check_position_non_tariff(
        hs_code=hs_code,
        description=description,
        country=country,
        permits=permit_list,
        skip_registry_verify=skip_registry_verify,
        rules_enforcement_enabled=False,
    )
    enforced = await check_position_non_tariff(
        hs_code=hs_code,
        description=description,
        country=country,
        permits=permit_list,
        skip_registry_verify=skip_registry_verify,
        rules_enforcement_enabled=True,
    )
    base_types = set(baseline.get("required_permit_types") or [])
    enf_types = set(enforced.get("required_permit_types") or [])
    base_missing = set(baseline.get("missing_permit_types") or [])
    enf_missing = set(enforced.get("missing_permit_types") or [])
    return {
        "hs_code": normalize_hs_code(hs_code),
        "baseline_required_permit_types": sorted(base_types),
        "enforced_required_permit_types": sorted(enf_types),
        "added_permit_types": sorted(enf_types - base_types),
        "removed_permit_types": sorted(base_types - enf_types),
        "baseline_missing_permit_types": sorted(base_missing),
        "enforced_missing_permit_types": sorted(enf_missing),
        "status_before": baseline.get("status"),
        "status_after": enforced.get("status"),
        "changed": (
            base_types != enf_types
            or base_missing != enf_missing
            or baseline.get("status") != enforced.get("status")
        ),
    }


def compare_legacy_non_tariff_rules_vs_ntm_v2(
    hs_code: str,
    *,
    as_of: date | None = None,
) -> dict[str, Any]:
    """
    Shadow: пары ``permit_type|tr_ts`` для legacy ``find_non_tariff_rules_for_hs`` vs v2
    (только ``source_kind=legacy_non_tariff_rules``).
    """
    with db.SessionLocal() as session:
        legacy_keys = _legacy_keys_for_hs(hs_code, as_of=as_of)
        v2_keys = _v2_legacy_rules_keys_for_hs(hs_code, as_of=as_of, session=session)
    return {
        "hs_code": normalize_hs_code(hs_code),
        "as_of": (as_of or date.today()).isoformat(),
        "legacy_only": sorted(legacy_keys - v2_keys),
        "v2_only": sorted(v2_keys - legacy_keys),
        "overlap": sorted(legacy_keys & v2_keys),
        "is_full_match": legacy_keys == v2_keys,
    }
