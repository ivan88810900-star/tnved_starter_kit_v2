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
    backend_opendata_dir,
    download_bytes,
    fetch_fts_meta,
    latest_version,
    snapshot_date_from_id,
)

MASK44_DATASET_ID = "7730176610-mask44"
CATALOG_URL = "https://customs.gov.ru/opendata/list.csv"


def sync_mask44(*, force: bool = False) -> dict[str, Any]:
    meta = fetch_fts_meta(MASK44_DATASET_ID)
    version = latest_version(meta)
    if version is None:
        raise RuntimeError("mask44: нет версий в meta.csv")

    snapshot_id = version.snapshot_id
    with SessionLocal() as db:
        if not force:
            done = (
                db.query(OpendataSyncLog)
                .filter(
                    OpendataSyncLog.source_key == "mask44",
                    OpendataSyncLog.snapshot_id == snapshot_id,
                    OpendataSyncLog.status == "ok",
                )
                .first()
            )
            if done:
                return {"status": "skipped", "snapshot_id": snapshot_id, "rows": done.row_count}

    dest = backend_opendata_dir() / "mask44" / snapshot_id
    raw = download_bytes(version.url, dest=dest)
    sha = hashlib.sha256(raw).hexdigest()
    text = raw.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    rows_in = 0
    with SessionLocal() as db:
        db.query(CustomsDocMask).delete()
        for row in reader:
            pattern = (row.get("K_MASKA") or "").strip().strip('"')
            if not pattern:
                continue
            db.add(
                CustomsDocMask(
                    sid_smev=(row.get("SID_SMEV") or "").strip().strip('"')[:64],
                    kod=(row.get("KOD") or "").strip().strip('"')[:16],
                    mask_number=(row.get("N_MSK") or "").strip().strip('"')[:8],
                    name=(row.get("NAME_MSK") or "").strip().strip('"'),
                    mask_pattern=pattern,
                    description=(row.get("DSCR_MSK") or "").strip().strip('"'),
                    valid_from=(row.get("DATBEG") or "").strip().strip('"')[:32],
                    valid_to=(row.get("DATEND") or "").strip().strip('"')[:32],
                )
            )
            rows_in += 1
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
            )
        )
        db.commit()
    logger.info("mask44: imported {} masks from {}", rows_in, snapshot_id)
    return {"status": "ok", "snapshot_id": snapshot_id, "rows": rows_in}


def fetch_customs_catalog() -> list[dict[str, str]]:
    """Скачивает list.csv — каталог opendata-наборов ФТС."""
    dest = backend_opendata_dir() / "customs_catalog" / "list.csv"
    raw = download_bytes(CATALOG_URL, dest=dest)
    rows: list[dict[str, str]] = []
    for row in csv.reader(io.StringIO(raw.decode("utf-8-sig", errors="replace"))):
        if len(row) >= 4:
            rows.append({"id": row[0], "title": row[1], "meta_url": row[2], "format": row[3]})
    return rows


def sync_customs_catalog() -> dict[str, Any]:
    rows = fetch_customs_catalog()
    ved_keywords = ("троис", "маск", "валют", "пропуск", "тн вэд", "деклар", "склад")
    relevant = [r for r in rows if any(k in r["title"].lower() for k in ved_keywords)]
    return {"status": "ok", "total": len(rows), "ved_relevant": relevant}
