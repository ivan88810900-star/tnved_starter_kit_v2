"""Product-facing Smart Payments quote API."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from loguru import logger

from ..schemas.payment_quote import PaymentQuoteRequest, PaymentQuoteResponse
from ..services.payment_quote_service import build_payment_quote

router = APIRouter()


@router.post("/quote", response_model=PaymentQuoteResponse)
async def payment_quote(req: PaymentQuoteRequest) -> PaymentQuoteResponse:
    """Расчёт платежей с построчной разбивкой и явными статусами для акциза и торговых мер."""
    try:
        logger.info("Smart Payments quote для кода {}", req.hs_code)
        return build_payment_quote(req.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Ошибка /api/payments/quote")
        raise HTTPException(status_code=500, detail=f"Ошибка расчёта quote: {exc}")
