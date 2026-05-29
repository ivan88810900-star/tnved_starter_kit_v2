"""Нормализация и readiness-отчёт платёжных источников (диагностика, без смены расчёта)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import func, or_

from ..db import SessionLocal
from ..models.core import GeoSpecialDuty, HsRate, SourceStatus
from ..models.tnved import Commodity, HsDutyRule, SpecialDuty, VatPreference
from ..schemas.payment_data_normalization import (
    NormalizedSourceRef,
    PaymentDataNormalizationResponse,
    PaymentDomainNormalization,
    PaymentNormalizationStatus,
)
from .payment_data_coverage import (
    _EXPECTED_HS_RATES_MIN,
    _full_tnved_duty_coverage,
    _lookup_source_status,
    _registry_label,
    _source_configured,
    _TRADE_REMEDY_OFFICIAL_SOURCE_IDS,
    diagnose_duty_rates,
    diagnose_excise,
    diagnose_vat_rates,
)
from .regulatory_source_registry import AUTHORITY_LEVEL_LABELS, get_registry_entry

_BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
_SEED_REVISIONS = frozenset({"seed", "", "unknown", "fallback"})
_INVALID_EEC_REVISIONS = frozenset({"unavailable", "seed", "unknown", "fallback", "partial"})

_STATUS_RANK: dict[str, int] = {
    "missing": 0,
    "not_configured": 1,
    "stale": 2,
    "partial": 3,
    "manual_review_required": 4,
    "present": 5,
    "not_applicable": 6,
}


def _utc_now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def _worst_status(*statuses: PaymentNormalizationStatus) -> PaymentNormalizationStatus:
    if not statuses:
        return "missing"
    return min(statuses, key=lambda s: _STATUS_RANK.get(s, 0))


def _eec_proven() -> tuple[bool, str | None]:
    st = _lookup_source_status("EEC_ETT")
    if st is None:
        return False, None
    revision = (st.revision or "").strip().lower()
    if st.is_stale or revision in _INVALID_EEC_REVISIONS:
        return False, st.synced_at.isoformat() if st.synced_at else None
    return True, st.synced_at.isoformat() if st.synced_at else None


def _local_path_present(rel_path: str) -> bool:
    return (_BACKEND_ROOT / rel_path).exists()


def _source_ref(
    source_id: str,
    *,
    present: bool,
    record_count: int | None = None,
    mapped_hs_codes: int | None = None,
    extra_notes: list[str] | None = None,
) -> NormalizedSourceRef:
    entry = get_registry_entry(source_id)
    label = entry.title if entry else source_id
    authority = (
        AUTHORITY_LEVEL_LABELS.get(entry.authority_level, entry.authority_level) if entry else None
    )
    notes = list(extra_notes or [])
    if entry and entry.local_paths:
        for p in entry.local_paths:
            if _local_path_present(p):
                notes.append(f"fixture: {p}")
    return NormalizedSourceRef(
        id=source_id,
        label=label,
        present=present,
        record_count=record_count,
        mapped_hs_codes=mapped_hs_codes,
        authority_level=authority,
        notes=notes,
    )


def _hs_rate_stats(db) -> dict[str, int]:
    total = db.query(HsRate).count()
    seed = (
        db.query(HsRate)
        .filter(or_(HsRate.source_revision.in_(tuple(_SEED_REVISIONS)), HsRate.source_revision.is_(None)))
        .count()
    )
    excise = db.query(HsRate).filter(HsRate.excise_type.in_(("percent", "fixed"))).count()
    ad_flag = db.query(HsRate).filter(HsRate.has_antidumping.is_(True)).count()
    ad_typed = db.query(HsRate).filter(HsRate.antidumping_type.in_(("percent", "fixed"))).count()
    vat_non_default = db.query(HsRate).filter(HsRate.vat_import_rate != 22.0).count()
    vat_rule = db.query(HsRate).filter(HsRate.vat_rule != "none").count()
    return {
        "hs_rates_total": total,
        "hs_rates_seed": seed,
        "hs_rates_excise": excise,
        "hs_rates_antidumping_flag": ad_flag,
        "hs_rates_antidumping_typed": ad_typed,
        "hs_rates_vat_non_default": vat_non_default,
        "hs_rates_vat_rule": vat_rule,
    }


def normalize_import_duty() -> PaymentDomainNormalization:
    """Импортная пошлина: hs_rates + hs_duty_rules, консервативный present."""
    duty_cov = diagnose_duty_rates()
    eec_ok, eec_sync = _eec_proven()
    label, authority = _registry_label("eec_ett_tnved")

    with SessionLocal() as db:
        stats = _hs_rate_stats(db)
        duty_rules = db.query(HsDutyRule).count()
        covered, total, missing_samples = _full_tnved_duty_coverage(db)

    gaps = list(duty_cov.gaps)
    manual = True
    hs_total = stats["hs_rates_total"]
    seed_total = stats["hs_rates_seed"]

    if hs_total == 0:
        status: PaymentNormalizationStatus = "missing"
        gaps.append("Таблица hs_rates пуста.")
    elif not eec_ok:
        status = "stale" if duty_cov.status == "stale" else "partial"
        gaps.append("EEC_ETT не подтверждён как актуальный официальный контур.")
    elif hs_total < _EXPECTED_HS_RATES_MIN:
        status = "partial"
    elif total > 0 and covered < total:
        status = "partial"
    elif seed_total >= hs_total and hs_total > 0:
        status = "partial"
        gaps.append("Все строки hs_rates помечены seed/fallback — не claim official present.")
    elif duty_rules == 0 and seed_total > 0:
        status = "partial"
        gaps.append("hs_duty_rules пуст при seed hs_rates — ставки не верифицированы структурно.")
    elif total > 0 and covered == total and eec_ok and seed_total < hs_total:
        status = "present"
        manual = False
    elif duty_cov.status == "present" and eec_ok and seed_total < max(hs_total, 1):
        status = "present"
        manual = False
    else:
        status = "partial" if hs_total > 0 else "missing"

    sources = [
        _source_ref("eec_ett_tnved", present=eec_ok, record_count=hs_total, mapped_hs_codes=covered),
        NormalizedSourceRef(
            id="hs_duty_rules",
            label="hs_duty_rules (структурированные ставки)",
            present=duty_rules > 0,
            record_count=duty_rules,
            authority_level=authority,
        ),
    ]

    snapshot = {
        **stats,
        "hs_duty_rules": duty_rules,
        "catalog_codes_total": total,
        "catalog_codes_covered": covered,
        "eec_ett_proven": eec_ok,
        "eec_last_sync": eec_sync,
    }

    return PaymentDomainNormalization(
        domain="import_duty",
        coverage_status=status,
        authority_level=authority if eec_ok else "legacy_seed",
        sources=sources,
        record_count=hs_total,
        mapped_hs_codes=covered if total else hs_total,
        total_catalog_codes=total or None,
        missing_samples=missing_samples,
        known_gaps=gaps,
        manual_review_required=manual,
        normalized_snapshot=snapshot,
    )


def normalize_vat() -> PaymentDomainNormalization:
    """НДС: hs_rates + vat_preferences; seed-only → не present."""
    vat_cov = diagnose_vat_rates()
    label, authority = _registry_label("eec_ett_tnved")
    eec_ok, _ = _eec_proven()

    with SessionLocal() as db:
        stats = _hs_rate_stats(db)
        pref_count = db.query(VatPreference).count()
        pref_codes = db.query(func.count(func.distinct(VatPreference.hs_code_prefix))).scalar() or 0

    gaps = list(vat_cov.gaps)
    manual = True
    hs_total = stats["hs_rates_total"]
    has_prefs = pref_count > 0
    has_rules = stats["hs_rates_vat_rule"] > 0 or stats["hs_rates_vat_non_default"] > 0

    if hs_total == 0:
        status: PaymentNormalizationStatus = "missing"
    elif not has_prefs and not has_rules:
        status = "partial"
        gaps.append("Только базовый НДС 22% в hs_rates без vat_preferences/vat_rule.")
    elif not eec_ok:
        status = "partial"
        gaps.append("НДС-контур без подтверждённого EEC_ETT — консервативно partial.")
    elif has_prefs and eec_ok:
        status = "present"
        manual = False
    elif has_rules and eec_ok and stats["hs_rates_seed"] < hs_total:
        status = "present"
        manual = False
    else:
        status = "partial"

    sources = [
        _source_ref("eec_ett_tnved", present=hs_total > 0, record_count=hs_total),
        NormalizedSourceRef(
            id="vat_preferences",
            label="vat_preferences (льготный НДС)",
            present=has_prefs,
            record_count=pref_count,
            mapped_hs_codes=int(pref_codes),
            authority_level=authority,
        ),
    ]

    return PaymentDomainNormalization(
        domain="vat",
        coverage_status=status,
        authority_level=authority if status == "present" else "legacy_seed",
        sources=sources,
        record_count=hs_total,
        mapped_hs_codes=int(pref_codes) if has_prefs else stats["hs_rates_vat_rule"] + stats["hs_rates_vat_non_default"],
        known_gaps=gaps,
        manual_review_required=manual,
        normalized_snapshot={**stats, "vat_preferences": pref_count},
    )


def normalize_excise() -> PaymentDomainNormalization:
    """Акциз: без официального контура — never present."""
    excise_cov = diagnose_excise()
    with SessionLocal() as db:
        stats = _hs_rate_stats(db)

    status: PaymentNormalizationStatus
    if excise_cov.status == "not_configured":
        status = "manual_review_required"
    elif stats["hs_rates_excise"] == 0:
        status = "missing"
    else:
        status = "partial"

    gaps = list(excise_cov.gaps)
    if stats["hs_rates_seed"] >= stats["hs_rates_excise"] > 0:
        gaps.append("Акцизные поля только из seed — требуется верификация.")

    return PaymentDomainNormalization(
        domain="excise",
        coverage_status=status,
        authority_level=excise_cov.authority_level or "legacy_seed",
        sources=[
            NormalizedSourceRef(
                id="hs_rates.excise",
                label="hs_rates (excise_type / excise_value)",
                present=stats["hs_rates_excise"] > 0,
                record_count=stats["hs_rates_excise"],
                authority_level="legacy_seed",
                notes=["Официальный контур акциза не зарегистрирован в реестре."],
            )
        ],
        record_count=stats["hs_rates_excise"],
        known_gaps=gaps,
        manual_review_required=True,
        normalized_snapshot=stats,
    )


def normalize_anti_dumping() -> PaymentDomainNormalization:
    """Антидемпинг: special_duties + hs_rates flags; без official contour — never present."""
    configured, reg_label, authority = _source_configured(_TRADE_REMEDY_OFFICIAL_SOURCE_IDS)

    with SessionLocal() as db:
        special = db.query(SpecialDuty).count()
        special_prefixes = (
            db.query(func.count(func.distinct(SpecialDuty.hs_code_prefix))).scalar() or 0
        )
        geo_ad = (
            db.query(GeoSpecialDuty)
            .filter(GeoSpecialDuty.measure_type == "anti_dumping")
            .count()
        )
        stats = _hs_rate_stats(db)

    local_rows = special + geo_ad + stats["hs_rates_antidumping_flag"] + stats["hs_rates_antidumping_typed"]
    gaps: list[str] = []

    if local_rows == 0 and not configured:
        status: PaymentNormalizationStatus = "missing"
        gaps.append("Нет локальных строк антидемпинга и официальный контур не настроен.")
    elif not configured:
        status = "manual_review_required"
        gaps.append(
            "Есть локальные special_duties/geo/hs_rates, но официальный контур торговых мер "
            "не зарегистрирован — не claim present."
        )
    elif special == 0:
        status = "partial"
        gaps.append("special_duties пуст при настроенном контуре.")
    else:
        status = "partial"
        gaps.append("Контур настроен, но полнота антидемпинга не верифицирована в этом MVP.")

    sources = [
        NormalizedSourceRef(
            id="special_duties",
            label="special_duties",
            present=special > 0,
            record_count=special,
            mapped_hs_codes=int(special_prefixes),
            authority_level=authority or "legacy_seed",
        ),
        NormalizedSourceRef(
            id="hs_rates.antidumping",
            label="hs_rates (antidumping_*)",
            present=stats["hs_rates_antidumping_typed"] > 0 or stats["hs_rates_antidumping_flag"] > 0,
            record_count=stats["hs_rates_antidumping_typed"] + stats["hs_rates_antidumping_flag"],
            authority_level="legacy_seed",
        ),
        _source_ref(
            "geo_special_duties_embargo",
            present=geo_ad > 0,
            record_count=geo_ad,
            extra_notes=["measure_type=anti_dumping"],
        ),
    ]

    return PaymentDomainNormalization(
        domain="anti_dumping",
        coverage_status=status,
        authority_level=authority or "legacy_seed",
        sources=sources,
        record_count=local_rows,
        mapped_hs_codes=int(special_prefixes) if special else None,
        known_gaps=gaps,
        manual_review_required=True,
        normalized_snapshot={
            **stats,
            "special_duties": special,
            "geo_special_duties_anti_dumping": geo_ad,
            "official_contour_configured": configured,
            "registry_label": reg_label,
        },
    )


def normalize_special_protective() -> PaymentDomainNormalization | None:
    """Защитные пошлины — только при явных geo_special_duties increased_duty."""
    with SessionLocal() as db:
        geo_prot = (
            db.query(GeoSpecialDuty)
            .filter(GeoSpecialDuty.measure_type == "increased_duty")
            .count()
        )
        geo_embargo = (
            db.query(GeoSpecialDuty).filter(GeoSpecialDuty.measure_type == "embargo").count()
        )

    if geo_prot == 0 and geo_embargo == 0:
        return None

    entry = get_registry_entry("geo_special_duties_embargo")
    authority = AUTHORITY_LEVEL_LABELS.get(entry.authority_level, entry.authority_level) if entry else "legacy_seed"

    return PaymentDomainNormalization(
        domain="special_protective",
        coverage_status="partial",
        authority_level=authority,
        sources=[
            _source_ref(
                "geo_special_duties_embargo",
                present=True,
                record_count=geo_prot + geo_embargo,
            )
        ],
        record_count=geo_prot + geo_embargo,
        known_gaps=[
            "geo_special_duties — legacy_seed; не полный официальный перечень защитных мер.",
        ],
        manual_review_required=True,
        normalized_snapshot={
            "geo_increased_duty": geo_prot,
            "geo_embargo": geo_embargo,
        },
    )


def normalize_countervailing() -> PaymentDomainNormalization:
    """Компенсационные пошлины: в схеме БД не отделены от special_duties — not_applicable."""
    return PaymentDomainNormalization(
        domain="countervailing",
        coverage_status="not_applicable",
        authority_level=None,
        sources=[],
        known_gaps=[
            "В локальной схеме нет отдельного контура countervailing; "
            "special_duties не различает тип меры.",
        ],
        manual_review_required=False,
        normalized_snapshot={"reason": "no_dedicated_local_source"},
    )


def run_payment_data_normalization_report() -> dict[str, Any]:
    """
    Детерминированный readiness-отчёт по доменам платежей.

    Не меняет payment_engine; нормализует метаданные локальных таблиц.
    """
    generated_at = _utc_now_iso()
    domains: dict[str, PaymentDomainNormalization] = {
        "import_duty": normalize_import_duty(),
        "vat": normalize_vat(),
        "excise": normalize_excise(),
        "anti_dumping": normalize_anti_dumping(),
        "countervailing": normalize_countervailing(),
    }
    optional = normalize_special_protective()
    if optional is not None:
        domains["special_protective"] = optional

    core_statuses = [
        domains["import_duty"].coverage_status,
        domains["vat"].coverage_status,
        domains["excise"].coverage_status,
        domains["anti_dumping"].coverage_status,
    ]
    overall = _worst_status(*core_statuses)
    if overall == "present" and any(d.manual_review_required for d in domains.values()):
        overall = "manual_review_required"

    notes = [
        "Отчёт консервативен: seed/fallback/ambiguous не маркируются как official present.",
        "coverage из payment_data_coverage; домены разбиты для карточки ТН ВЭД.",
    ]

    response = PaymentDataNormalizationResponse(
        status="OK",
        generated_at=generated_at,
        overall_readiness=overall,
        domains={k: v for k, v in domains.items()},
        notes=notes,
    )
    return response.model_dump(mode="json")
