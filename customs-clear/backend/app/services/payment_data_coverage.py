"""Диагностика покрытия ТН ВЭД, тарифов, НДС, акциза, торговых мер и платёжных источников."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, or_

from ..db import SessionLocal
from ..models.core import ExchangeRate, GeoSpecialDuty, HsRate, SourceStatus, TnvedEntry
from ..models.tnved import Chapter, Commodity, HsDutyRule, Section, SpecialDuty, VatPreference
from ..schemas.payment_data_coverage import (
    CoverageDomainSummary,
    PaymentDataCoverageResponse,
    SmartPaymentsReadiness,
    TnvedTreeCoverage,
)
from .exchange_rates import FALLBACK, TRACKED
from .normative_store import list_sync_log
from .regulatory_source_registry import AUTHORITY_LEVEL_LABELS, get_registry_entry

# Минимальные пороги для partial vs present (не claim полноту при seed-only).
_EXPECTED_FULL_CODES_MIN = 1_000
_EXPECTED_HS_RATES_MIN = 100
_EXCHANGE_RATE_STALE_DAYS = 7

# Официальные контуры excise / trade remedies в реестре (пока нет dedicated excise source).
_EXCISE_SOURCE_IDS: frozenset[str] = frozenset()
_TRADE_REMEDY_OFFICIAL_SOURCE_IDS: frozenset[str] = frozenset(
    {
        # geo_special_duties — только legacy_seed; не считается полным official contour.
    }
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def _digits(code: str) -> str:
    return re.sub(r"\D", "", code or "")


def _status_rank(status: str) -> int:
    order = {
        "missing": 0,
        "parser_failed": 1,
        "not_configured": 2,
        "stale": 3,
        "partial": 4,
        "manual_review_required": 5,
        "present": 6,
    }
    return order.get(status, 0)


def _merge_status(*statuses: str) -> str:
    if not statuses:
        return "missing"
    return min(statuses, key=_status_rank)


def _lookup_source_status(code: str | None) -> SourceStatus | None:
    if not code:
        return None
    with SessionLocal() as db:
        return db.query(SourceStatus).filter(SourceStatus.source_code == code).first()


def _latest_sync_ok(code: str | None) -> str | None:
    if not code:
        return None
    rows = list_sync_log(source_code=code, limit=5)
    for row in rows:
        if (row.get("status") or "").upper() == "OK":
            return row.get("synced_at")
    return None


def _registry_label(source_id: str) -> tuple[str | None, str | None]:
    entry = get_registry_entry(source_id)
    if not entry:
        return None, None
    return entry.title, AUTHORITY_LEVEL_LABELS.get(entry.authority_level, entry.authority_level)


def _source_configured(
    source_ids: frozenset[str],
    *,
    require_official: bool = True,
) -> tuple[bool, str | None, str | None]:
    """Источник считается настроенным только при записи реестра и успешном sync/данных."""
    labels: list[str] = []
    authority: str | None = None
    any_configured = False
    for sid in sorted(source_ids):
        entry = get_registry_entry(sid)
        if not entry:
            continue
        if require_official and entry.authority_level not in (
            "official_binding",
            "official_reference",
            "registry_evidence",
        ):
            continue
        labels.append(entry.title)
        authority = AUTHORITY_LEVEL_LABELS.get(entry.authority_level, entry.authority_level)
        st = _lookup_source_status(entry.source_status_code)
        if st and not st.is_stale and (st.revision or "") not in ("unavailable", "seed", "unknown"):
            any_configured = True
    return any_configured, ", ".join(labels) if labels else None, authority


def _hs_rate_lookup_sets(db) -> frozenset[str]:
    """Объединённый набор hs_code/hs_prefix для проверки покрытия (как find_rate_for_hs)."""
    merged: set[str] = set()
    for hs_code, hs_prefix in db.query(HsRate.hs_code, HsRate.hs_prefix).all():
        if hs_code:
            merged.add(_digits(hs_code))
        if hs_prefix:
            merged.add(_digits(hs_prefix))
    return frozenset(merged)


def _code_covered_by_hs_rates(code: str, lookup: frozenset[str]) -> bool:
    c = _digits(code)
    if len(c) < 10:
        return False
    for length in (10, 8, 6, 4, 2):
        if len(c) >= length and c[:length] in lookup:
            return True
    return False


def _full_tnved_duty_coverage(db) -> tuple[int, int, list[str]]:
    """
    Полное покрытие 10-значных кодов каталога ставками hs_rates (точное + префикс 10→2).

    Returns (covered_count, total_count, missing_samples up to 5).
    """
    lookup = _hs_rate_lookup_sets(db)
    commodity_codes = [
        _digits(c)
        for (c,) in db.query(Commodity.code).filter(func.length(Commodity.code) >= 10).all()
        if _digits(c) and len(_digits(c)) >= 10
    ]
    if not commodity_codes:
        commodity_codes = [
            _digits(c)
            for (c,) in db.query(TnvedEntry.hs_code).filter(TnvedEntry.level >= 10).all()
            if _digits(c) and len(_digits(c)) >= 10
        ]
    unique = sorted(set(commodity_codes))
    if not unique:
        return 0, 0, []

    missing_samples: list[str] = []
    covered = 0
    for code in unique:
        if _code_covered_by_hs_rates(code, lookup):
            covered += 1
        elif len(missing_samples) < 5:
            missing_samples.append(code)
    return covered, len(unique), missing_samples


def _sample_missing_codes(limit: int = 5) -> list[str]:
    """Примеры кодов без hs_rates — только иллюстрация, не основание для status."""
    with SessionLocal() as db:
        _covered, _total, missing = _full_tnved_duty_coverage(db)
        return missing[:limit]


def diagnose_tnved_tree() -> TnvedTreeCoverage:
    with SessionLocal() as db:
        sections = db.query(Section).count()
        chapters = db.query(Chapter).count()
        commodities = db.query(Commodity).count()
        flat_entries = db.query(TnvedEntry).count()
        headings = db.query(TnvedEntry).filter(TnvedEntry.level == 4).count()
        subheadings = db.query(TnvedEntry).filter(TnvedEntry.level == 6).count()
        full_codes = db.query(TnvedEntry).filter(TnvedEntry.level >= 10).count()

    label, authority = _registry_label("eec_ett_tnved")
    eec = _lookup_source_status("EEC_ETT")
    gaps: list[str] = []
    if sections == 0:
        gaps.append("Каталог tnved_sections пуст.")
    if chapters == 0:
        gaps.append("Каталог tnved_chapters пуст.")
    if commodities == 0 and flat_entries == 0:
        gaps.append("Нет tnved_commodities и tnved_entries — справочник кодов не загружен.")
    if full_codes < _EXPECTED_FULL_CODES_MIN and commodities < _EXPECTED_FULL_CODES_MIN:
        gaps.append(
            f"Мало полных кодов (< {_EXPECTED_FULL_CODES_MIN}): flat={full_codes}, catalog={commodities}."
        )

    if flat_entries == 0 and commodities == 0:
        status = "missing"
    elif eec and eec.is_stale:
        status = "stale"
    elif full_codes >= _EXPECTED_FULL_CODES_MIN or commodities >= _EXPECTED_FULL_CODES_MIN:
        status = "present"
    else:
        status = "partial"

    manual = status in {"missing", "partial", "stale"}
    return TnvedTreeCoverage(
        status=status,
        sections=sections,
        chapters=chapters,
        headings=headings,
        subheadings=subheadings,
        full_codes=full_codes,
        catalog_commodities=commodities,
        flat_entries=flat_entries,
        manual_review_required=manual,
        source_label=label,
        gaps=gaps,
        missing_samples=[],
    )


def diagnose_duty_rates() -> CoverageDomainSummary:
    with SessionLocal() as db:
        hs_count = db.query(HsRate).count()
        duty_rules = db.query(HsDutyRule).count()
        covered_codes, total_codes, missing_samples = _full_tnved_duty_coverage(db)

    label, authority = _registry_label("eec_ett_tnved")
    eec = _lookup_source_status("EEC_ETT")
    last_ok = _latest_sync_ok("EEC_ETT")
    gaps: list[str] = []

    if hs_count == 0:
        status = "missing"
        gaps.append("Таблица hs_rates пуста — пошлины не импортированы.")
    elif eec and (eec.is_stale or (eec.revision or "") in ("unavailable",)):
        status = "stale"
        gaps.append("Источник EEC_ETT устарел или недоступен.")
    elif hs_count < _EXPECTED_HS_RATES_MIN:
        status = "partial"
        gaps.append(f"Мало строк hs_rates ({hs_count} < {_EXPECTED_HS_RATES_MIN}).")
    elif total_codes > 0 and covered_codes < total_codes:
        status = "partial"
        gaps.append(
            f"Покрыто hs_rates: {covered_codes}/{total_codes} полных кодов каталога "
            f"(без ставки: {total_codes - covered_codes})."
        )
    elif total_codes == 0 and hs_count < _EXPECTED_HS_RATES_MIN:
        status = "partial"
        gaps.append("Нет 10-значных кодов в каталоге для проверки полноты покрытия.")
    else:
        status = "present"

    if duty_rules == 0:
        gaps.append("hs_duty_rules пуст — структурированные ставки не импортированы.")

    manual = status in {"missing", "partial", "stale"}
    return CoverageDomainSummary(
        status=status,
        count=hs_count,
        covered_codes=covered_codes if total_codes else hs_count,
        total_codes=total_codes if total_codes else None,
        manual_review_required=manual,
        source_label=label or "hs_rates / hs_duty_rules (ЕТТ ЕАЭС)",
        authority_level=authority,
        last_successful_sync_at=last_ok or (eec.synced_at.isoformat() if eec and eec.synced_at else None),
        gaps=gaps,
        missing_samples=missing_samples,
        notes=[f"hs_duty_rules: {duty_rules}"] if duty_rules else [],
    )


def diagnose_vat_rates() -> CoverageDomainSummary:
    with SessionLocal() as db:
        hs_count = db.query(HsRate).count()
        pref_count = db.query(VatPreference).count()
        reduced = db.query(HsRate).filter(HsRate.vat_import_rate != 22.0).count()
        with_rule = db.query(HsRate).filter(HsRate.vat_rule != "none").count()

    label, authority = _registry_label("eec_ett_tnved")
    gaps: list[str] = []

    if hs_count == 0:
        status = "missing"
        gaps.append("Нет hs_rates — базовые ставки НДС не определены.")
    elif pref_count == 0 and with_rule == 0:
        status = "partial"
        gaps.append("Нет vat_preferences и vat_rule в hs_rates — льготный НДС не импортирован.")
    else:
        status = "present" if pref_count > 0 or with_rule > 0 else "partial"

    manual = status != "present"
    return CoverageDomainSummary(
        status=status,
        count=hs_count,
        covered_codes=with_rule + reduced,
        manual_review_required=manual,
        source_label=label or "hs_rates + vat_preferences",
        authority_level=authority,
        gaps=gaps,
        notes=[f"vat_preferences: {pref_count}", f"hs_rates с нестандартным НДС: {reduced + with_rule}"],
    )


def diagnose_customs_fees() -> CoverageDomainSummary:
    return CoverageDomainSummary(
        status="present",
        count=8,
        manual_review_required=False,
        source_label="customs_fees.py (шкала РФ 2026)",
        authority_level="official_binding",
        gaps=[],
        notes=["Расписание таможенных сборов зашито в код; не требует импорта таблицы."],
    )


def diagnose_excise() -> CoverageDomainSummary:
    configured, label, authority = _source_configured(_EXCISE_SOURCE_IDS)
    with SessionLocal() as db:
        hs_count = db.query(HsRate).count()
        excise_rows = (
            db.query(HsRate)
            .filter(HsRate.excise_type.in_(("percent", "fixed")))
            .count()
        )
        seed_only = (
            db.query(HsRate)
            .filter(
                HsRate.excise_type.in_(("percent", "fixed")),
                or_(HsRate.source_revision == "seed", HsRate.source_revision == ""),
            )
            .count()
        )

    gaps: list[str] = []
    if not configured:
        if excise_rows > 0:
            status = "partial"
            gaps.append(
                "В hs_rates есть акцизные поля, но официальный контур акциза не зарегистрирован — "
                "не считается полным покрытием."
            )
        else:
            status = "not_configured"
            gaps.append("Официальный контур акцизных ставок не настроен/не синхронизирован.")
    elif hs_count == 0:
        status = "missing"
        gaps.append("hs_rates пуст — акцизные поля недоступны.")
    elif excise_rows == 0:
        status = "partial"
        gaps.append("В hs_rates нет строк с excise_type percent/fixed.")
    elif seed_only == excise_rows:
        status = "partial"
        gaps.append("Акцизные данные только из seed — требуется верификация источника.")
    else:
        status = "partial"

    manual = True
    return CoverageDomainSummary(
        status=status,
        count=excise_rows,
        manual_review_required=manual,
        source_label=label or "не настроен",
        authority_level=authority,
        gaps=gaps,
        notes=[
            "Smart Payments не трактует отсутствие акциза как 0 без данных hs_rates.",
            f"Строк hs_rates с акцизом: {excise_rows}.",
        ],
    )


def diagnose_trade_remedies() -> CoverageDomainSummary:
    configured, label, authority = _source_configured(_TRADE_REMEDY_OFFICIAL_SOURCE_IDS)
    with SessionLocal() as db:
        special = db.query(SpecialDuty).count()
        geo = db.query(GeoSpecialDuty).count()
        ad_hs = db.query(HsRate).filter(HsRate.has_antidumping.is_(True)).count()
        ad_fields = (
            db.query(HsRate)
            .filter(HsRate.antidumping_type.in_(("percent", "fixed")))
            .count()
        )

    gaps: list[str] = []
    total_rows = special + geo + ad_hs

    if not configured:
        if total_rows == 0:
            status = "not_configured"
            gaps.append("Нет настроенных официальных источников торговых мер и локальные таблицы пусты.")
        else:
            status = "partial"
            gaps.append(
                "Есть локальные строки special_duties/geo_special_duties/hs_rates, "
                "но официальный контур торговых мер не зарегистрирован — не считается полным покрытием."
            )
    elif special == 0:
        status = "partial"
        gaps.append("special_duties пуст — защитные/компенсационные пошлины не загружены.")
    else:
        status = "present"

    manual = True
    notes = [
        f"special_duties: {special}",
        f"geo_special_duties: {geo}",
        f"hs_rates has_antidumping: {ad_hs}",
        f"hs_rates antidumping_type percent/fixed: {ad_fields}",
    ]
    if geo > 0:
        notes.append("geo_special_duties — legacy_seed; не claim полного официального покрытия.")

    return CoverageDomainSummary(
        status=status,
        count=total_rows,
        manual_review_required=manual,
        source_label=label or "special_duties / geo_special_duties / hs_rates",
        authority_level=authority,
        gaps=gaps,
        notes=notes,
    )


_CBR_SYNC_SOURCE_CODES: tuple[str, ...] = ("CBR", "CBRF", "EXCHANGE_RATES", "cbr_exchange_rates")


def _rates_match_fallback_constants(rows: list[ExchangeRate]) -> bool:
    """True, если все TRACKED-валюты совпадают с константами FALLBACK (типичный offline upsert)."""
    by_code = {r.currency_code: float(r.rate) for r in rows if r.currency_code in TRACKED}
    if len(by_code) < len(TRACKED):
        return False
    return all(abs(by_code[code] - FALLBACK[code]) <= 0.001 for code in TRACKED)


def _cbr_sync_proven() -> tuple[bool, str | None]:
    """Доказательство успешного CBR sync — только sync-log / source_status, не updated_at."""
    for code in _CBR_SYNC_SOURCE_CODES:
        synced_at = _latest_sync_ok(code)
        if synced_at:
            return True, synced_at
    for code in _CBR_SYNC_SOURCE_CODES:
        st = _lookup_source_status(code)
        if st and not st.is_stale and (st.revision or "") not in (
            "unavailable",
            "seed",
            "unknown",
            "fallback",
        ):
            if st.synced_at:
                return True, st.synced_at.isoformat()
    return False, None


def diagnose_exchange_rates() -> CoverageDomainSummary:
    with SessionLocal() as db:
        rows = db.query(ExchangeRate).order_by(ExchangeRate.updated_at.desc()).all()

    tracked_present = {r.currency_code for r in rows if r.currency_code in TRACKED}
    latest_at: datetime | None = max((r.updated_at for r in rows if r.updated_at), default=None)
    gaps: list[str] = []
    notes: list[str] = []
    cbr_proven, cbr_sync_at = _cbr_sync_proven()
    matches_fallback = _rates_match_fallback_constants(rows)

    if not rows:
        status = "missing"
        gaps.append("Таблица exchange_rates пуста — используется только FALLBACK из кода.")
        authority = "official_reference"
    elif len(tracked_present) < len(TRACKED):
        status = "partial"
        missing_ccy = sorted(set(TRACKED) - tracked_present)
        gaps.append(f"Нет курсов для: {', '.join(missing_ccy)}.")
        authority = "official_reference"
    elif latest_at and latest_at < datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
        days=_EXCHANGE_RATE_STALE_DAYS
    ):
        status = "stale"
        gaps.append(f"Последнее обновление старше {_EXCHANGE_RATE_STALE_DAYS} дней.")
        authority = "official_reference"
    elif matches_fallback:
        status = "partial"
        gaps.append(
            "Курсы в exchange_rates совпадают с константами FALLBACK — "
            "нет доказательства успешного CBR sync."
        )
        authority = "legacy_seed"
        notes.append("Вероятный источник: fallback/local constant, не live ЦБ.")
    elif not cbr_proven:
        status = "manual_review_required"
        gaps.append(
            "Нельзя подтвердить, что exchange_rates загружены из успешного CBR sync "
            "(в модели нет поля source; нет записи sync-log/source_status)."
        )
        authority = "official_reference"
        notes.append("Свежие строки в БД ≠ официальное покрытие ЦБ без provenance.")
    else:
        status = "present"
        authority = "official_binding"

    manual = status in {"missing", "partial", "stale", "manual_review_required"}
    return CoverageDomainSummary(
        status=status,
        count=len(rows),
        manual_review_required=manual,
        source_label="ЦБ РФ (CBR XML) — требуется подтверждённый sync",
        authority_level=authority,
        last_successful_sync_at=cbr_sync_at or (latest_at.isoformat() if latest_at else None),
        gaps=gaps,
        notes=notes or ([f"FALLBACK в коде: {', '.join(sorted(FALLBACK))}"] if not rows else []),
    )


def _build_smart_payments_readiness(
    *,
    duty: CoverageDomainSummary,
    vat: CoverageDomainSummary,
    fees: CoverageDomainSummary,
    excise: CoverageDomainSummary,
    trade: CoverageDomainSummary,
    fx: CoverageDomainSummary,
) -> SmartPaymentsReadiness:
    blocking: list[str] = []
    manual_domains: list[str] = []

    for name, domain in (
        ("duty_rates", duty),
        ("vat_rates", vat),
        ("customs_fees", fees),
        ("excise", excise),
        ("trade_remedies", trade),
        ("exchange_rates", fx),
    ):
        if domain.status in {"missing", "not_configured", "parser_failed"}:
            blocking.append(name)
        elif domain.manual_review_required or domain.status in {"partial", "stale", "manual_review_required"}:
            manual_domains.append(name)

    can_final = not blocking and not manual_domains
    can_estimate = duty.status not in {"missing"} and fees.status == "present"

    if can_final:
        sp_status = "present"
    elif can_estimate:
        sp_status = "partial"
    elif blocking:
        sp_status = "not_configured" if "excise" in blocking or "trade_remedies" in blocking else "missing"
    else:
        sp_status = "manual_review_required"

    notes: list[str] = []
    if not can_final:
        notes.append(
            "Итог total_payable_rub в Smart Payments = null, если excise/special_duty/antidumping "
            "в статусе unknown / not_configured / manual_review_required."
        )
    if excise.status == "not_configured":
        notes.append("Акциз: источник не настроен — только оценка с ручной проверкой.")
    if trade.status == "not_configured":
        notes.append("Торговые меры: special_duties не импортированы — спецпошлины блокируют финальный итог.")

    return SmartPaymentsReadiness(
        status=sp_status,
        can_produce_final_total=can_final,
        can_produce_estimate=can_estimate,
        blocking_domains=blocking,
        manual_review_domains=manual_domains,
        notes=notes,
    )


def _build_next_actions(
    tnved: TnvedTreeCoverage,
    duty: CoverageDomainSummary,
    vat: CoverageDomainSummary,
    excise: CoverageDomainSummary,
    trade: CoverageDomainSummary,
    fx: CoverageDomainSummary,
) -> list[str]:
    actions: list[str] = []
    if tnved.status in {"missing", "partial", "stale"}:
        actions.append("Загрузить справочник ТН ВЭД: POST /api/sources/import/bundle или POST /api/sources/sync.")
    if duty.status in {"missing", "partial", "stale"}:
        actions.append("Синхронизировать ЕТТ/ставки: POST /api/sources/sync (EEC_ETT) или импорт hs_rates.")
    if vat.status in {"missing", "partial"}:
        actions.append("Импортировать льготный НДС: tamdoc targeted sync или vat_preferences через bundle.")
    if excise.status == "not_configured":
        actions.append("Настроить контур акцизных ставок (официальный источник) — сейчас только seed/partial hs_rates.")
    if trade.status in {"not_configured", "partial"}:
        actions.append("Импорт торговых мер: scripts/import_special_duties.py или POST /api/sources/sync/tamdoc/targeted.")
    if fx.status in {"missing", "stale", "partial"}:
        actions.append("Обновить курсы ЦБ: GET /api/currency/rates или scheduled sync exchange_rates.")
    return actions


def run_payment_data_coverage_report() -> dict[str, Any]:
    """
    Детерминированный отчёт покрытия платёжных и тарифных данных.

    Не меняет расчётную семантику; только диагностика для data-trust.
    """
    generated_at = _utc_now_iso()
    tnved = diagnose_tnved_tree()
    duty = diagnose_duty_rates()
    vat = diagnose_vat_rates()
    fees = diagnose_customs_fees()
    excise = diagnose_excise()
    trade = diagnose_trade_remedies()
    fx = diagnose_exchange_rates()
    smart = _build_smart_payments_readiness(
        duty=duty,
        vat=vat,
        fees=fees,
        excise=excise,
        trade=trade,
        fx=fx,
    )

    response = PaymentDataCoverageResponse(
        status="OK",
        generated_at=generated_at,
        summary={
            "tnved_entries": tnved,
            "duty_rates": duty,
            "vat_rates": vat,
            "customs_fees": fees,
            "excise": excise,
            "trade_remedies": trade,
            "exchange_rates": fx,
            "smart_payments": smart,
        },
        smart_payments=smart,
        next_actions=_build_next_actions(tnved, duty, vat, excise, trade, fx),
    )
    return response.model_dump(mode="json")
