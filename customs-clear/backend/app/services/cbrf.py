from __future__ import annotations

import asyncio
from datetime import datetime
import xml.etree.ElementTree as ET

import httpx

_URL = "https://www.cbr.ru/scripts/XML_daily.asp"
_FALLBACK_RATES = {"EUR": 100.0, "USD": 92.0}

_cache_lock = asyncio.Lock()
_cache_date: str | None = None
_cache_rates: dict[str, float] | None = None


def _today_key() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _parse_rates(xml_text: str) -> dict[str, float]:
    root = ET.fromstring(xml_text)
    rates: dict[str, float] = {}
    for valute in root.findall("Valute"):
        code = (valute.findtext("CharCode") or "").strip().upper()
        if code not in ("EUR", "USD"):
            continue
        value_text = (valute.findtext("Value") or "").replace(",", ".")
        nominal_text = (valute.findtext("Nominal") or "1").replace(",", ".")
        value = float(value_text)
        nominal = float(nominal_text)
        if nominal <= 0:
            continue
        rates[code] = value / nominal
    return rates


async def get_cbrf_rates() -> dict[str, object]:
    """
    Возвращает словарь:
      {
        "rates": {"EUR": float, "USD": float},
        "source": "CBRF" | "fallback",
        "date": "YYYY-MM-DD"
      }
    """
    global _cache_date, _cache_rates
    today = _today_key()
    async with _cache_lock:
        if _cache_date == today and _cache_rates:
            return {"rates": dict(_cache_rates), "source": "CBRF", "date": today}

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(_URL)
                resp.raise_for_status()
            parsed = _parse_rates(resp.text)
            merged = dict(_FALLBACK_RATES)
            merged.update(parsed)
            _cache_date = today
            _cache_rates = merged
            return {"rates": dict(merged), "source": "CBRF", "date": today}
        except Exception:
            # При проблемах сети/парсинга отдаём fallback.
            if _cache_rates:
                return {"rates": dict(_cache_rates), "source": "cache", "date": _cache_date or today}
            return {"rates": dict(_FALLBACK_RATES), "source": "fallback", "date": today}
