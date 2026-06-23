"""Синхронизация реестра ТРОИС из официального opendata ФТС (7730176610-trois)."""

from __future__ import annotations

import csv
import hashlib
import io
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger

from ..db import SessionLocal
from ..models.tnved import OpendataSyncLog
from .opendata_client import (
    backend_opendata_dir,
    download_bytes,
    fetch_fts_meta,
    latest_version,
    snapshot_date_from_id,
)
from .trois_registry_sync import normalize_trademark_for_registry, upsert_trois_registry_rows

TROIS_DATASET_ID = "7730176610-trois"
SOURCE_KEY = "trois"

_TROIS_FIELDS = (
    "REGNOM",
    "G31_12",
    "NOTE",
    "NAME",
    "NAMEL",
    "DATEEND",
    "NAMET",
    "MKTU",
)


def _parse_trois_csv(text: str) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    if not reader.fieldnames:
        return []
    rows: list[dict[str, str]] = []
    for raw in reader:
        reg = (raw.get("REGNOM") or "").strip().strip('"')
        tm = normalize_trademark_for_registry(raw.get("G31_12") or "")
        if not reg or not tm:
            continue
        holder = (raw.get("NAME") or raw.get("NAMEL") or "").strip()
        status = (raw.get("NOTE") or "").strip()
        valid_until = (raw.get("DATEEND") or "").strip()
        goods = (raw.get("NAMET") or "").strip()
        mktu = (raw.get("MKTU") or "").strip()
        reps = "; ".join(x for x in (goods, f"МКТУ {mktu}" if mktu else "") if x)
        rows.append(
            {
                "reg_number": reg,
                "trademark": tm,
                "brand": tm,
                "right_holder": holder,
                "status": status or "OPENDATA_FTS",
                "valid_until": valid_until,
                "representatives": reps,
            }
        )
    return rows


def sync_trois_opendata(*, force: bool = False) -> dict[str, Any]:
    """
    Скачивает последний полный CSV-снимок ТРОИС (~50k строк, ~42 MB) и upsert в ``trois_registry``.
    """
    meta = fetch_fts_meta(TROIS_DATASET_ID)
    version = latest_version(meta)
    if version is None:
        raise RuntimeError(f"ТРОИС opendata: нет версий данных в meta.csv ({TROIS_DATASET_ID})")

    snapshot_id = version.snapshot_id
    with SessionLocal() as db:
        if not force:
            done = (
                db.query(OpendataSyncLog)
                .filter(
                    OpendataSyncLog.source_key == SOURCE_KEY,
                    OpendataSyncLog.snapshot_id == snapshot_id,
                    OpendataSyncLog.status == "ok",
                )
                .first()
            )
            if done:
                logger.info("ТРОИС opendata: snapshot {} уже импортирован", snapshot_id)
                return {
                    "status": "skipped",
                    "snapshot_id": snapshot_id,
                    "rows": done.row_count,
                    "data_as_of": done.data_as_of,
                }

    dest_dir = backend_opendata_dir() / "trois"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_file = dest_dir / snapshot_id
    raw = download_bytes(version.url, dest=dest_file)
    sha = hashlib.sha256(raw).hexdigest()
    text = raw.decode("utf-8-sig", errors="replace")
    parsed = _parse_trois_csv(text)
    # В официальном CSV иногда встречаются повторяющиеся REGNOM — оставляем последнюю версию.
    dedup: dict[str, dict[str, str]] = {}
    for row in parsed:
        reg = (row.get("reg_number") or "").strip()
        if reg:
            dedup[reg] = row
    parsed = list(dedup.values())
    stats = upsert_trois_registry_rows(parsed)

    data_as_of = snapshot_date_from_id(snapshot_id) or meta.modified
    synced_at = datetime.now(timezone.utc).isoformat()
    with SessionLocal() as db:
        db.add(
            OpendataSyncLog(
                source_key=SOURCE_KEY,
                dataset_id=TROIS_DATASET_ID,
                snapshot_id=snapshot_id,
                file_url=version.url,
                file_sha256=sha,
                row_count=len(parsed),
                synced_at=synced_at,
                data_as_of=data_as_of,
                status="ok",
                details=f"created={stats['created']} updated={stats['updated']} skipped={stats['skipped']}",
            )
        )
        db.commit()

    from .trois_registry_loader import sync_db_to_local_cache

    sync_db_to_local_cache(force=True)

    return {
        "status": "ok",
        "snapshot_id": snapshot_id,
        "file": str(dest_file),
        "parsed_rows": len(parsed),
        "data_as_of": data_as_of,
        **stats,
    }
