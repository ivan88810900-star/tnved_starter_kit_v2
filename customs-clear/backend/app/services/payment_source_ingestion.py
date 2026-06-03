"""Планирование и dry-run ingestion официальных платёжных источников (без мутации БД по умолчанию)."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func

from ..db import SessionLocal
from ..models.core import GeoSpecialDuty, HsRate, SourceStatus
from ..models.tnved import HsDutyRule, SpecialDuty, VatPreference
from ..schemas.payment_source_ingestion import (
    PaymentDomainIngestionPlan,
    PaymentSourceCandidate,
    PaymentSourceIngestionPlanResponse,
    RowEstimate,
)
from .payment_data_coverage import run_payment_data_coverage_report
from .payment_data_normalization import (
    _is_seed_or_fallback_revision,
    run_payment_data_normalization_report,
)
from .payment_revision_utils import raw_rate_rows
from .payment_source_registry import (
    PAYMENT_DOMAINS,
    PAYMENT_SOURCE_REGISTRY,
    PaymentSourceEntry,
    list_payment_sources_for_domain,
    payment_source_entry_to_dict,
)
from .regulatory_source_registry import SOURCE_OF_TRUTH_LEVELS

_BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent

# Ревизии bundle/файлов, явно не официальные.
_NON_OFFICIAL_FILE_REVISIONS = frozenset(
    {"example", "seed", "unknown", "ambiguous", "legacy", "legacy_seed", "fallback", "test", "demo"}
)
_NON_OFFICIAL_FILE_PREFIXES = ("example-", "seed-", "seed:", "fallback-", "test-", "demo-")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def _local_path_present(rel_path: str) -> bool:
    return (_BACKEND_ROOT / rel_path).is_file()


def _file_sha256(rel_path: str) -> str | None:
    path = _BACKEND_ROOT / rel_path
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _lookup_source_status(code: str | None) -> SourceStatus | None:
    if not code:
        return None
    with SessionLocal() as db:
        return db.query(SourceStatus).filter(SourceStatus.source_code == code).first()


def _is_official_revision(revision: str | None) -> bool:
    """Единый источник истины: revision официальная только если non-empty, non-seed/fallback,
    не входит в non-official tokens и не начинается с non-official префикса (example-/demo-/test-/…)."""
    rev = (revision or "").strip().lower()
    if not rev or rev in _NON_OFFICIAL_FILE_REVISIONS:
        return False
    if _is_seed_or_fallback_revision(rev):
        return False
    return not any(rev.startswith(p) for p in _NON_OFFICIAL_FILE_PREFIXES)


def _provenance_kind(entry: PaymentSourceEntry, *, revision: str | None = None) -> str:
    if entry.authority_level == "commercial_mirror":
        return "commercial_mirror"
    if entry.authority_level == "legacy_seed":
        return "legacy_seed"
    if entry.authority_level not in SOURCE_OF_TRUTH_LEVELS:
        return "ambiguous"
    rev = (revision or "").strip().lower()
    if not rev:
        st = _lookup_source_status(entry.source_status_code)
        rev = (st.revision or "").strip().lower() if st else ""
    if not rev:
        return "missing"
    # Official только если revision реально проходит единый _is_official_revision().
    if _is_official_revision(rev):
        return "official"
    if _is_seed_or_fallback_revision(rev) or rev in _NON_OFFICIAL_FILE_REVISIONS:
        return "seed" if "seed" in rev or rev in {"seed", "legacy", "legacy_seed"} else "fallback"
    # example-/demo-/test-* и прочие non-official, но non-seed ревизии — не official.
    return "ambiguous"


# --- Parser / loader stubs (read-only) ---


def parse_normative_bundle_file(rel_path: str) -> dict[str, Any]:
    """
    Безопасный read-only парсер normative bundle.

    Возвращает manual_review_required для example/seed revision; не пишет в БД.
    """
    path = _BACKEND_ROOT / rel_path
    if not path.is_file():
        return {
            "status": "missing_source",
            "error": f"file not found: {rel_path}",
            "record_count": 0,
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return {
            "status": "parser_failed",
            "error": str(exc),
            "record_count": 0,
        }

    revision = str(payload.get("revision") or "").strip().lower()
    fmt = str(payload.get("format") or "")

    # Malformed контейнеры: rates/rows должны быть JSON-массивом — иначе parser_failed
    # без итерации (общий helper с import-duty ingestion), чтобы /plan не падал 500.
    rates, container_err = raw_rate_rows(payload)
    if container_err is not None:
        return {
            "status": "parser_failed",
            "reason": container_err,
            "error": f"bundle '{container_err.split('_')[1]}' must be a JSON array",
            "revision": revision,
            "record_count": 0,
            "checksum_sha256": _file_sha256(rel_path),
        }
    # Non-object строки в rates/rows → parser_failed (без silent skip / AttributeError).
    if any(not isinstance(r, dict) for r in rates):
        return {
            "status": "parser_failed",
            "reason": "malformed_rate_row",
            "error": "bundle rate rows must be JSON objects",
            "revision": revision,
            "record_count": len(rates),
            "rates_count": len(rates),
            "checksum_sha256": _file_sha256(rel_path),
        }
    raw_tnved = payload.get("tnved")
    tnved = raw_tnved if isinstance(raw_tnved, list) else []

    if revision in _NON_OFFICIAL_FILE_REVISIONS or not _is_official_revision(revision):
        return {
            "status": "manual_review_required",
            "reason": "non_official_bundle_revision",
            "revision": revision,
            "format": fmt,
            "record_count": len(rates) + len(tnved),
            "rates_count": len(rates),
            "tnved_count": len(tnved),
            "checksum_sha256": _file_sha256(rel_path),
        }

    # Любой explicit (непустой) row-level revision, который не official, блокирует весь bundle.
    # Наследование bundle revision разрешено только для blank/missing row.source_revision —
    # это совпадает с реальным importer (normative_bundle.import_normative_bundle_dict).
    explicit_unsafe: list[str] = []
    for r in rates:
        rev = str(r.get("source_revision") or "").strip().lower()
        if rev and not _is_official_revision(rev):
            explicit_unsafe.append(rev)
    if explicit_unsafe:
        return {
            "status": "manual_review_required",
            "reason": "explicit_unsafe_row_revision",
            "revision": revision,
            "unsafe_row_revisions": sorted(set(explicit_unsafe))[:10],
            "record_count": len(rates),
            "rates_count": len(rates),
            "checksum_sha256": _file_sha256(rel_path),
        }

    # Defensive net: на effective revision (row.source_revision или inherited bundle revision)
    # ни одна строка не должна быть seed/fallback (bundle revision здесь уже official).
    seed_rates = sum(
        1
        for r in rates
        if _is_seed_or_fallback_revision(
            (str(r.get("source_revision") or "").strip() or revision)
        )
    )
    if rates and seed_rates >= len(rates):
        return {
            "status": "manual_review_required",
            "reason": "all_rates_seed_revision",
            "revision": revision,
            "record_count": len(rates),
            "checksum_sha256": _file_sha256(rel_path),
        }

    return {
        "status": "parsed",
        "revision": revision,
        "format": fmt,
        "record_count": len(rates) + len(tnved),
        "rates_count": len(rates),
        "tnved_count": len(tnved),
        "checksum_sha256": _file_sha256(rel_path),
    }


def parse_sanctions_fixture_file(rel_path: str) -> dict[str, Any]:
    """Read-only парсер fixture geo/sanctions — всегда legacy_seed, не official."""
    path = _BACKEND_ROOT / rel_path
    if not path.is_file():
        return {"status": "missing_source", "error": f"file not found: {rel_path}", "record_count": 0}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return {"status": "parser_failed", "error": str(exc), "record_count": 0}

    geo = payload.get("geo_special_duties") or payload.get("geo_measures") or []
    return {
        "status": "manual_review_required",
        "reason": "legacy_seed_fixture",
        "record_count": len(geo) if isinstance(geo, list) else 0,
        "checksum_sha256": _file_sha256(rel_path),
    }


def parse_payment_source_file(entry: PaymentSourceEntry) -> dict[str, Any]:
    """Диспетчер read-only парсеров по типу локального файла."""
    if not entry.local_canonical_paths:
        return {"status": "missing_source", "reason": "no_local_canonical_path", "record_count": 0}

    rel = entry.local_canonical_paths[0]
    if rel.endswith(".json") and ("normative_bundle" in rel or "eec_ett" in rel):
        return parse_normative_bundle_file(rel)
    if rel.endswith(".json"):
        return parse_sanctions_fixture_file(rel)
    return {
        "status": "stub_only",
        "reason": "parser_not_implemented_for_format",
        "path": rel,
        "record_count": 0,
    }


def _table_row_counts() -> dict[str, int]:
    with SessionLocal() as db:
        return {
            "hs_rates": db.query(HsRate).count(),
            "hs_duty_rules": db.query(HsDutyRule).count(),
            "vat_preferences": db.query(VatPreference).count(),
            "special_duties": db.query(SpecialDuty).count(),
            "geo_special_duties": db.query(GeoSpecialDuty).count(),
        }


def _hs_rate_seed_count() -> int:
    with SessionLocal() as db:
        seed = 0
        for revision, count in (
            db.query(HsRate.source_revision, func.count()).group_by(HsRate.source_revision).all()
        ):
            if _is_seed_or_fallback_revision(revision):
                seed += int(count or 0)
        return seed


def _estimate_rows_for_candidate(
    entry: PaymentSourceEntry,
    parser_result: dict[str, Any],
    *,
    provenance_kind: str,
) -> dict[str, RowEstimate]:
    """Консервативные оценки insert/update/skip — только при безопасных условиях."""
    estimates: dict[str, RowEstimate] = {}
    if provenance_kind not in ("official",):
        return {
            "skip": RowEstimate(
                action="skip",
                count=None,
                note="Оценки недоступны: источник не official или заблокирован.",
            )
        }

    parse_status = parser_result.get("status")
    file_count = int(parser_result.get("rates_count") or parser_result.get("record_count") or 0)
    db_counts = _table_row_counts()

    if parse_status == "parsed" and file_count > 0:
        primary = entry.target_tables[0] if entry.target_tables else "hs_rates"
        existing = db_counts.get(primary, 0)
        estimates["insert"] = RowEstimate(
            action="insert",
            count=max(0, file_count - existing) if existing else file_count,
            note=f"Оценка по файлу vs {primary}={existing}",
        )
        estimates["update"] = RowEstimate(
            action="update",
            count=min(existing, file_count),
            note="Строки с совпадающим hs_code могут потребовать update revision.",
        )
        estimates["skip"] = RowEstimate(action="skip", count=0, note="Точный skip требует key-by-key diff.")
        return estimates

    if entry.source_status_code and provenance_kind == "official":
        st = _lookup_source_status(entry.source_status_code)
        if st and not st.is_stale and _is_official_revision(st.revision):
            primary = entry.target_tables[0] if entry.target_tables else "hs_rates"
            existing = db_counts.get(primary, 0)
            estimates["skip"] = RowEstimate(
                action="skip",
                count=existing,
                note="Proven sync уже загрузил данные; file-based ingest не требуется.",
            )
            return estimates

    return {
        "skip": RowEstimate(
            action="skip",
            count=None,
            note="Безопасная оценка insert/update недоступна.",
        )
    }


def _candidate_readiness(
    entry: PaymentSourceEntry,
    provenance_kind: str,
    parser_result: dict[str, Any],
    *,
    domain_normalization_status: str | None,
) -> tuple[str, list[str], bool]:
    blockers: list[str] = []
    manual = entry.manual_review_default

    if provenance_kind in ("seed", "fallback", "legacy_seed"):
        blockers.append(f"Источник {entry.source_code}: provenance={provenance_kind} — blocked from official ingestion.")
        return "blocked", blockers, True

    if provenance_kind == "commercial_mirror":
        blockers.append("Коммерческое зеркало не может быть official ingestion contour.")
        return "blocked", blockers, True

    if entry.loader_status == "not_available":
        blockers.append("Loader/parser не доступен для этого контура.")
        return "missing_source", blockers, True

    if provenance_kind == "missing":
        if not entry.local_canonical_paths and not entry.source_status_code:
            blockers.append("Нет локального canonical файла и нет source_status_code.")
            return "missing_source", blockers, True
        st = _lookup_source_status(entry.source_status_code)
        if st is None:
            blockers.append(f"SourceStatus отсутствует для {entry.source_status_code}.")
            return "missing_source", blockers, True
        blockers.append("Revision/provenance не подтверждена.")
        return "manual_review_required", blockers, True

    parse_status = parser_result.get("status")
    if parse_status in ("manual_review_required", "missing_source", "parser_failed"):
        blockers.append(f"Parser: {parse_status} — {parser_result.get('reason') or parser_result.get('error', '')}")
        return "manual_review_required", blockers, True

    if entry.loader_status == "stub":
        return "stub_only", ["Loader в статусе stub — только планирование."], True

    if domain_normalization_status in ("missing", "manual_review_required", "partial", "stale"):
        blockers.append(
            f"Normalization readiness={domain_normalization_status} — консервативно не ready_to_ingest."
        )
        return "manual_review_required", blockers, True

    if provenance_kind == "official" and entry.loader_status in ("partial", "ready"):
        st = _lookup_source_status(entry.source_status_code) if entry.source_status_code else None
        # Stale official contour не может быть ready, даже если normalization present.
        if st is not None and st.is_stale:
            blockers.append(
                f"source_status_stale: SourceStatus {entry.source_status_code} is_stale=True — "
                "stale official contour не может быть ready_to_ingest."
            )
            return "manual_review_required", blockers, True
        if parse_status in ("parsed", None) or (
            st is not None and _is_official_revision(st.revision)
        ):
            return "ready_to_ingest", [], False

    return "manual_review_required", blockers or ["Условия ready_to_ingest не выполнены."], True


def _build_candidate(
    entry: PaymentSourceEntry,
    *,
    domain: str,
    domain_normalization_status: str | None,
) -> PaymentSourceCandidate:
    st = _lookup_source_status(entry.source_status_code)
    revision = st.revision if st else None
    provenance_kind = _provenance_kind(entry, revision=revision)

    local_found = [p for p in entry.local_canonical_paths if _local_path_present(p)]
    parser_result: dict[str, Any] = {"status": "not_run"}
    if local_found:
        parser_result = parse_payment_source_file(entry)
    elif entry.source_status_code and provenance_kind == "official":
        parser_result = {
            "status": "sync_provenance",
            "source_status_code": entry.source_status_code,
            "revision": revision,
        }
    elif not entry.local_canonical_paths and entry.loader_status == "not_available":
        parser_result = {"status": "missing_source", "reason": "no_loader_no_file"}

    readiness, blockers, manual = _candidate_readiness(
        entry,
        provenance_kind,
        parser_result,
        domain_normalization_status=domain_normalization_status,
    )
    row_estimates = _estimate_rows_for_candidate(entry, parser_result, provenance_kind=provenance_kind)

    return PaymentSourceCandidate(
        source_code=entry.source_code,
        name=entry.name,
        domains=list(entry.domains),
        provenance_kind=provenance_kind,  # type: ignore[arg-type]
        authority_level=entry.authority_level,
        official_url=entry.official_url or None,
        legal_basis=entry.legal_basis,
        local_paths_found=local_found,
        source_status_revision=revision,
        source_status_stale=st.is_stale if st else None,
        loader_status=entry.loader_status,
        target_tables=list(entry.target_tables),
        readiness=readiness,  # type: ignore[arg-type]
        blockers=blockers,
        manual_review_required=manual,
        row_estimates=row_estimates,
        parser_result=parser_result,
    )


def _domain_overall_readiness(candidates: list[PaymentSourceCandidate]) -> str:
    order = {
        "ready_to_ingest": 5,
        "stub_only": 4,
        "manual_review_required": 3,
        "missing_source": 2,
        "blocked": 1,
        "not_applicable": 0,
    }
    if not candidates:
        return "missing_source"
    best = max(candidates, key=lambda c: order.get(c.readiness, 0))
    if best.readiness == "ready_to_ingest":
        return "ready_to_ingest"
    if any(c.readiness == "blocked" for c in candidates):
        return "blocked"
    if any(c.readiness == "manual_review_required" for c in candidates):
        return "manual_review_required"
    return best.readiness


def _build_domain_plan(
    domain: str,
    *,
    normalization_domains: dict[str, Any],
    coverage_summary: dict[str, Any],
) -> PaymentDomainIngestionPlan:
    norm = normalization_domains.get(domain) or {}
    norm_status = norm.get("coverage_status")
    cov_key = {
        "import_duty": "duty_rates",
        "vat": "vat_rates",
        "excise": "excise",
        "anti_dumping": "trade_remedies",
        "special_protective": "trade_remedies",
        "countervailing": "trade_remedies",
    }.get(domain)
    cov_status = (coverage_summary.get(cov_key) or {}).get("status") if cov_key else None

    entries = list_payment_sources_for_domain(domain)
    candidates = [
        _build_candidate(e, domain=domain, domain_normalization_status=norm_status) for e in entries
    ]
    affected: set[str] = set()
    blockers: list[str] = []
    notes: list[str] = []
    manual = False

    for c in candidates:
        affected.update(c.target_tables)
        blockers.extend(c.blockers)
        manual = manual or c.manual_review_required

    readiness = _domain_overall_readiness(candidates)

    if domain == "countervailing" and norm_status == "not_applicable":
        readiness = "not_applicable"
        notes.append("countervailing не выделен в локальной схеме — ingestion not_applicable.")

    if any(c.readiness == "ready_to_ingest" for c in candidates) and norm_status in (
        "partial",
        "manual_review_required",
        "missing",
    ):
        readiness = "manual_review_required"
        blockers.append(
            "False ready_to_ingest предотвращён: normalization status не present/official."
        )
        notes.append("Связь с payment-normalization: domain не present — ingest заблокирован.")

    return PaymentDomainIngestionPlan(
        domain=domain,
        normalization_status=norm_status,
        coverage_status=cov_status,
        readiness=readiness,  # type: ignore[arg-type]
        candidates=candidates,
        affected_tables=sorted(affected),
        blockers=sorted(set(blockers)),
        manual_review_required=manual,
        notes=notes,
    )


def _overall_readiness(domains: dict[str, PaymentDomainIngestionPlan]) -> str:
    order = {
        "ready_to_ingest": 5,
        "stub_only": 4,
        "manual_review_required": 3,
        "missing_source": 2,
        "blocked": 1,
        "not_applicable": 0,
    }
    core = [domains[d] for d in ("import_duty", "vat", "excise", "anti_dumping") if d in domains]
    if not core:
        return "missing_source"
    return min((d.readiness for d in core), key=lambda r: order.get(r, 0))


def run_payment_source_ingestion_plan(*, dry_run: bool = False) -> dict[str, Any]:
    """
    Детерминированный план ingestion (или dry-run отчёт).

    dry_run=True: те же вычисления + row estimates; db_mutated всегда False.
    """
    generated_at = _utc_now_iso()
    norm_report = run_payment_data_normalization_report()
    cov_report = run_payment_data_coverage_report()

    normalization_domains = norm_report.get("domains") or {}
    coverage_summary = cov_report.get("summary") or {}

    domains: dict[str, PaymentDomainIngestionPlan] = {}
    for domain in PAYMENT_DOMAINS:
        if domain == "special_protective" and domain not in normalization_domains:
            continue
        if domain == "countervailing":
            domains[domain] = _build_domain_plan(
                domain,
                normalization_domains=normalization_domains,
                coverage_summary=coverage_summary,
            )
            continue
        domains[domain] = _build_domain_plan(
            domain,
            normalization_domains=normalization_domains,
            coverage_summary=coverage_summary,
        )

    response = PaymentSourceIngestionPlanResponse(
        status="OK",
        generated_at=generated_at,
        mode="dry_run" if dry_run else "plan",
        dry_run=dry_run,
        db_mutated=False,
        overall_readiness=_overall_readiness(domains),  # type: ignore[arg-type]
        domains={k: v for k, v in domains.items()},
        registry_snapshot=[payment_source_entry_to_dict(e) for e in PAYMENT_SOURCE_REGISTRY],
        normalization_link={
            "overall_readiness": norm_report.get("overall_readiness"),
            "generated_at": norm_report.get("generated_at"),
        },
        notes=[
            "Dry-run/plan не мутирует БД.",
            "seed/fallback/commercial_mirror/legacy_seed blocked from official ingestion.",
            "ready_to_ingest только при official provenance + normalization не блокирует.",
        ],
    )
    return response.model_dump(mode="json")


def run_payment_source_ingestion_dry_run() -> dict[str, Any]:
    """Alias dry-run: parse local files, row estimates, db_mutated=False."""
    return run_payment_source_ingestion_plan(dry_run=True)
