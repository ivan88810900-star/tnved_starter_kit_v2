"""Read-only аудит покрытия официальных платёжных контуров (issue #53)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import func

from ..db import SessionLocal
from ..models.core import HsRate, SourceStatus
from ..models.tnved import SpecialDuty
from ..schemas.official_payment_coverage_audit import (
    BackfillSituation,
    CoverageAuditStatus,
    OfficialPaymentCoverageAuditResponse,
    OfficialPaymentDomainAudit,
    RecommendedNextAction,
)
from .anti_dumping_ingestion import _load_bundle_payload as _load_anti_dumping_bundle
from .anti_dumping_ingestion import discover_anti_dumping_bundle_path
from .countervailing_ingestion import _load_bundle_payload as _load_countervailing_bundle
from .countervailing_ingestion import discover_countervailing_bundle_path
from .excise_ingestion import _load_bundle_payload as _load_excise_bundle
from .excise_ingestion import discover_excise_bundle_path
from .import_duty_ingestion import _load_bundle_payload as _load_import_duty_bundle
from .import_duty_ingestion import discover_import_duty_bundle_path
from .payment_data_normalization import (
    _anti_dumping_proven,
    _countervailing_proven,
    _eec_proven,
    _excise_proven,
    _is_seed_or_fallback_revision,
    _special_safeguard_proven,
    _vat_proven,
)
from .payment_revision_utils import (
    is_conservative_official_excise_source_url,
    is_official_anti_dumping_revision,
    is_official_anti_dumping_row_marker,
    is_official_countervailing_revision,
    is_official_countervailing_row_marker,
    is_official_eec_ett_revision,
    is_official_excise_revision,
    is_official_excise_row_marker,
    is_official_special_safeguard_revision,
    is_official_special_safeguard_row_marker,
    is_official_vat_revision,
    is_official_vat_row_marker,
    is_safe_official_anti_dumping_source_url,
    is_safe_official_countervailing_source_url,
    is_safe_official_special_safeguard_source_url,
    is_unsafe_official_source_url,
)
from .payment_source_registry import PaymentSourceEntry, get_payment_source_entry
from .special_safeguard_ingestion import _load_bundle_payload as _load_special_safeguard_bundle
from .special_safeguard_ingestion import discover_special_safeguard_bundle_path
from .vat_ingestion import _load_bundle_payload as _load_vat_bundle
from .vat_ingestion import discover_vat_bundle_path


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def _lookup_source_status(code: str | None) -> SourceStatus | None:
    if not code:
        return None
    with SessionLocal() as db:
        return db.query(SourceStatus).filter(SourceStatus.source_code == code).first()


@dataclass(frozen=True)
class _DomainSpec:
    domain: str
    domain_key: str
    registry_source_code: str
    source_status_code: str
    discover_bundle: Callable[..., str | None]
    load_bundle: Callable[[str], tuple[dict[str, Any] | None, dict[str, Any]]]
    is_official_revision: Callable[[str | None], bool]
    url_fields: tuple[str, ...]
    is_url_safe: Callable[[str], bool]
    trade_remedy: bool = False
    measure_type: str | None = None


_DOMAIN_SPECS: tuple[_DomainSpec, ...] = (
    _DomainSpec(
        domain="import_duty",
        domain_key="EEC_ETT",
        registry_source_code="eec_ett_tariff",
        source_status_code="EEC_ETT",
        discover_bundle=discover_import_duty_bundle_path,
        load_bundle=_load_import_duty_bundle,
        is_official_revision=is_official_eec_ett_revision,
        url_fields=("official_ett_url", "source_url"),
        is_url_safe=lambda u: not is_unsafe_official_source_url(u),
    ),
    _DomainSpec(
        domain="vat",
        domain_key="EEC_VAT",
        registry_source_code="eec_ett_vat",
        source_status_code="EEC_VAT",
        discover_bundle=discover_vat_bundle_path,
        load_bundle=_load_vat_bundle,
        is_official_revision=is_official_vat_revision,
        url_fields=("official_ett_url", "source_url"),
        is_url_safe=lambda u: not is_unsafe_official_source_url(u),
    ),
    _DomainSpec(
        domain="excise",
        domain_key="EEC_EXCISE",
        registry_source_code="excise_official_contour",
        source_status_code="EEC_EXCISE",
        discover_bundle=discover_excise_bundle_path,
        load_bundle=_load_excise_bundle,
        is_official_revision=is_official_excise_revision,
        url_fields=("official_excise_url", "source_url"),
        is_url_safe=lambda u: is_conservative_official_excise_source_url(
            u,
            registry_official_url=(
                get_payment_source_entry("excise_official_contour").official_url
                if get_payment_source_entry("excise_official_contour")
                else None
            ),
        ),
    ),
    _DomainSpec(
        domain="anti_dumping",
        domain_key="EEC_ANTI_DUMPING",
        registry_source_code="trade_remedies_official",
        source_status_code="EEC_ANTI_DUMPING",
        discover_bundle=discover_anti_dumping_bundle_path,
        load_bundle=_load_anti_dumping_bundle,
        is_official_revision=is_official_anti_dumping_revision,
        url_fields=("official_url", "source_url"),
        is_url_safe=lambda u: is_safe_official_anti_dumping_source_url(
            u,
            registry_official_url=(
                get_payment_source_entry("trade_remedies_official").official_url
                if get_payment_source_entry("trade_remedies_official")
                else None
            ),
        ),
        trade_remedy=True,
        measure_type="anti_dumping",
    ),
    _DomainSpec(
        domain="special_safeguard",
        domain_key="EEC_SPECIAL_SAFEGUARD",
        registry_source_code="trade_remedies_special_safeguard_official",
        source_status_code="EEC_SPECIAL_SAFEGUARD",
        discover_bundle=discover_special_safeguard_bundle_path,
        load_bundle=_load_special_safeguard_bundle,
        is_official_revision=is_official_special_safeguard_revision,
        url_fields=("official_url", "source_url"),
        is_url_safe=lambda u: is_safe_official_special_safeguard_source_url(
            u,
            registry_official_url=(
                get_payment_source_entry("trade_remedies_special_safeguard_official").official_url
                if get_payment_source_entry("trade_remedies_special_safeguard_official")
                else None
            ),
        ),
        trade_remedy=True,
        measure_type="special_safeguard",
    ),
    _DomainSpec(
        domain="countervailing",
        domain_key="EEC_COUNTERVAILING",
        registry_source_code="trade_remedies_countervailing_official",
        source_status_code="EEC_COUNTERVAILING",
        discover_bundle=discover_countervailing_bundle_path,
        load_bundle=_load_countervailing_bundle,
        is_official_revision=is_official_countervailing_revision,
        url_fields=("official_url", "source_url"),
        is_url_safe=lambda u: is_safe_official_countervailing_source_url(
            u,
            registry_official_url=(
                get_payment_source_entry("trade_remedies_countervailing_official").official_url
                if get_payment_source_entry("trade_remedies_countervailing_official")
                else None
            ),
        ),
        trade_remedy=True,
        measure_type="countervailing",
    ),
)


def _bundle_url(payload: dict[str, Any] | None, url_fields: tuple[str, ...]) -> str:
    if not payload:
        return ""
    for key in url_fields:
        val = str(payload.get(key) or "").strip()
        if val:
            return val
    return ""


def _parsed_row_count(parser_result: dict[str, Any]) -> int:
    for key in ("measures_count", "rates_count", "record_count"):
        val = parser_result.get(key)
        if isinstance(val, int) and val >= 0:
            return val
    return int(parser_result.get("record_count") or 0)


def _proven_for_domain(domain_key: str) -> tuple[bool, str | None]:
    if domain_key == "EEC_ETT":
        return _eec_proven()
    if domain_key == "EEC_VAT":
        return _vat_proven()
    if domain_key == "EEC_EXCISE":
        return _excise_proven()
    if domain_key == "EEC_ANTI_DUMPING":
        return _anti_dumping_proven()
    if domain_key == "EEC_SPECIAL_SAFEGUARD":
        return _special_safeguard_proven()
    if domain_key == "EEC_COUNTERVAILING":
        return _countervailing_proven()
    return False, None


def _count_hs_rate_rows(
    *,
    official_marker: Callable[..., bool],
    marker_kwargs: Callable[[Any], dict[str, Any]],
    signal_predicate: Callable[[Any], bool],
    query_fields: tuple[Any, ...],
) -> tuple[int, int, int]:
    official = 0
    legacy = 0
    total_signal = 0
    with SessionLocal() as db:
        for row in db.query(*query_fields).all():
            if not signal_predicate(row):
                continue
            total_signal += 1
            kwargs = marker_kwargs(row)
            if official_marker(**kwargs):
                official += 1
            else:
                legacy += 1
    return total_signal, official, legacy


def _count_import_duty_rows() -> tuple[int, int, int]:
    official = 0
    legacy = 0
    with SessionLocal() as db:
        for revision, count in (
            db.query(HsRate.source_revision, func.count()).group_by(HsRate.source_revision).all()
        ):
            n = int(count or 0)
            if is_official_eec_ett_revision(str(revision or "")):
                official += n
            elif _is_seed_or_fallback_revision(revision):
                legacy += n
            else:
                legacy += n
        total = db.query(HsRate).count()
    return total, official, legacy


def _hs_vat_signal(row: tuple[Any, ...]) -> bool:
    vat_rule, vat_rate, vat_basis = row[0], row[1], row[2]
    if (vat_rule or "none") != "none":
        return True
    if float(vat_rate or 22.0) != 22.0:
        return True
    return bool((vat_basis or "").strip())


def _hs_excise_signal(row: tuple[Any, ...]) -> bool:
    excise_type, excise_value, excise_basis = row[0], row[1], row[2]
    if str(excise_type or "none").strip().lower() in {"percent", "fixed"}:
        return True
    if float(excise_value or 0) > 0:
        return True
    return bool((excise_basis or "").strip())


def _count_domain_db_rows(spec: _DomainSpec) -> tuple[int, int, int]:
    if spec.domain == "import_duty":
        return _count_import_duty_rows()
    if spec.domain == "vat":
        return _count_hs_rate_rows(
            official_marker=is_official_vat_row_marker,
            marker_kwargs=lambda r: {
                "vat_source_code": r[3],
                "vat_source_revision": r[4],
            },
            signal_predicate=_hs_vat_signal,
            query_fields=(
                HsRate.vat_rule,
                HsRate.vat_import_rate,
                HsRate.vat_rule_basis,
                HsRate.vat_source_code,
                HsRate.vat_source_revision,
            ),
        )
    if spec.domain == "excise":
        return _count_hs_rate_rows(
            official_marker=is_official_excise_row_marker,
            marker_kwargs=lambda r: {
                "excise_source_code": r[3],
                "excise_source_revision": r[4],
            },
            signal_predicate=_hs_excise_signal,
            query_fields=(
                HsRate.excise_type,
                HsRate.excise_value,
                HsRate.excise_basis,
                HsRate.excise_source_code,
                HsRate.excise_source_revision,
            ),
        )
    assert spec.measure_type is not None
    official = 0
    legacy = 0
    with SessionLocal() as db:
        rows = (
            db.query(SpecialDuty)
            .filter(SpecialDuty.measure_type == spec.measure_type)
            .all()
        )
        for sd in rows:
            if spec.measure_type == "anti_dumping":
                if is_official_anti_dumping_row_marker(
                    source_code=sd.source_code, source_revision=sd.source_revision
                ):
                    official += 1
                else:
                    legacy += 1
            elif spec.measure_type == "special_safeguard":
                if is_official_special_safeguard_row_marker(
                    safeguard_source_code=sd.safeguard_source_code,
                    safeguard_source_revision=sd.safeguard_source_revision,
                ):
                    official += 1
                else:
                    legacy += 1
            elif spec.measure_type == "countervailing":
                if is_official_countervailing_row_marker(
                    countervailing_source_code=sd.countervailing_source_code,
                    countervailing_source_revision=sd.countervailing_source_revision,
                ):
                    official += 1
                else:
                    legacy += 1
    return len(rows), official, legacy


def _derive_backfill(
    *,
    missing_source: bool,
    parser_failed: bool,
    unsafe_revision: bool,
    unsafe_url: bool,
    stale_source_status: bool,
    source_present_but_not_applied: bool,
    partial_rows: bool,
    proven: bool,
    official_row_count: int,
    row_count: int,
    trade_remedy: bool,
) -> tuple[RecommendedNextAction, BackfillSituation, list[str]]:
    notes: list[str] = []
    if missing_source:
        notes.append("Локальный official bundle отсутствует.")
        return "acquire_official_source", "missing_official_source", notes
    if parser_failed:
        notes.append("Bundle не прошёл read-only парсинг.")
        return "manual_review_required", "parser_failure", notes
    if unsafe_revision and unsafe_url:
        notes.append("Revision и URL bundle не проходят conservative allowlist.")
        return "manual_review_required", "unsafe_revision", notes
    if unsafe_revision:
        notes.append("Revision bundle/SourceStatus не проходит official revision check.")
        return "manual_review_required", "unsafe_revision", notes
    if unsafe_url:
        notes.append("URL bundle/SourceStatus не проходит conservative allowlist.")
        return "manual_review_required", "unsafe_url", notes
    if stale_source_status:
        notes.append("SourceStatus помечен is_stale — требуется refresh sync.")
        return "refresh_official_source", "stale_source_status", notes
    if source_present_but_not_applied:
        notes.append("Official bundle распарсен, но строки не применены в БД.")
        return "run_apply", "official_source_present_not_applied", notes
    if partial_rows or (proven and official_row_count == 0 and row_count > 0):
        notes.append("Есть локальные строки без row-level official provenance.")
        return "reapply_official_bundle", "applied_no_row_provenance", notes
    if trade_remedy and official_row_count > 0:
        notes.append("Trade-remedy contour synced; completeness not verified.")
        return "manual_review_required", "completeness_not_verified", notes
    if proven and official_row_count > 0:
        notes.append("Official contour applied с row-level provenance.")
        return "none", "ok", notes
    if row_count > 0:
        notes.append("Локальные данные без полного official proof.")
        return "manual_review_required", "applied_no_row_provenance", notes
    notes.append("Нет локальных строк и нет подтверждённого apply.")
    return "none", "ok", notes


def _derive_coverage_status(
    *,
    missing_source: bool,
    parser_failed: bool,
    stale_source_status: bool,
    unsafe_revision: bool,
    unsafe_url: bool,
    proven: bool,
    official_row_count: int,
    row_count: int,
    parsed_rows: int,
    trade_remedy: bool,
) -> CoverageAuditStatus:
    if parser_failed:
        return "parser_failed"
    if missing_source and row_count == 0:
        return "missing"
    if stale_source_status:
        return "stale"
    if unsafe_revision or unsafe_url:
        return "manual_review_required"
    if trade_remedy:
        if official_row_count > 0 and proven:
            return "manual_review_required"
        if row_count > 0 or parsed_rows > 0:
            return "partial"
        return "missing"
    if proven and official_row_count > 0:
        if official_row_count >= row_count and row_count > 0:
            return "present"
        return "partial"
    if row_count > 0 or parsed_rows > 0:
        return "partial"
    return "missing"


def _audit_domain(spec: _DomainSpec, entry: PaymentSourceEntry | None) -> OfficialPaymentDomainAudit:
    bundle_path = spec.discover_bundle()
    local_present = bool(bundle_path)
    parser_result: dict[str, Any] = {}
    payload: dict[str, Any] | None = None
    parsed_rows = 0
    parser_failed = False
    unsafe_revision = False
    unsafe_url = False
    bundle_revision = ""

    if bundle_path:
        payload, parser_result = spec.load_bundle(bundle_path)
        parsed_rows = _parsed_row_count(parser_result)
        parse_status = str(parser_result.get("status") or "")
        if parse_status == "parser_failed":
            parser_failed = True
        elif parse_status == "manual_review_required":
            reason = str(parser_result.get("reason") or "")
            if "revision" in reason or "non_official" in reason:
                unsafe_revision = True
            if "url" in reason:
                unsafe_url = True
        if payload:
            bundle_revision = str(payload.get("revision") or "").strip()
            if bundle_revision and not spec.is_official_revision(bundle_revision):
                unsafe_revision = True
            url = _bundle_url(payload, spec.url_fields)
            if url and not spec.is_url_safe(url):
                unsafe_url = True

    st = _lookup_source_status(spec.source_status_code)
    proven, synced_at = _proven_for_domain(spec.domain_key)
    stale_source_status = bool(st and st.is_stale)
    source_revision = (
        (st.revision if st and st.revision else None)
        or (bundle_revision or None)
    )
    source_url = (
        (st.source_url if st and st.source_url else None)
        or _bundle_url(payload, spec.url_fields)
        or (entry.official_url if entry else None)
    )
    if st and st.revision and not spec.is_official_revision(st.revision):
        unsafe_revision = True
    if st and st.source_url and not spec.is_url_safe(st.source_url):
        unsafe_url = True

    row_count, official_row_count, legacy_row_count = _count_domain_db_rows(spec)
    missing_source = not local_present

    bundle_parsed_ok = local_present and not parser_failed and not unsafe_revision and not unsafe_url
    source_present_but_not_applied = bool(
        bundle_parsed_ok and parsed_rows > 0 and official_row_count == 0 and not proven
    )
    partial_rows = bool(
        proven and parsed_rows > 0 and official_row_count > 0 and official_row_count < parsed_rows
    )

    coverage_status = _derive_coverage_status(
        missing_source=missing_source,
        parser_failed=parser_failed,
        stale_source_status=stale_source_status,
        unsafe_revision=unsafe_revision,
        unsafe_url=unsafe_url,
        proven=proven,
        official_row_count=official_row_count,
        row_count=row_count,
        parsed_rows=parsed_rows,
        trade_remedy=spec.trade_remedy,
    )
    recommended, backfill_situation, backfill_notes = _derive_backfill(
        missing_source=missing_source,
        parser_failed=parser_failed,
        unsafe_revision=unsafe_revision,
        unsafe_url=unsafe_url,
        stale_source_status=stale_source_status,
        source_present_but_not_applied=source_present_but_not_applied,
        partial_rows=partial_rows,
        proven=proven,
        official_row_count=official_row_count,
        row_count=row_count,
        trade_remedy=spec.trade_remedy,
    )

    known_gaps: list[str] = []
    if missing_source:
        known_gaps.append(f"Нет локального bundle для {spec.domain_key}.")
    if parser_failed:
        known_gaps.append(f"Parser failed: {parser_result.get('error') or parser_result.get('reason')}.")
    if unsafe_revision:
        known_gaps.append("Revision bundle/SourceStatus не проходит official revision check.")
    if unsafe_url:
        known_gaps.append("URL bundle/SourceStatus не проходит conservative allowlist.")
    if stale_source_status:
        known_gaps.append(f"{spec.source_status_code} SourceStatus is_stale=true.")
    if source_present_but_not_applied:
        known_gaps.append("Official bundle present, но apply не выполнен (нет row-level provenance).")
    if legacy_row_count > 0:
        known_gaps.append(f"Legacy rows без official marker: {legacy_row_count}.")
    if spec.trade_remedy and official_row_count > 0:
        known_gaps.append("Completeness not verified — present не выдаётся для trade remedies.")
    if entry and entry.known_gaps:
        known_gaps.extend(entry.known_gaps[:2])

    manual_review = (
        coverage_status in {"manual_review_required", "partial", "stale", "parser_failed"}
        or spec.trade_remedy
        or legacy_row_count > 0
        or unsafe_revision
        or unsafe_url
    )

    countervailing_source_url: str | None = None
    countervailing_synced_at: str | None = None
    if spec.domain == "countervailing":
        countervailing_synced_at = synced_at or (st.synced_at.isoformat() if st and st.synced_at else None)
        if st and st.source_url:
            countervailing_source_url = st.source_url
        elif source_url:
            countervailing_source_url = source_url
        with SessionLocal() as db:
            sample = (
                db.query(SpecialDuty.countervailing_source_url)
                .filter(
                    SpecialDuty.measure_type == "countervailing",
                    SpecialDuty.countervailing_source_url != "",
                )
                .first()
            )
            if sample and sample[0]:
                countervailing_source_url = str(sample[0])

    return OfficialPaymentDomainAudit(
        domain=spec.domain,
        domain_key=spec.domain_key,
        expected_official_source=spec.registry_source_code,
        configured_official_source=entry is not None,
        local_bundle_present=local_present,
        local_bundle_path=bundle_path,
        source_revision=source_revision,
        source_url=source_url,
        row_count=row_count,
        official_row_count=official_row_count,
        legacy_row_count=legacy_row_count,
        parsed_rows=parsed_rows,
        missing_source=missing_source,
        parser_failed=parser_failed,
        manual_review_required=manual_review,
        source_present_but_not_applied=source_present_but_not_applied,
        stale_source_status=stale_source_status,
        unsafe_revision=unsafe_revision,
        unsafe_url=unsafe_url,
        partial_rows=partial_rows,
        domain_unsupported=False,
        coverage_status=coverage_status,
        known_gaps=known_gaps,
        recommended_next_action=recommended,
        backfill_situation=backfill_situation,
        backfill_notes=backfill_notes,
        countervailing_source_url=countervailing_source_url,
        countervailing_synced_at=countervailing_synced_at,
    )


def _build_domain_summary(domains: list[OfficialPaymentDomainAudit]) -> dict[str, Any]:
    by_coverage_status: dict[str, int] = {}
    by_recommended_next_action: dict[str, int] = {}
    for domain in domains:
        by_coverage_status[domain.coverage_status] = (
            by_coverage_status.get(domain.coverage_status, 0) + 1
        )
        by_recommended_next_action[domain.recommended_next_action] = (
            by_recommended_next_action.get(domain.recommended_next_action, 0) + 1
        )
    return {
        "domain_count": len(domains),
        "by_coverage_status": dict(sorted(by_coverage_status.items())),
        "by_recommended_next_action": dict(sorted(by_recommended_next_action.items())),
    }


def _trade_remedies_aggregate(domains: list[OfficialPaymentDomainAudit]) -> dict[str, Any]:
    tr = [d for d in domains if d.domain in {"anti_dumping", "special_safeguard", "countervailing"}]
    official_total = sum(d.official_row_count for d in tr)
    any_present = any(d.local_bundle_present for d in tr)
    status: CoverageAuditStatus = "missing"
    if official_total > 0:
        status = "manual_review_required"
    elif any_present or any(d.row_count > 0 for d in tr):
        status = "partial"
    return {
        "status": status,
        "official_row_count": official_total,
        "domains": [d.domain for d in tr],
        "manual_review_required": True,
        "completeness_verified": False,
        "notes": [
            "Aggregate trade_remedies не claim present без completeness model.",
        ],
    }


def run_official_payment_coverage_audit() -> dict[str, Any]:
    """Детерминированный read-only аудит шести official payment/remedy доменов."""
    generated_at = _utc_now_iso()
    domains: list[OfficialPaymentDomainAudit] = []
    for spec in _DOMAIN_SPECS:
        entry = get_payment_source_entry(spec.registry_source_code)
        domains.append(_audit_domain(spec, entry))

    response = OfficialPaymentCoverageAuditResponse(
        status="OK",
        generated_at=generated_at,
        db_mutated=False,
        domains=domains,
        summary=_build_domain_summary(domains),
        trade_remedies_aggregate=_trade_remedies_aggregate(domains),
        notes=[
            "Read-only audit: SourceStatus/SyncLog/HsRate/SpecialDuty не мутируются.",
            "Countervailing — отдельный supported domain (trade_remedies_countervailing_official).",
            "Trade remedies: manual_review_required при official rows; aggregate present не выдаётся.",
        ],
    )
    return response.model_dump(mode="json")
