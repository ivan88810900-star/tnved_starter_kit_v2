from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from loguru import logger
import httpx
from xml.etree import ElementTree as ET

from ..services.exchange_rates import get_rates_payload


router = APIRouter()

CBR_URLS = [
    "https://www.cbr.ru/scripts/XML_daily.asp",
    "https://www.cbr-xml-daily.ru/daily_utf8.xml",
]


def _parse_cbr_xml(xml_text: str) -> dict:
    """Парсинг XML ЦБ РФ в словарь курсов."""
    tree = ET.fromstring(xml_text)
    rates = {}
    for valute in tree.findall("Valute"):
        code = valute.findtext("CharCode")
        nominal = float(valute.findtext("Nominal") or 1)
        value = float((valute.findtext("Value") or "0").replace(",", "."))
        if code:
            rates[code] = round(value / nominal, 6)
    return rates


@router.get("/rates")
async def get_rates() -> JSONResponse:
    """Получение актуальных курсов ЦБ РФ с fallback на локальный кэш."""
    last_error = None
    for url in CBR_URLS:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(url)
            resp.raise_for_status()
            rates = _parse_cbr_xml(resp.text)
            if rates:
                logger.info("Курсы ЦБ РФ успешно получены")
                return JSONResponse({"status": "OK", "source": "cbr", "rates": rates})
        except Exception as exc:
            last_error = exc
            logger.warning(f"ЦБ РФ {url}: {exc}")
            continue

    cached = get_rates_payload()
    map_rates = cached.get("map") if isinstance(cached, dict) else None
    if isinstance(map_rates, dict) and map_rates:
        logger.warning(f"Внешний источник недоступен, используем локальный кэш: {last_error}")
        return JSONResponse(
            {
                "status": "OK",
                "source": "local_cache",
                "updated_at": cached.get("updated_at"),
                "rates": map_rates,
            }
        )

    logger.exception("Ошибка при получении курсов ЦБ РФ и отсутствии локального кэша")
    raise HTTPException(status_code=500, detail=str(last_error or "Rates unavailable"))

