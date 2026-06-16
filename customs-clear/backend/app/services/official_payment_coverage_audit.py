"""Аудит покрытия официальных платёжных/remedy доменов и консервативное backfill-планирование (issue #51)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import func

from ..db import SessionLocal
from ..models.core import HsRate, SourceStatus
from ..models.tnved import HsDutyRule, SpecialDuty
from ..schemas.official_payment_coverage_audit import (
    BackfillRecommendation,
    BackfillSituation,
    OfficialDomainCoverageAudit,
    OfficialPaymentCoverageAuditResponse,
)
from .payment_data_coverage import _lookup_source_status
from .payment_data_normalization import _is_seed_or_fallback_revision
from .payment_revision_utils import (
    is_conservative_official_excise_source_url,
    is_official_anti_dumping_row_marker,
    is_official_eec_ett_revision,
    is_official_excise_row_marker,
    is_official_special_safeguard_row_marker,
    is_official_vat_row_marker,
    is_safe_official_anti_dumping_source_url,
    is_unsafe_official_source_url,
)
from .payment_source_ingestion import parse_payment_source_file
from .payment_source_registry import (
    PAYMENT_SOURCE_REGISTRY,
    PaymentSourceEntry,
    get_payment_source_entry,
)
from .regulatory_source_registry import SOURCE_OF_TRUTH_LEVELS

_BACKEND_DOMAIN_ORDER: tuple[str, ...] = (
    "EEC_ETT",
    "EEC_VAT",
    "EEC_EXCISE",
    "EEC_ANTI_DUMPING",
    "EEC_SPECIAL_SAFEGUARD",
    "EEC_COUNTERVAILING",
)

_DOMAIN_KEY_BY_CODE: dict[str, str] = {
    "EEC_ETT": "import_duty",
    "EEC_VAT": "vat",
    "EEC_EXCISE": "excise",
    "EEC_ANTI_DUMPING": "anti_dumping",
    "EEC_SPECIAL_SAFEGUARD": "special_safeguard",
    "EEC_COUNTERVAILING": "countervailing",
}

_REGISTRY_BY_DOMAIN: dict[str, str] = {
    "EEC_ETT": "eec_ett_tariff",
    "EEC_VAT": "eec_ett_vat",
    "EEC_EXCISE": "excise_official_contour",
    "EEC_ANTI_DUMPING": "trade_remedies_official",
    "EEC_SPECIAL_SAFEGUARD": "trade_remedies_special_safeguard_official",
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def _official_registry_entry(domain_code: str) -> PaymentSourceEntry | None:
    if domain_code == "EEC_COUNTERVAILING":
        return None
    source_code = _REGISTRY_BY_DOMAIN.get(domain_code)
    if not source_code:
        return None
    return get_payment_source_entry(source_code)


def _discover_bundle_path(domain_code: str) -> str | None:
    if domain_code == "EEC_ETT":
        from .import_duty_ingestion import discover_import_duty_bundle_path

        return discover_import_duty_bundle_path()
    if domain_code == "EEC_VAT":
        from .vat_ingestion import discover_vat_bundle_path

        return discover_vat_bundle_path()
    if domain_code == "EEC_EXCISE":
        from .excise_ingestion import discover_excise_bundle_path

        return discover_excise_bundle_path()
    if domain_code == "EEC_ANTI_DUMPING":
        from .anti_dumping_ingestion import discover_anti_dumping_bundle_path

        return discover_anti_dumping_bundle_path()
    if domain_code == "EEC_SPECIAL_SAFEGUARD":
        from .special_safeguard_ingestion import discover_special_safeguard_bundle_path

        return discover_special_safeguard_bundle_path()
    return None


def _revision_validator(domain_code: str) -> Callable[[str | None], bool]:
    if domain_code == "EEC_ETT":
        return is_official_eec_ett_revision
    if domain_code == "EEC_VAT":
        from .payment_revision_utils import is_official_vat_revision

        return is_official_vat_revision
    if domain_code == "EEC_EXCISE":
        from .payment_revision_utils import is_official_excise_revision

        return is_official_excise_revision
    if domain_code == "EEC_ANTI_DUMPING":
        from .payment_revision_utils import is_official_anti_dumping_revision

        return is_official_anti_dumping_revision
    if domain_code == "EEC_SPECIAL_SAFEGUARD":
        from .payment_revision_utils import is_official_special_safeguard_revision

        return is_official_special_safeguard_revision
    return lambda _rev: False


def _url_is_safe(domain_code: str, url: str | None, *, registry_url: str | None) -> bool:
    if domain_code in {"EEC_ANTI_DUMPING", "EEC_SPECIAL_SAFEGUARD"}:
        return is_safe_official_anti_dumping_source_url(url, registry_official_url=registry_url)
    if domain_code == "EEC_EXCISE":
        return is_conservative_official_excise_source_url(url, registry_official_url=registry_url)
    if not url:
        return False
    return not is_unsafe_official_source_url(url)


def _count_import_duty_rows(db) -> tuple[int, int, int]:
    total = db.query(HsRate).count()
    official = 0
    legacy = 0
    for revision, count in (
        db.query(HsRate.source_revision, func.count()).group_by(HsRate.source_revision).all()
    ):
        n = int(count or 0)
        if is_official_eec_ett_revision(str(revision or "")):
            official += n
        elif n:
            legacy += n
    return total, official, legacy


def _hs_rate_has_vat_signal(vat_rule, vat_rate, vat_basis) -> bool:
    if (vat_rule or "none") != "none":
        return True
    if float(vat_rate or 22.0) != 22.0:
        return True
    return bool((vat_basis or "").strip())


def _count_vat_rows(db) -> tuple[int, int, int]:
    official = 0
    legacy = 0
    total_signal = 0
    for vat_rule, vat_rate, vat_basis, vat_source_code, vat_source_revision in db.query(
        HsRate.vat_rule,
        HsRate.vat_import_rate,
        HsRate.vat_rule_basis,
        HsRate.vat_source_code,
        HsRate.vat_source_revision,
    ).all():
        if not _hs_rate_has_vat_signal(vat_rule, vat_rate, vat_basis):
            continue
        total_signal += 1
        if is_official_vat_row_marker(
            vat_source_code=vat_source_code,
            vat_source_revision=vat_source_revision,
        ):
            official += 1
        else:
            legacy += 1
    return total_signal, official, legacy


def _hs_rate_has_excise_signal(excise_type, excise_value, excise_basis) -> bool:
    if str(excise_type or "none").strip().lower() in {"percent", "fixed"}:
        return True
    if float(excise_value or 0) > 0:
        return True
    return bool((excise_basis or "").strip())


def _count_excise_rows(db) -> tuple[int, int, int]:
    official = 0
    legacy = 0
    total_signal = 0
    for excise_type, excise_value, excise_basis, excise_source_code, excise_source_revision in db.query(
        HsRate.excise_type,
        HsRate.excise_value,
        HsRate.excise_basis,
        HsRate.excise_source_code,
        HsRate.excise_source_revision,
    ).all():
        if not _hs_rate_has_excise_signal(excise_type, excise_value, excise_basis):
            continue
        total_signal += 1
        if is_official_excise_row_marker(
            excise_source_code=excise_source_code,
            excise_source_revision=excise_source_revision,
        ):
            official += 1
        else:
            legacy += 1
    return total_signal, official, legacy


def _count_trade_remedy_rows(db, *, measure_type: str) -> tuple[int, int, int]:
    official = 0
    legacy = 0
    total = (
        db.query(SpecialDuty)
        .filter(SpecialDuty.measure_type == measure_type)
        .count()
    )
    if measure_type == "anti_dumping":
        rows = db.query(SpecialDuty.source_code, SpecialDuty.source_revision).filter(
            SpecialDuty.measure_type == "anti_dumping"
        )
        for source_code, source_revision in rows:
            if is_official_anti_dumping_row_marker(
                source_code=source_code, source_revision=source_revision
            ):
                official += 1
            else:
                legacy += 1
    elif measure_type == "special_safeguard":
        rows = db.query(
            SpecialDuty.safeguard_source_code,
            SpecialDuty.safeguard_source_revision,
        ).filter(SpecialDuty.measure_type == "special_safeguard")
        for safeguard_source_code, safeguard_source_revision in rows:
            if is_official_special_safeguard_row_marker(
                safeguard_source_code=safeguard_source_code,
                safeguard_source_revision=safeguard_source_revision,
            ):
                official += 1
            else:
                legacy += 1
    else:
        legacy = total
    return total, official, legacy


def _domain_row_counts(domain_code: str) -> tuple[int, int, int]:
    with SessionLocal() as db:
        if domain_code == "EEC_ETT":
            total, official, legacy = _count_import_duty_rows(db)
            duty_rules = db.query(HsDutyRule).count()
            return max(total, duty_rules), official, legacy
        if domain_code == "EEC_VAT":
            return _count_vat_rows(db)
        if domain_code == "EEC_EXCISE":
            return _count_excise_rows(db)
        if domain_code == "EEC_ANTI_DUMPING":
            return _count_trade_remedy_rows(db, measure_type="anti_dumping")
        if domain_code == "EEC_SPECIAL_SAFEGUARD":
            return _count_trade_remedy_rows(db, measure_type="special_safeguard")
        return 0, 0, 0


def _parse_local_bundle(domain_code: str, entry: PaymentSourceEntry | None, bundle_path: str | None) -> dict[str, Any]:
    if entry is None or not bundle_path:
        return {"status": "missing_source", "record_count": 0}

    if domain_code == "EEC_ANTI_DUMPING":
        from .anti_dumping_ingestion import _load_bundle_payload

        _payload, result = _load_bundle_payload(bundle_path)
        return result

    if domain_code == "EEC_SPECIAL_SAFEGUARD":
        from .special_safeguard_ingestion import _load_bundle_payload

        _payload, result = _load_bundle_payload(bundle_path)
        return result

    if domain_code in {"EEC_ETT", "EEC_VAT", "EEC_EXCISE"}:
        from .payment_source_ingestion import parse_normative_bundle_file

        return parse_normative_bundle_file(bundle_path)

    return parse_payment_source_file(entry)


def _derive_coverage_status(
    *,
    domain_code: str,
    missing_source: bool,
    parser_failed: bool,
    stale_source_status: bool,
    official_row_count: int,
    legacy_row_count: int,
    row_count: int,
    domain_unsupported: bool,
    source_proven: bool,
) -> str:
    if domain_unsupported:
        return "not_configured"
    if parser_failed:
        return "parser_failed"
    if stale_source_status:
        return "stale"
    if missing_source and row_count == 0 and official_row_count == 0:
        return "missing"
    if domain_code in {"EEC_ANTI_DUMPING", "EEC_SPECIAL_SAFEGUARD", "EEC_COUNTERVAILING"}:
        if official_row_count > 0 or source_proven:
            return "manual_review_required"
        if row_count > 0 or legacy_row_count > 0:
            return "partial"
        return "missing" if missing_source else "partial"
    if official_row_count > 0 and source_proven and legacy_row_count == 0:
        return "present"
    if official_row_count > 0 and source_proven:
        return "partial"
    if row_count > 0 or legacy_row_count > 0:
        return "partial"
    if missing_source:
        return "missing"
    return "incomplete"


def _derive_backfill(
    *,
    domain_code: str,
    configured: bool,
    local_bundle_present: bool,
    parser_result: dict[str, Any],
    source_status: SourceStatus | None,
    official_row_count: int,
    legacy_row_count: int,
    row_count: int,
    unsafe_revision: bool,
    unsafe_url: bool,
    domain_unsupported: bool,
    revision_ok: bool,
) -> tuple[BackfillRecommendation, BackfillSituation, list[str], bool, list[str]]:
    notes: list[str] = []
    gaps: list[str] = []
    parse_status = str(parser_result.get("status") or "")

    if domain_unsupported:
        gaps.append("countervailing не выделен в локальной схеме — completeness not verified.")
        return "manual_review_required", "domain_unsupported", gaps, True, notes

    if parse_status == "parser_failed":
        gaps.append(f"Parser failed: {parser_result.get('error') or parser_result.get('reason')}")
        return "manual_review_required", "parser_failure", gaps, True, notes

    if unsafe_url:
        gaps.append("Unsafe/fake official URL — ingestion blocked.")
        return "manual_review_required", "unsafe_url", gaps, True, notes

    if unsafe_revision:
        gaps.append("Unsafe/non-versioned SourceStatus revision.")
        if local_bundle_present and revision_ok:
            notes.append("Локальный bundle revision безопасен; SourceStatus требует refresh.")
            return "refresh_official_source", "unsafe_revision", gaps, True, notes
        return "manual_review_required", "unsafe_revision", gaps, True, notes

    if source_status is not None and source_status.is_stale:
        gaps.append(f"SourceStatus {domain_code} is_stale=True.")
        return "refresh_official_source", "stale_source_status", gaps, True, notes

    bundle_parsed = parse_status == "parsed"
    source_present_not_applied = bool(
        local_bundle_present
        and bundle_parsed
        and official_row_count == 0
        and revision_ok
        and not unsafe_url
    )

    if not configured and not local_bundle_present:
        gaps.append("Official contour не настроен и локальный bundle отсутствует.")
        return "acquire_official_source", "missing_official_source", gaps, True, notes

    if not local_bundle_present and row_count == 0:
        gaps.append("Локальный official bundle отсутствует.")
        return "acquire_official_source", "missing_official_source", gaps, True, notes

    if source_present_not_applied:
        gaps.append("Official bundle распарсен, но строки с row-level provenance отсутствуют.")
        notes.append("Dry-run apply доступен через guarded ingestion endpoint.")
        return "run_apply", "official_source_present_not_applied", gaps, True, notes

    proven = source_status is not None and revision_ok and not source_status.is_stale
    if proven and legacy_row_count > 0:
        gaps.append("Есть legacy/non-official строки рядом с official contour.")
        return "reapply_official_bundle", "applied_no_row_provenance", gaps, True, notes

    if proven and official_row_count == 0 and row_count > 0:
        gaps.append("Данные в БД без row-level official provenance.")
        if local_bundle_present and bundle_parsed:
            return "reapply_official_bundle", "applied_no_row_provenance", gaps, True, notes
        return "reapply_official_bundle", "applied_no_row_provenance", gaps, True, notes

    if proven and official_row_count > 0 and legacy_row_count > 0:
        gaps.append("Частичное official покрытие — legacy rows остаются.")
        return "reapply_official_bundle", "partial_rows", gaps, True, notes

    if domain_code in {"EEC_ANTI_DUMPING", "EEC_SPECIAL_SAFEGUARD"} and (official_row_count > 0 or proven):
        gaps.append("Trade remedies: completeness not verified без official full-list model.")
        return "manual_review_required", "completeness_not_verified", gaps, True, notes

    if official_row_count > 0 and proven and legacy_row_count == 0:
        if domain_code in {"EEC_ANTI_DUMPING", "EEC_SPECIAL_SAFEGUARD"}:
            gaps.append("completeness not verified")
            return "manual_review_required", "completeness_not_verified", gaps, True, notes
        return "none", "ok", gaps, False, notes

    if row_count > 0:
        gaps.append("Partial/incomplete official coverage.")
        return "manual_review_required", "partial_rows", gaps, True, notes

    return "acquire_official_source", "missing_official_source", gaps, True, notes


def audit_official_domain(domain_code: str) -> OfficialDomainCoverageAudit:
    """Детерминированный аудит одного официального домена (read-only)."""
    domain_key = _DOMAIN_KEY_BY_CODE[domain_code]
    entry = _official_registry_entry(domain_code)
    domain_unsupported = domain_code == "EEC_COUNTERVAILING"

    configured = bool(
        entry is not None and entry.authority_level in SOURCE_OF_TRUTH_LEVELS
    )
    expected_source = entry.name if entry else (
        "ЕЭК — компенсационные пошлины (контур не настроен)"
        if domain_unsupported
        else domain_code
    )

    bundle_path = None if domain_unsupported else _discover_bundle_path(domain_code)
    local_bundle_present = bundle_path is not None

    parser_result: dict[str, Any] = {"status": "not_run", "record_count": 0}
    parsed_rows: int | None = None
    if entry is not None and local_bundle_present and bundle_path:
        parser_result = _parse_local_bundle(domain_code, entry, bundle_path)
        parsed_rows = int(
            parser_result.get("measures_count")
            or parser_result.get("rates_count")
            or parser_result.get("record_count")
            or 0
        )
    elif domain_unsupported:
        parser_result = {"status": "not_applicable", "record_count": 0}
    elif not local_bundle_present:
        parser_result = {"status": "missing_source", "record_count": 0}

    source_status_code = entry.source_status_code if entry else (
        "EEC_COUNTERVAILING" if domain_unsupported else None
    )
    source_status = _lookup_source_status(source_status_code) if source_status_code else None
    source_revision = source_status.revision if source_status else None
    source_url = (
        (source_status.source_url if source_status and source_status.source_url else None)
        or (entry.official_url if entry else None)
    )

    revision_validator = _revision_validator(domain_code)
    revision_ok = revision_validator(source_revision) if source_revision else False
    bundle_revision = str(parser_result.get("revision") or "").strip()
    bundle_revision_ok = revision_validator(bundle_revision) if bundle_revision else False

    unsafe_revision = bool(
        source_revision
        and not revision_ok
        and (
            _is_seed_or_fallback_revision(source_revision)
            or source_revision.strip().lower() in {"manual", "local-copy", "unknown", "unavailable"}
        )
    )
    if not unsafe_revision and source_revision and not revision_ok:
        unsafe_revision = True

    registry_url = entry.official_url if entry else None
    unsafe_url = bool(source_url and not _url_is_safe(domain_code, source_url, registry_url=registry_url))

    row_count, official_row_count, legacy_row_count = _domain_row_counts(domain_code)
    parser_failed = parser_result.get("status") == "parser_failed"
    missing_source = bool(
        domain_unsupported
        or (
            not local_bundle_present
            and source_status is None
            and row_count == 0
            and official_row_count == 0
        )
    )

    source_proven = bool(
        source_status is not None
        and revision_ok
        and not source_status.is_stale
    )
    stale_source_status = bool(source_status is not None and source_status.is_stale)

    source_present_but_not_applied = bool(
        local_bundle_present
        and parser_result.get("status") == "parsed"
        and official_row_count == 0
        and (bundle_revision_ok or revision_ok)
    )
    partial_rows = bool(
        official_row_count > 0 and legacy_row_count > 0
    ) or bool(
        parsed_rows is not None
        and parsed_rows > 0
        and official_row_count < parsed_rows
    )

    known_gaps = list(entry.known_gaps) if entry else []
    recommendation, situation, gap_notes, manual, backfill_notes = _derive_backfill(
        domain_code=domain_code,
        configured=configured,
        local_bundle_present=local_bundle_present,
        parser_result=parser_result,
        source_status=source_status,
        official_row_count=official_row_count,
        legacy_row_count=legacy_row_count,
        row_count=row_count,
        unsafe_revision=unsafe_revision,
        unsafe_url=unsafe_url,
        domain_unsupported=domain_unsupported,
        revision_ok=bundle_revision_ok or revision_ok,
    )
    known_gaps.extend(gap_notes)

    coverage_status = _derive_coverage_status(
        domain_code=domain_code,
        missing_source=missing_source,
        parser_failed=parser_failed,
        stale_source_status=stale_source_status,
        official_row_count=official_row_count,
        legacy_row_count=legacy_row_count,
        row_count=row_count,
        domain_unsupported=domain_unsupported,
        source_proven=source_proven,
    )
    if situation == "completeness_not_verified":
        manual = True
        coverage_status = "manual_review_required"

    return OfficialDomainCoverageAudit(
        domain=domain_code,
        domain_key=domain_key,
        expected_official_source=expected_source,
        configured_official_source=configured,
        local_bundle_present=local_bundle_present,
        local_bundle_path=bundle_path,
        source_revision=source_revision,
        source_url=source_url,
        row_count=row_count,
        official_row_count=official_row_count,
        legacy_row_count=legacy_row_count,
        parsed_rows=parsed_rows,
        missing_source=missing_source,
        parser_failed=parser_failed,
        manual_review_required=manual,
        source_present_but_not_applied=source_present_but_not_applied,
        stale_source_status=stale_source_status,
        unsafe_revision=unsafe_revision,
        unsafe_url=unsafe_url,
        partial_rows=partial_rows,
        domain_unsupported=domain_unsupported,
        coverage_status=coverage_status,  # type: ignore[arg-type]
        known_gaps=known_gaps,
        recommended_next_action=recommendation,
        backfill_situation=situation,
        backfill_notes=backfill_notes,
    )


def run_official_payment_coverage_audit() -> dict[str, Any]:
    """
    Machine-readable аудит всех official payment/remedy доменов.

    Read-only: не мутирует БД; консервативно не маркирует completeness без proof.
    """
    generated_at = _utc_now_iso()
    domains = [audit_official_domain(code) for code in _BACKEND_DOMAIN_ORDER]
    summary = {d.domain: d for d in domains}

    notes = [
        "Audit read-only: db_mutated всегда false.",
        "Ни один домен не помечается complete без explicit completeness proof.",
        "Trade remedies (AD/SS/CV): manual_review_required / completeness not verified.",
        f"Registry entries loaded: {len(PAYMENT_SOURCE_REGISTRY)} payment source candidates.",
    ]

    response = OfficialPaymentCoverageAuditResponse(
        status="OK",
        generated_at=generated_at,
        db_mutated=False,
        domains=domains,
        summary=summary,
        notes=notes,
    )
    return response.model_dump(mode="json")
