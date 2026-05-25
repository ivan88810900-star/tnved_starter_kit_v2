"""Диагностика полноты нормативных источников: gap-отчёт по реестру."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..db import SessionLocal
from ..models.core import ClassificationDecision, CustomsCaseLaw, SgrCertificate
from ..models.ntm_v2 import NtmApplicabilityRuleV2
from ..models.regulatory import RegulatoryDocument
from ..models.tnved import NonTariffMeasure
from .normative_store import list_source_status, list_sync_log
from .regulatory_source_registry import (
    AUTHORITY_LEVEL_LABELS,
    REGULATORY_SOURCE_REGISTRY,
    SOURCE_OF_TRUTH_LEVELS,
    RegulatorySourceEntry,
    registry_entry_to_dict,
)
from .ntm_v2_official_sgr_import import OFFICIAL_SGR_SOURCE_KIND
from .ntm_v2_import import SOURCE_KIND as LEGACY_TR_TS_SOURCE_KIND

_BACKEND_ROOT = Path(__file__).resolve().parents[2]

CoverageStatus = str  # missing | present | stale | partial | parser_failed | not_applicable


def _backend_path(rel: str) -> Path:
    return _BACKEND_ROOT / rel


def _count_db_probe(probe: str | None) -> int | None:
    if not probe:
        return None
    with SessionLocal() as db:
        if probe == "tnved_entries":
            from ..models.core import TnvedEntry

            return db.query(TnvedEntry).count()
        if probe == "tr_ts_acts":
            from ..models.core import TrTsAct

            return db.query(TrTsAct).count()
        if probe == "classification_decisions":
            return db.query(ClassificationDecision).count()
        if probe == "classification_decisions_official_fts":
            # Официальный фид ФТС не подключён; зеркальные ПКР не считаем official coverage.
            return 0
        if probe == "classification_decisions_tks":
            return (
                db.query(ClassificationDecision)
                .filter(ClassificationDecision.decision_number.isnot(None))
                .count()
            )
        if probe == "preliminary_decisions_fts_alta":
            from ..models.core import PreliminaryDecision

            return (
                db.query(PreliminaryDecision)
                .filter(PreliminaryDecision.source == "fts_alta")
                .count()
            )
        if probe == "customs_case_law_eec":
            return (
                db.query(CustomsCaseLaw)
                .filter(CustomsCaseLaw.source_type == "eec")
                .count()
            )
        if probe == "regulatory_documents":
            return db.query(RegulatoryDocument).count()
        if probe == "regulatory_documents_pravo":
            return (
                db.query(RegulatoryDocument)
                .filter(RegulatoryDocument.agency == "PRAVO_GOV")
                .count()
            )
        if probe == "preliminary_decisions_ifcg":
            from ..models.core import PreliminaryDecision

            return (
                db.query(PreliminaryDecision)
                .filter(PreliminaryDecision.source == "ifcg")
                .count()
            )
        if probe == "sgr_certificates":
            return db.query(SgrCertificate).count()
        if probe == "ntm_v2_official_sgr_rules":
            return (
                db.query(NtmApplicabilityRuleV2)
                .filter(NtmApplicabilityRuleV2.source_kind == OFFICIAL_SGR_SOURCE_KIND)
                .count()
            )
        if probe == "ntm_v2_legacy_tr_catalog":
            return (
                db.query(NtmApplicabilityRuleV2)
                .filter(NtmApplicabilityRuleV2.source_kind == LEGACY_TR_TS_SOURCE_KIND)
                .count()
            )
        if probe == "regulatory_ai_extracts":
            from ..models import RegulatoryAiExtract

            return db.query(RegulatoryAiExtract).count()
        if probe == "non_tariff_measures":
            return db.query(NonTariffMeasure).count()
        if probe == "permits_fsa_usage":
            # Нет отдельной таблицы bulk — маркер «runtime-only»
            return -1
    return None


def _local_paths_status(paths: tuple[str, ...]) -> dict[str, Any]:
    if not paths:
        return {"configured": False, "exists": False, "paths_checked": []}
    checked: list[dict[str, Any]] = []
    any_exists = False
    for rel in paths:
        p = _backend_path(rel)
        exists = p.is_file()
        any_exists = any_exists or exists
        checked.append({"path": rel, "exists": exists, "size_bytes": p.stat().st_size if exists else 0})
    return {"configured": True, "exists": any_exists, "paths_checked": checked}


def _lookup_source_status(
    code: str | None,
    status_by_code: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    if not code:
        return None
    return status_by_code.get(code)


def _latest_sync_for_code(code: str | None) -> dict[str, Any] | None:
    if not code:
        return None
    rows = list_sync_log(source_code=code, limit=1)
    return rows[0] if rows else None


def _derive_parser_status(
    entry: RegulatorySourceEntry,
    source_status: dict[str, Any] | None,
    last_sync: dict[str, Any] | None,
    doc_count: int | None,
) -> str:
    sync_status = (last_sync or {}).get("status", "").upper()
    if sync_status == "ERROR":
        return "failed"
    if source_status and source_status.get("is_stale"):
        return "stale"
    rev = (source_status or {}).get("revision") or ""
    if rev in ("unavailable",):
        return "failed"
    if doc_count is not None and doc_count < 0:
        return "runtime_only"
    if doc_count is not None and doc_count == 0 and not entry.local_paths:
        return "not_run"
    if doc_count is not None and entry.min_document_count > 0 and doc_count < entry.min_document_count:
        return "partial"
    if last_sync and sync_status == "OK":
        return "ok"
    if doc_count is not None and doc_count >= entry.min_document_count:
        return "ok"
    return "unknown"


def _derive_coverage_status(
    entry: RegulatorySourceEntry,
    local: dict[str, Any],
    doc_count: int | None,
    source_status: dict[str, Any] | None,
    parser_status: str,
) -> CoverageStatus:
    if doc_count is not None and doc_count < 0:
        return "not_applicable"
    has_local = bool(local.get("exists"))
    has_db = doc_count is not None and doc_count > 0
    if parser_status == "failed":
        return "parser_failed"
    if source_status and source_status.get("is_stale"):
        return "stale"
    if not has_local and not has_db:
        return "missing"
    if has_db or has_local:
        if (
            doc_count is not None
            and entry.min_document_count > 0
            and doc_count < entry.min_document_count
        ):
            return "partial"
        rev = (source_status or {}).get("revision") or ""
        if rev in ("seed", "unknown") and entry.authority_level in SOURCE_OF_TRUTH_LEVELS:
            return "partial"
        if parser_status == "partial":
            return "partial"
        if parser_status == "stale":
            return "stale"
        return "present"
    return "missing"


def _manual_review_required(
    entry: RegulatorySourceEntry,
    coverage_status: CoverageStatus,
) -> bool:
    if entry.manual_review_default:
        return True
    if entry.authority_level in ("advisory_letter", "commercial_mirror", "ai_extracted", "legacy_seed"):
        return True
    if coverage_status in ("missing", "partial", "parser_failed", "stale"):
        return True
    if entry.known_gaps:
        return coverage_status != "present"
    return False


def diagnose_source_entry(
    entry: RegulatorySourceEntry,
    *,
    status_by_code: dict[str, dict[str, Any]] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Диагностика одной записи реестра."""
    status_by_code = status_by_code or {r["source_code"]: r for r in list_source_status()}
    local = _local_paths_status(entry.local_paths)
    doc_count = _count_db_probe(entry.db_probe)
    src_st = _lookup_source_status(entry.source_status_code, status_by_code)
    last_sync = _latest_sync_for_code(entry.source_status_code)
    parser_status = _derive_parser_status(entry, src_st, last_sync, doc_count)
    coverage_status = _derive_coverage_status(entry, local, doc_count, src_st, parser_status)
    manual = _manual_review_required(entry, coverage_status)

    last_checked = (src_st or {}).get("synced_at")
    if last_sync and last_sync.get("synced_at"):
        last_checked = last_sync["synced_at"]

    last_success: str | None = None
    if last_sync and (last_sync.get("status") or "").upper() == "OK":
        last_success = last_sync.get("synced_at")
    elif src_st and not src_st.get("is_stale") and (src_st.get("revision") or "") not in (
        "unavailable",
        "seed",
        "unknown",
    ):
        last_success = src_st.get("synced_at")

    row = registry_entry_to_dict(entry)
    row.update(
        {
            "coverage_status": coverage_status,
            "parser_status": parser_status,
            "local_source": local,
            "local_document_count": doc_count if doc_count is not None and doc_count >= 0 else None,
            "last_checked_at": last_checked,
            "last_successful_sync_at": last_success,
            "source_status": src_st,
            "last_sync_log": last_sync,
            "manual_review_required": manual,
            "reported_at": generated_at,
        }
    )
    return row


