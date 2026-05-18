"""Админ-эндпоинты API v1: синхронизация нормативных данных."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, Header, HTTPException, UploadFile

from ..security import require_admin_token
from ..services.bulk_normative_ai import (
    create_import_job,
    get_job_status,
    is_import_running,
    raw_normative_dir,
    run_bulk_import,
)
from ..services.sync_engine import get_sync_status_payload, sync_daily_regulatory_data

router = APIRouter()


@router.get("/sync/status")
async def regulatory_sync_status(x_admin_token: str | None = Header(None, alias="X-Admin-Token")) -> dict:
    require_admin_token(x_admin_token)
    return get_sync_status_payload()


@router.post("/sync/start")
async def regulatory_sync_start(
    background_tasks: BackgroundTasks,
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
) -> dict:
    require_admin_token(x_admin_token)

    async def _run_manual() -> None:
        await sync_daily_regulatory_data(trigger="manual")

    background_tasks.add_task(_run_manual)
    return {"status": "started", "message": "Синхронизация поставлена в фоновую очередь"}


def _safe_upload_name(name: str | None) -> str:
    base = Path(name or "document").name
    base = re.sub(r"[^\w.\-]", "_", base, flags=re.UNICODE).strip("._") or "document"
    return base[:220]


@router.get("/import/bulk/status")
async def bulk_import_status(
    job_id: int | None = None,
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
) -> dict:
    require_admin_token(x_admin_token)
    return get_job_status(job_id)


@router.post("/import/bulk/start")
async def bulk_import_start(
    background_tasks: BackgroundTasks,
    delay_sec: float = 4.0,
    skip_checkpoint: bool = False,
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
) -> dict:
    require_admin_token(x_admin_token)
    if is_import_running():
        raise HTTPException(status_code=409, detail="Импорт уже выполняется в этом процессе API")

    jid = create_import_job()

    async def _run() -> None:
        await run_bulk_import(jid, delay_sec=delay_sec, skip_checkpoint=skip_checkpoint)

    background_tasks.add_task(_run)
    return {"job_id": jid, "status": "started", "delay_sec": delay_sec, "skip_checkpoint": skip_checkpoint}


@router.post("/import/bulk/upload")
async def bulk_import_upload(
    files: list[UploadFile] | None = File(None),
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
) -> dict:
    require_admin_token(x_admin_token)
    if not files:
        raise HTTPException(status_code=400, detail="Нет файлов (multipart, поле files)")
    root = raw_normative_dir()
    saved: list[str] = []
    for up in files:
        raw_name = _safe_upload_name(up.filename)
        suf = Path(raw_name).suffix.lower()
        if suf not in {".pdf", ".docx", ".html", ".htm"}:
            continue
        dest = root / raw_name
        data = await up.read()
        if not data:
            continue
        dest.write_bytes(data)
        saved.append(str(dest.relative_to(root)))
    if not saved:
        raise HTTPException(
            status_code=400,
            detail="Ни один файл не сохранён. Допустимы: .pdf, .docx, .html, .htm",
        )
    return {"saved": saved, "count": len(saved), "directory": str(root)}
