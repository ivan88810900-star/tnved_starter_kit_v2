"""Импорт реестров СС/ДС Росаккредитации из opendata (7736638268-rss / 7736638268-rds)."""

from __future__ import annotations

import csv
import hashlib
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import py7zr
from loguru import logger
from sqlalchemy.orm import Session

from ..db import SessionLocal
from ..models.tnved import FsaCertificate, OpendataSyncLog
from .opendata_client import (
    FSA_BASE,
    backend_opendata_dir,
    download_bytes,
    fetch_fsa_meta,
    snapshot_date_from_id,
)
from .permits_service import normalize_number
from .snapshot_safety import configured_minimum_rows, validate_full_snapshot

FSA_RSS_ID = "7736638268-rss"
FSA_RDS_ID = "7736638268-rds"
_FSA_MINIMUM_ROWS = 1_000

_NUMBER_COLS = {
    "СС": ("Номер СС", "Номер сертификата", "reg_number"),
    "ДС": ("Номер ДС", "Номер декларации", "reg_number"),
}


def _cell(row: dict[str, str], *keys: str) -> str:
    for k in keys:
        if k in row and (row[k] or "").strip():
            return (row[k] or "").strip().strip('"')
    return ""


def _map_fsa_row(row: dict[str, str], *, doc_type: str) -> dict[str, str] | None:
    num_keys = _NUMBER_COLS.get(doc_type, ("reg_number",))
    reg_raw = _cell(row, *num_keys)
    if not reg_raw:
        return None
    reg = normalize_number(reg_raw)
    if not reg:
        return None
    product = _cell(row, "Общее наименование продукции", "Группа продукции", "product_name")
    return {
        "registry_number": reg,
        "doc_type": doc_type,
        "status": _cell(row, "Статус", "cert_status"),
        "applicant": _cell(row, "Заявитель", "applicant_name")[:500],
        "manufacturer": _cell(row, "Изготовитель", "manufacturer_name")[:500],
        "product_name": product[:4000],
        "tn_ved_codes": _cell(row, "Коды ОКПД2/ТНВЭД", "product_tn_ved", "Коды ТН ВЭД"),
        "tr_ts": _cell(row, "Тех регламенты", "product_tech_reg"),
        "issue_date": _cell(row, "Дата рег", "date_begining", "Дата регистрации"),
        "expiry_date": _cell(row, "Срок действия", "date_finish", "Дата окончания действия"),
        "fsa_record_id": _cell(row, "id", "id_cert"),
    }


def _iter_csv_rows(path: Path) -> Iterator[dict[str, str]]:
    csv.field_size_limit(min(sys.maxsize, 10_000_000))
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            yield row


def _apply_fsa_rows(
    db: Session,
    rows: list[dict[str, str]],
    *,
    snapshot_id: str,
) -> dict[str, int]:
    """Upsert по registry_number; дубликаты в одном снимке схлопываются (последняя строка)."""
    by_reg: dict[str, dict[str, str]] = {}
    skipped = 0
    for row in rows:
        reg = row.get("registry_number") or ""
        if not reg:
            skipped += 1
            continue
        by_reg[reg] = row

    created = updated = 0
    for reg, row in by_reg.items():
        existing = (
            db.query(FsaCertificate).filter(FsaCertificate.registry_number == reg).one_or_none()
        )
        if existing:
            existing.doc_type = row.get("doc_type") or existing.doc_type
            existing.status = row.get("status") or existing.status
            existing.applicant = row.get("applicant") or existing.applicant
            existing.manufacturer = row.get("manufacturer") or existing.manufacturer
            existing.product_name = row.get("product_name") or existing.product_name
            existing.tn_ved_codes = row.get("tn_ved_codes") or existing.tn_ved_codes
            existing.tr_ts = row.get("tr_ts") or existing.tr_ts
            existing.issue_date = row.get("issue_date") or existing.issue_date
            existing.expiry_date = row.get("expiry_date") or existing.expiry_date
            existing.fsa_record_id = row.get("fsa_record_id") or existing.fsa_record_id
            existing.source_snapshot = snapshot_id
            updated += 1
        else:
            db.add(
                FsaCertificate(
                    registry_number=reg,
                    doc_type=row.get("doc_type") or "СС",
                    status=row.get("status") or "",
                    applicant=row.get("applicant") or "",
                    manufacturer=row.get("manufacturer") or "",
                    product_name=row.get("product_name") or "",
                    tn_ved_codes=row.get("tn_ved_codes") or "",
                    tr_ts=row.get("tr_ts") or "",
                    issue_date=row.get("issue_date") or "",
                    expiry_date=row.get("expiry_date") or "",
                    fsa_record_id=row.get("fsa_record_id") or "",
                    source_snapshot=snapshot_id,
                )
            )
            created += 1
    return {"created": created, "updated": updated, "skipped": skipped}


def _upsert_fsa_rows(rows: list[dict[str, str]], *, snapshot_id: str) -> dict[str, int]:
    """Backward-compatible transactional batch upsert used by focused tests/tools."""
    with SessionLocal() as db:
        try:
            result = _apply_fsa_rows(db, rows, snapshot_id=snapshot_id)
            db.commit()
            return result
        except Exception:
            db.rollback()
            raise


