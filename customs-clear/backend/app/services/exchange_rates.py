from __future__ import annotations

from datetime import datetime
import xml.etree.ElementTree as ET

import httpx

from ..datetime_util import utc_now_naive
from ..db import SessionLocal
from ..models.core import ExchangeRate

CBR_DAILY_URL = "https://www.cbr.ru/scripts/XML_daily.asp"
TRACKED = ("USD", "EUR", "CNY", "BYN", "KZT")
FALLBACK: dict[str, float] = {
    "USD": 92.0,
    "EUR": 100.0,
    "CNY": 12.7,
    "BYN": 28.0,
    "KZT": 0.19,
    "RUB": 1.0,
}


def _parse_cbr_xml(xml_text: str) -> tuple[str, dict[str, tuple[float, float]]]:
    root = ET.fromstring(xml_text)
    date_raw = root.attrib.get("Date", "")
    try:
        date_key = datetime.strptime(date_raw, "%d.%m.%Y").strftime("%Y-%m-%d")
    except Exception:
        date_key = datetime.now().strftime("%Y-%m-%d")

    out: dict[str, tuple[float, float]] = {}
    for valute in root.findall("Valute"):
        code = (valute.findtext("CharCode") or "").upper().strip()
        if code not in TRACKED:
            continue
        value = float((valute.findtext("Value") or "0").replace(",", "."))
        nominal = float((valute.findtext("Nominal") or "1").replace(",", "."))
        if nominal <= 0:
            continue
        out[code] = (value / nominal, nominal)
    return date_key, out


async def fetch_cbr_rates() -> tuple[str, dict[str, tuple[float, float]]]:
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(CBR_DAILY_URL)
    resp.raise_for_status()
    return _parse_cbr_xml(resp.text)


def _upsert_rates(rows: dict[str, tuple[float, float]]) -> int:
    changed = 0
    now = utc_now_naive()
    with SessionLocal() as db:
        for code in TRACKED:
            rate, nominal = rows.get(code, (FALLBACK[code], 1.0))
            obj = db.query(ExchangeRate).filter(ExchangeRate.currency_code == code).first()
            if obj is None:
                db.add(
                    ExchangeRate(
                        currency_code=code,
                        rate=float(rate),
                        nominal=float(nominal),
                        updated_at=now,
                    )
                )
                changed += 1
            else:
                obj.rate = float(rate)
                obj.nominal = float(nominal)
                obj.updated_at = now
                changed += 1
        db.commit()
    return changed


async def update_exchange_rates_from_cbrf() -> dict[str, object]:
    try:
        date_key, rows = await fetch_cbr_rates()
        changed = _upsert_rates(rows)
        return {"status": "OK", "source": "CBRF", "date": date_key, "updated": changed}
    except Exception:
        fallback_rows = {k: (v, 1.0) for k, v in FALLBACK.items() if k in TRACKED}
        changed = _upsert_rates(fallback_rows)
        return {"status": "OK", "source": "fallback", "date": datetime.now().strftime("%Y-%m-%d"), "updated": changed}


def get_rates_map() -> dict[str, float]:
    with SessionLocal() as db:
        rows = db.query(ExchangeRate).all()
        rates = {r.currency_code: float(r.rate) for r in rows}
    for code, value in FALLBACK.items():
        rates.setdefault(code, value)
    rates["RUB"] = 1.0
    return rates


def get_rates_payload() -> dict[str, object]:
    with SessionLocal() as db:
        rows = db.query(ExchangeRate).order_by(ExchangeRate.currency_code.asc()).all()
        items = [
            {
                "currency_code": r.currency_code,
                "rate": float(r.rate),
                "nominal": float(r.nominal),
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rows
        ]
    if not items:
        items = [
            {"currency_code": c, "rate": v, "nominal": 1.0, "updated_at": None}
            for c, v in FALLBACK.items()
            if c in TRACKED
        ]
    map_data = {i["currency_code"]: i["rate"] for i in items}
    map_data["RUB"] = 1.0
    latest = max((i["updated_at"] or "" for i in items), default=None)
    return {
        "status": "OK",
        "base": "RUB",
        "updated_at": latest,
        "rates": items,
        "map": map_data,
    }

