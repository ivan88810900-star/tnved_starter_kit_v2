"""Сводный статус opendata-реестров и прогресс backfill ФСА."""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func

from ..db import SessionLocal
from ..models.tnved import CustomsDocMask, FsaCertificate, OpendataSyncLog, TroisRegistry
from .opendata_client import FSA_BASE, fetch_fsa_meta

FSA_RSS_ID = "7736638268-rss"
FSA_RDS_ID = "7736638268-rds"
BACKFILL_LOG = Path(__file__).resolve().parents[2] / "logs" / "fsa_backfill.log"
BACKFILL_PID = Path(__file__).resolve().parents[2] / "logs" / "fsa_backfill.pid"


def _month_from_snapshot(snapshot_id: str) -> str:
    m = re.search(r"data-(\d{4})(\d{2})\d{2}", snapshot_id or "")
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    m = re.search(r"(\d{4})(\d{2})\d{2}", snapshot_id or "")
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    return ""


def _backfill_running() -> bool:
    if not BACKFILL_PID.exists():
        return False
    try:
        pid = int(BACKFILL_PID.read_text().strip())
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False


def _count_sync_months(source_key: str) -> tuple[int, str, str]:
    with SessionLocal() as db:
        rows = (
            db.query(OpendataSyncLog.snapshot_id, OpendataSyncLog.data_as_of)
            .filter(OpendataSyncLog.source_key == source_key, OpendataSyncLog.status == "ok")
            .all()
        )
    months = sorted({_month_from_snapshot(s) for s, _ in rows if _month_from_snapshot(s)})
    last = months[-1] if months else ""
    first = months[0] if months else ""
    return len(months), first, last


def _fsa_total_months(dataset_id: str) -> int:
    try:
        meta = fetch_fsa_meta(dataset_id)
        return len(meta.versions)
    except Exception:
        return 0


def build_opendata_status() -> dict[str, Any]:
    running = _backfill_running()
    with SessionLocal() as db:
        trois_count = int(db.query(func.count(TroisRegistry.id)).scalar() or 0)
        mask_count = int(db.query(func.count(CustomsDocMask.id)).scalar() or 0)
        cert_count = int(
            db.query(func.count(FsaCertificate.id)).filter(FsaCertificate.doc_type == "СС").scalar() or 0
        )
        decl_count = int(
            db.query(func.count(FsaCertificate.id)).filter(FsaCertificate.doc_type == "ДС").scalar() or 0
        )
        trois_log = (
            db.query(OpendataSyncLog)
            .filter(OpendataSyncLog.source_key == "trois", OpendataSyncLog.status == "ok")
            .order_by(OpendataSyncLog.id.desc())
            .first()
        )
        mask_log = (
            db.query(OpendataSyncLog)
            .filter(OpendataSyncLog.source_key == "mask44", OpendataSyncLog.status == "ok")
            .order_by(OpendataSyncLog.id.desc())
            .first()
        )

    rss_months, rss_first, rss_last = _count_sync_months("fsa_rss")
    rds_months, rds_first, rds_last = _count_sync_months("fsa_rds")
    rss_total = _fsa_total_months(FSA_RSS_ID)
    rds_total = _fsa_total_months(FSA_RDS_ID)

    def _eta(done: int, total: int) -> str | None:
        if not running or total <= 0 or done <= 0:
            return None
        remaining = max(0, total - done)
        if remaining == 0:
            return "завершено"
        # грубая оценка: ~3 мин на месячный архив RSS + ~15 мин RDS
        per_month_sec = 900
        sec = remaining * per_month_sec
        hours = sec // 3600
        mins = (sec % 3600) // 60
        if hours:
            return f"~{hours}ч {mins}м"
        return f"~{mins}м"

    return {
        "status": "OK",
        "backfill_process_running": running,
        "trois": {
            "records": trois_count,
            "as_of": (trois_log.data_as_of if trois_log else ""),
            "snapshot_id": (trois_log.snapshot_id if trois_log else ""),
            "source": "customs.gov.ru/opendata/7730176610-trois",
        },
        "mask44": {
            "records": mask_count,
            "as_of": (mask_log.data_as_of if mask_log else ""),
            "source": "customs.gov.ru/opendata/7730176610-mask44",
        },
        "fsa_certificates": {
            "records": cert_count,
            "months_imported": rss_months,
            "months_total": rss_total,
            "first_month": rss_first,
            "last_month": rss_last,
            "backfill_in_progress": running and rss_months < rss_total,
            "eta": _eta(rss_months, rss_total),
            "source": f"{FSA_BASE}/opendata/{FSA_RSS_ID}",
        },
        "fsa_declarations": {
            "records": decl_count,
            "months_imported": rds_months,
            "months_total": rds_total,
            "first_month": rds_first,
            "last_month": rds_last,
            "backfill_in_progress": running and rds_months < rds_total,
            "eta": _eta(rds_months, rds_total),
            "source": f"{FSA_BASE}/opendata/{FSA_RDS_ID}",
        },
    }


def build_backfill_progress_report() -> dict[str, Any]:
    status = build_opendata_status()
    log_tail = ""
    if BACKFILL_LOG.exists():
        try:
            lines = BACKFILL_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
            log_tail = "\n".join(lines[-8:])
        except OSError:
            pass
    return {
        **status,
        "log_tail": log_tail,
        "checked_at": datetime.utcnow().isoformat() + "Z",
    }
