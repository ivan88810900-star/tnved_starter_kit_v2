import os

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from loguru import logger

from ..services.trois_service import (
    check_trademark,
    get_trois_local_cache_stats,
    load_extra_brands_from_file,
    suggest_trois_brands,
)
from ..security import require_admin_token
from ..services.trois_sync import sync_trois_sources


router = APIRouter()


class TroisRequest(BaseModel):
    query: str


class TroisReloadBody(BaseModel):
    path: str | None = None


@router.get("/stats")
async def trois_stats() -> JSONResponse:
    """Размер локального индекса брендов ТРОИС (и пример ключей)."""
    payload = get_trois_local_cache_stats()
    extra = (os.getenv("TROIS_EXTRA_BRANDS_PATH") or "").strip()
    return JSONResponse({"status": "OK", **payload, "extra_brands_path_configured": bool(extra)})


@router.post("/reload-cache")
async def trois_reload_cache(
    body: TroisReloadBody = TroisReloadBody(),
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
) -> JSONResponse:
    """Подгрузить бренды из JSON (путь в теле или TROIS_EXTRA_BRANDS_PATH). Требует X-Admin-Token."""
    require_admin_token(x_admin_token)
    path = (body.path or "").strip() or os.getenv("TROIS_EXTRA_BRANDS_PATH", "").strip()
    if not path:
        raise HTTPException(status_code=400, detail="Укажите path в теле или TROIS_EXTRA_BRANDS_PATH в окружении")
    n = load_extra_brands_from_file(path)
    return JSONResponse(
        {
            "status": "OK",
            "added": n,
            "local_brands_count": get_trois_local_cache_stats()["local_brands_count"],
        }
    )


@router.get("/suggest")
async def trois_suggest(
    q: str = Query(..., min_length=2, description="Часть названия бренда"),
    limit: int = Query(10, ge=1, le=30),
) -> JSONResponse:
    """Подсказки брендов из локального кэша ТРОИС (fuzzy + подстрока)."""
    return JSONResponse({"status": "OK", "suggestions": suggest_trois_brands(q, limit=limit)})


@router.get("/check/{query:path}")
async def trois_check_get(query: str) -> JSONResponse:
    """GET-алиас проверки ТРОИС (удобно для curl/Smoke)."""
    q = (query or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="Запрос не должен быть пустым")
    result = await check_trademark(q)
    result.setdefault("status", "OK")
    return JSONResponse(result)


@router.post("/check")
async def trois_check(req: TroisRequest) -> JSONResponse:
    """Проверка товарного знака в реестре ТРОИС."""
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="Запрос не должен быть пустым")
    try:
        logger.info(f"Проверка ТРОИС по запросу: {req.query}")
        result = await check_trademark(req.query)
        result.setdefault("status", "OK")
        return JSONResponse(result)
    except Exception as exc:
        logger.exception("Ошибка при проверке ТРОИС")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/sync")
async def trois_sync(
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
) -> JSONResponse:
    """Синхронизация ТРОИС из alta/customs с upsert в БД."""
    require_admin_token(x_admin_token)
    data = await sync_trois_sources()
    return JSONResponse(data)


@router.post("/fetch-registry")
async def trois_fetch_registry(
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
) -> JSONResponse:
    """Загрузка открытых данных ТРОИС (customs.gov.ru/folder/14344) + reload кэша."""
    require_admin_token(x_admin_token)
    from ..services.trois_fts_fetch import fetch_fts_trois_open_data
    from ..services.trois_registry_loader import export_db_brands_json, sync_db_to_local_cache

    fts = fetch_fts_trois_open_data()
    sync_db_to_local_cache(force=True)
    exported = export_db_brands_json()
    stats = get_trois_local_cache_stats()
    return JSONResponse({"status": "OK", "fts_fetch": fts, "brands_exported": exported, **stats})