def _import_7z(
    path: Path,
    *,
    doc_type: str,
    snapshot_id: str,
    db: Session | None = None,
    minimum_rows: int = 1,
) -> dict[str, int]:
    """Validate and atomically replace one FSA document-type snapshot.

    ``minimum_rows`` defaults to one for focused/manual callers.  Scheduled
    synchronization passes the production floor.  When ``db`` is supplied,
    the caller owns the transaction so RSS and RDS can commit together.
    """
    totals = {"created": 0, "updated": 0, "skipped": 0, "parsed": 0}
    with tempfile.TemporaryDirectory(prefix="fsa_opendata_") as tmp:
        tmp_path = Path(tmp)
        with py7zr.SevenZipFile(path, mode="r") as archive:
            archive.extractall(path=tmp_path)
        csv_files = sorted(tmp_path.glob("*.csv"))
        if not csv_files:
            raise RuntimeError(f"В архиве {path.name} нет CSV")
        owns_session = db is None
        work_db = db or SessionLocal()
        try:
            # First pass: prove completeness before deleting a single live row.
            # Remember the last occurrence so cross-file/batch duplicates retain
            # the same "last row wins" behavior as the small batch helper.
            last_position: dict[str, int] = {}
            valid_position = 0
            invalid_rows = 0
            for csv_file in csv_files:
                for raw in _iter_csv_rows(csv_file):
                    mapped = _map_fsa_row(raw, doc_type=doc_type)
                    if not mapped:
                        invalid_rows += 1
                        continue
                    valid_position += 1
                    last_position[mapped["registry_number"]] = valid_position

            candidate_count = len(last_position)
            if candidate_count <= 0:
                raise RuntimeError(
                    f"FSA {doc_type} snapshot contains zero valid registry rows; "
                    "live table preserved"
                )
            existing_count = (
                work_db.query(FsaCertificate)
                .filter(FsaCertificate.doc_type == doc_type)
                .count()
            )
            source_id = "fsa_rss_registry" if doc_type == "СС" else "fsa_rds_registry"
            validate_full_snapshot(
                source_id=source_id,
                candidate_count=candidate_count,
                existing_count=existing_count,
                minimum_rows=minimum_rows,
            )

            work_db.query(FsaCertificate).filter(
                FsaCertificate.doc_type == doc_type
            ).delete(synchronize_session=False)

            batch: list[dict[str, str]] = []
            batch_size = 500
            valid_position = 0
            duplicate_rows = 0

            def flush_batch() -> None:
                if not batch:
                    return
                stats = _apply_fsa_rows(work_db, batch, snapshot_id=snapshot_id)
                for key in ("created", "updated", "skipped"):
                    totals[key] += stats[key]
                totals["parsed"] += len(batch)
                batch.clear()

            for csv_file in csv_files:
                for raw in _iter_csv_rows(csv_file):
                    mapped = _map_fsa_row(raw, doc_type=doc_type)
                    if not mapped:
                        continue
                    valid_position += 1
                    if last_position[mapped["registry_number"]] != valid_position:
                        duplicate_rows += 1
                        continue
                    batch.append(mapped)
                    if len(batch) >= batch_size:
                        flush_batch()
            flush_batch()
            totals["skipped"] += invalid_rows + duplicate_rows
            if totals["parsed"] != candidate_count:
                raise RuntimeError(
                    f"FSA {doc_type} parsed_rows={totals['parsed']} does not match "
                    f"validated_rows={candidate_count}; live table preserved"
                )
            if owns_session:
                work_db.commit()
        except Exception:
            if owns_session:
                work_db.rollback()
            raise
        finally:
            if owns_session:
                work_db.close()
    return totals


