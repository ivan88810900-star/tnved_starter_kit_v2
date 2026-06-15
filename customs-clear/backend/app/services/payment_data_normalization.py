"""Нормализация и readiness-отчёт платёжных источников (диагностика, без смены расчёта)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import func

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
from .payment_source_registry import get_payment_source_entry

_BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
# Exact seed/fallback/ambiguous tokens (для legacy совместимости и явных значений).
_SEED_REVISIONS = frozenset(
    {"seed", "", "unknown", "ambiguous", "legacy", "legacy_seed", "fallback"}
)
# Префиксы версионированных seed/fallback ревизий: seed-2026-03, fallback:cbrf, legacy-… и т.п.
_SEED_REVISION_PREFIXES = ("seed-", "seed:", "seed_", "fallback-", "fallback:", "fallback_", "legacy-", "legacy_")


def _is_seed_or_fallback_revision(revision: str | None) -> bool:
    """Seed/fallback/legacy/ambiguous detection по pattern/prefix, не только exact match."""
    rev = (revision or "").strip().lower()
    if rev in _SEED_REVISIONS:
        return True
    return any(rev.startswith(p) for p in _SEED_REVISION_PREFIXES)

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
    from .payment_revision_utils import is_official_eec_ett_revision

    st = _lookup_source_status("EEC_ETT")
    if st is None:
        return False, None
    synced = st.synced_at.isoformat() if st.synced_at else None
    # Official EEC/ETT provenance: не stale и revision строго versioned EEC/ETT.
    # Это отсекает seed/fallback/legacy/demo/test/example и arbitrary non-versioned
    # (local-copy/manual/foo/official/prod) — единый strict rule с import-duty ingestion.
    if st.is_stale or not is_official_eec_ett_revision(st.revision):
        return False, synced
    return True, synced


def _vat_proven() -> tuple[bool, str | None]:
    """Official VAT contour proof через SourceStatus EEC_VAT (не duty source_revision)."""
    from .payment_revision_utils import is_official_vat_revision

    st = _lookup_source_status("EEC_VAT")
    if st is None:
        return False, None
    synced = st.synced_at.isoformat() if st.synced_at else None
    if st.is_stale or not is_official_vat_revision(st.revision):
        return False, synced
    return True, synced


def _excise_proven() -> tuple[bool, str | None]:
    """Official excise contour proof через SourceStatus EEC_EXCISE."""
    from .payment_revision_utils import is_official_excise_revision

    st = _lookup_source_status("EEC_EXCISE")
    if st is None:
        return False, None
    synced = st.synced_at.isoformat() if st.synced_at else None
    if st.is_stale or not is_official_excise_revision(st.revision):
        return False, synced
    return True, synced


def _anti_dumping_proven() -> tuple[bool, str | None]:
    """Official anti-dumping contour proof через SourceStatus EEC_ANTI_DUMPING."""
    from .payment_revision_utils import is_official_anti_dumping_revision

    st = _lookup_source_status("EEC_ANTI_DUMPING")
    if st is None:
        return False, None
    synced = st.synced_at.isoformat() if st.synced_at else None
    if st.is_stale or not is_official_anti_dumping_revision(st.revision):
        return False, synced
    return True, synced


def _special_safeguard_proven() -> tuple[bool, str | None]:
    """Official special-safeguard contour proof через SourceStatus EEC_SPECIAL_SAFEGUARD."""
    from .payment_revision_utils import is_official_special_safeguard_revision

    st = _lookup_source_status("EEC_SPECIAL_SAFEGUARD")
    if st is None:
        return False, None
    synced = st.synced_at.isoformat() if st.synced_at else None
    if st.is_stale or not is_official_special_safeguard_revision(st.revision):
        return False, synced
    return True, synced


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
    seed = 0
    for revision, count in (
        db.query(HsRate.source_revision, func.count()).group_by(HsRate.source_revision).all()
    ):
        if _is_seed_or_fallback_revision(revision):
            seed += int(count or 0)
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
    elif not total:
        status = "manual_review_required"
        gaps.append(
            "Нет каталога ТН ВЭД (10-знаков) для подтверждения полноты покрытия пошлин "
            "(no TN VED 10-digit catalog coverage available) — present недопустим."
        )
    elif total > 0 and covered == total and eec_ok and seed_total < hs_total:
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


def _count_vat_signal_hs_rows(db) -> int:
    """Строки hs_rates с VAT-сигналом (без классификации official/partial)."""
    count = 0
    for vat_rule, vat_rate, vat_basis in db.query(
        HsRate.vat_rule,
        HsRate.vat_import_rate,
        HsRate.vat_rule_basis,
    ).all():
        if (vat_rule or "none") != "none":
            count += 1
            continue
        if float(vat_rate or 22.0) != 22.0:
            count += 1
            continue
        if (vat_basis or "").strip():
            count += 1
    return count


def _count_official_vat_marker_rows(db) -> int:
    """Строки с row-level official VAT marker (vat_source_* + EEC_VAT)."""
    from .payment_revision_utils import is_official_vat_row_marker

    count = 0
    for vat_rule, vat_rate, vat_basis, vat_source_code, vat_source_revision in db.query(
        HsRate.vat_rule,
        HsRate.vat_import_rate,
        HsRate.vat_rule_basis,
        HsRate.vat_source_code,
        HsRate.vat_source_revision,
    ).all():
        if not (
            (vat_rule or "none") != "none"
            or float(vat_rate or 22.0) != 22.0
            or (vat_basis or "").strip()
        ):
            continue
        if is_official_vat_row_marker(
            vat_source_code=vat_source_code,
            vat_source_revision=vat_source_revision,
        ):
            count += 1
    return count


def normalize_vat() -> PaymentDomainNormalization:
    """НДС: hs_rates + vat_preferences; seed-only → не present."""
    vat_cov = diagnose_vat_rates()
    label, authority = _registry_label("eec_ett_tnved")
    vat_ok, _ = _vat_proven()

    with SessionLocal() as db:
        stats = _hs_rate_stats(db)
        pref_count = db.query(VatPreference).count()
        pref_codes = db.query(func.count(func.distinct(VatPreference.hs_code_prefix))).scalar() or 0
        vat_signal_rows = _count_vat_signal_hs_rows(db)
        official_vat_marker_rows = _count_official_vat_marker_rows(db)

    gaps = list(vat_cov.gaps)
    manual = True
    hs_total = stats["hs_rates_total"]
    seed_total = stats["hs_rates_seed"]
    seed_only = hs_total > 0 and seed_total >= hs_total
    has_prefs = pref_count > 0
    has_rules = stats["hs_rates_vat_rule"] > 0 or stats["hs_rates_vat_non_default"] > 0

    if hs_total == 0:
        status: PaymentNormalizationStatus = "missing"
    elif not has_prefs and not has_rules and vat_signal_rows == 0:
        status = "partial"
        gaps.append("Только базовый НДС 22% в hs_rates без vat_preferences/vat_rule.")
    elif not vat_ok:
        status = "partial"
        gaps.append("НДС-контур без подтверждённого EEC_VAT SourceStatus — консервативно partial.")
    elif official_vat_marker_rows == 0 and (has_prefs or has_rules or vat_signal_rows > 0):
        status = "partial"
        gaps.append("Есть VAT-сигнал в данных, но нет row-level official VAT provenance (vat_source_*).")
    elif official_vat_marker_rows > 0 and vat_ok:
        status = "present"
        manual = False
    else:
        status = "partial"

    sources = [
        _source_ref(
            "eec_ett_tnved",
            present=vat_ok and official_vat_marker_rows > 0,
            record_count=hs_total,
            mapped_hs_codes=official_vat_marker_rows,
        ),
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
        mapped_hs_codes=official_vat_marker_rows
        or (int(pref_codes) if has_prefs else stats["hs_rates_vat_rule"] + stats["hs_rates_vat_non_default"]),
        known_gaps=gaps,
        manual_review_required=manual,
        normalized_snapshot={
            **stats,
            "vat_preferences": pref_count,
            "vat_signal_hs_rows": vat_signal_rows,
            "official_vat_marker_rows": official_vat_marker_rows,
        },
    )


def normalize_excise() -> PaymentDomainNormalization:
    """Акциз: present только при EEC_EXCISE + row-level excise_source_*."""
    excise_cov = diagnose_excise()
    excise_ok, _ = _excise_proven()

    with SessionLocal() as db:
        stats = _hs_rate_stats(db)
        excise_signal_rows = _count_excise_signal_hs_rows(db)
        official_excise_marker_rows = _count_official_excise_marker_rows(db)

    gaps = list(excise_cov.gaps)
    manual = True

    if stats["hs_rates_total"] == 0:
        status: PaymentNormalizationStatus = "missing"
    elif excise_signal_rows == 0:
        status = "missing"
        gaps.append("В hs_rates нет строк с excise_type percent/fixed.")
    elif not excise_ok:
        status = "partial"
        gaps.append("Excise-контур без подтверждённого EEC_EXCISE SourceStatus — консервативно partial.")
    elif official_excise_marker_rows == 0 and excise_signal_rows > 0:
        status = "partial"
        gaps.append(
            "Есть excise-сигнал в данных, но нет row-level official excise provenance (excise_source_*)."
        )
    elif official_excise_marker_rows > 0 and excise_ok:
        status = "present"
        manual = False
    else:
        status = "partial"

    if stats["hs_rates_seed"] >= stats["hs_rates_excise"] > 0 and status != "present":
        gaps.append("Акцизные поля только из seed — требуется верификация.")

    entry = get_payment_source_entry("excise_official_contour")
    return PaymentDomainNormalization(
        domain="excise",
        coverage_status=status,
        authority_level=excise_cov.authority_level or "legacy_seed",
        sources=[
            NormalizedSourceRef(
                id="hs_rates.excise",
                label="hs_rates (excise_type / excise_value)",
                present=official_excise_marker_rows > 0 and excise_ok,
                record_count=stats["hs_rates_excise"],
                mapped_hs_codes=official_excise_marker_rows,
                authority_level="official_binding" if status == "present" else "legacy_seed",
                notes=[
                    "Official excise требует EEC_EXCISE SourceStatus и excise_source_* на строке.",
                ],
            ),
            NormalizedSourceRef(
                id="excise_official_contour",
                label=entry.name if entry else "excise_official_contour",
                present=excise_ok and official_excise_marker_rows > 0,
                record_count=official_excise_marker_rows,
                mapped_hs_codes=official_excise_marker_rows,
                authority_level="official_binding" if status == "present" else "legacy_seed",
            ),
        ],
        record_count=stats["hs_rates_excise"],
        mapped_hs_codes=official_excise_marker_rows,
        known_gaps=gaps,
        manual_review_required=manual,
        normalized_snapshot={
            **stats,
            "excise_signal_hs_rows": excise_signal_rows,
            "official_excise_marker_rows": official_excise_marker_rows,
        },
    )


def _count_excise_signal_hs_rows(db) -> int:
    count = 0
    for excise_type, excise_value, excise_basis in db.query(
        HsRate.excise_type,
        HsRate.excise_value,
        HsRate.excise_basis,
    ).all():
        if str(excise_type or "none").strip().lower() in {"percent", "fixed"}:
            count += 1
            continue
        if float(excise_value or 0) > 0:
            count += 1
            continue
        if (excise_basis or "").strip():
            count += 1
    return count


def _count_official_excise_marker_rows(db) -> int:
    from .payment_revision_utils import is_official_excise_row_marker

    count = 0
    for excise_type, excise_value, excise_basis, excise_source_code, excise_source_revision in db.query(
        HsRate.excise_type,
        HsRate.excise_value,
        HsRate.excise_basis,
        HsRate.excise_source_code,
        HsRate.excise_source_revision,
    ).all():
        if not (
            str(excise_type or "none").strip().lower() in {"percent", "fixed"}
            or float(excise_value or 0) > 0
            or (excise_basis or "").strip()
        ):
            continue
        if is_official_excise_row_marker(
            excise_source_code=excise_source_code,
            excise_source_revision=excise_source_revision,
        ):
            count += 1
    return count


def normalize_anti_dumping() -> PaymentDomainNormalization:
    """Антидемпинг: special_duties с row-level provenance; без official contour — never present."""
    from .payment_revision_utils import is_official_anti_dumping_row_marker

    configured, reg_label, authority = _source_configured(_TRADE_REMEDY_OFFICIAL_SOURCE_IDS)
    ad_ok, ad_sync = _anti_dumping_proven()

    with SessionLocal() as db:
        special = db.query(SpecialDuty).filter(SpecialDuty.measure_type == "anti_dumping").count()
        special_prefixes = (
            db.query(func.count(func.distinct(SpecialDuty.hs_code_prefix)))
            .filter(SpecialDuty.measure_type == "anti_dumping")
            .scalar()
            or 0
        )
        official_rows = 0
        legacy_rows = 0
        for source_code, source_revision in db.query(
            SpecialDuty.source_code, SpecialDuty.source_revision
        ).filter(SpecialDuty.measure_type == "anti_dumping"):
            if is_official_anti_dumping_row_marker(
                source_code=source_code, source_revision=source_revision
            ):
                official_rows += 1
            else:
                legacy_rows += 1
        geo_ad = (
            db.query(GeoSpecialDuty)
            .filter(GeoSpecialDuty.measure_type == "anti_dumping")
            .count()
        )
        stats = _hs_rate_stats(db)

    local_rows = special + geo_ad + stats["hs_rates_antidumping_flag"] + stats["hs_rates_antidumping_typed"]
    gaps: list[str] = []

    if local_rows == 0 and not configured and not ad_ok:
        status: PaymentNormalizationStatus = "missing"
        gaps.append("Нет локальных строк антидемпинга и официальный контур не настроен.")
    elif not ad_ok:
        status = "manual_review_required" if local_rows > 0 else "partial"
        gaps.append(
            "EEC_ANTI_DUMPING SourceStatus не подтверждён — не claim present "
            "(global SourceStatus alone недостаточен без row-level provenance)."
        )
        if legacy_rows > 0:
            gaps.append(
                "Есть special_duties без row-level official anti-dumping provenance "
                "(source_code/source_revision)."
            )
    elif official_rows == 0:
        status = "partial"
        gaps.append("Нет special_duties с official anti-dumping row markers.")
    else:
        # MVP: контур работает, но полнота торговых мер не верифицирована — present не выдаётся.
        status = "manual_review_required"
        gaps.append(
            "Anti-dumping MVP: official anti-dumping contour synced, completeness not verified "
            "(special-safeguard / countervailing — отдельные контуры) — present не выдаётся."
        )

    sources = [
        NormalizedSourceRef(
            id="special_duties",
            label="special_duties (anti_dumping)",
            present=special > 0,
            record_count=special,
            mapped_hs_codes=int(special_prefixes),
            authority_level=authority or "legacy_seed",
            notes=[f"official row markers: {official_rows}", f"legacy rows: {legacy_rows}"],
        ),
        NormalizedSourceRef(
            id="hs_rates.antidumping",
            label="hs_rates (antidumping_*)",
            present=stats["hs_rates_antidumping_typed"] > 0 or stats["hs_rates_antidumping_flag"] > 0,
            record_count=stats["hs_rates_antidumping_typed"] + stats["hs_rates_antidumping_flag"],
            authority_level="legacy_seed",
            notes=["Не обновляется official anti-dumping ingestion MVP."],
        ),
        _source_ref(
            "geo_special_duties_embargo",
            present=geo_ad > 0,
            record_count=geo_ad,
            extra_notes=["measure_type=anti_dumping", "legacy_seed"],
        ),
        _source_ref(
            "trade_remedies_official",
            present=ad_ok,
            record_count=official_rows if ad_ok else None,
            extra_notes=[f"EEC_ANTI_DUMPING synced_at={ad_sync or 'n/a'}"],
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
            "special_duties_official_rows": official_rows,
            "special_duties_legacy_rows": legacy_rows,
            "geo_special_duties_anti_dumping": geo_ad,
            "official_contour_configured": configured,
            "eec_anti_dumping_proven": ad_ok,
            "registry_label": reg_label,
        },
    )


def normalize_special_safeguard() -> PaymentDomainNormalization:
    """Специальные защитные пошлины: special_duties с row-level EEC_SPECIAL_SAFEGUARD provenance."""
    from .payment_revision_utils import is_official_special_safeguard_row_marker

    configured, reg_label, authority = _source_configured(_TRADE_REMEDY_OFFICIAL_SOURCE_IDS)
    ss_ok, ss_sync = _special_safeguard_proven()

    with SessionLocal() as db:
        special = db.query(SpecialDuty).filter(SpecialDuty.measure_type == "special_safeguard").count()
        special_prefixes = (
            db.query(func.count(func.distinct(SpecialDuty.hs_code_prefix)))
            .filter(SpecialDuty.measure_type == "special_safeguard")
            .scalar()
            or 0
        )
        official_rows = 0
        legacy_rows = 0
        for safeguard_source_code, safeguard_source_revision in db.query(
            SpecialDuty.safeguard_source_code, SpecialDuty.safeguard_source_revision
        ).filter(SpecialDuty.measure_type == "special_safeguard"):
            if is_official_special_safeguard_row_marker(
                safeguard_source_code=safeguard_source_code,
                safeguard_source_revision=safeguard_source_revision,
            ):
                official_rows += 1
            else:
                legacy_rows += 1

    gaps: list[str] = []
    if special == 0 and not configured and not ss_ok:
        status: PaymentNormalizationStatus = "missing"
        gaps.append("Нет локальных строк special-safeguard и официальный контур не настроен.")
    elif not ss_ok:
        status = "manual_review_required" if special > 0 else "partial"
        gaps.append(
            "EEC_SPECIAL_SAFEGUARD SourceStatus не подтверждён — не claim present "
            "(global SourceStatus alone недостаточен без row-level provenance)."
        )
        if legacy_rows > 0:
            gaps.append(
                "Есть special_duties без row-level official special-safeguard provenance "
                "(source_code/source_revision)."
            )
    elif official_rows == 0:
        status = "partial"
        gaps.append("Нет special_duties с official special-safeguard row markers.")
    else:
        status = "manual_review_required"
        gaps.append(
            "Special-safeguard MVP: official contour synced, completeness not verified "
            "(countervailing вне scope) — present не выдаётся."
        )

    sources = [
        NormalizedSourceRef(
            id="special_duties",
            label="special_duties (special_safeguard)",
            present=special > 0,
            record_count=special,
            mapped_hs_codes=int(special_prefixes),
            authority_level=authority or "legacy_seed",
            notes=[f"official row markers: {official_rows}", f"legacy rows: {legacy_rows}"],
        ),
        _source_ref(
            "trade_remedies_special_safeguard_official",
            present=ss_ok,
            record_count=official_rows if ss_ok else None,
            extra_notes=[f"EEC_SPECIAL_SAFEGUARD synced_at={ss_sync or 'n/a'}"],
        ),
    ]

    return PaymentDomainNormalization(
        domain="special_safeguard",
        coverage_status=status,
        authority_level=authority or "legacy_seed",
        sources=sources,
        record_count=special,
        mapped_hs_codes=int(special_prefixes) if special else None,
        known_gaps=gaps,
        manual_review_required=True,
        normalized_snapshot={
            "special_duties": special,
            "special_duties_official_rows": official_rows,
            "special_duties_legacy_rows": legacy_rows,
            "official_contour_configured": configured,
            "eec_special_safeguard_proven": ss_ok,
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
        "special_safeguard": normalize_special_safeguard(),
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
