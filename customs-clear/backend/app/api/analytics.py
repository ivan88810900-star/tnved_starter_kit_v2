"""Сводная аналитика для профессионального дашборда (БД, ИИ, журналы, ФСА)."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse

from ..security import require_admin_token
from ..services.analytics_overview import build_analytics_overview
from ..services.cache_layer import redis_ping

router = APIRouter()


@router.get("/overview")
async def analytics_overview(x_admin_token: str | None = Header(None, alias="X-Admin-Token")) -> JSONResponse:
    """Единая сводка: нормативка, журналы, конфигурация ИИ, ФСА, ТРОИС, эмбеддинги, текстовые выводы."""
    require_admin_token(x_admin_token)
    payload = await asyncio.to_thread(build_analytics_overview)
    redis_ok = await redis_ping()
    body = dict(payload)
    body["redis_reachable"] = redis_ok
    return JSONResponse(body)
