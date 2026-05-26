"""API нетарифного контроля."""
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from loguru import logger

from ..services.non_tariff_service import check_position_non_tariff
from ..services.normative_store import list_tr_ts_acts
from ..security import require_authenticated_user

router = APIRouter()


@router.get("/tr-ts-registry")
async def non_tariff_tr_ts_registry(
    q: str | None = Query(None, description="Фильтр по коду или краткому названию"),
    limit: int = Query(200, ge=1, le=500),
) -> JSONResponse:
    """Справочник карточек ТР ТС (редакции — справочно; официальный текст на портале ЕЭК)."""
    return JSONResponse({"status": "OK", "items": list_tr_ts_acts(query=q, limit=limit)})


class PermitIn(BaseModel):
    type: str
    number: str


class NonTariffItemIn(BaseModel):
    hs_code: str
    description: str
    country: str | None = None
    permits: List[PermitIn] = []


class NonTariffRequest(BaseModel):
    items: List[NonTariffItemIn]


class NormativeBlockItemIn(BaseModel):
    hs_code: str
    description: str = ""
    country: str | None = None
    permits: List[PermitIn] = []


class NormativeBlockRequest(BaseModel):
    items: List[NormativeBlockItemIn]


class RiskBlockItemIn(BaseModel):
    hs_code: str
    description: str = ""
    country: str | None = None
    destination_country: str | None = None
    counterparty_name: str | None = None


class RiskBlockRequest(BaseModel):
    items: List[RiskBlockItemIn]


@router.post("/normative-block")
async def non_tariff_normative_block(
    req: NormativeBlockRequest,
    _user: dict = Depends(require_authenticated_user),
) -> JSONResponse:
    """Продуктовый блок нормативных требований по позициям (без расчёта платежей)."""
    if not req.items:
        raise HTTPException(status_code=400, detail="Список позиций пуст")
    results: List[Dict[str, Any]] = []
    for item in req.items:
        nt = await check_position_non_tariff(
            item.hs_code,
            item.description,
            item.country,
            [{"type": p.type, "number": p.number} for p in item.permits],
        )
        results.append(
            {
                "hs_code": item.hs_code,
                "description": item.description,
                "country": item.country,
                "non_tariff_status": nt.get("status"),
                "normative_block": nt.get("normative_block") or {},
            }
        )
    errors = any(r["non_tariff_status"] == "ERROR" for r in results)
    warnings = any(r["non_tariff_status"] == "WARNING" for r in results)
    overall = "ERROR" if errors else ("WARNING" if warnings else "OK")
    return JSONResponse({"status": overall, "items": results})


@router.post("/risk-block")
async def non_tariff_risk_block(
    req: RiskBlockRequest,
    _user: dict = Depends(require_authenticated_user),
) -> JSONResponse:
    """Продуктовый блок санкций/рисков по позициям (без расчёта платежей)."""
    if not req.items:
        raise HTTPException(status_code=400, detail="Список позиций пуст")
    from ..services.sanctions_risk_block import build_sanctions_risk_block

    results: List[Dict[str, Any]] = []
    for item in req.items:
        block = build_sanctions_risk_block(
            hs_code=item.hs_code,
            description=item.description,
            country=item.country,
            destination_country=item.destination_country,
            counterparty_name=item.counterparty_name,
        )
        results.append(
            {
                "hs_code": item.hs_code,
                "description": item.description,
                "country": item.country,
                "counterparty_name": item.counterparty_name,
                "risk_block": block.model_dump(),
            }
        )
    order = {"CRITICAL": 3, "MANUAL_REVIEW": 2, "WARNING": 1, "OK": 0}
    overall = "OK"
    for r in results:
        st = str((r.get("risk_block") or {}).get("status") or "OK")
        if order.get(st, 0) > order.get(overall, 0):
            overall = st
    return JSONResponse({"status": overall, "items": results})


@router.post("/check")
async def non_tariff_check(
    req: NonTariffRequest,
    _user: dict = Depends(require_authenticated_user),
) -> JSONResponse:
    """Проверка нетарифных требований по списку позиций."""
    if not req.items:
        raise HTTPException(status_code=400, detail="Список позиций пуст")
    logger.info(f"Нетарифная проверка {len(req.items)} позиций")
    results: List[Dict[str, Any]] = []
    for item in req.items:
        res = await check_position_non_tariff(
            item.hs_code,
            item.description,
            item.country,
            [{"type": p.type, "number": p.number} for p in item.permits],
        )
        results.append(res)

    errors = any(r["status"] == "ERROR" for r in results)
    warnings = any(r["status"] == "WARNING" for r in results)
    overall = "ERROR" if errors else ("WARNING" if warnings else "OK")

    return JSONResponse({"status": overall, "items": results})
