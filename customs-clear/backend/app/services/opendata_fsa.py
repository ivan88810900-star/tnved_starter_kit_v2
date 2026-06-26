"""Импорт реестров СС/ДС Росаккредитации из opendata (7736638268-rss / 7736638268-rds)."""

from __future__ import annotations

import csv
import hashlib
import io
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import py7zr
from loguru import logger

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

FSA_RSS_ID = "7736638268-rss"
FSA_RDS_ID = "7736638268-rds"

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


def _upsert_fsa_rows(rows: list[dict[str, str]], *, snapshot_id: str) -> dict[str, int]:
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
    with SessionLocal() as db:
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
        db.commit()
    return {"created": created, "updated": updated, "skipped": skipped}


def _import_7z(path: Path, *, doc_type: str, snapshot_id: str) -> dict[str, int]:
    totals = {"created": 0, "updated": 0, "skipped": 0, "parsed": 0}
    with tempfile.TemporaryDirectory(prefix="fsa_opendata_") as tmp:
        tmp_path = Path(tmp)
        with py7zr.SevenZipFile(path, mode="r") as archive:
            archive.extractall(path=tmp_path)
        csv_files = sorted(tmp_path.glob("*.csv"))
        if not csv_files:
            raise RuntimeError(f"В архиве {path.name} нет CSV")
        batch: list[dict[str, str]] = []
        batch_size = 500
        for csv_file in csv_files:
            for raw in _iter_csv_rows(csv_file):
                mapped = _map_fsa_row(raw, doc_type=doc_type)
                if not mapped:
                    totals["skipped"] += 1
                    continue
                batch.append(mapped)
                if len(batch) >= batch_size:
                    st = _upsert_fsa_rows(batch, snapshot_id=snapshot_id)
                    for k in ("created", "updated", "skipped"):
                        totals[k] += st[k]
                    totals["parsed"] += len(batch)
                    batch.clear()
        if batch:
            st = _upsert_fsa_rows(batch, snapshot_id=snapshot_id)
            for k in ("created", "updated", "skipped"):
                totals[k] += st[k]
            totals["parsed"] += len(batch)
    return totals


def _sync_fsa_dataset(
    dataset_id: str,
    *,
    doc_type: str,
    source_key: str,
    backfill_all: bool = False,
    force: bool = False,
) -> list[dict[str, Any]]:
    meta = fetch_fsa_meta(dataset_id)
    referer = f"{FSA_BASE}/opendata/{dataset_id}/"
    dest_root = backend_opendata_dir() / source_key
    dest_root.mkdir(parents=True, exist_ok=True)

    versions = meta.versions if backfill_all else meta.versions[:1]
    results: list[dict[str, Any]] = []

    with SessionLocal() as db:
        imported = {
            r.snapshot_id
            for r in db.query(OpendataSyncLog.snapshot_id)
            .filter(OpendataSyncLog.source_key == source_key, OpendataSyncLog.status == "ok")
            .all()
        }

    for version in versions:
        snapshot_id = version.snapshot_id.strip()
        if not force and snapshot_id in imported:
            logger.info("FSA {}: snapshot {} уже импортирован", source_key, snapshot_id)
            results.append({"status": "skipped", "snapshot_id": snapshot_id})
            continue
        dest_file = dest_root / snapshot_id
        try:
            raw = download_bytes(version.url, referer=referer, dest=dest_file, for_fsa=True)
            sha = hashlib.sha256(raw).hexdigest()
            stats = _import_7z(dest_file, doc_type=doc_type, snapshot_id=snapshot_id)
            data_as_of = snapshot_date_from_id(snapshot_id) or meta.modified
            with SessionLocal() as db:
                db.add(
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
                db.commit()
            results.append({"status": "ok", "snapshot_id": snapshot_id, "data_as_of": data_as_of, **stats})
        except Exception as exc:
            logger.exception("FSA opendata import failed {} {}", source_key, snapshot_id)
            with SessionLocal() as db:
                db.add(
                    OpendataSyncLog(
                        source_key=source_key,
                        dataset_id=dataset_id,
                        snapshot_id=snapshot_id,
                        file_url=version.url,
                        synced_at=datetime.now(timezone.utc).isoformat(),
                        status="error",
                        error_message=str(exc)[:2000],
                    )
                )
                db.commit()
            results.append({"status": "error", "snapshot_id": snapshot_id, "error": str(exc)})
    return results


def sync_fsa_certificates(*, backfill_all: bool = False, force: bool = False) -> dict[str, Any]:
    """Синхронизация СС (rss) и ДС (rds). По умолчанию — последний месячный снимок каждого набора."""
    rss = _sync_fsa_dataset(
        FSA_RSS_ID, doc_type="СС", source_key="fsa_rss", backfill_all=backfill_all, force=force
    )
    rds = _sync_fsa_dataset(
        FSA_RDS_ID, doc_type="ДС", source_key="fsa_rds", backfill_all=backfill_all, force=force
    )
    return {"rss": rss, "rds": rds}
