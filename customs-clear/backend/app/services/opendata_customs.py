"""Справочники ФТС из opendata: маски графы 44, каталог наборов."""

from __future__ import annotations

import csv
import hashlib
import io
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger

from ..db import SessionLocal
from ..models.tnved import CustomsDocMask, OpendataSyncLog
from .opendata_client import (
    _validate_official_url,
    backend_opendata_dir,
    download_bytes,
    fetch_fts_meta,
    latest_version,
    require_no_snapshot_rollback,
    snapshot_date_from_id,
)
from .opendata_snapshot_evidence import (
    acquire_opendata_write_lock,
    canonical_rows_fingerprint,
    encode_live_snapshot_details,
    live_snapshot_details_match,
    require_immutable_snapshot_hash,
)
from .snapshot_safety import configured_minimum_rows, validate_full_snapshot

MASK44_DATASET_ID = "7730176610-mask44"
CATALOG_URL = "https://customs.gov.ru/opendata/list.csv"


def _mask44_live_fingerprint(db) -> tuple[int, str]:
    columns = (
        CustomsDocMask.sid_smev,
        CustomsDocMask.kod,
        CustomsDocMask.mask_number,
        CustomsDocMask.name,
        CustomsDocMask.mask_pattern,
        CustomsDocMask.description,
        CustomsDocMask.valid_from,
        CustomsDocMask.valid_to,
    )
    rows = db.query(*columns).order_by(*columns).yield_per(2_000)
    return canonical_rows_fingerprint(tuple(row) for row in rows)


def _successful_snapshot_ids(db) -> list[str]:
    return [
        str(snapshot_id or "").strip()
        for (snapshot_id,) in db.query(OpendataSyncLog.snapshot_id)
        .filter(
            OpendataSyncLog.source_key == "mask44",
            OpendataSyncLog.dataset_id == MASK44_DATASET_ID,
            OpendataSyncLog.status == "ok",
            OpendataSyncLog.row_count > 0,
        )
        .all()
    ]


def _parse_mask44_csv(text: str) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    fieldnames = {
        str(name or "").strip().lstrip("\ufeff")
        for name in (reader.fieldnames or ())
    }
    required = {"K_MASKA", "KOD", "N_MSK", "NAME_MSK"}
    if not required.issubset(fieldnames):
        raise RuntimeError(
            "mask44 snapshot has an unexpected schema; missing: "
            + ", ".join(sorted(required - fieldnames))
        )
    candidate_rows: list[dict[str, str]] = []
    for row in reader:
        pattern = (row.get("K_MASKA") or "").strip().strip('"')
        kod = (row.get("KOD") or "").strip().strip('"')[:16]
        name = (row.get("NAME_MSK") or "").strip().strip('"')
        description = (row.get("DSCR_MSK") or "").strip().strip('"')
        if not pattern or not (kod or name or description):
            continue
        candidate_rows.append(
            {
                "sid_smev": (row.get("SID_SMEV") or "").strip().strip('"')[:64],
                "kod": kod,
                "mask_number": (row.get("N_MSK") or "").strip().strip('"')[:8],
                "name": name,
                "mask_pattern": pattern,
                "description": description,
                "valid_from": (row.get("DATBEG") or "").strip().strip('"')[:32],
                "valid_to": (row.get("DATEND") or "").strip().strip('"')[:32],
            }
        )
    return candidate_rows


