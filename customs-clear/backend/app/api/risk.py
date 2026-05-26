"""Product-facing sanctions and risk checks API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from loguru import logger

from ..schemas.sanctions_risk import (
    RiskCheckBatchRequest,
    RiskCheckBatchResponse,
    RiskCheckRequest,
    SanctionsRiskBlockOut,
)
from ..security import require_authenticated_user
from ..services.sanctions_risk_block import build_sanctions_risk_block

router = APIRouter()


def _overall_status(items: list[SanctionsRiskBlockOut]) -> str:
    order = {"CRITICAL": 3, "MANUAL_REVIEW": 2, "WARNING": 1, "OK": 0}
    best = "OK"
    for item in items:
        st = str(item.status)
        if order.get(st, 0) > order.get(best, 0):
            best = st
    return best


@router.post("/check", response_model=SanctionsRiskBlockOut)
async def risk_check(
    req: RiskCheckRequest,
    _user: dict = Depends(require_authenticated_user),
) -> SanctionsRiskBlockOut:
    """Диагностическая проверка санкций/рисков по позиции."""
    if not (req.hs_code or "").strip():
        raise HTTPException(status_code=400, detail="hs_code обязателен")
    try:
        logger.info("Sanctions/risk check для кода {}", req.hs_code)
        return build_sanctions_risk_block(
            hs_code=req.hs_code,
            description=req.description,
            country=req.country,
            destination_country=req.destination_country,
            counterparty_name=req.counterparty_name,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Ошибка /api/risk/check")
        raise HTTPException(status_code=500, detail=f"Ошибка проверки рисков: {exc}")


@router.post("/check-batch", response_model=RiskCheckBatchResponse)
async def risk_check_batch(
    req: RiskCheckBatchRequest,
    _user: dict = Depends(require_authenticated_user),
) -> RiskCheckBatchResponse:
    """Пакетная проверка санкций/рисков."""
    if not req.items:
        raise HTTPException(status_code=400, detail="Список позиций пуст")
    items: list[SanctionsRiskBlockOut] = []
    for item in req.items:
        if not (item.hs_code or "").strip():
            raise HTTPException(status_code=400, detail="hs_code обязателен для каждой позиции")
        items.append(
            build_sanctions_risk_block(
                hs_code=item.hs_code,
                description=item.description,
                country=item.country,
                destination_country=item.destination_country,
                counterparty_name=item.counterparty_name,
            )
        )
    return RiskCheckBatchResponse(status=_overall_status(items), items=items)


@router.post("/block")
async def risk_block_alias(
    req: RiskCheckBatchRequest,
    _user: dict = Depends(require_authenticated_user),
) -> JSONResponse:
    """Alias для пакетного блока (совместимость с normative-block)."""
    batch = await risk_check_batch(req, _user=_user)
    return JSONResponse(batch.model_dump())