def _sync_fsa_dataset(
    dataset_id: str,
    *,
    doc_type: str,
    source_key: str,
    backfill_all: bool = False,
    force: bool = False,
    db: Session | None = None,
) -> list[dict[str, Any]]:
    meta = fetch_fsa_meta(dataset_id)
    referer = f"{FSA_BASE}/opendata/{dataset_id}/"
    dest_root = backend_opendata_dir() / source_key
    dest_root.mkdir(parents=True, exist_ok=True)

    # FSA publishes newest first.  Historical replay must finish with the
    # newest snapshot; otherwise a backfill can leave the live table stale.
    versions = list(reversed(meta.versions)) if backfill_all else meta.versions[:1]
    if not versions:
        raise RuntimeError(f"FSA {source_key}: official metadata contains no snapshots")
    results: list[dict[str, Any]] = []
    owns_session = db is None
    work_db = db or SessionLocal()
    try:
        imported = {
            r.snapshot_id: int(r.row_count or 0)
            for r in work_db.query(OpendataSyncLog.snapshot_id, OpendataSyncLog.row_count)
            .filter(OpendataSyncLog.source_key == source_key, OpendataSyncLog.status == "ok")
            .all()
        }

        missing_historical = backfill_all and any(
            version.snapshot_id.strip() not in imported for version in versions[:-1]
        )
        for index, version in enumerate(versions):
            snapshot_id = version.snapshot_id.strip()
            # If an old archive is replayed, always replay the newest one too,
            # even when it has an existing success log.
            replay_latest = missing_historical and index == len(versions) - 1
            if not force and not replay_latest and snapshot_id in imported:
                logged_rows = imported[snapshot_id]
                live_rows = (
                    work_db.query(FsaCertificate)
                    .filter(FsaCertificate.doc_type == doc_type)
                    .count()
                )
                exact_snapshot_rows = (
                    work_db.query(FsaCertificate)
                    .filter(
                        FsaCertificate.doc_type == doc_type,
                        FsaCertificate.source_snapshot == snapshot_id,
                    )
                    .count()
                )
                snapshot_must_match_live = not backfill_all or index == len(versions) - 1
                complete_live_evidence = bool(
                    logged_rows > 0
                    and live_rows > 0
                    and (
                        not snapshot_must_match_live
                        or (
                            exact_snapshot_rows == logged_rows
                            and live_rows == logged_rows
                        )
                    )
                )
                if (
                    not complete_live_evidence
                ):
                    logger.warning(
                        "FSA {}: snapshot {} has a success log without positive "
                        "and complete matching live evidence "
                        "(logged={}, live={}, exact_snapshot={}); re-importing",
                        source_key,
                        snapshot_id,
                        logged_rows,
                        live_rows,
                        exact_snapshot_rows,
                    )
                else:
                    logger.info("FSA {}: snapshot {} уже импортирован", source_key, snapshot_id)
                    results.append(
                        {
                            "status": "skipped",
                            "snapshot_id": snapshot_id,
                            "rows": live_rows,
                            "parsed": live_rows,
                            "verified_live_rows": live_rows,
                        }
                    )
                    continue
            dest_file = dest_root / snapshot_id
            raw = download_bytes(version.url, referer=referer, dest=dest_file, for_fsa=True)
            sha = hashlib.sha256(raw).hexdigest()
            source_id = "fsa_rss_registry" if doc_type == "СС" else "fsa_rds_registry"
            stats = _import_7z(
                dest_file,
                doc_type=doc_type,
                snapshot_id=snapshot_id,
                db=work_db,
                minimum_rows=configured_minimum_rows(source_id, _FSA_MINIMUM_ROWS),
            )
            data_as_of = snapshot_date_from_id(snapshot_id) or meta.modified
            work_db.add(
                OpendataSyncLog(
                    source_key=source_key,
                    dataset_id=dataset_id,
                    snapshot_id=snapshot_id,
                    file_url=version.url,
                    file_sha256=sha,
                    row_count=stats.get("parsed", 0),
                    synced_at=datetime.now(timezone.utc).isoformat(),
                    data_as_of=data_as_of,
                    status="ok",
                    details=str(stats),
                )
            )
            results.append({"status": "ok", "snapshot_id": snapshot_id, "data_as_of": data_as_of, **stats})
        if owns_session:
            work_db.commit()
        return results
    except Exception:
        if owns_session:
            work_db.rollback()
        raise
    finally:
        if owns_session:
            work_db.close()


def _record_fsa_aggregate_failure(exc: Exception) -> None:
    """Persist failure evidence after the aggregate data transaction rolls back."""
    synced_at = datetime.now(timezone.utc).isoformat()
    with SessionLocal() as db:
        for dataset_id, source_key in ((FSA_RSS_ID, "fsa_rss"), (FSA_RDS_ID, "fsa_rds")):
            db.add(
                OpendataSyncLog(
                    source_key=source_key,
                    dataset_id=dataset_id,
                    snapshot_id="aggregate-failed",
                    synced_at=synced_at,
                    status="error",
                    error_message=str(exc)[:2000],
                )
            )
        db.commit()


def sync_fsa_certificates(*, backfill_all: bool = False, force: bool = False) -> dict[str, Any]:
    """Synchronize RSS and RDS as one aggregate database transaction."""
    try:
        with SessionLocal() as db:
            try:
                rss = _sync_fsa_dataset(
                    FSA_RSS_ID,
                    doc_type="СС",
                    source_key="fsa_rss",
                    backfill_all=backfill_all,
                    force=force,
                    db=db,
                )
                rds = _sync_fsa_dataset(
                    FSA_RDS_ID,
                    doc_type="ДС",
                    source_key="fsa_rds",
                    backfill_all=backfill_all,
                    force=force,
                    db=db,
                )
                db.commit()
            except Exception:
                db.rollback()
                raise
        return {"aggregate_status": "ok", "rss": rss, "rds": rds}
    except Exception as exc:
        logger.exception("FSA aggregate opendata import failed; RSS and RDS preserved")
        try:
            _record_fsa_aggregate_failure(exc)
        except Exception:
            logger.exception("Unable to persist FSA aggregate failure log")
        failure = {"status": "error", "snapshot_id": "aggregate-failed", "error": str(exc)}
        return {"aggregate_status": "error", "rss": [dict(failure)], "rds": [dict(failure)]}
