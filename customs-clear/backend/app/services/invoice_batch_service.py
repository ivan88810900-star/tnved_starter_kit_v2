"""
Пакетный расчёт платежей по позициям инвойса (пошлина, НДС, сбор, акциз, РОП, утильсбор).
"""

from __future__ import annotations

import io
import re
from typing import Any

import pandas as pd

from ..db import SessionLocal
from .payment_engine_compat import compute_payments
from .rop_calculator import calculate_rop

_COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "description": ("description", "описание", "наименование", "товар", "product"),
    "hs_code": ("hs_code", "hs", "tnved", "тн вэд", "код"),
    "quantity": ("quantity", "qty", "количество", "кол-во"),
    "unit": ("unit", "ед", "единица"),
    "unit_price": ("unit_price", "price", "цена", "unit price"),
    "currency": ("currency", "валюта", "curr"),
    "weight_gross_kg": ("weight_gross_kg", "gross_kg", "брутто", "gross"),
    "weight_net_kg": ("weight_net_kg", "net_kg", "нетто", "net"),
    "country_of_origin": ("country_of_origin", "country", "страна", "origin"),
    "image_url": ("image_url", "photo_url", "фото url", "url фото", "image url", "photo"),
    "image_base64": ("image_base64", "фото", "photo_base64", "image"),
    "article": ("article", "артикул", "sku", "part_no", "part number"),
    "manufacturer": ("manufacturer", "производитель", "brand", "бренд", "maker"),
}


def _norm_col(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().lower())


