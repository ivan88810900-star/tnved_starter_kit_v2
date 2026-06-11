"""Официальный excise ingestion: dry-run / guarded apply (issue #42)."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..db import SessionLocal
from ..models.core import HsRate
from ..schemas.excise_ingestion import ExciseIngestionResponse, ExciseProvenance, ExciseRowCounts
from .normative_bundle import _normalize_rate_row
from .normative_store import append_sync_log, upsert_source_status
from .payment_data_coverage import run_payment_data_coverage_report
from .payment_revision_utils import (
    is_conservative_official_excise_source_url,
    is_excise_only_bundle_path,
    is_import_duty_bundle_path,
    is_official_excise_ingestion_revision,
    is_vat_only_bundle_path,
    is_wrong_domain_revision_in_excise_bundle,
    raw_rate_rows,
)
from .payment_source_registry import get_payment_source_entry

_BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
_EXCISE_SOURCE_CODE = "EEC_EXCISE"
_REGISTRY_SOURCE_CODE = "excise_official_contour"

_LOCAL_BUNDLE_CANDIDATES: tuple[str, ...] = (
    "data/raw_normative/eec_excise.json",
)

# Только excise-поля hs_rates — import-duty / VAT provenance не трогаем.
_EXCISE_APPLY_FIELDS = ("excise_type", "excise_value", "excise_basis")

_NON_OFFICIAL_EXCISE_REVISION_EXACT = frozenset(
    {"example", "seed", "unknown", "ambiguous", "legacy", "legacy_seed", "fallback", "test", "demo", "manual", "local-copy"}
)
_NON_OFFICIAL_EXCISE_REVISION_PREFIXES = (
    "seed-",
    "seed:",
    "seed_",
    "fallback-",
    "fallback:",
    "fallback_",
    "legacy-",
    "legacy_",
    "example-",
    "demo-",
    "test-",
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def _local_path_present(rel_path: str) -> bool:
    return (_BACKEND_ROOT / rel_path).is_file()


def _file_sha256_at(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_non_official_excise_revision_token(revision: str) -> bool:
    rev = (revision or "").strip().lower()
    if not rev:
        return True
    if rev in _NON_OFFICIAL_EXCISE_REVISION_EXACT:
        return True
    return any(rev.startswith(p) for p in _NON_OFFICIAL_EXCISE_REVISION_PREFIXES)


def _validate_official_excise_bundle_payload(
    payload: dict[str, Any], *, rel_path: str, checksum: str | None
) -> dict[str, Any]:
    revision = str(payload.get("revision") or "").strip().lower()
    fmt = str(payload.get("format") or "")

    rates, container_err = raw_rate_rows(payload)
    if container_err is not None:
        return {
            "status": "parser_failed",
            "reason": container_err,
            "error": f"bundle '{container_err.split('_')[1]}' must be a JSON array",
            "revision": revision,
            "record_count": 0,
            "checksum_sha256": checksum,
        }

    if any(not isinstance(r, dict) for r in rates):
        return {
            "status": "parser_failed",
            "reason": "malformed_rate_row",
            "error": "bundle rate rows must be JSON objects",
            "revision": revision,
            "record_count": len(rates),
            "rates_count": len(rates),
            "checksum_sha256": checksum,
        }

    raw_tnved = payload.get("tnved")
    tnved = raw_tnved if isinstance(raw_tnved, list) else []

    if _is_non_official_excise_revision_token(revision):
        return {
            "status": "manual_review_required",
            "reason": "non_official_bundle_revision",
            "revision": revision,
            "format": fmt,
            "record_count": len(rates) + len(tnved),
            "rates_count": len(rates),
            "checksum_sha256": checksum,
        }
    if is_wrong_domain_revision_in_excise_bundle(revision):
        return {
            "status": "manual_review_required",
            "reason": "wrong_domain_revision_in_excise_bundle",
            "revision": revision,
            "format": fmt,
            "record_count": len(rates) + len(tnved),
            "rates_count": len(rates),
            "checksum_sha256": checksum,
        }
    if not is_official_excise_ingestion_revision(revision):
        return {
            "status": "manual_review_required",
            "reason": "non_official_bundle_revision",
            "revision": revision,
            "format": fmt,
            "record_count": len(rates) + len(tnved),
            "rates_count": len(rates),
            "checksum_sha256": checksum,
        }

    explicit_unsafe: list[str] = []
    wrong_domain_rows: list[str] = []
    for r in rates:
        rev = str(r.get("source_revision") or "").strip().lower()
        if not rev:
            continue
        if is_wrong_domain_revision_in_excise_bundle(rev):
            wrong_domain_rows.append(rev)
            continue
        if not is_official_excise_ingestion_revision(rev):
            explicit_unsafe.append(rev)
    if wrong_domain_rows:
        return {
            "status": "manual_review_required",
            "reason": "wrong_domain_excise_row_revision",
            "revision": revision,
            "wrong_domain_row_revisions": sorted(set(wrong_domain_rows))[:10],
            "record_count": len(rates),
            "rates_count": len(rates),
            "checksum_sha256": checksum,
        }
    if explicit_unsafe:
        return {
            "status": "manual_review_required",
            "reason": "explicit_unsafe_row_revision",
            "revision": revision,
            "unsafe_row_revisions": sorted(set(explicit_unsafe))[:10],
            "record_count": len(rates),
            "rates_count": len(rates),
            "checksum_sha256": checksum,
        }

    return {
        "status": "parsed",
        "revision": revision,
        "format": fmt,
        "record_count": len(rates) + len(tnved),
        "rates_count": len(rates),
        "tnved_count": len(tnved),
        "checksum_sha256": checksum,
    }


def _load_bundle_payload(rel_path: str) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    path = _BACKEND_ROOT / rel_path
    if not path.is_file():
        return None, {
            "status": "missing_source",
            "error": f"file not found: {rel_path}",
            "record_count": 0,
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return None, {"status": "parser_failed", "error": str(exc), "record_count": 0}
    if not isinstance(payload, dict):
        return None, {"status": "parser_failed", "error": "bundle must be JSON object", "record_count": 0}
    checksum = _file_sha256_at(path)
    return payload, _validate_official_excise_bundle_payload(payload, rel_path=rel_path, checksum=checksum)


def discover_excise_bundle_path(*, rel_path: str | None = None) -> str | None:
    """Найти локальный official excise bundle (не import-duty / VAT paths)."""
    if rel_path:
        if not _local_path_present(rel_path):
            return None
        if is_import_duty_bundle_path(rel_path) or is_vat_only_bundle_path(rel_path):
            if not is_excise_only_bundle_path(rel_path):
                return None
        return rel_path

    entry = get_payment_source_entry(_REGISTRY_SOURCE_CODE)
    if entry:
        for p in entry.local_canonical_paths:
            if _local_path_present(p):
                return p

    for p in _LOCAL_BUNDLE_CANDIDATES:
        if _local_path_present(p):
            return p
    return None


def _raw_row_has_excise_signal(raw: dict[str, Any]) -> bool:
    ex_type = str(raw.get("excise_type") or "none").strip().lower()
    if ex_type in {"percent", "fixed"}:
        return True
    if raw.get("excise_value") is not None and str(raw.get("excise_value") or "").strip():
        return True
    if str(raw.get("excise_basis") or "").strip():
        return True
    return False


def _registry_official_excise_url() -> str | None:
    entry = get_payment_source_entry(_REGISTRY_SOURCE_CODE)
    url = (entry.official_url if entry else "") or ""
    return url.strip() or None


def _bundle_official_url(payload: dict[str, Any]) -> str:
    return str(
        payload.get("official_excise_url") or payload.get("source_url") or ""
    ).strip()


def _validate_excise_source_url(url: str) -> bool:
    return is_conservative_official_excise_source_url(
        url, registry_official_url=_registry_official_excise_url()
    )


def _extract_excise_rows(
    payload: dict[str, Any], rows_in: list[dict[str, Any]] | None = None
) -> tuple[str, list[dict[str, Any]], list[str]]:
    revision = str(payload.get("revision") or payload.get("source_revision") or "").strip()
    bundle_url = _bundle_official_url(payload)

    rows: list[dict[str, Any]] = []
    blockers: list[str] = []
    if rows_in is None:
        rows_in, container_err = raw_rate_rows(payload)
        if container_err is not None:
            return revision, [], [f"parser_failed: {container_err}"]

    for raw in rows_in or []:
        if not isinstance(raw, dict):
            return revision, [], ["parser_failed: malformed_rate_row (rate row not an object)"]
        if not _raw_row_has_excise_signal(raw):
            continue
        normalized = _normalize_rate_row(raw)
        if not normalized:
            blockers.append(f"invalid_rate_row: hs_code={raw.get('hs_code')!r}")
            continue
        if not str(normalized.get("source_revision") or "").strip():
            normalized["source_revision"] = revision
        row_rev = str(normalized.get("source_revision") or "").strip().lower()
        if is_wrong_domain_revision_in_excise_bundle(row_rev):
            blockers.append(
                f"wrong_domain_row_revision: {row_rev} for hs_code={normalized.get('hs_code')}"
            )
            continue
        if not is_official_excise_ingestion_revision(row_rev):
            blockers.append(
                f"unsafe_row_revision: {row_rev or '<empty>'} for hs_code={normalized.get('hs_code')}"
            )
            continue
        row_url = str(normalized.get("source_url") or "").strip() or bundle_url
        if not row_url:
            blockers.append(
                f"official_source_url_required: нет official source_url для hs_code={normalized.get('hs_code')}"
            )
            continue
        if not _validate_excise_source_url(row_url):
            blockers.append(
                f"unsafe_official_source_url: {row_url!r} для hs_code={normalized.get('hs_code')}"
            )
            continue
        normalized["source_url"] = row_url
        rows.append(normalized)
    return revision, rows, blockers


def _existing_hs_rate(db, hs_code: str) -> HsRate | None:
    lookup = str(hs_code or "").strip().replace(" ", "")
    if not lookup:
        return None
    return db.query(HsRate).filter(HsRate.hs_code == lookup).first()


def _row_needs_excise_value_update(existing: HsRate, row: dict[str, Any]) -> bool:
    if (existing.excise_type or "none") != str(row.get("excise_type") or "none"):
        return True
    if float(existing.excise_value or 0) != float(row.get("excise_value") or 0):
        return True
    if (existing.excise_basis or "").strip() != str(row.get("excise_basis") or "").strip():
        return True
    return False


def _row_needs_excise_provenance_stamp(
    existing: HsRate,
    row: dict[str, Any],
    *,
    bundle_revision: str,
    bundle_url: str | None,
) -> bool:
    """Missing/stale excise_source_* marker требует stamp даже при совпадающих excise values."""
    expected_code = _EXCISE_SOURCE_CODE
    expected_rev = str(row.get("source_revision") or bundle_revision or "").strip()
    expected_url = str(row.get("source_url") or bundle_url or "").strip()
    if (existing.excise_source_code or "").strip().upper() != expected_code:
        return True
    if not (existing.excise_source_revision or "").strip():
        return True
    if expected_rev and (existing.excise_source_revision or "").strip() != expected_rev:
        return True
    if not (existing.excise_source_url or "").strip():
        return True
    if expected_url and (existing.excise_source_url or "").strip() != expected_url:
        return True
    if existing.excise_synced_at is None:
        return True
    return False


def _row_needs_excise_apply_action(
    existing: HsRate,
    row: dict[str, Any],
    *,
    bundle_revision: str = "",
    bundle_url: str | None = None,
) -> bool:
    return _row_needs_excise_value_update(existing, row) or _row_needs_excise_provenance_stamp(
        existing,
        row,
        bundle_revision=bundle_revision,
        bundle_url=bundle_url,
    )


def _plan_excise_rows(rows: list[dict[str, Any]]) -> tuple[ExciseRowCounts, list[str]]:
    counts = ExciseRowCounts(total_in_source=len(rows))
    missing_blockers: list[str] = []
    with SessionLocal() as db:
        for row in rows:
            hs_code = str(row.get("hs_code") or "").strip()
            existing = _existing_hs_rate(db, hs_code)
            if existing is None:
                counts.blocked += 1
                missing_blockers.append(f"missing_hs_rate: {hs_code or '<empty>'}")
            elif _row_needs_excise_apply_action(existing, row):
                counts.update += 1
            else:
                counts.skip += 1
    return counts, missing_blockers


def _build_provenance(
    *,
    rel_path: str,
    revision: str,
    payload: dict[str, Any],
    parser_result: dict[str, Any],
    loaded_at: str,
) -> ExciseProvenance:
    entry = get_payment_source_entry(_REGISTRY_SOURCE_CODE)
    return ExciseProvenance(
        source_code=_EXCISE_SOURCE_CODE,
        source_name=entry.name if entry else "Официальный контур акцизных ставок",
        legal_basis=entry.legal_basis if entry else "НК РФ / подзаконные акты по акцизам",
        official_url=_bundle_official_url(payload) or None,
        revision=revision or None,
        checksum_sha256=parser_result.get("checksum_sha256") or _file_sha256_at(_BACKEND_ROOT / rel_path),
        effective_from=str(payload.get("effective_from") or "").strip() or None,
        effective_to=str(payload.get("effective_to") or "").strip() or None,
        loaded_at=loaded_at,
        local_path=rel_path,
    )


def _blocked_response(
    *,
    status: str,
    mode: str,
    dry_run: bool,
    blockers: list[str],
    parser_result: dict[str, Any] | None = None,
    provenance: ExciseProvenance | None = None,
    row_counts: ExciseRowCounts | None = None,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    response = ExciseIngestionResponse(
        status=status,  # type: ignore[arg-type]
        mode=mode,  # type: ignore[arg-type]
        dry_run=dry_run,
        db_mutated=False,
        provenance=provenance,
        row_counts=row_counts or ExciseRowCounts(),
        blockers=blockers,
        parser_result=parser_result or {},
        notes=notes or [],
    )
    return response.model_dump(mode="json")


def _validate_bundle_for_ingest(
    rel_path: str,
) -> tuple[dict[str, Any] | None, dict[str, Any], str, list[dict[str, Any]], list[str]]:
    if is_import_duty_bundle_path(rel_path) and not is_excise_only_bundle_path(rel_path):
        return None, {"status": "manual_review_required", "reason": "import_duty_only_bundle"}, "", [], [
            "manual_review_required: import_duty_only_bundle_not_excise"
        ]
    if is_vat_only_bundle_path(rel_path):
        return None, {"status": "manual_review_required", "reason": "vat_only_bundle"}, "", [], [
            "manual_review_required: vat_only_bundle_not_excise"
        ]

    payload, parser_result = _load_bundle_payload(rel_path)
    if payload is None:
        status = parser_result.get("status")
        if status == "missing_source":
            return None, parser_result, "", [], ["missing_official_source: bundle file not found"]
        if status == "parser_failed":
            return None, parser_result, "", [], [
                f"parser_failed: {parser_result.get('error') or 'invalid bundle payload'}"
            ]
        return None, parser_result, "", [], [
            f"parser_failed: {parser_result.get('error') or status or 'unloadable bundle'}"
        ]

    parse_status = parser_result.get("status")
    if parse_status == "missing_source":
        return payload, parser_result, "", [], ["missing_official_source: bundle file not found"]
    if parse_status == "parser_failed":
        return payload, parser_result, "", [], [f"parser_failed: {parser_result.get('error', '')}"]
    if parse_status == "manual_review_required":
        reason = parser_result.get("reason") or "non_official_bundle"
        return payload, parser_result, "", [], [f"manual_review_required: {reason}"]

    rows_in, container_err = raw_rate_rows(payload)
    if container_err is not None:
        return payload, parser_result, "", [], [f"parser_failed: {container_err}"]

    revision, rows, row_blockers = _extract_excise_rows(payload, rows_in)
    blockers: list[str] = []
    if is_wrong_domain_revision_in_excise_bundle(revision):
        blockers.append(f"wrong_domain_bundle_revision: {revision}")
    elif not is_official_excise_ingestion_revision(revision):
        blockers.append(f"non_official_bundle_revision: {revision or '<empty>'}")
    if row_blockers:
        blockers.extend(row_blockers)
    if not rows:
        blockers.append("no_importable_excise_rows")
    bundle_url = _bundle_official_url(payload) if payload else ""
    if bundle_url and not _validate_excise_source_url(bundle_url):
        blockers.append(f"unsafe_official_bundle_url: {bundle_url!r}")
    return payload, parser_result, revision, rows, blockers


def run_excise_dry_run(*, rel_path: str | None = None) -> dict[str, Any]:
    """Dry-run: insert/update/skip counts и blockers без мутации БД."""
    loaded_at = _utc_now_iso()
    bundle_path = discover_excise_bundle_path(rel_path=rel_path)
    if not bundle_path:
        return _blocked_response(
            status="missing_official_source",
            mode="dry_run",
            dry_run=True,
            blockers=[
                "Нет локального official excise bundle. "
                f"Ожидается один из: {', '.join(_LOCAL_BUNDLE_CANDIDATES)} "
                "или local_canonical_paths в payment_source_registry."
            ],
            notes=["Dry-run не мутирует БД.", "SourceStatus/SyncLog не записываются."],
        )

    payload, parser_result, revision, rows, blockers = _validate_bundle_for_ingest(bundle_path)
    provenance = _build_provenance(
        rel_path=bundle_path,
        revision=revision,
        payload=payload or {},
        parser_result=parser_result,
        loaded_at=loaded_at,
    )

    if blockers:
        status = "manual_review_required"
        if any("missing_official_source" in b for b in blockers):
            status = "missing_official_source"
        elif any("parser_failed" in b for b in blockers):
            status = "parser_failed"
        return _blocked_response(
            status=status,
            mode="dry_run",
            dry_run=True,
            blockers=blockers,
            parser_result=parser_result,
            provenance=provenance,
            row_counts=ExciseRowCounts(total_in_source=len(rows), blocked=len(rows)),
            notes=["Dry-run не мутирует БД.", "SourceStatus/SyncLog не записываются."],
        )

    row_counts, missing_blockers = _plan_excise_rows(rows)
    dry_blockers = list(missing_blockers)
    if row_counts.blocked > 0:
        dry_blockers.append(
            f"excise_rows_without_hs_rate: {row_counts.blocked} "
            "(excise slice не создаёт hs_rates/duty_rate=0)."
        )
    if dry_blockers:
        return _blocked_response(
            status="manual_review_required",
            mode="dry_run",
            dry_run=True,
            blockers=dry_blockers,
            parser_result=parser_result,
            provenance=provenance,
            row_counts=row_counts,
            notes=["Dry-run не мутирует БД.", "SourceStatus/SyncLog не записываются."],
        )
    coverage = run_payment_data_coverage_report()
    response = ExciseIngestionResponse(
        status="OK",
        mode="dry_run",
        dry_run=True,
        db_mutated=False,
        provenance=provenance,
        row_counts=row_counts,
        blockers=[],
        parser_result=parser_result,
        coverage_link={
            "excise_status": (coverage.get("summary") or {}).get("excise", {}).get("status"),
            "generated_at": coverage.get("generated_at"),
        },
        notes=[
            "Dry-run не мутирует БД.",
            "Apply доступен только при status=OK dry-run и official provenance.",
            "Coverage present требует official excise rows (не seed/fallback).",
        ],
    )
    return response.model_dump(mode="json")


def _apply_excise_field(existing: HsRate, row: dict[str, Any], field: str) -> None:
    if field in row and row[field] is not None:
        setattr(existing, field, row[field])


def _stamp_excise_row_provenance(
    existing: HsRate,
    *,
    row: dict[str, Any],
    bundle_revision: str,
    bundle_url: str | None,
    synced_at: datetime,
) -> None:
    existing.excise_source_code = _EXCISE_SOURCE_CODE
    existing.excise_source_revision = str(row.get("source_revision") or bundle_revision or "").strip()
    existing.excise_source_url = str(row.get("source_url") or bundle_url or "").strip()
    existing.excise_synced_at = synced_at


def _apply_excise_rows(
    rows: list[dict[str, Any]],
    *,
    bundle_revision: str,
    bundle_url: str | None,
    synced_at: datetime,
) -> ExciseRowCounts | None:
    counts = ExciseRowCounts(total_in_source=len(rows))

    with SessionLocal() as db:
        try:
            pending: list[tuple[HsRate, dict[str, Any]]] = []
            for row in rows:
                hs_code = str(row.get("hs_code") or "").strip().replace(" ", "")
                if not hs_code:
                    db.rollback()
                    return None
                existing = _existing_hs_rate(db, hs_code)
                if existing is None:
                    db.rollback()
                    return None
                pending.append((existing, row))

            for existing, row in pending:
                needs_values = _row_needs_excise_value_update(existing, row)
                needs_stamp = _row_needs_excise_provenance_stamp(
                    existing,
                    row,
                    bundle_revision=bundle_revision,
                    bundle_url=bundle_url,
                )
                if needs_values:
                    for k in _EXCISE_APPLY_FIELDS:
                        _apply_excise_field(existing, row, k)
                if needs_values or needs_stamp:
                    _stamp_excise_row_provenance(
                        existing,
                        row=row,
                        bundle_revision=bundle_revision,
                        bundle_url=bundle_url,
                        synced_at=synced_at,
                    )
                    counts.update += 1
                else:
                    counts.skip += 1
            db.commit()
        except Exception:
            db.rollback()
            raise
    return counts


def run_excise_apply(*, rel_path: str | None = None) -> dict[str, Any]:
    """Guarded apply: мутирует БД только при official provenance и отсутствии blockers."""
    loaded_at = _utc_now_iso()
    bundle_path = discover_excise_bundle_path(rel_path=rel_path)
    if not bundle_path:
        return _blocked_response(
            status="missing_official_source",
            mode="apply",
            dry_run=False,
            blockers=["missing_official_source: локальный official excise bundle не найден"],
            notes=["Apply отменён — SourceStatus/SyncLog не записаны."],
        )

    payload, parser_result, revision, rows, blockers = _validate_bundle_for_ingest(bundle_path)
    provenance = _build_provenance(
        rel_path=bundle_path,
        revision=revision,
        payload=payload or {},
        parser_result=parser_result,
        loaded_at=loaded_at,
    )

    if blockers:
        status = "manual_review_required"
        if any("missing_official_source" in b for b in blockers):
            status = "missing_official_source"
        elif any("parser_failed" in b for b in blockers):
            status = "parser_failed"
        return _blocked_response(
            status=status,
            mode="apply",
            dry_run=False,
            blockers=blockers,
            parser_result=parser_result,
            provenance=provenance,
            notes=["Apply отменён — SourceStatus/SyncLog не записаны."],
        )

    row_counts, missing_blockers = _plan_excise_rows(rows)
    if row_counts.blocked > 0:
        apply_blockers = list(missing_blockers)
        apply_blockers.append(
            f"excise_rows_without_hs_rate: {row_counts.blocked} "
            "(excise slice не создаёт hs_rates/duty_rate=0)."
        )
        return _blocked_response(
            status="manual_review_required",
            mode="apply",
            dry_run=False,
            blockers=apply_blockers,
            parser_result=parser_result,
            provenance=provenance,
            row_counts=row_counts,
            notes=[
                "Apply атомарно отменён — ни одна excise row не обновлена.",
                "SourceStatus/SyncLog не записаны.",
            ],
        )

    synced_at = datetime.now(timezone.utc).replace(tzinfo=None)
    applied = _apply_excise_rows(
        rows,
        bundle_revision=revision,
        bundle_url=provenance.official_url,
        synced_at=synced_at,
    )
    if applied is None:
        return _blocked_response(
            status="manual_review_required",
            mode="apply",
            dry_run=False,
            blockers=list(missing_blockers) + ["atomic_apply_aborted: missing_hs_rate detected during apply"],
            parser_result=parser_result,
            provenance=provenance,
            row_counts=row_counts,
            notes=["Apply атомарно отменён — ни одна excise row не обновлена.", "SourceStatus/SyncLog не записаны."],
        )
    row_counts = applied

    entry = get_payment_source_entry(_REGISTRY_SOURCE_CODE)
    note_txt = (
        f"excise apply {bundle_path}: revision={revision}; "
        f"update={row_counts.update}, skip={row_counts.skip}, "
        f"blocked={row_counts.blocked}; checksum={provenance.checksum_sha256 or 'n/a'}"
    )
    upsert_source_status(
        source_code=_EXCISE_SOURCE_CODE,
        source_name=entry.name if entry else provenance.source_name,
        source_url=provenance.official_url or bundle_path,
        revision=revision,
        is_stale=False,
        note=note_txt,
    )
    append_sync_log(
        source_code=_EXCISE_SOURCE_CODE,
        status="OK",
        revision=revision,
        rows_affected=row_counts.update,
        note=note_txt,
    )

    coverage = run_payment_data_coverage_report()
    response = ExciseIngestionResponse(
        status="OK",
        mode="apply",
        dry_run=False,
        db_mutated=row_counts.update > 0,
        provenance=provenance,
        row_counts=row_counts,
        blockers=[],
        parser_result=parser_result,
        coverage_link={
            "excise_status": (coverage.get("summary") or {}).get("excise", {}).get("status"),
            "excise_authority_level": (coverage.get("summary") or {}).get("excise", {}).get("authority_level"),
            "generated_at": coverage.get("generated_at"),
        },
        notes=[
            "Excise slice: обновлены только excise_type/excise_value/excise_basis.",
            "Import-duty / VAT поля (duty_rate, source_revision, vat_source_*) не изменяются.",
        ],
    )
    return response.model_dump(mode="json")
