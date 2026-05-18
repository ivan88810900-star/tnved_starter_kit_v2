from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from loguru import logger
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..models.core import FssNotification, ReoRegistryEntry, SgrCertificate


def _norm_text(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v or "").strip())


def _norm_lower(v: Any) -> str:
    return _norm_text(v).lower()


def _is_active(status: str, expiry: datetime | None) -> bool:
    s = _norm_lower(status)
    if any(x in s for x in ("действ", "active", "зарегистр", "подписан")):
        return True
    if expiry is not None and expiry >= datetime.now():
        return True
    return False


def _year_tail(dt: datetime | None) -> str:
    if not dt:
        return ""
    try:
        return f" до {dt.year} г."
    except Exception:
        return ""


def _collect_item_keys(item_data: dict[str, Any] | None) -> dict[str, str]:
    d = item_data or {}
    product_name = _norm_text(d.get("product_name") or d.get("name_ru") or d.get("name") or d.get("name_cn"))
    brand = _norm_text(d.get("brand") or d.get("trademark"))
    model = _norm_text(d.get("model") or d.get("article") or d.get("sku"))
    return {"product_name": product_name, "brand": brand, "model": model}


def _extract_registry_number(item_data: dict[str, Any] | None) -> str:
    d = item_data or {}
    blob = " ".join(
        _norm_text(d.get(k))
        for k in ("article", "sku", "model", "name", "name_ru", "name_cn", "usage", "manufacturer", "counterparty")
    )
    # requested strict pattern
    m = re.search(r"\b([A-Z]{2}0000\d{7})\b", blob, flags=re.IGNORECASE)
    if m:
        num = m.group(1).upper()
        logger.debug("Extracted RegNumber: {}", num)
        return num
    # fallback for legacy formats in current dataset
    m2 = re.search(r"\b([A-Z]{2}\d{11,14})\b", blob, flags=re.IGNORECASE)
    if m2:
        num = m2.group(1).upper()
        logger.debug("Extracted RegNumber (fallback): {}", num)
        return num
    return ""


def _is_fsb_requirement(doc_type: str, title: str) -> bool:
    dt = _norm_lower(doc_type)
    tt = _norm_lower(title)
    return "нотификация фсб" in dt or "нотификация фсб" in tt or ("фсб" in tt and "нотиф" in tt)


def _is_reo_requirement(doc_type: str, title: str, legal_ref: str) -> bool:
    blob = " ".join((_norm_lower(doc_type), _norm_lower(title), _norm_lower(legal_ref)))
    return (
        "лицензия_рчц" in blob
        or "рчц" in blob
        or "радиочаст" in blob
        or "рэс" in blob
        or "ркн" in blob
        or "гкрч" in blob
    )


def _is_sgr_requirement(doc_type: str, title: str) -> bool:
    return "сгр" in _norm_lower(doc_type) or "сгр" in _norm_lower(title)


def _match_fss(db: Session, keys: dict[str, str], reg_number: str = "") -> str | None:
    if reg_number:
        row_num = db.query(FssNotification).filter(FssNotification.number == reg_number).first()
        if row_num:
            if _is_active(row_num.status or "", row_num.expiry_date):
                return f"Найдена действующая нотификация {row_num.number}{_year_tail(row_num.expiry_date)}"
            return f"Найдена нотификация {row_num.number} (статус: {row_num.status or 'не указан'})"

    conds = []
    if keys["model"]:
        conds.append(FssNotification.name.ilike(f"%{keys['model']}%"))
    if keys["brand"]:
        conds.append(func.lower(FssNotification.brand) == keys["brand"].lower())
    if keys["product_name"]:
        conds.append(FssNotification.name.ilike(f"%{keys['product_name'][:80]}%"))
    if not conds:
        return None
    row = (
        db.query(FssNotification)
        .filter(or_(*conds))
        .order_by(FssNotification.id.desc())
        .first()
    )
    if not row:
        return None
    if _is_active(row.status or "", row.expiry_date):
        return f"Найдена действующая нотификация {row.number}{_year_tail(row.expiry_date)}"
    return f"Найдена нотификация {row.number} (статус: {row.status or 'не указан'})"


def _match_reo(db: Session, keys: dict[str, str]) -> str | None:
    conds = []
    if keys["model"]:
        conds.append(ReoRegistryEntry.model_name.ilike(f"%{keys['model']}%"))
        conds.append(ReoRegistryEntry.characteristics.ilike(f"%{keys['model']}%"))
    if keys["brand"]:
        conds.append(func.lower(ReoRegistryEntry.brand) == keys["brand"].lower())
    if keys["product_name"]:
        conds.append(ReoRegistryEntry.model_name.ilike(f"%{keys['product_name'][:80]}%"))
    if not conds:
        return None
    row = (
        db.query(ReoRegistryEntry)
        .filter(or_(*conds))
        .order_by(ReoRegistryEntry.id.desc())
        .first()
    )
    if not row:
        return None
    if _is_active(row.status or "", row.expiry_date):
        return f"Найдена действующая запись РЭС/РЧЦ {row.number}{_year_tail(row.expiry_date)}"
    return f"Найдена запись РЭС/РЧЦ {row.number} (статус: {row.status or 'не указан'})"


def _match_sgr(db: Session, keys: dict[str, str]) -> str | None:
    conds = []
    if keys["product_name"]:
        conds.append(SgrCertificate.product_name.ilike(f"%{keys['product_name'][:120]}%"))
    if keys["brand"]:
        conds.append(func.lower(SgrCertificate.brand) == keys["brand"].lower())
    if keys["model"]:
        conds.append(SgrCertificate.product_name.ilike(f"%{keys['model']}%"))
    if not conds:
        return None
    row = (
        db.query(SgrCertificate)
        .filter(or_(*conds))
        .order_by(SgrCertificate.id.desc())
        .first()
    )
    if not row:
        return None
    return f"Найдено СГР {row.sgr_number} ({row.status or 'статус не указан'})"


def match_document_in_registries(
    *,
    doc_type: str,
    title: str,
    legal_ref: str,
    item_data: dict[str, Any] | None,
    db: Session,
) -> str | None:
    """
    Возвращает человекочитаемый результат сверки документа с госреестрами.
    Для неподходящих типов документов возвращает None.
    """
    keys = _collect_item_keys(item_data)
    reg_number = _extract_registry_number(item_data)
    if _is_fsb_requirement(doc_type, title):
        return _match_fss(db, keys, reg_number=reg_number)
    if _is_reo_requirement(doc_type, title, legal_ref):
        return _match_reo(db, keys)
    if _is_sgr_requirement(doc_type, title):
        return _match_sgr(db, keys)
    return None

