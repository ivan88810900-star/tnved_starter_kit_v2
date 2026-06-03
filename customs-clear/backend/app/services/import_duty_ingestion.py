"""Официальный import-duty ingestion ЕТТ ЕАЭС: dry-run / guarded apply (issue #37)."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..db import SessionLocal
from ..models.core import HsRate, SourceStatus, SyncLog
from ..schemas.import_duty_ingestion import (
    ImportDutyIngestionResponse,
    ImportDutyProvenance,
    ImportDutyRowCounts,
)
from .normative_bundle import _normalize_rate_row
from .normative_store import append_sync_log, normalize_hs_duty_rate_string, upsert_source_status
from .payment_data_coverage import run_payment_data_coverage_report
from .payment_revision_utils import is_official_eec_ett_revision as _is_official_eec_ett_revision
from .payment_source_registry import get_payment_source_entry

_BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
_EEC_SOURCE_CODE = "EEC_ETT"
_REGISTRY_SOURCE_CODE = "eec_ett_tariff"
# Кандидаты локального canonical bundle (относительно customs-clear/backend/).
_LOCAL_BUNDLE_CANDIDATES: tuple[str, ...] = (
    "data/raw_normative/eec_ett_normative_bundle.json",
    "data/raw_normative/eec_ett_import_duty.json",
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def _local_path_present(rel_path: str) -> bool:
    return (_BACKEND_ROOT / rel_path).is_file()


def discover_import_duty_bundle_path(*, rel_path: str | None = None) -> str | None:
    """Найти локальный official bundle: явный путь или первый существующий из реестра/кандидатов."""
    if rel_path:
        return rel_path if _local_path_present(rel_path) else None

    entry = get_payment_source_entry(_REGISTRY_SOURCE_CODE)
    if entry:
        for p in entry.local_canonical_paths:
            if _local_path_present(p):
                return p

    for p in _LOCAL_BUNDLE_CANDIDATES:
        if _local_path_present(p):
            return p
    return None


def _file_sha256_at(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _raw_rates_list(payload: dict[str, Any]) -> tuple[list[Any] | None, str | None]:
    """Единый безопасный доступ к rates/rows.

    rates/rows должны быть JSON-массивом. Возвращает (list, None) при валидном контейнере
    (или [] если оба отсутствуют), либо (None, reason) для malformed non-list контейнера.
    """
    raw_rates = payload.get("rates")
    if raw_rates is not None and not isinstance(raw_rates, list):
        return None, "malformed_rates_container"
    raw_rows = payload.get("rows")
    if raw_rows is not None and not isinstance(raw_rows, list):
        return None, "malformed_rows_container"
    if isinstance(raw_rates, list):
        return raw_rates, None
    if isinstance(raw_rows, list):
        return raw_rows, None
    return [], None


def _validate_official_bundle_payload(payload: dict[str, Any], *, rel_path: str, checksum: str | None) -> dict[str, Any]:
    """Локальная валидация bundle (без зависимости от payment_source_ingestion._BACKEND_ROOT)."""
    revision = str(payload.get("revision") or "").strip().lower()
    fmt = str(payload.get("format") or "")

    # Malformed containers: rates/rows должны быть list — иначе parser_failed без итерации.
    rates, container_err = _raw_rates_list(payload)
    if container_err is not None:
        return {
            "status": "parser_failed",
            "reason": container_err,
            "error": f"bundle '{container_err.split('_')[1]}' must be a JSON array",
            "revision": revision,
            "record_count": 0,
            "checksum_sha256": checksum,
        }

    raw_tnved = payload.get("tnved")
    tnved = raw_tnved if isinstance(raw_tnved, list) else []

    if revision in {"example", "seed", "unknown", "ambiguous", "legacy", "legacy_seed", "fallback", "test", "demo"}:
        return {
            "status": "manual_review_required",
            "reason": "non_official_bundle_revision",
            "revision": revision,
            "format": fmt,
            "record_count": len(rates) + len(tnved),
            "rates_count": len(rates),
            "tnved_count": len(tnved),
            "checksum_sha256": checksum,
        }
    if not _is_official_eec_ett_revision(revision):
        return {
            "status": "manual_review_required",
            "reason": "non_official_bundle_revision",
            "revision": revision,
            "format": fmt,
            "record_count": len(rates) + len(tnved),
            "rates_count": len(rates),
            "checksum_sha256": checksum,
        }

    # Non-object rows в official import → parser_failed (без silent skip).
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

    explicit_unsafe: list[str] = []
    for r in rates:
        rev = str(r.get("source_revision") or "").strip().lower()
        if rev and not _is_official_eec_ett_revision(rev):
            explicit_unsafe.append(rev)
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
    return payload, _validate_official_bundle_payload(payload, rel_path=rel_path, checksum=checksum)


def _extract_duty_rows(
    payload: dict[str, Any], rows_in: list[dict[str, Any]] | None = None
) -> tuple[str, list[dict[str, Any]], list[str]]:
    """Нормализовать rates[]; blank source_revision наследует bundle revision.

    rows_in — уже validated list (из _raw_rates_list). Если не передан, валидируем сами,
    чтобы любой вызов был safe от malformed non-list контейнеров.
    """
    revision = str(payload.get("revision") or payload.get("source_revision") or "").strip()
    official_url = str(
        payload.get("official_ett_url")
        or payload.get("source_url")
        or "https://eec.eaeunion.org/comission/department/catr/ett/"
    ).strip()
    effective_from = str(payload.get("effective_from") or "").strip() or None
    effective_to = str(payload.get("effective_to") or "").strip() or None

    rows: list[dict[str, Any]] = []
    blockers: list[str] = []
    if rows_in is None:
        rows_in, container_err = _raw_rates_list(payload)
        if container_err is not None:
            return revision, [], [f"parser_failed: {container_err}"]
    for raw in rows_in or []:
        if not isinstance(raw, dict):
            # Official import: non-object row — структурная ошибка, не silent skip.
            return revision, [], ["parser_failed: malformed_rate_row (rate row not an object)"]
        normalized = _normalize_rate_row(raw)
        if not normalized:
            blockers.append(f"invalid_rate_row: hs_code={raw.get('hs_code')!r}")
            continue
        if not str(normalized.get("source_revision") or "").strip():
            normalized["source_revision"] = revision
        row_rev = str(normalized.get("source_revision") or "").strip().lower()
        if not _is_official_eec_ett_revision(row_rev):
            blockers.append(f"unsafe_row_revision: {row_rev or '<empty>'} for hs_code={normalized.get('hs_code')}")
            continue
        # P1: exact 10-значный hs_code не должен сохраняться с broad auto-filled prefix
        # (иначе ставка протекает на sibling-коды и завышает official coverage). Prefix
        # сохраняем только для явных prefix-rate строк (prefix_scope/prefix_rate, либо
        # когда исходно нет 10-значного кода).
        raw_code_digits = re.sub(r"\D", "", str(raw.get("hs_code") or ""))[:10]
        explicit_prefix_scope = raw.get("prefix_scope") is True or raw.get("prefix_rate") is True
        if len(raw_code_digits) >= 10 and not explicit_prefix_scope:
            normalized["hs_prefix"] = raw_code_digits
        normalized["source_url"] = str(normalized.get("source_url") or official_url).strip()
        if effective_from:
            normalized.setdefault("valid_from", effective_from)
        if effective_to:
            normalized.setdefault("valid_to", effective_to)
        rows.append(normalized)
    return revision, rows, blockers


def _existing_hs_rate(db, hs_code: str) -> HsRate | None:
    lookup = str(hs_code or "").strip().replace(" ", "")
    if not lookup:
        return None
    return db.query(HsRate).filter(HsRate.hs_code == lookup).first()


def _desired_hs_prefix(row: dict[str, Any]) -> str:
    """Целевой hs_prefix для строки (после P1 scope-fix), с fallback на полный hs_code."""
    hs_code = str(row.get("hs_code") or "").strip().replace(" ", "")
    return str(row.get("hs_prefix") or hs_code).strip()


def _row_needs_update(existing: HsRate, row: dict[str, Any]) -> bool:
    new_duty = normalize_hs_duty_rate_string(row.get("duty_rate"))
    if (existing.duty_rate or "") != (new_duty or ""):
        return True
    if (existing.source_revision or "").strip() != str(row.get("source_revision") or "").strip():
        return True
    if str(row.get("source_url") or "").strip() and (existing.source_url or "").strip() != str(
        row.get("source_url") or ""
    ).strip():
        return True
    # P1: stale broad hs_prefix (например 8471) должен обновляться на exact full code,
    # даже если остальные поля не изменились — иначе sibling leakage / false coverage.
    desired_prefix = _desired_hs_prefix(row)
    if desired_prefix and (existing.hs_prefix or "").strip() != desired_prefix:
        return True
    return False


def _plan_import_duty_rows(rows: list[dict[str, Any]]) -> ImportDutyRowCounts:
    counts = ImportDutyRowCounts(total_in_source=len(rows))
    with SessionLocal() as db:
        for row in rows:
            hs_code = str(row.get("hs_code") or "").strip()
            existing = _existing_hs_rate(db, hs_code)
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
) -> ImportDutyProvenance:
    entry = get_payment_source_entry(_REGISTRY_SOURCE_CODE)
    return ImportDutyProvenance(
        source_code=_EEC_SOURCE_CODE,
        source_name=entry.name if entry else "ЕТТ ЕАЭС — импортные пошлины",
        legal_basis=entry.legal_basis if entry else "Единый таможенный тариф ЕАЭС (ЕТТ)",
        official_url=str(
            payload.get("official_ett_url")
            or (entry.official_url if entry else "")
            or "https://eec.eaeunion.org/comission/department/catr/ett/"
        ).strip()
        or None,
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
    provenance: ImportDutyProvenance | None = None,
    row_counts: ImportDutyRowCounts | None = None,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    response = ImportDutyIngestionResponse(
        status=status,  # type: ignore[arg-type]
        mode=mode,  # type: ignore[arg-type]
        dry_run=dry_run,
        db_mutated=False,
        provenance=provenance,
        row_counts=row_counts or ImportDutyRowCounts(),
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
        # payload не загружен: missing/invalid JSON/не object/parser_failed → жёсткий blocker,
        # apply не должен продолжать с 0 rows и писать OK provenance.
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

    # Единый validated доступ к rates/rows: parser_result уже гарантирует list of dicts,
    # но повторно валидируем перед итерацией (defense-in-depth, без raw payload-итерации ниже).
    rows_in, container_err = _raw_rates_list(payload)
    if container_err is not None:
        return payload, parser_result, "", [], [f"parser_failed: {container_err}"]

    revision, rows, row_blockers = _extract_duty_rows(payload, rows_in)
    blockers: list[str] = []
    if not _is_official_eec_ett_revision(revision):
        blockers.append(f"non_official_bundle_revision: {revision or '<empty>'}")
    if row_blockers:
        blockers.extend(row_blockers)
    if not rows:
        blockers.append("no_importable_duty_rows")
    return payload, parser_result, revision, rows, blockers


def run_import_duty_dry_run(*, rel_path: str | None = None) -> dict[str, Any]:
    """Dry-run: insert/update/skip counts и blockers без мутации БД."""
    loaded_at = _utc_now_iso()
    bundle_path = discover_import_duty_bundle_path(rel_path=rel_path)
    if not bundle_path:
        return _blocked_response(
            status="missing_official_source",
            mode="dry_run",
            dry_run=True,
            blockers=[
                "Нет локального official EEC/ETT bundle. "
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
            row_counts=ImportDutyRowCounts(total_in_source=len(rows), blocked=len(rows)),
            notes=["Dry-run не мутирует БД.", "SourceStatus/SyncLog не записываются."],
        )

    row_counts = _plan_import_duty_rows(rows)
    coverage = run_payment_data_coverage_report()
    response = ImportDutyIngestionResponse(
        status="OK",
        mode="dry_run",
        dry_run=True,
        db_mutated=False,
        provenance=provenance,
        row_counts=row_counts,
        blockers=[],
        parser_result=parser_result,
        coverage_link={
            "duty_rates_status": (coverage.get("summary") or {}).get("duty_rates", {}).get("status"),
            "generated_at": coverage.get("generated_at"),
        },
        notes=[
            "Dry-run не мутирует БД.",
            "Apply доступен только при status=OK dry-run и official provenance.",
            "Coverage present требует полного покрытия каталога ТН ВЭД.",
        ],
    )
    return response.model_dump(mode="json")


def _apply_duty_rows(rows: list[dict[str, Any]]) -> ImportDutyRowCounts:
    """Upsert только import-duty полей hs_rates (без VAT/excise/trade slice)."""
    counts = ImportDutyRowCounts(total_in_source=len(rows))
    duty_fields = ("duty_rate", "source_url", "source_revision", "valid_from", "valid_to")

    with SessionLocal() as db:
        for row in rows:
            hs_code = str(row.get("hs_code") or "").strip().replace(" ", "")
            # Не подставлять broad 4-значный fallback: для exact rows _extract_duty_rows уже
            # выставил hs_prefix = полный код; fallback на полный hs_code, не на hs_code[:4].
            hs_prefix = str(row.get("hs_prefix") or hs_code).strip()
            if not hs_prefix:
                counts.blocked += 1
                continue

            existing = _existing_hs_rate(db, hs_code)
            if existing is None:
                create_kwargs = {
                    k: row[k]
                    for k in duty_fields
                    if k in row and row[k] is not None
                }
                if "duty_rate" in create_kwargs:
                    create_kwargs["duty_rate"] = normalize_hs_duty_rate_string(create_kwargs["duty_rate"])
                db.add(
                    HsRate(
                        hs_code=hs_code or hs_prefix,
                        hs_prefix=hs_prefix,
                        **create_kwargs,
                    )
                )
                counts.insert += 1
            elif _row_needs_update(existing, row):
                for k in duty_fields:
                    if k in row and row[k] is not None:
                        val = row[k]
                        if k == "duty_rate":
                            val = normalize_hs_duty_rate_string(val)
                        setattr(existing, k, val)
                existing.hs_prefix = hs_prefix
                counts.update += 1
            else:
                counts.skip += 1
        db.commit()
    return counts


def run_import_duty_apply(*, rel_path: str | None = None) -> dict[str, Any]:
    """Guarded apply: мутирует БД только при official provenance и отсутствии blockers."""
    loaded_at = _utc_now_iso()
    bundle_path = discover_import_duty_bundle_path(rel_path=rel_path)
    if not bundle_path:
        return _blocked_response(
            status="missing_official_source",
            mode="apply",
            dry_run=False,
            blockers=["missing_official_source: локальный official bundle не найден"],
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

    entry = get_payment_source_entry(_REGISTRY_SOURCE_CODE)
    row_counts = _apply_duty_rows(rows)

    note_txt = (
        f"import-duty apply {bundle_path}: revision={revision}; "
        f"insert={row_counts.insert}, update={row_counts.update}, skip={row_counts.skip}, "
        f"blocked={row_counts.blocked}; checksum={provenance.checksum_sha256 or 'n/a'}"
    )
    upsert_source_status(
        source_code=_EEC_SOURCE_CODE,
        source_name=entry.name if entry else provenance.source_name,
        source_url=provenance.official_url or bundle_path,
        revision=revision,
        is_stale=False,
        note=note_txt,
    )
    append_sync_log(
        source_code=_EEC_SOURCE_CODE,
        status="OK",
        revision=revision,
        rows_affected=row_counts.insert + row_counts.update,
        note=note_txt,
    )

    coverage = run_payment_data_coverage_report()
    response = ImportDutyIngestionResponse(
        status="OK",
        mode="apply",
        dry_run=False,
        db_mutated=True,
        provenance=provenance,
        row_counts=row_counts,
        blockers=[],
        parser_result=parser_result,
        coverage_link={
            "duty_rates_status": (coverage.get("summary") or {}).get("duty_rates", {}).get("status"),
            "duty_authority_level": (coverage.get("summary") or {}).get("duty_rates", {}).get("authority_level"),
            "generated_at": coverage.get("generated_at"),
        },
        notes=[
            "Import-duty slice: обновлены только duty_rate/source_* в hs_rates.",
            "VAT/excise/trade remedies не импортируются в этом срезе.",
        ],
    )
    return response.model_dump(mode="json")
