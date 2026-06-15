"""Официальный anti-dumping ingestion ЕЭК: dry-run / guarded apply (issue #45)."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..db import SessionLocal
from ..models.core import SourceStatus, SyncLog
from ..models.tnved import SpecialDuty
from ..schemas.anti_dumping_ingestion import (
    AntiDumpingIngestionResponse,
    AntiDumpingProvenance,
    AntiDumpingRowCounts,
)
from .normative_store import append_sync_log, upsert_source_status
from .payment_data_coverage import run_payment_data_coverage_report
from .payment_revision_utils import (
    is_anti_dumping_only_bundle_path,
    is_import_duty_bundle_path,
    is_official_anti_dumping_ingestion_revision,
    is_safe_official_anti_dumping_source_url,
    is_vat_only_bundle_path,
    is_wrong_domain_revision_in_anti_dumping_bundle,
    raw_measure_rows,
)
from .payment_source_registry import get_payment_source_entry


def _registry_official_anti_dumping_url() -> str | None:
    entry = get_payment_source_entry(_REGISTRY_SOURCE_CODE)
    url = (entry.official_url if entry else "") or ""
    return url.strip() or None


def _is_unsafe_anti_dumping_url(url: str) -> bool:
    """Строгий allowlist: только eec.eaeunion.org / registry domain через HTTPS."""
    return not is_safe_official_anti_dumping_source_url(
        url, registry_official_url=_registry_official_anti_dumping_url()
    )

_BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
_ANTI_DUMPING_SOURCE_CODE = "EEC_ANTI_DUMPING"
_REGISTRY_SOURCE_CODE = "trade_remedies_official"

_LOCAL_BUNDLE_CANDIDATES: tuple[str, ...] = (
    "data/raw_normative/eec_anti_dumping.json",
)

_NON_OFFICIAL_REVISION_EXACT = frozenset(
    {
        "example",
        "seed",
        "unknown",
        "ambiguous",
        "legacy",
        "legacy_seed",
        "fallback",
        "test",
        "demo",
        "manual",
        "local-copy",
    }
)
_NON_OFFICIAL_REVISION_PREFIXES = (
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


def _is_non_official_revision_token(revision: str) -> bool:
    rev = (revision or "").strip().lower()
    if not rev:
        return True
    if rev in _NON_OFFICIAL_REVISION_EXACT:
        return True
    return any(rev.startswith(p) for p in _NON_OFFICIAL_REVISION_PREFIXES)


def _hs_prefix_from_raw(raw: dict[str, Any]) -> str:
    code = re.sub(r"\D", "", str(raw.get("hs_code") or ""))[:10]
    prefix = re.sub(r"\D", "", str(raw.get("hs_prefix") or raw.get("hs_code_prefix") or ""))[:16]
    if code and len(code) >= 4:
        explicit_prefix_scope = raw.get("prefix_scope") is True or raw.get("prefix_rate") is True
        if len(code) >= 10 and not explicit_prefix_scope:
            return code
        if prefix:
            return prefix[:16]
        return code[:4]
    return prefix[:16]


def _validate_official_anti_dumping_bundle_payload(
    payload: dict[str, Any], *, rel_path: str, checksum: str | None
) -> dict[str, Any]:
    revision = str(payload.get("revision") or "").strip().lower()
    fmt = str(payload.get("format") or "")

    measures, container_err = raw_measure_rows(payload)
    if container_err is not None:
        return {
            "status": "parser_failed",
            "reason": container_err,
            "error": f"bundle '{container_err.split('_')[1]}' must be a JSON array",
            "revision": revision,
            "record_count": 0,
            "checksum_sha256": checksum,
        }

    if any(not isinstance(m, dict) for m in measures):
        return {
            "status": "parser_failed",
            "reason": "malformed_measure_row",
            "error": "bundle measure rows must be JSON objects",
            "revision": revision,
            "record_count": len(measures),
            "measures_count": len(measures),
            "checksum_sha256": checksum,
        }

    if _is_non_official_revision_token(revision):
        return {
            "status": "manual_review_required",
            "reason": "non_official_bundle_revision",
            "revision": revision,
            "format": fmt,
            "record_count": len(measures),
            "measures_count": len(measures),
            "checksum_sha256": checksum,
        }
    if is_wrong_domain_revision_in_anti_dumping_bundle(revision):
        return {
            "status": "manual_review_required",
            "reason": "wrong_domain_revision_in_anti_dumping_bundle",
            "revision": revision,
            "format": fmt,
            "record_count": len(measures),
            "measures_count": len(measures),
            "checksum_sha256": checksum,
        }
    if not is_official_anti_dumping_ingestion_revision(revision):
        return {
            "status": "manual_review_required",
            "reason": "non_official_bundle_revision",
            "revision": revision,
            "format": fmt,
            "record_count": len(measures),
            "measures_count": len(measures),
            "checksum_sha256": checksum,
        }

    bundle_url = str(payload.get("official_url") or payload.get("source_url") or "").strip()
    if _is_unsafe_anti_dumping_url(bundle_url):
        return {
            "status": "manual_review_required",
            "reason": "unsafe_official_source_url",
            "revision": revision,
            "record_count": len(measures),
            "measures_count": len(measures),
            "checksum_sha256": checksum,
        }

    explicit_unsafe: list[str] = []
    wrong_domain_rows: list[str] = []
    for row in measures:
        rev = str(row.get("source_revision") or "").strip().lower()
        if not rev:
            continue
        if is_wrong_domain_revision_in_anti_dumping_bundle(rev):
            wrong_domain_rows.append(rev)
            continue
        if not is_official_anti_dumping_ingestion_revision(rev):
            explicit_unsafe.append(rev)
    if wrong_domain_rows:
        return {
            "status": "manual_review_required",
            "reason": "wrong_domain_row_revision",
            "revision": revision,
            "wrong_domain_row_revisions": sorted(set(wrong_domain_rows))[:10],
            "record_count": len(measures),
            "measures_count": len(measures),
            "checksum_sha256": checksum,
        }
    if explicit_unsafe:
        return {
            "status": "manual_review_required",
            "reason": "explicit_unsafe_row_revision",
            "revision": revision,
            "unsafe_row_revisions": sorted(set(explicit_unsafe))[:10],
            "record_count": len(measures),
            "measures_count": len(measures),
            "checksum_sha256": checksum,
        }

    return {
        "status": "parsed",
        "revision": revision,
        "format": fmt,
        "record_count": len(measures),
        "measures_count": len(measures),
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
    return payload, _validate_official_anti_dumping_bundle_payload(payload, rel_path=rel_path, checksum=checksum)


def discover_anti_dumping_bundle_path(*, rel_path: str | None = None) -> str | None:
    """Найти локальный official anti-dumping bundle."""
    if rel_path:
        if not _local_path_present(rel_path):
            return None
        if not is_anti_dumping_only_bundle_path(rel_path):
            return None
        return rel_path

    entry = get_payment_source_entry(_REGISTRY_SOURCE_CODE)
    if entry:
        for p in entry.local_canonical_paths:
            if is_anti_dumping_only_bundle_path(p) and _local_path_present(p):
                return p

    for p in _LOCAL_BUNDLE_CANDIDATES:
        if _local_path_present(p):
            return p
    return None


def _raw_row_has_anti_dumping_signal(raw: dict[str, Any]) -> bool:
    mt = str(raw.get("measure_type") or "").strip().lower()
    if mt == "anti_dumping":
        return True
    if raw.get("has_antidumping") or raw.get("antidumping_type"):
        return True
    if raw.get("rate_type") or raw.get("rate_value") is not None or raw.get("rate_percent") is not None:
        return True
    if raw.get("rate_specific") is not None:
        return True
    return False


def _normalize_measure_row(raw: dict[str, Any]) -> dict[str, Any] | None:
    prefix = _hs_prefix_from_raw(raw)
    if not prefix:
        return None
    origin = str(raw.get("origin_country") or raw.get("country_iso") or raw.get("country") or "").strip().upper()
    rate_type = str(
        raw.get("rate_type") or raw.get("antidumping_type") or raw.get("duty_type") or "percent"
    ).strip().lower()
    rate_value = raw.get("rate_value")
    if rate_value is None:
        rate_value = raw.get("rate_percent")
    if rate_value is None:
        rate_value = raw.get("antidumping_value")
    rate_specific = float(raw.get("rate_specific") or raw.get("rate_specific_value") or 0.0)
    currency = str(raw.get("currency_code") or raw.get("currency") or "").strip().upper()
    regulatory_act = str(
        raw.get("regulatory_act") or raw.get("legal_basis") or raw.get("document_basis") or ""
    ).strip()
    if not regulatory_act:
        return None
    row: dict[str, Any] = {
        "hs_code_prefix": prefix,
        "origin_country": origin,
        "measure_type": "anti_dumping",
        "rate_type": rate_type,
        "rate_percent": float(rate_value or 0.0) if rate_type == "percent" else 0.0,
        "rate_specific": rate_specific if rate_type in ("fixed", "specific") else 0.0,
        "currency_code": currency,
        "regulatory_act": regulatory_act,
        "manufacturer_exporter": str(raw.get("manufacturer_exporter") or raw.get("manufacturer") or "").strip(),
        "product_description": str(raw.get("product_description") or raw.get("description") or "").strip(),
        "effective_from": str(raw.get("effective_from") or raw.get("valid_from") or "").strip(),
        "effective_to": str(raw.get("effective_to") or raw.get("valid_to") or "").strip(),
        "source_revision": str(raw.get("source_revision") or "").strip(),
        "source_url": str(raw.get("source_url") or "").strip(),
    }
    return row


def _extract_anti_dumping_rows(
    payload: dict[str, Any], rows_in: list[dict[str, Any]] | None = None
) -> tuple[str, list[dict[str, Any]], list[str]]:
    revision = str(payload.get("revision") or payload.get("source_revision") or "").strip()
    bundle_url = str(payload.get("official_url") or payload.get("source_url") or "").strip()
    effective_from = str(payload.get("effective_from") or "").strip() or None
    effective_to = str(payload.get("effective_to") or "").strip() or None

    rows: list[dict[str, Any]] = []
    blockers: list[str] = []
    if rows_in is None:
        rows_in, container_err = raw_measure_rows(payload)
        if container_err is not None:
            return revision, [], [f"parser_failed: {container_err}"]

    for raw in rows_in or []:
        if not isinstance(raw, dict):
            return revision, [], ["parser_failed: malformed_measure_row (row not an object)"]
        if not _raw_row_has_anti_dumping_signal(raw):
            continue
        normalized = _normalize_measure_row(raw)
        if not normalized:
            blockers.append(
                f"invalid_measure_row: hs={raw.get('hs_code')!r} origin={raw.get('origin_country')!r}"
            )
            continue
        if not str(normalized.get("source_revision") or "").strip():
            normalized["source_revision"] = revision
        row_rev = str(normalized.get("source_revision") or "").strip().lower()
        if is_wrong_domain_revision_in_anti_dumping_bundle(row_rev):
            blockers.append(
                f"wrong_domain_row_revision: {row_rev} for hs_prefix={normalized.get('hs_code_prefix')}"
            )
            continue
        if not is_official_anti_dumping_ingestion_revision(row_rev):
            blockers.append(
                f"unsafe_row_revision: {row_rev or '<empty>'} for hs_prefix={normalized.get('hs_code_prefix')}"
            )
            continue
        row_url = str(normalized.get("source_url") or "").strip() or bundle_url
        if _is_unsafe_anti_dumping_url(row_url):
            blockers.append(
                f"unsafe_official_source_url: {row_url or '<empty>'} "
                f"for hs_prefix={normalized.get('hs_code_prefix')}"
            )
            continue
        normalized["source_url"] = row_url
        if effective_from and not str(normalized.get("effective_from") or "").strip():
            normalized["effective_from"] = effective_from
        if effective_to and not str(normalized.get("effective_to") or "").strip():
            normalized["effective_to"] = effective_to
        rows.append(normalized)
    return revision, rows, blockers


def _norm_identity_text(value: Any) -> str:
    """Нормализация текста для сравнения идентичности меры (whitespace/регистр)."""
    return " ".join(str(value or "").split()).casefold()


def _special_duty_identity(obj: Any) -> tuple[str, ...]:
    """Детерминированный ключ идентичности официальной антидемпинговой меры.

    Две меры считаются одной только при полном совпадении: один товар (hs_prefix),
    одна страна происхождения, один нормативный акт, один производитель/экспортёр,
    одно окно действия и один товарный scope. Иначе — это разные меры и они не
    должны перезаписывать друг друга.

    Принимает как SpecialDuty ORM-объект, так и normalized row dict.
    """
    if isinstance(obj, dict):
        get = obj.get
    else:
        get = lambda key: getattr(obj, key, None)  # noqa: E731
    return (
        "anti_dumping",
        str(get("hs_code_prefix") or "").strip(),
        str(get("origin_country") or "").strip(),
        _norm_identity_text(get("regulatory_act")),
        _norm_identity_text(get("manufacturer_exporter")),
        _norm_identity_text(get("product_description")),
        str(get("effective_from") or "").strip(),
        str(get("effective_to") or "").strip(),
    )


def _lookup_special_duty(db, row: dict[str, Any]) -> SpecialDuty | None:
    target = _special_duty_identity(row)
    candidates = (
        db.query(SpecialDuty)
        .filter(
            SpecialDuty.hs_code_prefix == row["hs_code_prefix"],
            SpecialDuty.origin_country == row["origin_country"],
            SpecialDuty.measure_type == "anti_dumping",
        )
        .all()
    )
    for candidate in candidates:
        if _special_duty_identity(candidate) == target:
            return candidate
    return None


def _row_needs_update(existing: SpecialDuty, row: dict[str, Any]) -> bool:
    if float(existing.rate_percent or 0) != float(row.get("rate_percent") or 0):
        return True
    if float(existing.rate_specific or 0) != float(row.get("rate_specific") or 0):
        return True
    if (existing.currency_code or "") != str(row.get("currency_code") or ""):
        return True
    if (existing.manufacturer_exporter or "").strip() != str(row.get("manufacturer_exporter") or "").strip():
        return True
    if (existing.product_description or "").strip() != str(row.get("product_description") or "").strip():
        return True
    if str(row.get("effective_from") or "").strip() and (existing.effective_from or "").strip() != str(
        row.get("effective_from") or ""
    ).strip():
        return True
    if str(row.get("effective_to") or "").strip() and (existing.effective_to or "").strip() != str(
        row.get("effective_to") or ""
    ).strip():
        return True
    if (existing.source_code or "") != _ANTI_DUMPING_SOURCE_CODE:
        return True
    if (existing.source_revision or "") != str(row.get("source_revision") or ""):
        return True
    if (existing.source_url or "").strip() != str(row.get("source_url") or "").strip():
        return True
    return False


def _plan_anti_dumping_rows(rows: list[dict[str, Any]]) -> AntiDumpingRowCounts:
    counts = AntiDumpingRowCounts(total_in_source=len(rows))
    with SessionLocal() as db:
        for row in rows:
            existing = _lookup_special_duty(db, row)
            if existing is None:
                counts.insert += 1
            elif _row_needs_update(existing, row):
                counts.update += 1
            else:
                counts.skip += 1
    return counts


def _build_provenance(
    *,
    rel_path: str,
    revision: str,
    payload: dict[str, Any],
    parser_result: dict[str, Any],
    loaded_at: str,
) -> AntiDumpingProvenance:
    entry = get_payment_source_entry(_REGISTRY_SOURCE_CODE)
    return AntiDumpingProvenance(
        source_code=_ANTI_DUMPING_SOURCE_CODE,
        source_name=entry.name if entry else "Официальный контур антидемпинговых мер",
        legal_basis=entry.legal_basis if entry else "Решения ЕЭК / Комиссии по торговым мерам",
        official_url=str(payload.get("official_url") or payload.get("source_url") or "").strip() or None,
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
    provenance: AntiDumpingProvenance | None = None,
    row_counts: AntiDumpingRowCounts | None = None,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    response = AntiDumpingIngestionResponse(
        status=status,  # type: ignore[arg-type]
        mode=mode,  # type: ignore[arg-type]
        dry_run=dry_run,
        db_mutated=False,
        provenance=provenance,
        row_counts=row_counts or AntiDumpingRowCounts(),
        blockers=blockers,
        parser_result=parser_result or {},
        notes=notes or [],
    )
    return response.model_dump(mode="json")


def _validate_bundle_for_ingest(
    rel_path: str,
) -> tuple[dict[str, Any] | None, dict[str, Any], str, list[dict[str, Any]], list[str]]:
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
    if parse_status == "parser_failed":
        return payload, parser_result, "", [], [f"parser_failed: {parser_result.get('error', '')}"]
    if parse_status == "manual_review_required":
        reason = parser_result.get("reason") or "non_official_bundle"
        return payload, parser_result, "", [], [f"manual_review_required: {reason}"]

    measures_in, container_err = raw_measure_rows(payload)
    if container_err is not None:
        return payload, parser_result, "", [], [f"parser_failed: {container_err}"]

    revision, rows, row_blockers = _extract_anti_dumping_rows(payload, measures_in)
    blockers: list[str] = []
    if is_import_duty_bundle_path(rel_path) or is_vat_only_bundle_path(rel_path):
        blockers.append("manual_review_required: wrong_domain_bundle_path")
    if is_wrong_domain_revision_in_anti_dumping_bundle(revision):
        blockers.append(f"wrong_domain_bundle_revision: {revision}")
    elif not is_official_anti_dumping_ingestion_revision(revision):
        blockers.append(f"non_official_bundle_revision: {revision or '<empty>'}")
    if row_blockers:
        blockers.extend(row_blockers)
    if not rows:
        blockers.append("no_importable_anti_dumping_rows")
    return payload, parser_result, revision, rows, blockers


def run_anti_dumping_dry_run(*, rel_path: str | None = None) -> dict[str, Any]:
    """Dry-run: insert/update/skip counts и blockers без мутации БД."""
    loaded_at = _utc_now_iso()
    bundle_path = discover_anti_dumping_bundle_path(rel_path=rel_path)
    if not bundle_path:
        return _blocked_response(
            status="missing_official_source",
            mode="dry_run",
            dry_run=True,
            blockers=[
                "Нет локального official anti-dumping bundle. "
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
            row_counts=AntiDumpingRowCounts(total_in_source=len(rows), blocked=len(rows)),
            notes=["Dry-run не мутирует БД.", "SourceStatus/SyncLog не записываются."],
        )

    row_counts = _plan_anti_dumping_rows(rows)
    coverage = run_payment_data_coverage_report()
    response = AntiDumpingIngestionResponse(
        status="OK",
        mode="dry_run",
        dry_run=True,
        db_mutated=False,
        provenance=provenance,
        row_counts=row_counts,
        blockers=[],
        parser_result=parser_result,
        coverage_link={
            "trade_remedies_status": (coverage.get("summary") or {}).get("trade_remedies", {}).get("status"),
            "generated_at": coverage.get("generated_at"),
        },
        notes=[
            "Dry-run не мутирует БД.",
            "Apply доступен только при status=OK dry-run и official provenance.",
            "Coverage present требует official anti-dumping rows (не seed/fallback).",
        ],
    )
    return response.model_dump(mode="json")


def _stamp_row_provenance(existing: SpecialDuty, *, row: dict[str, Any], synced_at: datetime) -> None:
    existing.source_code = _ANTI_DUMPING_SOURCE_CODE
    existing.source_revision = str(row.get("source_revision") or "").strip()
    existing.source_url = str(row.get("source_url") or "").strip()
    existing.synced_at = synced_at
    existing.measure_type = "anti_dumping"


def _apply_row_fields(existing: SpecialDuty, row: dict[str, Any]) -> None:
    existing.hs_code_prefix = row["hs_code_prefix"]
    existing.origin_country = row["origin_country"]
    existing.rate_percent = float(row.get("rate_percent") or 0.0)
    existing.rate_specific = float(row.get("rate_specific") or 0.0)
    existing.currency_code = str(row.get("currency_code") or "")
    existing.regulatory_act = row["regulatory_act"]
    existing.manufacturer_exporter = str(row.get("manufacturer_exporter") or "")
    existing.product_description = str(row.get("product_description") or "")
    if str(row.get("effective_from") or "").strip():
        existing.effective_from = str(row.get("effective_from") or "")
    if str(row.get("effective_to") or "").strip():
        existing.effective_to = str(row.get("effective_to") or "")


def _apply_anti_dumping_rows(
    rows: list[dict[str, Any]],
    *,
    synced_at: datetime,
) -> AntiDumpingRowCounts | None:
    counts = AntiDumpingRowCounts(total_in_source=len(rows))
    with SessionLocal() as db:
        try:
            for row in rows:
                if not row.get("hs_code_prefix") or not row.get("regulatory_act"):
                    db.rollback()
                    return None
                existing = _lookup_special_duty(db, row)
                if existing is None:
                    entity = SpecialDuty(
                        hs_code_prefix=row["hs_code_prefix"],
                        origin_country=row["origin_country"],
                        rate_percent=float(row.get("rate_percent") or 0.0),
                        rate_specific=float(row.get("rate_specific") or 0.0),
                        currency_code=str(row.get("currency_code") or ""),
                        regulatory_act=row["regulatory_act"],
                        measure_type="anti_dumping",
                        manufacturer_exporter=str(row.get("manufacturer_exporter") or ""),
                        product_description=str(row.get("product_description") or ""),
                        effective_from=str(row.get("effective_from") or ""),
                        effective_to=str(row.get("effective_to") or ""),
                    )
                    _stamp_row_provenance(entity, row=row, synced_at=synced_at)
                    db.add(entity)
                    counts.insert += 1
                elif _row_needs_update(existing, row):
                    _apply_row_fields(existing, row)
                    _stamp_row_provenance(existing, row=row, synced_at=synced_at)
                    counts.update += 1
                else:
                    counts.skip += 1
            db.commit()
        except Exception:
            db.rollback()
            raise
    return counts


def run_anti_dumping_apply(*, rel_path: str | None = None) -> dict[str, Any]:
    """Guarded apply: мутирует БД только при official provenance и отсутствии blockers."""
    loaded_at = _utc_now_iso()
    bundle_path = discover_anti_dumping_bundle_path(rel_path=rel_path)
    if not bundle_path:
        return _blocked_response(
            status="missing_official_source",
            mode="apply",
            dry_run=False,
            blockers=["missing_official_source: локальный official anti-dumping bundle не найден"],
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

    synced_at = datetime.now(timezone.utc).replace(tzinfo=None)
    applied = _apply_anti_dumping_rows(rows, synced_at=synced_at)
    if applied is None:
        return _blocked_response(
            status="manual_review_required",
            mode="apply",
            dry_run=False,
            blockers=["atomic_apply_aborted: invalid measure row detected during apply"],
            parser_result=parser_result,
            provenance=provenance,
            notes=["Apply атомарно отменён.", "SourceStatus/SyncLog не записаны."],
        )
    row_counts = applied

    entry = get_payment_source_entry(_REGISTRY_SOURCE_CODE)
    note_txt = (
        f"anti-dumping apply {bundle_path}: revision={revision}; "
        f"insert={row_counts.insert}, update={row_counts.update}, skip={row_counts.skip}; "
        f"checksum={provenance.checksum_sha256 or 'n/a'}"
    )
    upsert_source_status(
        source_code=_ANTI_DUMPING_SOURCE_CODE,
        source_name=entry.name if entry else provenance.source_name,
        source_url=provenance.official_url or bundle_path,
        revision=revision,
        is_stale=False,
        note=note_txt,
    )
    append_sync_log(
        source_code=_ANTI_DUMPING_SOURCE_CODE,
        status="OK",
        revision=revision,
        rows_affected=row_counts.insert + row_counts.update,
        note=note_txt,
    )

    coverage = run_payment_data_coverage_report()
    response = AntiDumpingIngestionResponse(
        status="OK",
        mode="apply",
        dry_run=False,
        db_mutated=(row_counts.insert + row_counts.update) > 0,
        provenance=provenance,
        row_counts=row_counts,
        blockers=[],
        parser_result=parser_result,
        coverage_link={
            "trade_remedies_status": (coverage.get("summary") or {}).get("trade_remedies", {}).get("status"),
            "generated_at": coverage.get("generated_at"),
        },
        notes=[
            "Anti-dumping slice: обновляет только special_duties с measure-level provenance.",
            "Import-duty/VAT/excise поля hs_rates не изменяются.",
        ],
    )
    return response.model_dump(mode="json")
