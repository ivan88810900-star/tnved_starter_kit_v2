from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional, Tuple

import io

import pdfplumber
import pandas as pd
from fastapi import UploadFile
from loguru import logger


_EXTRACTOR_ALIASES: Optional[Dict[str, Tuple[str, ...]]] = None


def _get_extractor_column_aliases() -> Dict[str, Tuple[str, ...]]:
    """Доп. алиасы заголовков колонок из JSON (шаблоны packing list по заказчику). См. EXTRACTOR_COLUMN_ALIASES_JSON."""
    global _EXTRACTOR_ALIASES
    if _EXTRACTOR_ALIASES is not None:
        return _EXTRACTOR_ALIASES
    path = (os.getenv("EXTRACTOR_COLUMN_ALIASES_JSON") or "").strip()
    if not path or not os.path.isfile(path):
        _EXTRACTOR_ALIASES = {}
        return _EXTRACTOR_ALIASES
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        out: Dict[str, Tuple[str, ...]] = {}
        if isinstance(raw, dict):
            for k, v in raw.items():
                if isinstance(v, list):
                    out[str(k)] = tuple(str(x) for x in v if str(x).strip())
        _EXTRACTOR_ALIASES = out
        logger.info(f"Загружены доп. алиасы колонок: {path} ({len(out)} полей)")
    except Exception as e:
        logger.warning(f"EXTRACTOR_COLUMN_ALIASES_JSON: не прочитан {path}: {e}")
        _EXTRACTOR_ALIASES = {}
    return _EXTRACTOR_ALIASES


def _col_match(col_name: str, *needles: str) -> bool:
    """Подбор колонки по рус/англ/китайским подстрокам (без жёсткой привязки к регистру латиницы)."""
    raw = str(col_name).strip()
    low = raw.lower()
    for n in needles:
        if not n:
            continue
        nl = n.lower()
        if nl in low or n in raw:
            return True
    return False


def _ocr_pdf_pages(content: bytes, max_pages: int = 4) -> str:
    """Распознавание текста со сканов PDF (китайский/русский/английский)."""
    if not content or len(content) < 100:
        return ""
    try:
        import fitz  # PyMuPDF
        import pytesseract
        from PIL import Image
    except ImportError as e:
        logger.warning(f"OCR недоступен (импорт): {e}")
        return ""
    lang = os.getenv("OCR_LANGUAGES", "rus+eng+chi_sim").replace(",", "+")
    parts: list[str] = []
    try:
        doc = fitz.open(stream=content, filetype="pdf")
        n = min(len(doc), max_pages)
        for i in range(n):
            page = doc[i]
            pix = page.get_pixmap(dpi=int(os.getenv("OCR_DPI", "132") or "132"))
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            chunk = pytesseract.image_to_string(img, lang=lang) or ""
            if chunk.strip():
                parts.append(chunk)
        doc.close()
    except Exception as e:
        logger.warning(f"OCR PDF: {e}")
    return "\n\n".join(parts).strip()


async def _read_upload_bytes(upload: UploadFile) -> bytes:
    """Чтение тела загруженного файла в память."""
    content = await upload.read()
    logger.info(f"Файл {upload.filename} прочитан, размер={len(content)} байт")
    return content


def _extract_from_pdf(content: bytes) -> Dict[str, Any]:
    """Простейшее извлечение текста из PDF.

    В MVP мы не реализуем полный парсер инвойсов, а возвращаем текстовый блок.
    При необходимости позже сюда можно добавить полноценный анализ таблиц.
    """
    if not content or len(content) < 10:
        return {"raw_text": "", "items": [], "summary": {"gross_weight_total": 0, "net_weight_total": 0, "lines_count": 0}}
    try:
        text_parts = []
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                text_parts.append(page_text)
        text = "\n".join(text_parts)
        logger.info("Извлечён текст из PDF")
        plain = (text or "").strip()
        if len(plain) < 80:
            ocr = _ocr_pdf_pages(content)
            if len(ocr) > len(plain):
                text = ocr
                logger.info("PDF: использован OCR (мало текстового слоя)")
        return {"raw_text": text, "items": [], "summary": {"gross_weight_total": 0, "net_weight_total": 0, "lines_count": 0}}
    except Exception as e:
        logger.warning(f"Ошибка парсинга PDF: {e}")
        return {"raw_text": content.decode("utf-8", errors="ignore")[:5000], "items": [], "summary": {}}


