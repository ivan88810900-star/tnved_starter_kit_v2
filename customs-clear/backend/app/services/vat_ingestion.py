"""Официальный VAT/reference ingestion ЕТТ ЕАЭС: dry-run / guarded apply (issue #39)."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..db import SessionLocal
from ..models.core import HsRate, SourceStatus, SyncLog
from ..schemas.vat_ingestion import VatIngestionResponse, VatProvenance, VatRowCounts
from .normative_bundle import _normalize_rate_row
from .normative_store import append_sync_log, upsert_source_status
from .payment_data_coverage import run_payment_data_coverage_report
from .payment_revision_utils import (
    is_import_duty_bundle_path,
    is_official_vat_ingestion_revision,
    is_vat_only_bundle_path,
    is_anti_dumping_only_bundle_path,
    is_countervailing_only_bundle_path,
    is_special_safeguard_only_bundle_path,
    is_wrong_domain_eec_ett_revision_in_vat_bundle,
    is_wrong_domain_anti_dumping_revision_in_vat_bundle,
    is_wrong_domain_special_safeguard_revision_in_vat_bundle,
    is_wrong_domain_countervailing_revision_in_vat_bundle,
    raw_rate_rows,
)
from .payment_source_registry import get_payment_source_entry

_BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
_VAT_SOURCE_CODE = "EEC_VAT"
_REGISTRY_SOURCE_CODE = "eec_ett_vat"

# Кандидаты локального canonical VAT bundle (import-duty-only paths исключены).
_LOCAL_BUNDLE_CANDIDATES: tuple[str, ...] = (
    "data/raw_normative/eec_ett_vat.json",
)

# Только VAT-поля hs_rates. source_revision/source_url — import-duty provenance, не трогаем.
# duty_rate/hs_prefix — import-duty semantics, VAT slice не меняет.
_VAT_APPLY_FIELDS = ("vat_import_rate", "vat_rule", "vat_rule_basis", "valid_from", "valid_to")
_DEFAULT_VAT_IMPORT_RATE = 22.0


def _vat_import_rate_value(row: dict[str, Any], *, default: float = _DEFAULT_VAT_IMPORT_RATE) -> float:
    """Explicit 0/0.0/"0" — валидная ставка; fallback 22.0 только при missing/None/blank."""
    if "vat_import_rate" not in row:
        return default
    raw = row["vat_import_rate"]
    if raw is None:
        return default
    if isinstance(raw, str) and not raw.strip():
        return default
    return float(str(raw).replace(",", "."))


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


_NON_OFFICIAL_VAT_REVISION_EXACT = frozenset(
    {"example", "seed", "unknown", "ambiguous", "legacy", "legacy_seed", "fallback", "test", "demo", "manual", "local-copy"}
)
_NON_OFFICIAL_VAT_REVISION_PREFIXES = (
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


def _is_non_official_vat_revision_token(revision: str) -> bool:
    rev = (revision or "").strip().lower()
    if not rev:
        return True
    if rev in _NON_OFFICIAL_VAT_REVISION_EXACT:
        return True
    return any(rev.startswith(p) for p in _NON_OFFICIAL_VAT_REVISION_PREFIXES)


def _validate_official_vat_bundle_payload(
    payload: dict[str, Any], *, rel_path: str, checksum: str | None
) -> dict[str, Any]:
    """VAT-domain bundle validation — не делегирует import-duty ETT validator."""
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

    if _is_non_official_vat_revision_token(revision):
        return {
            "status": "manual_review_required",
            "reason": "non_official_bundle_revision",
            "revision": revision,
            "format": fmt,
            "record_count": len(rates) + len(tnved),
            "rates_count": len(rates),
            "checksum_sha256": checksum,
        }
    if is_wrong_domain_eec_ett_revision_in_vat_bundle(revision):
        return {
            "status": "manual_review_required",
            "reason": "wrong_domain_eec_ett_revision_in_vat_bundle",
            "revision": revision,
            "format": fmt,
            "record_count": len(rates) + len(tnved),
            "rates_count": len(rates),
            "checksum_sha256": checksum,
        }
    if is_wrong_domain_anti_dumping_revision_in_vat_bundle(revision):
        return {
            "status": "manual_review_required",
            "reason": "wrong_domain_anti_dumping_revision_in_vat_bundle",
            "revision": revision,
            "format": fmt,
            "record_count": len(rates) + len(tnved),
            "rates_count": len(rates),
            "checksum_sha256": checksum,
        }
    if is_wrong_domain_special_safeguard_revision_in_vat_bundle(revision):
        return {
            "status": "manual_review_required",
            "reason": "wrong_domain_special_safeguard_revision_in_vat_bundle",
            "revision": revision,
            "format": fmt,
            "record_count": len(rates) + len(tnved),
            "rates_count": len(rates),
            "checksum_sha256": checksum,
        }
    if is_wrong_domain_countervailing_revision_in_vat_bundle(revision):
        return {
            "status": "manual_review_required",
            "reason": "wrong_domain_countervailing_revision_in_vat_bundle",
            "revision": revision,
            "format": fmt,
            "record_count": len(rates) + len(tnved),
            "rates_count": len(rates),
            "checksum_sha256": checksum,
        }
    if not is_official_vat_ingestion_revision(revision):
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
        if is_wrong_domain_eec_ett_revision_in_vat_bundle(rev):
            wrong_domain_rows.append(rev)
            continue
        if not is_official_vat_ingestion_revision(rev):
            explicit_unsafe.append(rev)
    if wrong_domain_rows:
        return {
            "status": "manual_review_required",
            "reason": "wrong_domain_eec_ett_row_revision",
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
    return payload, _validate_official_vat_bundle_payload(payload, rel_path=rel_path, checksum=checksum)


def discover_vat_bundle_path(*, rel_path: str | None = None) -> str | None:
    """Найти локальный official VAT bundle (не import-duty-only paths)."""
    if rel_path:
        if not _local_path_present(rel_path):
            return None
        if is_import_duty_bundle_path(rel_path) and not is_vat_only_bundle_path(rel_path):
            return None
        if is_anti_dumping_only_bundle_path(rel_path):
            return None
        if is_special_safeguard_only_bundle_path(rel_path):
            return None
        if is_countervailing_only_bundle_path(rel_path):
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


def _raw_row_has_vat_signal(raw: dict[str, Any]) -> bool:
    """Строка содержит явные VAT-поля (не только duty_rate)."""
    if "vat_import_rate" in raw and raw.get("vat_import_rate") is not None:
        return True
    rule = str(raw.get("vat_rule") or "").strip().lower()
    if rule and rule != "none":
        return True
    if str(raw.get("vat_rule_basis") or "").strip():
        return True
    return False


def _extract_vat_rows(
    payload: dict[str, Any], rows_in: list[dict[str, Any]] | None = None
) -> tuple[str, list[dict[str, Any]], list[str]]:
    """Нормализовать rates[] с VAT-сигналом; blank source_revision наследует bundle revision."""
    revision = str(payload.get("revision") or payload.get("source_revision") or "").strip()
    bundle_url = str(payload.get("official_ett_url") or payload.get("source_url") or "").strip()
    effective_from = str(payload.get("effective_from") or "").strip() or None
    effective_to = str(payload.get("effective_to") or "").strip() or None

    rows: list[dict[str, Any]] = []
    blockers: list[str] = []
    if rows_in is None:
        rows_in, container_err = raw_rate_rows(payload)
        if container_err is not None:
            return revision, [], [f"parser_failed: {container_err}"]

    for raw in rows_in or []:
        if not isinstance(raw, dict):
            return revision, [], ["parser_failed: malformed_rate_row (rate row not an object)"]
        if not _raw_row_has_vat_signal(raw):
            continue
        normalized = _normalize_rate_row(raw)
        if not normalized:
            blockers.append(f"invalid_rate_row: hs_code={raw.get('hs_code')!r}")
            continue
        if not str(normalized.get("source_revision") or "").strip():
            normalized["source_revision"] = revision
        row_rev = str(normalized.get("source_revision") or "").strip().lower()
        if is_wrong_domain_eec_ett_revision_in_vat_bundle(row_rev):
            blockers.append(
                f"wrong_domain_row_revision: {row_rev} for hs_code={normalized.get('hs_code')}"
            )
            continue
        if not is_official_vat_ingestion_revision(row_rev):
            blockers.append(f"unsafe_row_revision: {row_rev or '<empty>'} for hs_code={normalized.get('hs_code')}")
            continue
        raw_code_digits = re.sub(r"\D", "", str(raw.get("hs_code") or ""))[:10]
        explicit_prefix_scope = raw.get("prefix_scope") is True or raw.get("prefix_rate") is True
        if len(raw_code_digits) >= 10 and not explicit_prefix_scope:
            normalized["hs_prefix"] = raw_code_digits
        row_url = str(normalized.get("source_url") or "").strip() or bundle_url
        if not row_url:
            blockers.append(
                f"official_source_url_required: нет official source_url для hs_code={normalized.get('hs_code')}"
            )
            continue
        normalized["source_url"] = row_url
        if effective_from and not str(normalized.get("valid_from") or "").strip():
            normalized["valid_from"] = effective_from
        if effective_to and not str(normalized.get("valid_to") or "").strip():
            normalized["valid_to"] = effective_to
        rows.append(normalized)
    return revision, rows, blockers


def _existing_hs_rate(db, hs_code: str) -> HsRate | None:
    lookup = str(hs_code or "").strip().replace(" ", "")
    if not lookup:
        return None
    return db.query(HsRate).filter(HsRate.hs_code == lookup).first()


def _row_needs_vat_update(existing: HsRate, row: dict[str, Any]) -> bool:
    """Сравнение только VAT-полей — import-duty provenance/scope не участвуют."""
    if float(existing.vat_import_rate or 0) != _vat_import_rate_value(row):
        return True
    if (existing.vat_rule or "none") != str(row.get("vat_rule") or "none"):
        return True
    if (existing.vat_rule_basis or "").strip() != str(row.get("vat_rule_basis") or "").strip():
        return True
    if str(row.get("valid_from") or "").strip() and (existing.valid_from or "").strip() != str(
        row.get("valid_from") or ""
    ).strip():
        return True
    if str(row.get("valid_to") or "").strip() and (existing.valid_to or "").strip() != str(
        row.get("valid_to") or ""
    ).strip():
        return True
    return False


def _plan_vat_rows(rows: list[dict[str, Any]]) -> tuple[VatRowCounts, list[str]]:
    """План без insert: отсутствующий hs_rate → blocked (нет VAT-safe storage для новых duty rows)."""
    counts = VatRowCounts(total_in_source=len(rows))
    missing_blockers: list[str] = []
    with SessionLocal() as db:
        for row in rows:
            hs_code = str(row.get("hs_code") or "").strip()
            existing = _existing_hs_rate(db, hs_code)
            if existing is None:
                counts.blocked += 1
                missing_blockers.append(f"missing_hs_rate: {hs_code or '<empty>'}")
            elif _row_needs_vat_update(existing, row):
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
) -> VatProvenance:
    entry = get_payment_source_entry(_REGISTRY_SOURCE_CODE)
    return VatProvenance(
        source_code=_VAT_SOURCE_CODE,
        source_name=entry.name if entry else "ЕТТ ЕАЭС — НДС при ввозе",
        legal_basis=entry.legal_basis if entry else "Единый таможенный тариф ЕАЭС (ЕТТ)",
        official_url=str(payload.get("official_ett_url") or payload.get("source_url") or "").strip() or None,
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
    provenance: VatProvenance | None = None,
    row_counts: VatRowCounts | None = None,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    response = VatIngestionResponse(
        status=status,  # type: ignore[arg-type]
        mode=mode,  # type: ignore[arg-type]
        dry_run=dry_run,
        db_mutated=False,
        provenance=provenance,
        row_counts=row_counts or VatRowCounts(),
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

    revision, rows, row_blockers = _extract_vat_rows(payload, rows_in)
    blockers: list[str] = []
    if is_import_duty_bundle_path(rel_path) and not is_vat_only_bundle_path(rel_path):
        blockers.append("manual_review_required: import_duty_only_bundle_not_vat")
    if is_anti_dumping_only_bundle_path(rel_path):
        blockers.append("manual_review_required: anti_dumping_only_bundle_not_vat")
    if is_special_safeguard_only_bundle_path(rel_path):
        blockers.append("manual_review_required: special_safeguard_only_bundle_not_vat")
    if is_countervailing_only_bundle_path(rel_path):
        blockers.append("manual_review_required: countervailing_only_bundle_not_vat")
    if is_wrong_domain_eec_ett_revision_in_vat_bundle(revision):
        blockers.append(f"wrong_domain_bundle_revision: {revision}")
    elif not is_official_vat_ingestion_revision(revision):
        blockers.append(f"non_official_bundle_revision: {revision or '<empty>'}")
    if row_blockers:
        blockers.extend(row_blockers)
    if not rows:
        blockers.append("no_importable_vat_rows")
    return payload, parser_result, revision, rows, blockers


def run_vat_dry_run(*, rel_path: str | None = None) -> dict[str, Any]:
    """Dry-run: insert/update/skip counts и blockers без мутации БД."""
    loaded_at = _utc_now_iso()
    bundle_path = discover_vat_bundle_path(rel_path=rel_path)
    if not bundle_path:
        return _blocked_response(
            status="missing_official_source",
            mode="dry_run",
            dry_run=True,
            blockers=[
                "Нет локального official EEC/ETT VAT bundle. "
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
            row_counts=VatRowCounts(total_in_source=len(rows), blocked=len(rows)),
            notes=["Dry-run не мутирует БД.", "SourceStatus/SyncLog не записываются."],
        )

    row_counts, missing_blockers = _plan_vat_rows(rows)
    dry_blockers = list(missing_blockers)
    if row_counts.blocked > 0 and row_counts.update == 0 and row_counts.skip == 0:
        dry_blockers.append(
            f"no_applicable_vat_rows: все {row_counts.blocked} строк без existing hs_rate "
            "(VAT slice не создаёт duty rows с duty_rate=0)."
        )
    coverage = run_payment_data_coverage_report()
    response = VatIngestionResponse(
        status="OK",
        mode="dry_run",
        dry_run=True,
        db_mutated=False,
        provenance=provenance,
        row_counts=row_counts,
        blockers=dry_blockers,
        parser_result=parser_result,
        coverage_link={
            "vat_rates_status": (coverage.get("summary") or {}).get("vat_rates", {}).get("status"),
            "generated_at": coverage.get("generated_at"),
        },
        notes=[
            "Dry-run не мутирует БД.",
            "Apply доступен только при status=OK dry-run и official provenance.",
            "Coverage present требует official VAT rows (не seed/fallback).",
        ],
    )
    return response.model_dump(mode="json")


def _apply_vat_field(existing: HsRate, row: dict[str, Any], field: str) -> None:
    """Записать одно VAT-поле; vat_import_rate=0 не теряется из-за truthy fallback."""
    if field == "vat_import_rate":
        raw = row.get("vat_import_rate")
        if raw is None or (isinstance(raw, str) and not str(raw).strip()):
            return
        existing.vat_import_rate = _vat_import_rate_value(row, default=float(existing.vat_import_rate or 0))
        return
    if field in row and row[field] is not None:
        setattr(existing, field, row[field])


def _stamp_vat_row_provenance(
    existing: HsRate,
    *,
    row: dict[str, Any],
    bundle_revision: str,
    bundle_url: str | None,
    synced_at: datetime,
) -> None:
    """VAT-specific row marker — только для строк, реально обновлённых official VAT apply."""
    existing.vat_source_code = _VAT_SOURCE_CODE
    existing.vat_source_revision = str(row.get("source_revision") or bundle_revision or "").strip()
    existing.vat_source_url = str(row.get("source_url") or bundle_url or "").strip()
    existing.vat_synced_at = synced_at


def _apply_vat_rows(
    rows: list[dict[str, Any]],
    *,
    bundle_revision: str,
    bundle_url: str | None,
    synced_at: datetime,
) -> VatRowCounts | None:
    """Атомарно обновить VAT-поля. None = blocked (ни одна строка не изменена, без commit)."""
    counts = VatRowCounts(total_in_source=len(rows))

    with SessionLocal() as db:
        try:
            # Preflight: собрать все existing rows до любого setattr.
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
                if _row_needs_vat_update(existing, row):
                    for k in _VAT_APPLY_FIELDS:
                        _apply_vat_field(existing, row, k)
                    _stamp_vat_row_provenance(
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


def run_vat_apply(*, rel_path: str | None = None) -> dict[str, Any]:
    """Guarded apply: мутирует БД только при official provenance и отсутствии blockers."""
    loaded_at = _utc_now_iso()
    bundle_path = discover_vat_bundle_path(rel_path=rel_path)
    if not bundle_path:
        return _blocked_response(
            status="missing_official_source",
            mode="apply",
            dry_run=False,
            blockers=["missing_official_source: локальный official VAT bundle не найден"],
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

    # Validate-before-apply: тот же blocker set, что и dry-run; без commit при blocked>0.
    row_counts, missing_blockers = _plan_vat_rows(rows)
    if row_counts.blocked > 0:
        apply_blockers = list(missing_blockers)
        apply_blockers.append(
            f"vat_rows_without_hs_rate: {row_counts.blocked} (VAT slice не создаёт hs_rates/duty_rate=0)."
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
                "Apply атомарно отменён — ни одна VAT row не обновлена.",
                "SourceStatus/SyncLog не записаны.",
            ],
        )

    synced_at = datetime.now(timezone.utc).replace(tzinfo=None)
    applied = _apply_vat_rows(
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
            notes=["Apply атомарно отменён — ни одна VAT row не обновлена.", "SourceStatus/SyncLog не записаны."],
        )
    row_counts = applied

    entry = get_payment_source_entry(_REGISTRY_SOURCE_CODE)
    note_txt = (
        f"vat apply {bundle_path}: revision={revision}; "
        f"update={row_counts.update}, skip={row_counts.skip}, "
        f"blocked={row_counts.blocked}; checksum={provenance.checksum_sha256 or 'n/a'}"
    )
    upsert_source_status(
        source_code=_VAT_SOURCE_CODE,
        source_name=entry.name if entry else provenance.source_name,
        source_url=provenance.official_url or bundle_path,
        revision=revision,
        is_stale=False,
        note=note_txt,
    )
    append_sync_log(
        source_code=_VAT_SOURCE_CODE,
        status="OK",
        revision=revision,
        rows_affected=row_counts.update,
        note=note_txt,
    )

    coverage = run_payment_data_coverage_report()
    response = VatIngestionResponse(
        status="OK",
        mode="apply",
        dry_run=False,
        db_mutated=row_counts.update > 0,
        provenance=provenance,
        row_counts=row_counts,
        blockers=[],
        parser_result=parser_result,
        coverage_link={
            "vat_rates_status": (coverage.get("summary") or {}).get("vat_rates", {}).get("status"),
            "vat_authority_level": (coverage.get("summary") or {}).get("vat_rates", {}).get("authority_level"),
            "generated_at": coverage.get("generated_at"),
        },
        notes=[
            "VAT slice: обновлены только vat_import_rate/vat_rule/vat_rule_basis/valid_from/valid_to.",
            "Import-duty поля (duty_rate, source_revision, source_url, hs_prefix) не изменяются.",
        ],
    )
    return response.model_dump(mode="json")
