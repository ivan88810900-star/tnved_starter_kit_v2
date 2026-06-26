from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse

from ..security import require_admin_token
from ..services.exchange_rates import get_rates_payload, update_exchange_rates_from_cbrf

router = APIRouter()


@router.get("/rates")
async def rates() -> JSONResponse:
    return JSONResponse(get_rates_payload())


@router.post("/rates/update")
async def update_rates(x_admin_token: str | None = Header(None, alias="X-Admin-Token")) -> JSONResponse:
    """Обновление курсов в БД из ЦБ РФ — только с X-Admin-Token (операционное действие)."""
    require_admin_token(x_admin_token)
    refresh = await update_exchange_rates_from_cbrf()
    payload = get_rates_payload()
    payload["refresh"] = refresh
    return JSONResponse(payload)