def _extract_items_from_dataframe(df: pd.DataFrame) -> Dict[str, Any]:
    """Извлечение строк из Excel/CSV: латиница, кириллица, частые китайские заголовки."""
    col_list = [c for c in df.columns]
    xa = _get_extractor_column_aliases()

    def pick(*needles: str) -> str | None:
        for c in col_list:
            if isinstance(c, str) and _col_match(c, *needles):
                return c
        return None

    desc_col = pick(
        "description",
        "описан",
        "наименован",
        "品名",
        "商品名称",
        "货物名称",
        "规格",
        "型号",
        "name",
        "product",
        "item",
        "goods",
        "material",
        "descr",
        "description of goods",
        "cargo",
        "产品名称",
        "货描",
        "名稱",
        *xa.get("description", ()),
    )
    qty_col = pick(
        "qty",
        "кол",
        "quantity",
        "数量",
        "件数",
        "pcs",
        "партия",
        "batch",
        "order qty",
        "件",
        "q'ty",
        "qty.",
        *xa.get("quantity", ()),
    )
    unit_col = pick("unit", "единиц", "单位", "uom", "计量单位", "單位", *xa.get("unit", ()))
    gross_col = pick(
        "gross",
        "брутто",
        "g.w",
        "gw",
        "毛重",
        "總毛重",
        "gross weight",
        "g.wt",
        "total gross",
        *xa.get("gross", ()),
    )
    net_col = pick("net", "нетто", "n.w", "nw", "净重", "net weight", "n.wt", *xa.get("net", ()))
    unit_price_col = pick(
        "unit price",
        "цена за",
        "unit_price",
        "单价",
        "价格",
        "price",
        "u/price",
        "rate",
        *xa.get("unit_price", ()),
    )
    total_col = pick(
        "total",
        "amount",
        "сумма",
        "金额",
        "总价",
        "amt",
        "line total",
        "ext price",
        "小计",
        *xa.get("total", ()),
    )
    pkg_col = pick(
        "package",
        "carton",
        "箱数",
        "件",
        "мест",
        "pkgs",
        "packages",
        "ctns",
        "箱",
        "ctn",
        "cartons",
        "件数",
        "no. of packages",
        *xa.get("package", ()),
    )

    items = []
    for idx, row in df.iterrows():
        description = str(row.get(desc_col, "")).strip() if desc_col else ""
        if not description:
            continue

        def _f(cell: Any) -> float:
            try:
                if cell is None or (isinstance(cell, float) and pd.isna(cell)):
                    return 0.0
                return float(str(cell).replace(",", ".").replace(" ", ""))
            except (TypeError, ValueError):
                return 0.0

        item = {
            "line": int(idx) + 1,
            "description": description,
            "quantity": _f(row.get(qty_col)) if qty_col else 0.0,
            "unit": str(row.get(unit_col, "") or "").strip() if unit_col else "",
            "weight_gross": _f(row.get(gross_col)) if gross_col else 0.0,
            "weight_net": _f(row.get(net_col)) if net_col else 0.0,
            "unit_price": _f(row.get(unit_price_col)) if unit_price_col else 0.0,
            "total_price": _f(row.get(total_col)) if total_col else 0.0,
            "packages": _f(row.get(pkg_col)) if pkg_col else 0.0,
            "places": _f(row.get(pkg_col)) if pkg_col else 0.0,
        }
        items.append(item)

    summary = {
        "gross_weight_total": sum(i["weight_gross"] for i in items),
        "net_weight_total": sum(i["weight_net"] for i in items),
        "total_amount": sum(i["total_price"] for i in items) or sum(
            (i["quantity"] * i["unit_price"]) for i in items
        ),
        "lines_count": len(items),
        "packages": sum(i.get("packages") or 0 for i in items),
    }
    return {"items": items, "summary": summary}


def _extract_from_excel(content: bytes) -> Dict[str, Any]:
    """Извлечение таблицы товаров из Excel-файла."""
    if not content or len(content) < 10:
        return {"items": [], "summary": {"gross_weight_total": 0, "net_weight_total": 0, "lines_count": 0, "total_amount": 0}}
    try:
        with io.BytesIO(content) as bio:
            df = pd.read_excel(bio)
        logger.info("Excel загружен в DataFrame")
        return _extract_items_from_dataframe(df)
    except Exception as e:
        logger.warning(f"Ошибка парсинга Excel: {e}")
        return {"items": [], "summary": {"gross_weight_total": 0, "net_weight_total": 0, "lines_count": 0, "total_amount": 0}}


async def extract_invoice_and_packing_from_files(
    invoice: UploadFile,
    packing_list: Optional[UploadFile] = None,
) -> Dict[str, Dict[str, Any]]:
    """Извлекает данные инвойса и (если передан файл) упаковочного листа.

    В MVP:
    - если расширение .pdf — используем pdfplumber и возвращаем только сырой текст;
    - если Excel (.xls/.xlsx/.csv) — пытаемся собрать структуры товаров.
    """
    invoice_bytes = await _read_upload_bytes(invoice)

    def detect_and_extract(filename: str, content: bytes) -> Dict[str, Any]:
        name_lower = filename.lower()
        if name_lower.endswith(".pdf"):
            return _extract_from_pdf(content)
        if name_lower.endswith(".xlsx") or name_lower.endswith(".xls") or name_lower.endswith(".csv"):
            return _extract_from_excel(content)
        # по умолчанию пробуем как Excel
        try:
            return _extract_from_excel(content)
        except Exception:
            return {"raw_text": content.decode("utf-8", errors="ignore")}

    invoice_data = detect_and_extract(invoice.filename or "invoice", invoice_bytes)
    if packing_list is not None and (packing_list.filename or "").strip():
        packing_bytes = await _read_upload_bytes(packing_list)
        packing_data = detect_and_extract(packing_list.filename or "packing", packing_bytes)
    else:
        packing_data = {
            "items": [],
            "summary": {},
            "raw_text": "",
        }

    # Минимальная мета-информация, которую будет использовать validator
    invoice_data.setdefault("invoice_number", None)
    invoice_data.setdefault("extracted_at", None)

    return {"invoice": invoice_data, "packing": packing_data}