def sync_mask44(*, force: bool = False) -> dict[str, Any]:
    meta = fetch_fts_meta(MASK44_DATASET_ID)
    version = latest_version(meta)
    if version is None:
        raise RuntimeError("mask44: нет версий в meta.csv")

    snapshot_id = version.snapshot_id
    with SessionLocal() as preflight_db:
        require_no_snapshot_rollback(
            snapshot_id,
            _successful_snapshot_ids(preflight_db),
            source_key="mask44",
        )
    dest = backend_opendata_dir() / "mask44" / snapshot_id
    raw = download_bytes(
        version.url,
        dest=dest,
        expected_kind="csv",
        dataset_id=MASK44_DATASET_ID,
        expected_suffix=".csv",
    )
    sha = hashlib.sha256(raw).hexdigest()
    text = raw.decode("utf-8-sig", errors="replace")
    candidate_rows = _parse_mask44_csv(text)
    if not candidate_rows:
        raise RuntimeError("mask44: official snapshot contains zero valid masks; live table preserved")

    rows_in = len(candidate_rows)
    with SessionLocal() as db:
        try:
            acquire_opendata_write_lock(
                db,
                source_key="mask44",
                dataset_id=MASK44_DATASET_ID,
            )
            require_no_snapshot_rollback(
                snapshot_id,
                _successful_snapshot_ids(db),
                source_key="mask44",
            )
            same_revision_logs = (
                db.query(OpendataSyncLog)
                .filter(
                    OpendataSyncLog.source_key == "mask44",
                    OpendataSyncLog.dataset_id == MASK44_DATASET_ID,
                    OpendataSyncLog.snapshot_id == snapshot_id,
                    OpendataSyncLog.status == "ok",
                )
                .order_by(OpendataSyncLog.id.desc())
                .all()
            )
            require_immutable_snapshot_hash(
                sha,
                (row.file_sha256 for row in same_revision_logs),
                source_key="mask44",
                snapshot_id=snapshot_id,
            )
            if not force:
                done = same_revision_logs[0] if same_revision_logs else None
                if done:
                    live_rows, live_fingerprint = _mask44_live_fingerprint(db)
                    logged_rows = int(done.row_count or 0)
                    exact_live_evidence = live_snapshot_details_match(
                        done.details,
                        source_key="mask44",
                        dataset_id=MASK44_DATASET_ID,
                        snapshot_id=snapshot_id,
                        artifact_url=version.url,
                        artifact_sha256=sha,
                        live_rows=live_rows,
                        live_fingerprint_sha256=live_fingerprint,
                    )
                    if (
                        logged_rows > 0
                        and live_rows == logged_rows
                        and str(done.file_sha256 or "").casefold() == sha
                        and exact_live_evidence
                    ):
                        return {
                            "status": "skipped",
                            "official_source_verified": bool(
                                getattr(meta, "provenance_verified", False)
                            ),
                            "dataset_id": MASK44_DATASET_ID,
                            "snapshot_id": snapshot_id,
                            "rows": live_rows,
                            "verified_live_rows": live_rows,
                        }
                    logger.warning(
                        "mask44 snapshot {} has no exact current artifact/live "
                        "evidence (logged={}, live={}, exact={}); re-importing",
                        snapshot_id,
                        logged_rows,
                        live_rows,
                        exact_live_evidence,
                    )
            existing_count = db.query(CustomsDocMask).count()
            validate_full_snapshot(
                source_id="fts_customs_document_masks",
                candidate_count=rows_in,
                existing_count=existing_count,
                minimum_rows=configured_minimum_rows("fts_customs_document_masks", 10),
            )
            db.query(CustomsDocMask).delete(synchronize_session=False)
            db.add_all(CustomsDocMask(**row) for row in candidate_rows)
            db.flush()
            live_rows, live_fingerprint = _mask44_live_fingerprint(db)
            if live_rows != rows_in:
                raise RuntimeError(
                    "mask44 persisted row count differs from the validated snapshot; "
                    "transaction rolled back"
                )
            db.add(
                OpendataSyncLog(
                    source_key="mask44",
                    dataset_id=MASK44_DATASET_ID,
                    snapshot_id=snapshot_id,
                    file_url=version.url,
                    file_sha256=sha,
                    row_count=rows_in,
                    synced_at=datetime.now(timezone.utc).isoformat(),
                    data_as_of=snapshot_date_from_id(snapshot_id) or meta.modified,
                    status="ok",
                    details=encode_live_snapshot_details(
                        source_key="mask44",
                        dataset_id=MASK44_DATASET_ID,
                        snapshot_id=snapshot_id,
                        artifact_url=version.url,
                        artifact_sha256=sha,
                        live_rows=live_rows,
                        live_fingerprint_sha256=live_fingerprint,
                    ),
                )
            )
            db.commit()
        except Exception:
            db.rollback()
            raise
    logger.info("mask44: imported {} masks from {}", rows_in, snapshot_id)
    return {
        "status": "ok",
        "official_source_verified": bool(getattr(meta, "provenance_verified", False)),
        "dataset_id": MASK44_DATASET_ID,
        "snapshot_id": snapshot_id,
        "rows": rows_in,
        "verified_live_rows": live_rows,
    }


def fetch_customs_catalog() -> list[dict[str, str]]:
    """Скачивает list.csv — каталог opendata-наборов ФТС."""
    dest = backend_opendata_dir() / "customs_catalog" / "list.csv"
    raw = download_bytes(
        CATALOG_URL,
        dest=dest,
        expected_kind="csv",
        expected_path="/opendata/list.csv",
    )
    rows: list[dict[str, str]] = []
    for row in csv.reader(io.StringIO(raw.decode("utf-8-sig", errors="replace"))):
        if len(row) >= 4:
            rows.append({"id": row[0], "title": row[1], "meta_url": row[2], "format": row[3]})
    return rows


def sync_customs_catalog() -> dict[str, Any]:
    rows = fetch_customs_catalog()
    if not rows:
        raise RuntimeError("FTS opendata catalog contains zero rows")
    ved_keywords = ("троис", "маск", "валют", "пропуск", "тн вэд", "деклар", "склад")
    relevant = [r for r in rows if any(k in r["title"].lower() for k in ved_keywords)]
    managed = {MASK44_DATASET_ID, "7730176610-trois"}
    normalized_ids = [str(row.get("id") or "").strip() for row in rows]
    by_id = {dataset_id: row for dataset_id, row in zip(normalized_ids, rows)}
    missing = sorted(managed - set(by_id))
    if missing:
        raise RuntimeError(
            "FTS opendata catalog is missing managed datasets: " + ", ".join(missing)
        )
    for dataset_id in sorted(managed):
        if normalized_ids.count(dataset_id) != 1:
            raise RuntimeError(
                f"FTS opendata catalog contains duplicate managed dataset: {dataset_id}"
            )
        row = by_id[dataset_id]
        meta_url = str(row.get("meta_url") or "").strip()
        _validate_official_url(
            meta_url,
            agency="fts",
            dataset_id=dataset_id,
            expected_suffix=".csv",
            expected_path=f"/{dataset_id}/meta.csv",
        )
        if str(row.get("format") or "").strip().casefold() != "csv":
            raise RuntimeError(
                f"FTS opendata catalog has unexpected format for {dataset_id}: "
                f"{row.get('format')!r}"
            )
    return {
        "status": "ok",
        "official_source_verified": True,
        "managed_dataset_ids": sorted(managed),
        "total": len(rows),
        "ved_relevant": relevant,
    }