def run_regulatory_source_completeness_report() -> dict[str, Any]:
    """
    Детерминированный gap-отчёт по всем записям реестра.

    Не меняет enforcement/broker; только диагностика для мониторинга и планирования sync.
    """
    generated_at = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
    status_by_code = {r["source_code"]: r for r in list_source_status()}

    sources: list[dict[str, Any]] = []
    for entry in sorted(REGULATORY_SOURCE_REGISTRY, key=lambda e: e.source_id):
        sources.append(
            diagnose_source_entry(entry, status_by_code=status_by_code, generated_at=generated_at)
        )

    by_coverage: dict[str, int] = {}
    by_authority: dict[str, int] = {}
    manual_queue: list[str] = []
    official_gaps: list[str] = []
    for s in sources:
        cov = s["coverage_status"]
        by_coverage[cov] = by_coverage.get(cov, 0) + 1
        auth = s["authority_level"]
        by_authority[auth] = by_authority.get(auth, 0) + 1
        if s.get("manual_review_required"):
            manual_queue.append(s["source_id"])
        if s.get("is_source_of_truth") and cov in ("missing", "partial", "stale", "parser_failed"):
            official_gaps.append(s["source_id"])

    return {
        "status": "OK",
        "generated_at": generated_at,
        "registry_version": "mvp-1",
        "summary": {
            "total_sources": len(sources),
            "by_coverage_status": dict(sorted(by_coverage.items())),
            "by_authority_level": dict(sorted(by_authority.items())),
            "authority_level_labels": AUTHORITY_LEVEL_LABELS,
            "manual_review_queue_count": len(manual_queue),
            "manual_review_queue": sorted(manual_queue),
            "official_source_gap_ids": sorted(official_gaps),
            "any_official_gap": bool(official_gaps),
        },
        "sources": sources,
        "future_sync_notes": [
            "Каждая запись реестра содержит sync_script — точка входа для следующих cursor-task на bulk download.",
            "source_status_code связывает отчёт с POST /api/sources/sync и sync_log.",
            "official_sgr: sync_sgr_registry.py (OData/CSV) + import_official_sgr_rules_to_ntm_v2.py для curated NTM v2.",
            "ПКР: замена commercial_mirror на официальный фид ФТС — отдельная задача без смены broker.",
        ],
    }


def list_registry_snapshot() -> dict[str, Any]:
    """Только реестр без DB-проб (для справочных API)."""
    from .regulatory_source_registry import list_registry_entries

    return {
        "status": "OK",
        "registry_version": "mvp-1",
        "authority_level_labels": AUTHORITY_LEVEL_LABELS,
        "entries": list_registry_entries(),
    }
