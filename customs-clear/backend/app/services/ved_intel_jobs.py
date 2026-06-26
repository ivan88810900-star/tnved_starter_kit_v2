"""Фоновые задания полного ВЭД-разбора (polling). Файлы во временной папке до завершения."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Dict, List
from uuid import uuid4

from fastapi import UploadFile
from loguru import logger
from sqlalchemy import func
from starlette.background import BackgroundTasks

from ..datetime_util import utc_now_naive
from ..db import SessionLocal
from ..models import VedIntelJob
from .ved_intel_analyze_core import run_ved_intel_analyze_core, ved_intel_semaphore


def _utc_ts(dt: datetime | None) -> float | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _db_insert_queued(job_id: str, request_payload: dict[str, Any]) -> None:
    with SessionLocal() as db:
        db.add(
            VedIntelJob(
                id=job_id,
                status="queued",
                request_payload=request_payload,
            )
        )
        db.commit()


def _db_set_running(job_id: str) -> None:
    with SessionLocal() as db:
        row = db.get(VedIntelJob, job_id)
        if row:
            row.status = "running"
            db.commit()


def _db_complete(job_id: str, result: Dict[str, Any]) -> None:
    with SessionLocal() as db:
        row = db.get(VedIntelJob, job_id)
        if row:
            row.status = "done"
            row.result = result
            row.finished_at = utc_now_naive()
            row.error = None
            db.commit()


def _db_fail(job_id: str, message: str) -> None:
    with SessionLocal() as db:
        row = db.get(VedIntelJob, job_id)
        if row:
            row.status = "error"
            row.error = message
            row.finished_at = utc_now_naive()
            db.commit()


def _db_get_job(job_id: str) -> VedIntelJob | None:
    with SessionLocal() as db:
        return db.get(VedIntelJob, job_id)


def mark_interrupted_ved_intel_jobs_on_startup() -> int:
    msg = "Прервано перезапуском сервера (временные файлы задания недоступны)"
    with SessionLocal() as db:
        rows = (
            db.query(VedIntelJob)
            .filter(VedIntelJob.status.in_(("queued", "running")))
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
            logger.info(f"ved_intel_jobs: помечено прерванных заданий: {n}")
        return n


def ved_intel_jobs_counts_by_status() -> Dict[str, int]:
    with SessionLocal() as db:
        rows = (
            db.query(VedIntelJob.status, func.count())
            .group_by(VedIntelJob.status)
            .all()
        )
        return {str(s or ""): int(c) for s, c in rows}


async def create_ved_intel_job(
    *,
    main_bytes: bytes,
    main_filename: str,
    main_content_type: str,
    companion_bytes: bytes | None,
    companion_filename: str | None,
    companion_content_type: str | None,
    country: str,
    freight_total_rub: float,
    fallback_customs_total_rub: float,
    extract_permits: bool,
    verify_fsa: bool,
    skip_registry_verify: bool,
    hs_code: str | None,
    use_ai_declaration: bool,
    client_id: str | None,
    persist: bool,
    run_payment: bool,
    document_store: Dict[str, Dict[str, Any]],
    background_tasks: BackgroundTasks,
) -> str:
    job_id = uuid4().hex
    workdir = os.path.join(tempfile.gettempdir(), f"cc_ved_intel_{job_id}")
    os.makedirs(workdir, exist_ok=True)
    main_path = os.path.join(workdir, "main.bin")
    with open(main_path, "wb") as f:
        f.write(main_bytes)
    companion_path: str | None = None
    if companion_bytes is not None and companion_filename:
        companion_path = os.path.join(workdir, "companion.bin")
        with open(companion_path, "wb") as f:
            f.write(companion_bytes)

    request_payload: dict[str, Any] = {
        "workdir": workdir,
        "main_filename": main_filename or "document",
        "main_content_type": main_content_type or "application/octet-stream",
        "companion_filename": companion_filename,
        "companion_content_type": companion_content_type or "application/octet-stream",
        "country": country,
        "freight_total_rub": freight_total_rub,
        "fallback_customs_total_rub": fallback_customs_total_rub,
        "extract_permits": extract_permits,
        "verify_fsa": verify_fsa,
        "skip_registry_verify": skip_registry_verify,
        "hs_code": hs_code,
        "use_ai_declaration": use_ai_declaration,
        "client_id": client_id,
        "persist": persist,
        "run_payment": run_payment,
    }
    await asyncio.to_thread(_db_insert_queued, job_id, request_payload)

    async def runner() -> None:
        await asyncio.to_thread(_db_set_running, job_id)
        try:
            async with ved_intel_semaphore():
                with open(main_path, "rb") as f:
                    mb = f.read()
                doc_uf = UploadFile(
                    file=BytesIO(mb),
                    filename=request_payload["main_filename"],
                )
                comp_uf = None
                if companion_path and os.path.isfile(companion_path):
                    with open(companion_path, "rb") as f:
                        cb = f.read()
                    comp_uf = UploadFile(
                        file=BytesIO(cb),
                        filename=request_payload.get("companion_filename") or "companion",
                    )
                merged = await run_ved_intel_analyze_core(
                    document=doc_uf,
                    companion=comp_uf,
                    country=request_payload["country"],
                    freight_total_rub=float(request_payload["freight_total_rub"]),
                    fallback_customs_total_rub=float(request_payload["fallback_customs_total_rub"]),
                    extract_permits=bool(request_payload["extract_permits"]),
                    verify_fsa=bool(request_payload["verify_fsa"]),
                    skip_registry_verify=bool(request_payload["skip_registry_verify"]),
                    hs_code=request_payload.get("hs_code"),
                    use_ai_declaration=bool(request_payload["use_ai_declaration"]),
                    client_id=request_payload.get("client_id"),
                    persist=bool(request_payload["persist"]),
                    run_payment=bool(request_payload["run_payment"]),
                    document_store=document_store,
                )
                await asyncio.to_thread(_db_complete, job_id, merged)
        except Exception as e:
            logger.exception(f"ved_intel_jobs {job_id}: {e}")
            await asyncio.to_thread(_db_fail, job_id, str(e))
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    background_tasks.add_task(runner)
    return job_id


async def get_ved_intel_job(job_id: str) -> Dict[str, Any] | None:

    def _load() -> VedIntelJob | None:
        return _db_get_job(job_id)

    j = await asyncio.to_thread(_load)
    if not j:
        return None
    out: Dict[str, Any] = {
        "status": j.status,
        "created_at": _utc_ts(j.created_at),
        "finished_at": _utc_ts(j.finished_at),
        "error": j.error,
    }
    if j.status == "done" and j.result is not None:
        out["result"] = j.result
    return out


async def list_ved_intel_jobs(limit: int = 50) -> List[Dict[str, Any]]:
    limit = max(1, min(limit, 200))

    def _load() -> List[Dict[str, Any]]:
        with SessionLocal() as db:
            rows = (
                db.query(VedIntelJob)
                .order_by(VedIntelJob.created_at.desc())
                .limit(limit)
                .all()
            )
            out = []
            for j in rows:
                rbytes = None
                if j.result is not None:
                    try:
                        rbytes = len(json.dumps(j.result, ensure_ascii=False))
                    except Exception:
                        rbytes = None
                out.append(
                    {
                        "id": j.id,
                        "status": j.status,
                        "created_at": _utc_ts(j.created_at),
                        "finished_at": _utc_ts(j.finished_at),
                        "error": (j.error or "")[:200] if j.error else None,
                        "result_size_hint": rbytes,
                    }
                )
            return out

    return await asyncio.to_thread(_load)
