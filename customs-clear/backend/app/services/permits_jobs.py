"""Фоновые задания массовой проверки разрешений (ФСА).

Сохраняются в БД (`permits_verify_jobs`) и переживают перезапуск процесса.
Задания в статусах queued/running при обрыве помечаются ошибкой при старте приложения.
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import uuid4

from loguru import logger
from sqlalchemy import func
from sqlalchemy.orm import load_only
from starlette.background import BackgroundTasks

from ..datetime_util import utc_now_naive
from ..db import SessionLocal
from ..models import PermitsVerifyJob
from .permits_service import check_permits


def _utc_ts(dt: datetime | None) -> float | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _summary(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "total": len(results),
        "valid": sum(1 for r in results if r.get("status") == "VALID"),
        "not_found": sum(1 for r in results if r.get("status") == "NOT_FOUND"),
        "unknown": sum(1 for r in results if r.get("status") == "UNKNOWN"),
        "hs_mismatch": sum(
            1 for r in results if (r.get("hs_code_check") or {}).get("hs_match") == "mismatch"
        ),
    }


def _db_insert_queued(job_id: str, request_payload: dict[str, Any], created_by_username: str | None) -> None:
    with SessionLocal() as db:
        db.add(
            PermitsVerifyJob(
                id=job_id,
                status="queued",
                request_payload=request_payload,
                created_by_username=(created_by_username or "").strip() or None,
            )
        )
        db.commit()


def _db_set_running(job_id: str) -> None:
    with SessionLocal() as db:
        row = db.get(PermitsVerifyJob, job_id)
        if row:
            row.status = "running"
            db.commit()


def _db_complete(job_id: str, items: List[Dict[str, Any]], summary: Dict[str, Any]) -> None:
    with SessionLocal() as db:
        row = db.get(PermitsVerifyJob, job_id)
        if row:
            row.status = "done"
            row.items = items
            row.summary = summary
            row.finished_at = utc_now_naive()
            row.error = None
            db.commit()


def _db_fail(job_id: str, message: str) -> None:
    with SessionLocal() as db:
        row = db.get(PermitsVerifyJob, job_id)
        if row:
            row.status = "error"
            row.error = message
            row.finished_at = utc_now_naive()
            db.commit()


def _db_get_job(job_id: str) -> PermitsVerifyJob | None:
    with SessionLocal() as db:
        return db.get(PermitsVerifyJob, job_id)


def permits_verify_jobs_counts_by_status() -> Dict[str, int]:
    """Число async-заданий ФСА по статусу (для дашборда)."""
    with SessionLocal() as db:
        rows = (
            db.query(PermitsVerifyJob.status, func.count())
            .group_by(PermitsVerifyJob.status)
            .all()
        )
        return {str(s or ""): int(c) for s, c in rows}


def permits_job_items_as_csv(items: List[Dict[str, Any]] | None) -> str:
    """CSV по строкам результата проверки разрешений."""
    fields = [
        "type",
        "number",
        "status",
        "holder",
        "valid_from",
        "valid_to",
        "registry_link",
        "verified_at",
        "registry_source",
        "hs_code_check_json",
    ]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    w.writeheader()
    for it in items or []:
        if not isinstance(it, dict):
            continue
        row = {k: it.get(k, "") for k in fields if k != "hs_code_check_json"}
        hc = it.get("hs_code_check")
        row["hs_code_check_json"] = json.dumps(hc, ensure_ascii=False) if hc is not None else ""
        w.writerow(row)
    return buf.getvalue()


def mark_interrupted_jobs_on_startup() -> int:
    """Пометить незавершённые задания (после рестарта) как error. Возвращает число обновлённых."""
    msg = "Прервано перезапуском сервера"
    with SessionLocal() as db:
        rows = (
            db.query(PermitsVerifyJob)
            .filter(PermitsVerifyJob.status.in_(("queued", "running")))
            .all()
        )
        n = 0
        now = utc_now_naive()
        for row in rows:
            row.status = "error"
            row.error = msg
            row.finished_at = now
            n += 1
        if n:
            db.commit()
            logger.info(f"permits_verify_jobs: помечено прерванных заданий: {n}")
        return n


async def create_verify_job(
    rows: List[Dict[str, str]],
    hs_code: str,
    enrich: bool,
    background_tasks: BackgroundTasks,
    *,
    created_by_username: str | None,
) -> str:
    job_id = uuid4().hex
    request_payload: dict[str, Any] = {"rows": rows, "hs_code": hs_code, "enrich": enrich}
    await asyncio.to_thread(_db_insert_queued, job_id, request_payload, created_by_username)

    async def runner() -> None:
        await asyncio.to_thread(_db_set_running, job_id)
        try:
            results = await check_permits(rows, hs_code, enrich=enrich)
            await asyncio.to_thread(_db_complete, job_id, results, _summary(results))
        except Exception as e:
            logger.exception(f"permits_verify_jobs {job_id}: {e}")
            await asyncio.to_thread(_db_fail, job_id, str(e))

    # Starlette выполняет задачи после ответа клиенту — надёжнее, чем asyncio.create_task (в т.ч. TestClient).
    background_tasks.add_task(runner)
    return job_id


def _job_visible_to(
    row: PermitsVerifyJob,
    *,
    access_username: str,
    access_is_admin: bool,
) -> bool:
    if access_is_admin:
        return True
    owner = (row.created_by_username or "").strip()
    if not owner:
        return False
    return owner == (access_username or "").strip()


async def get_job(
    job_id: str,
    *,
    access_username: str = "",
    access_is_admin: bool = False,
) -> Dict[str, Any] | None:

    def _load() -> PermitsVerifyJob | None:
        return _db_get_job(job_id)

    j = await asyncio.to_thread(_load)
    if not j:
        return None
    if not _job_visible_to(j, access_username=access_username, access_is_admin=access_is_admin):
        return None
    return {
        "status": j.status,
        "created_at": _utc_ts(j.created_at),
        "finished_at": _utc_ts(j.finished_at),
        "error": j.error,
        "summary": j.summary,
        "items": j.items,
        "created_by_username": j.created_by_username,
    }


async def list_jobs(
    limit: int = 50,
    *,
    access_username: str = "",
    access_is_admin: bool = False,
) -> List[Dict[str, Any]]:
    """Краткий список заданий (без полного items)."""
    limit = max(1, min(limit, 200))

    def _load() -> List[Dict[str, Any]]:
        with SessionLocal() as db:
            q = db.query(PermitsVerifyJob).options(
                load_only(
                    PermitsVerifyJob.id,
                    PermitsVerifyJob.created_by_username,
                    PermitsVerifyJob.status,
                    PermitsVerifyJob.created_at,
                    PermitsVerifyJob.finished_at,
                    PermitsVerifyJob.error,
                    PermitsVerifyJob.summary,
                )
            )
            if not access_is_admin:
                viewer = (access_username or "").strip()
                q = q.filter(PermitsVerifyJob.created_by_username == viewer)
            rows = (
                q.order_by(PermitsVerifyJob.created_at.desc())
                .limit(limit)
                .all()
            )
            out: List[Dict[str, Any]] = []
            for r in rows:
                out.append(
                    {
                        "job_id": r.id,
                        "status": r.status,
                        "created_at": _utc_ts(r.created_at),
                        "finished_at": _utc_ts(r.finished_at),
                        "error": r.error,
                        "summary": r.summary,
                        "created_by_username": r.created_by_username,
                    }
                )
            return out

    return await asyncio.to_thread(_load)
