from __future__ import annotations

from datetime import datetime
import xml.etree.ElementTree as ET

import httpx

from ..datetime_util import utc_now_naive
from ..db import SessionLocal
from ..models.core import ExchangeRate

CBR_DAILY_URL = "https://www.cbr.ru/scripts/XML_daily.asp"
CBRF_SOURCE_CODE = "CBRF"
CBRF_SOURCE_NAME = "Курсы валют ЦБ РФ (XML daily)"
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


def _missing_tracked_currencies(rows: dict[str, tuple[float, float]]) -> list[str]:
    """Валюты TRACKED, отсутствующие в ответе CBR XML (до добивки FALLBACK в upsert)."""
    return [code for code in TRACKED if code not in rows]


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


def _record_cbrf_sync_success(date_key: str, rows_updated: int) -> None:
    """Provenance для payment_data_coverage: успешный live CBRF sync."""
    from .normative_store import append_sync_log, upsert_source_status

    revision = f"cbrf:{date_key}"
    note = f"CBRF XML sync OK, currencies={len(TRACKED)}, updated={rows_updated}"
    upsert_source_status(
        source_code=CBRF_SOURCE_CODE,
        source_name=CBRF_SOURCE_NAME,
        source_url=CBR_DAILY_URL,
        revision=revision,
        is_stale=False,
        note=note,
    )
    append_sync_log(
        source_code=CBRF_SOURCE_CODE,
        status="OK",
        revision=revision,
        rows_affected=rows_updated,
        note=note,
    )


def _record_cbrf_sync_fallback(error: str, rows_updated: int) -> None:
    """Provenance при fallback — не считается official CBR coverage."""
    from .normative_store import append_sync_log, upsert_source_status

    note = f"CBRF fetch failed, used FALLBACK constants: {error[:200]}"
    upsert_source_status(
        source_code=CBRF_SOURCE_CODE,
        source_name=CBRF_SOURCE_NAME,
        source_url=CBR_DAILY_URL,
        revision="fallback",
        is_stale=True,
        note=note,
    )
    append_sync_log(
        source_code=CBRF_SOURCE_CODE,
        status="ERROR",
        revision="fallback",
        rows_affected=rows_updated,
        note=note,
    )


def _safe_record_provenance(record_fn, *args: object, **kwargs: object) -> str | None:
    """Запись provenance не должна ломать уже сохранённые live rates."""
    try:
        record_fn(*args, **kwargs)
        return None
    except Exception as exc:
        return str(exc)


def _apply_fallback_exchange_rates(error: str) -> dict[str, object]:
    """CBR fetch/parse/upsert failed — записать FALLBACK в exchange_rates."""
    fallback_rows = {k: (v, 1.0) for k, v in FALLBACK.items() if k in TRACKED}
    changed = _upsert_rates(fallback_rows)
    _safe_record_provenance(_record_cbrf_sync_fallback, error, changed)
    return {
        "status": "OK",
        "source": "fallback",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "updated": changed,
    }


async def update_exchange_rates_from_cbrf() -> dict[str, object]:
    try:
        date_key, rows = await fetch_cbr_rates()
    except Exception as exc:
        return _apply_fallback_exchange_rates(str(exc))

    missing = _missing_tracked_currencies(rows)
    if missing:
        changed = _upsert_rates(rows)
        _safe_record_provenance(
            _record_cbrf_sync_fallback,
            f"CBRF XML incomplete, missing tracked currencies: {', '.join(missing)}",
            changed,
        )
        return {
            "status": "OK",
            "source": "fallback",
            "date": date_key,
            "updated": changed,
            "missing_currencies": missing,
        }

    try:
        changed = _upsert_rates(rows)
    except Exception as exc:
        return _apply_fallback_exchange_rates(f"CBR rates upsert failed: {exc}")

    provenance_error = _safe_record_provenance(_record_cbrf_sync_success, date_key, changed)
    result: dict[str, object] = {
        "status": "OK",
        "source": "CBRF",
        "date": date_key,
        "updated": changed,
        "provenance_recorded": provenance_error is None,
    }
    if provenance_error:
        result["provenance_error"] = provenance_error
        _safe_record_provenance(
            _record_cbrf_sync_fallback,
            f"provenance write failed (live CBR rates kept): {provenance_error}",
            changed,
        )
    return result


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

