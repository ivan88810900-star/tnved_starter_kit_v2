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
from ..models.tnved import OpendataSyncLog, TroisRegistry
from .opendata_client import (
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
from .trois_registry_sync import normalize_trademark_for_registry, upsert_trois_registry_rows
from .snapshot_safety import configured_minimum_rows

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


def _trois_live_fingerprint(db) -> tuple[int, str]:
    rows = (
        db.query(
            TroisRegistry.reg_number,
            TroisRegistry.brand,
            TroisRegistry.trademark,
            TroisRegistry.right_holder,
            TroisRegistry.status,
            TroisRegistry.valid_until,
            TroisRegistry.representatives,
            TroisRegistry.is_active,
        )
        .order_by(TroisRegistry.reg_number)
        .yield_per(2_000)
    )
    return canonical_rows_fingerprint(tuple(row) for row in rows)


def _successful_snapshot_ids(db) -> list[str]:
    return [
        str(snapshot_id or "").strip()
        for (snapshot_id,) in db.query(OpendataSyncLog.snapshot_id)
        .filter(
            OpendataSyncLog.source_key == SOURCE_KEY,
            OpendataSyncLog.dataset_id == TROIS_DATASET_ID,
            OpendataSyncLog.status == "ok",
            OpendataSyncLog.row_count > 0,
        )
        .all()
    ]


def _parse_trois_csv(text: str) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    if not reader.fieldnames:
        raise RuntimeError("TROIS snapshot is missing its CSV header")
    fieldnames = {str(name or "").strip().lstrip("\ufeff") for name in reader.fieldnames}
    required = {"REGNOM", "G31_12"}
    if not required.issubset(fieldnames):
        raise RuntimeError(
            "TROIS snapshot has an unexpected schema; missing: "
            + ", ".join(sorted(required - fieldnames))
        )
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
    with SessionLocal() as preflight_db:
        require_no_snapshot_rollback(
            snapshot_id,
            _successful_snapshot_ids(preflight_db),
            source_key=SOURCE_KEY,
        )
    dest_dir = backend_opendata_dir() / "trois"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_file = dest_dir / snapshot_id
    raw = download_bytes(
        version.url,
        dest=dest_file,
        expected_kind="csv",
        dataset_id=TROIS_DATASET_ID,
        expected_suffix=".csv",
    )
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

    data_as_of = snapshot_date_from_id(snapshot_id) or meta.modified
    synced_at = datetime.now(timezone.utc).isoformat()
    with SessionLocal() as db:
        try:
            acquire_opendata_write_lock(
                db,
                source_key=SOURCE_KEY,
                dataset_id=TROIS_DATASET_ID,
            )
            require_no_snapshot_rollback(
                snapshot_id,
                _successful_snapshot_ids(db),
                source_key=SOURCE_KEY,
            )
            same_revision_logs = (
                db.query(OpendataSyncLog)
                .filter(
                    OpendataSyncLog.source_key == SOURCE_KEY,
                    OpendataSyncLog.dataset_id == TROIS_DATASET_ID,
                    OpendataSyncLog.snapshot_id == snapshot_id,
                    OpendataSyncLog.status == "ok",
                )
                .order_by(OpendataSyncLog.id.desc())
                .all()
            )
            require_immutable_snapshot_hash(
                sha,
                (row.file_sha256 for row in same_revision_logs),
                source_key=SOURCE_KEY,
                snapshot_id=snapshot_id,
            )
            if not force:
                done = same_revision_logs[0] if same_revision_logs else None
                if done:
                    live_rows, live_fingerprint = _trois_live_fingerprint(db)
                    logged_rows = int(done.row_count or 0)
                    exact_live_evidence = live_snapshot_details_match(
                        done.details,
                        source_key=SOURCE_KEY,
                        dataset_id=TROIS_DATASET_ID,
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
                        logger.info(
                            "ТРОИС opendata: snapshot {} уже импортирован",
                            snapshot_id,
                        )
                        return {
                            "status": "skipped",
                            "official_source_verified": bool(
                                getattr(meta, "provenance_verified", False)
                            ),
                            "dataset_id": TROIS_DATASET_ID,
                            "snapshot_id": snapshot_id,
                            "rows": live_rows,
                            "verified_live_rows": live_rows,
                            "data_as_of": done.data_as_of,
                        }
                    logger.warning(
                        "ТРОИС snapshot {} has no exact current artifact/live "
                        "evidence (logged={}, live={}, exact={}); re-importing",
                        snapshot_id,
                        logged_rows,
                        live_rows,
                        exact_live_evidence,
                    )
            stats = upsert_trois_registry_rows(
                parsed,
                replace_snapshot=True,
                db=db,
                commit=False,
                minimum_rows=configured_minimum_rows("fts_trois_registry", 100),
            )
            db.flush()
            live_rows, live_fingerprint = _trois_live_fingerprint(db)
            if live_rows <= 0:
                raise RuntimeError("TROIS persisted snapshot is empty; transaction rolled back")
            db.add(
                OpendataSyncLog(
                    source_key=SOURCE_KEY,
                    dataset_id=TROIS_DATASET_ID,
                    snapshot_id=snapshot_id,
                    file_url=version.url,
                    file_sha256=sha,
                    row_count=live_rows,
                    synced_at=synced_at,
                    data_as_of=data_as_of,
                    status="ok",
                    details=encode_live_snapshot_details(
                        source_key=SOURCE_KEY,
                        dataset_id=TROIS_DATASET_ID,
                        snapshot_id=snapshot_id,
                        artifact_url=version.url,
                        artifact_sha256=sha,
                        live_rows=live_rows,
                        live_fingerprint_sha256=live_fingerprint,
                        stats=stats,
                    ),
                )
            )
            db.commit()
        except Exception:
            db.rollback()
            raise

    from .trois_registry_loader import sync_db_to_local_cache

    sync_db_to_local_cache(force=True)

    return {
        "status": "ok",
        "official_source_verified": bool(getattr(meta, "provenance_verified", False)),
        "dataset_id": TROIS_DATASET_ID,
        "snapshot_id": snapshot_id,
        "file": str(dest_file),
        "parsed_rows": len(parsed),
        "verified_live_rows": live_rows,
        "data_as_of": data_as_of,
        **stats,
    }
