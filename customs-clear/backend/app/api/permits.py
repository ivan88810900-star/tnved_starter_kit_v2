"""Проверка СС/ДС/СГР в реестрах Росаккредитации и ЕАЭС."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field
from loguru import logger

from ..services.permit_suggest_service import suggest_permits
from ..services.permits_jobs import (
    create_verify_job,
    get_job,
    list_jobs,
    permits_job_items_as_csv,
)
from ..services.permits_metrics import get_permits_metrics
from ..services.permits_service import (
    PERMITS_DISCLAIMER_RU,
    check_permits,
    clear_permits_cache,
    infer_doc_type_from_number,
)
from ..security import require_admin_token, require_authenticated_user

router = APIRouter(dependencies=[Depends(require_authenticated_user)])


def _viewer_access(user: dict[str, Any]) -> Tuple[str, bool]:
    """Имя пользователя из JWT и признак роли admin (полный доступ к jobs)."""
    username = str(user.get("username") or "").strip()
    role = str(user.get("role") or "").strip().lower()
    return username, role == "admin"
class PermitVerifyIn(BaseModel):
    type: str
    number: str


class PermitVerifyRequest(BaseModel):
    permits: List[PermitVerifyIn] = Field(..., min_length=1)
    hs_code: str = Field("", description="Код ТН ВЭД позиции для сверки с реестром")
    enrich: bool = Field(True, description="Добавить verified_at, registry_source, hs_code_check")


class PermitSuggestRequest(BaseModel):
    query: str = Field("", description="Описание товара, например: электрический чайник")
    hs_code: str = Field("", description="Подсказка ТН ВЭД для ранжирования")
    doc_types: List[str] = Field(
        default_factory=list,
        description="Фильтр: СС, ДС; пусто — оба типа",
    )
    exclude_trois: bool = Field(
        True,
        description="Исключить варианты, где в тексте встречаются бренды из локального кэша ТРОИС",
    )
    country_hint: str = Field("CN", description="Страна происхождения для фильтра справочника (CN — Китай)")
    limit: int = Field(25, ge=1, le=100)


@router.post("/cache/clear")
async def permits_cache_clear(x_admin_token: str | None = Header(None, alias="X-Admin-Token")) -> JSONResponse:
    """Сброс кэша ответов ФСА/СГР. Требует заголовок X-Admin-Token."""
    require_admin_token(x_admin_token)
    await clear_permits_cache()
    return JSONResponse({"status": "OK", "message": "Кэш разрешений очищен"})


@router.post("/suggest")
async def permits_suggest(req: PermitSuggestRequest) -> JSONResponse:
    """Справочный подбор примеров СС/ДС под товар (см. disclaimer в ответе)."""
    logger.info(f"Подбор разрешений: query={req.query!r}, exclude_trois={req.exclude_trois}")
    payload = await suggest_permits(
        req.query,
        hs_code=req.hs_code,
        doc_types=req.doc_types or None,
        exclude_trois=req.exclude_trois,
        country_hint=req.country_hint,
        limit=req.limit,
    )
    return JSONResponse(payload)


@router.get("/suggest/{hs_code}")
async def permits_suggest_by_hs(
    hs_code: str,
    q: str = Query("", description="Описание товара"),
    limit: int = Query(10, ge=1, le=50),
) -> JSONResponse:
    """GET-алиас подбора СС/ДС по коду ТН ВЭД (curl/Smoke)."""
    payload = await suggest_permits(q, hs_code=re.sub(r"\D", "", hs_code), limit=limit)
    payload["disclaimer"] = PERMITS_DISCLAIMER_RU
    return JSONResponse(payload)


@router.post("/verify")
async def permits_verify(req: PermitVerifyRequest) -> JSONResponse:
    """Пакетная проверка документов в pub.fsa.gov.ru (СС/ДС) и fp.crc.ru (СГР)."""
    rows = [{"type": p.type, "number": p.number} for p in req.permits]
    logger.info(f"Проверка {len(rows)} разрешительных документов")
    results = await check_permits(rows, req.hs_code, enrich=req.enrich)
    summary = {
        "total": len(results),
        "valid": sum(1 for r in results if r.get("status") == "VALID"),
        "not_found": sum(1 for r in results if r.get("status") == "NOT_FOUND"),
        "unknown": sum(1 for r in results if r.get("status") == "UNKNOWN"),
        "hs_mismatch": sum(
            1 for r in results if (r.get("hs_code_check") or {}).get("hs_match") == "mismatch"
        ),
    }
    return JSONResponse({"status": "OK", "items": results, "summary": summary})


@router.get("/verify/number/{number:path}")
async def permits_verify_by_number(
    number: str,
    hs_code: str = Query("", description="Код ТН ВЭД для сверки"),
    doc_type: str = Query("", description="СС или ДС; если пусто — авто"),
) -> JSONResponse:
    """GET-алиас проверки одного номера в реестре ФСА."""
    dtype = (doc_type or infer_doc_type_from_number(number)).strip().upper() or "СС"
    if dtype not in ("СС", "ДС", "СГР"):
        dtype = infer_doc_type_from_number(number)
    results = await check_permits([{"type": dtype, "number": number}], hs_code, enrich=True)
    return JSONResponse(
        {
            "status": "OK",
            "disclaimer": PERMITS_DISCLAIMER_RU,
            "items": results,
            "summary": {"total": len(results)},
        }
    )


@router.post("/verify/async")
async def permits_verify_async(
    req: PermitVerifyRequest,
    background_tasks: BackgroundTasks,
    user: dict[str, Any] = Depends(require_authenticated_user),
) -> JSONResponse:
    """Постановка той же проверки в фон (результат — GET /verify/jobs/{job_id})."""
    rows = [{"type": p.type, "number": p.number} for p in req.permits]
    owner, _ = _viewer_access(user)
    job_id = await create_verify_job(
        rows,
        req.hs_code,
        req.enrich,
        background_tasks,
        created_by_username=owner or None,
    )
    return JSONResponse({"status": "accepted", "job_id": job_id})


@router.get("/verify/jobs")
async def permits_verify_jobs_list(
    limit: int = 50,
    user: dict[str, Any] = Depends(require_authenticated_user),
) -> JSONResponse:
    """Список недавних асинхронных заданий проверки (хранятся в БД)."""
    username, is_admin = _viewer_access(user)
    items = await list_jobs(limit=limit, access_username=username, access_is_admin=is_admin)
    return JSONResponse({"status": "OK", "items": items})


@router.get("/verify/jobs/{job_id}/export", response_model=None)
async def permits_verify_job_export(
    job_id: str,
    format: str = Query("csv", description="csv или json"),
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
) -> PlainTextResponse | JSONResponse:
    """Выгрузка результата завершённого async-задания. Требует заголовок X-Admin-Token."""
    require_admin_token(x_admin_token)
    row = await get_job(job_id, access_username="", access_is_admin=True)
    if not row:
        raise HTTPException(status_code=404, detail="Задание не найдено")
    if row.get("status") != "done":
        raise HTTPException(
            status_code=409,
            detail="Экспорт только для завершённых заданий (ожидайте status=done)",
        )
    fmt = (format or "csv").strip().lower()
    if fmt not in ("csv", "json"):
        raise HTTPException(status_code=400, detail="format: csv или json")
    items = row.get("items") or []
    if fmt == "csv":
        return PlainTextResponse(
            permits_job_items_as_csv(items if isinstance(items, list) else []),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="permits_job_{job_id[:16]}.csv"',
            },
        )
    return JSONResponse(
        {
            "status": "OK",
            "job_id": job_id,
            "summary": row.get("summary"),
            "items": items,
        }
    )


@router.get("/verify/jobs/{job_id}")
async def permits_verify_job_status(
    job_id: str,
    user: dict[str, Any] = Depends(require_authenticated_user),
) -> JSONResponse:
    username, is_admin = _viewer_access(user)
    row = await get_job(job_id, access_username=username, access_is_admin=is_admin)
    if not row:
        raise HTTPException(status_code=404, detail="Задание не найдено")
    return JSONResponse({"status": "OK", "job_id": job_id, **row})


@router.get("/metrics")
async def permits_metrics() -> JSONResponse:
    """Счётчики вызовов /verify (для дашбордов и алертов)."""
    return JSONResponse({"status": "OK", **get_permits_metrics()})
