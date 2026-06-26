"""
Запасной прокси к XML-API Альта-Софт (подсказки по классификации).
Основная нормативка — импорт в БД (в т.ч. Excel TWS.BY), см. docs/integration/tws_by.md.

Включение: ALTA_TIK_ENABLED / ALTA_APU_ENABLED и учётные данные в .env.
Документация: customs-clear/docs/integration/
"""
from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from ..services.alta_client import fetch_apu_codes, fetch_apu_suggest, fetch_tik_search
from ..security import require_authenticated_user

router = APIRouter(dependencies=[Depends(require_authenticated_user)])


def _truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in ("1", "true", "yes", "on")


def _tik_creds() -> tuple[str, str]:
    login = os.getenv("ALTA_TIK_LOGIN", "").strip()
    password = os.getenv("ALTA_TIK_PASSWORD", "").strip()
    return login, password


def _apu_creds() -> tuple[str, str]:
    login = os.getenv("ALTA_APU_LOGIN", "").strip() or os.getenv("ALTA_TIK_LOGIN", "").strip()
    password = os.getenv("ALTA_APU_PASSWORD", "").strip() or os.getenv("ALTA_TIK_PASSWORD", "").strip()
    return login, password


@router.get("/tik/search")
async def alta_tik_search(
    srchstr: str = Query(..., min_length=3, description="Строка поиска (от 3 символов)"),
    tncode: Optional[str] = Query(None, description="Фильтр по префиксу ТН ВЭД (2–10 цифр), по документации wiki"),
    tnfiltr: Optional[str] = Query(None, description="Альтернативный параметр пагинации/фильтра из примеров wiki"),
    page: Optional[int] = Query(None, ge=2, description="Номер страницы дозапроса (с 2)"),
) -> JSONResponse:
    if not _truthy("ALTA_TIK_ENABLED"):
        raise HTTPException(status_code=503, detail="Интеграция Альта ТиК отключена (ALTA_TIK_ENABLED)")
    login, password = _tik_creds()
    if not login or not password:
        raise HTTPException(status_code=503, detail="Задайте ALTA_TIK_LOGIN и ALTA_TIK_PASSWORD")
    try:
        data = await fetch_tik_search(
            srchstr=srchstr.strip(),
            login=login,
            password=password,
            tncode=tncode.strip() if tncode else None,
            tnfiltr=tnfiltr.strip() if tnfiltr else None,
            page=page,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Alta Tik: {e!s}") from e
    return JSONResponse({"source": "alta_tik", **data})


@router.get("/apu/suggest")
async def alta_apu_suggest(
    q: str = Query(..., min_length=1, description="Текст для подсказок АПУ"),
    limit: Optional[int] = Query(None, description="-1 или положительное число"),
) -> JSONResponse:
    if not _truthy("ALTA_APU_ENABLED"):
        raise HTTPException(status_code=503, detail="Интеграция Альта АПУ отключена (ALTA_APU_ENABLED)")
    try:
        data = await fetch_apu_suggest(q=q.strip(), limit=limit)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Alta APU suggest: {e!s}") from e
    return JSONResponse({"source": "alta_apu", "step": "suggest", **data})


@router.get("/apu/codes")
async def alta_apu_codes(
    code: str = Query(..., min_length=1, description="Идентификатор payload из /apu/suggest"),
    limit: Optional[int] = Query(None, description="-1 или положительное; 0 недопустимо у Альты"),
) -> JSONResponse:
    if not _truthy("ALTA_APU_ENABLED"):
        raise HTTPException(status_code=503, detail="Интеграция Альта АПУ отключена (ALTA_APU_ENABLED)")
    if limit is not None and limit == 0:
        raise HTTPException(status_code=400, detail="limit=0 запрещён API Альты (ошибка 201)")
    login, password = _apu_creds()
    if not login or not password:
        raise HTTPException(status_code=503, detail="Задайте ALTA_APU_LOGIN/ALTA_APU_PASSWORD или ALTA_TIK_*")
    try:
        data = await fetch_apu_codes(payload_id=code.strip(), login=login, password=password, limit=limit)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Alta APU codes: {e!s}") from e
    return JSONResponse({"source": "alta_apu", "step": "codes", **data})


@router.get("/status")
async def alta_status() -> JSONResponse:
    """Без секретов: какие интеграции включены в конфиге."""
    tik_on = _truthy("ALTA_TIK_ENABLED")
    apu_on = _truthy("ALTA_APU_ENABLED")
    t_l, t_p = _tik_creds()
    a_l, a_p = _apu_creds()
    return JSONResponse(
        {
            "status": "OK",
            "tik": {"enabled": tik_on, "configured": bool(tik_on and t_l and t_p)},
            "apu": {
                "enabled": apu_on,
                "configured": bool(apu_on and a_l and a_p),
                "suggest_public": apu_on,
            },
        }
    )