def _map_columns(cols: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    normalized = {_norm_col(c): c for c in cols}
    for field, aliases in _COLUMN_ALIASES.items():
        for a in aliases:
            if a in normalized:
                mapping[field] = normalized[a]
                break
    return mapping


def _cell(row: dict[str, Any], colmap: dict[str, str], field: str, default: Any = None) -> Any:
    src = colmap.get(field)
    if not src:
        return default
    val = row.get(src)
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return default
    return val


def parse_invoice_file(content: bytes, filename: str) -> list[dict[str, Any]]:
    """Парсинг xlsx/xls/csv в список позиций."""
    name = (filename or "").lower()
    if name.endswith(".csv"):
        df = pd.read_csv(io.BytesIO(content))
    else:
        df = pd.read_excel(io.BytesIO(content))
    if df.empty:
        return []
    colmap = _map_columns(list(df.columns.astype(str)))
    if "description" not in colmap:
        raise ValueError("Не найдена колонка description/описание")
    rows: list[dict[str, Any]] = []
    for _, ser in df.iterrows():
        row = ser.to_dict()
        desc = str(_cell(row, colmap, "description", "") or "").strip()
        if not desc:
            continue
        image_url = str(_cell(row, colmap, "image_url", "") or "").strip()
        image_b64 = str(_cell(row, colmap, "image_base64", "") or "").strip()
        article = str(_cell(row, colmap, "article", "") or "").strip()
        manufacturer = str(_cell(row, colmap, "manufacturer", "") or "").strip()
        qty = _cell(row, colmap, "quantity", 1)
        price = _cell(row, colmap, "unit_price", 0)
        try:
            qty_f = float(qty) if qty is not None else 1.0
            price_f = float(price) if price is not None else 0.0
        except (TypeError, ValueError):
            qty_f, price_f = 1.0, 0.0
        rows.append(
            {
                "description": desc,
                "hs_code": str(_cell(row, colmap, "hs_code", "") or "").strip(),
                "quantity": qty_f,
                "unit": str(_cell(row, colmap, "unit", "") or ""),
                "unit_price": price_f,
                "currency": str(_cell(row, colmap, "currency", "USD") or "USD").upper(),
                "weight_gross_kg": _cell(row, colmap, "weight_gross_kg"),
                "weight_net_kg": _cell(row, colmap, "weight_net_kg"),
                "country_of_origin": str(_cell(row, colmap, "country_of_origin", "") or "").strip().upper(),
                "image_url": image_url,
                "image_base64": image_b64,
                "article": article,
                "manufacturer": manufacturer,
            }
        )
    return rows


async def classify_hs_if_missing(line: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
    description = str(line.get("description") or "").strip()
    if not description and not (line.get("image_url") or line.get("image_base64") or line.get("article")):
        return "", None
    image_url = str(line.get("image_url") or "").strip() or None
    image_b64 = str(line.get("image_base64") or "").strip() or None
    article = str(line.get("article") or "").strip() or None
    manufacturer = str(line.get("manufacturer") or "").strip() or None
    use_smart = bool(image_url or image_b64 or article or manufacturer)

    try:
        if use_smart:
            from .smart_classifier import get_smart_classifier

            result = await get_smart_classifier().classify(
                description=description or None,
                image_base64=image_b64,
                image_url=image_url,
                article=article,
                manufacturer=manufacturer,
            )
            meta = {
                "visual_analysis": result.visual_analysis,
                "web_search_used": result.web_search_used,
                "translation_used": result.translation_used,
                "photo_analyzed": bool(result.visual_analysis),
            }
            if result.results:
                hs = re.sub(r"\D", "", str(result.results[0].get("hs_code") or ""))[:10]
                return hs, meta
            return "", meta

        from .claude_service import classify_hs_code

        res = await classify_hs_code(description[:1500], use_journal_hints=False)
        results = res.get("results") or []
        if results and isinstance(results[0], dict):
            hs = re.sub(r"\D", "", str(results[0].get("hs_code") or results[0].get("code") or ""))[:10]
            return hs, None
    except Exception:
        return "", None
    return "", None


def calculate_line_payments(
    line: dict[str, Any],
    *,
    db_session=None,
    calendar_year: int | None = None,
) -> dict[str, Any]:
    """Расчёт всех платежей для одной строки инвойса."""
    hs = re.sub(r"\D", "", str(line.get("hs_code") or ""))[:10]
    qty = float(line.get("quantity") or 1)
    price = float(line.get("unit_price") or 0)
    customs_value = qty * price
    gross = line.get("weight_gross_kg")
    net = line.get("weight_net_kg")
    country = (line.get("country_of_origin") or line.get("country") or "").strip().upper() or None

    pay_payload: dict[str, Any] = {
        "hs_code": hs,
        "customs_value": customs_value,
        "invoice_currency": str(line.get("currency") or "USD"),
        "country": country,
    }
    if net is not None:
        pay_payload["net_weight_kg"] = float(net)
    if gross is not None:
        pay_payload["gross_weight_kg"] = float(gross)
    if line.get("vehicle_is_new") is not None:
        pay_payload["vehicle_is_new"] = line.get("vehicle_is_new")
    if line.get("engine_volume") is not None:
        pay_payload["engine_volume"] = line.get("engine_volume")

    payments = compute_payments(pay_payload)
    bd = payments.get("breakdown") or {}
    rop_block: dict[str, Any] = {"total_rop_rub": 0.0, "not_subject_to_rop": True}
    if hs and gross is not None and net is not None:
        own = db_session is None
        db = db_session or SessionLocal()
        try:
            rop_block = calculate_rop(
                db,
                hs,
                float(gross),
                float(net),
                calendar_year=calendar_year,
            )
        finally:
            if own:
                db.close()

    total = float(bd.get("total_payable") or 0) + float(rop_block.get("total_rop_rub") or 0)
    return {
        "description": line.get("description"),
        "hs_code": hs,
        "customs_value": round(customs_value, 2),
        "currency": line.get("currency") or "USD",
        "country_of_origin": country,
        "duty": bd.get("duty", 0),
        "vat": bd.get("vat", 0),
        "excise": bd.get("excise", 0),
        "customs_fee": bd.get("customs_fee", 0),
        "recycling_fee": (payments.get("recycling_fee") or {}).get("fee_amount", 0),
        "rop": rop_block,
        "total_payable": round(total, 2),
        "payments_status": payments.get("status"),
        "tariff_preference": payments.get("tariff_preference"),
    }


async def calculate_batch_lines(
    lines: list[dict[str, Any]],
    *,
    auto_classify: bool = True,
    calendar_year: int | None = None,
) -> dict[str, Any]:
    """Расчёт пакета позиций с опциональной AI-классификацией."""
    results: list[dict[str, Any]] = []
    with SessionLocal() as db:
        for line in lines:
            row = dict(line)
            if auto_classify and not re.sub(r"\D", "", str(row.get("hs_code") or "")):
                hs, classify_meta = await classify_hs_if_missing(row)
                if hs:
                    row["hs_code"] = hs
                    row["hs_classified_by"] = "ai_smart" if classify_meta else "ai"
                if classify_meta:
                    row["classify_meta"] = classify_meta
            calc = calculate_line_payments(row, db_session=db, calendar_year=calendar_year)
            if row.get("classify_meta"):
                calc["classify_meta"] = row["classify_meta"]
            results.append(calc)

    totals = {
        "customs_value": round(sum(r["customs_value"] for r in results), 2),
        "duty": round(sum(float(r["duty"]) for r in results), 2),
        "vat": round(sum(float(r["vat"]) for r in results), 2),
        "excise": round(sum(float(r["excise"]) for r in results), 2),
        "customs_fee": round(sum(float(r["customs_fee"]) for r in results), 2),
        "recycling_fee": round(sum(float(r["recycling_fee"]) for r in results), 2),
        "rop": round(sum(float((r.get("rop") or {}).get("total_rop_rub") or 0) for r in results), 2),
        "total_payable": round(sum(float(r["total_payable"]) for r in results), 2),
    }
    return {"lines": results, "totals": totals, "line_count": len(results)}


def build_invoice_template_xlsx() -> bytes:
    df = pd.DataFrame(
        [
            {
                "description": "Laptop 14 inch",
                "hs_code": "",
                "quantity": 10,
                "unit": "pcs",
                "unit_price": 500,
                "currency": "USD",
                "weight_gross_kg": 25,
                "weight_net_kg": 22,
                "country_of_origin": "CN",
                "image_url": "",
                "article": "",
                "manufacturer": "",
            }
        ]
    )
    buf = io.BytesIO()
    df.to_excel(buf, index=False, sheet_name="invoice")
    return buf.getvalue()
