"""
Расчёт экологического сбора (РОП) по официальным ставкам ПП №1041 / перечню ПП №2414.

Формула (импорт, без фактической утилизации):
  amount = mass_kg × rate_per_ton × recycling_norm / 1000
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from ..models.rop import RopGoodsRate, RopPackagingDefault, RopPackagingRate

LEGAL_REF = "ПП РФ №1041 от 01.08.2024; перечень ПП №2414 от 29.12.2023"

_PACKAGING_TYPE_ALIASES: dict[str, str] = {
    "auto": "auto",
    "авто": "auto",
    "carton": "carton",
    "картон": "carton",
    "roll": "roll",
    "рулон": "roll",
    "bag": "bag",
    "мешок": "bag",
    "none": "none",
    "нет": "none",
    "paper": "paper",
    "polymer": "polymer",
    "plastic": "polymer",
    "glass": "glass",
    "metal": "metal",
    "wood": "wood",
    "textile": "textile",
    "combined": "combined",
    "other": "other",
}


def _norm_hs(raw: str) -> str:
    return re.sub(r"\D", "", (raw or "").strip())[:10]


def _normalize_packaging_type(raw: str | None) -> str:
    s = (raw or "auto").strip().lower()
    return _PACKAGING_TYPE_ALIASES.get(s, s)


def _parse_hs_prefixes(row: RopGoodsRate) -> list[str]:
    try:
        data = json.loads(row.hs_prefixes_json or "[]")
        return [str(x) for x in data if str(x).strip()]
    except json.JSONDecodeError:
        return []


def _match_goods_rate(session: Session, hs_code: str, calendar_year: int) -> RopGoodsRate | None:
    hs = _norm_hs(hs_code)
    if not hs:
        return None
    rows = session.query(RopGoodsRate).filter(RopGoodsRate.calendar_year == calendar_year).all()
    best: RopGoodsRate | None = None
    best_len = -1
    for row in rows:
        for pfx in _parse_hs_prefixes(row):
            p = re.sub(r"\D", "", pfx)
            if hs.startswith(p) and len(p) > best_len:
                best = row
                best_len = len(p)
    return best


def detect_packaging_type(session: Session, hs_code: str) -> tuple[str, str | None]:
    """Возвращает (packaging_type, reason)."""
    hs = _norm_hs(hs_code)
    rules = (
        session.query(RopPackagingDefault)
        .order_by(RopPackagingDefault.priority.desc())
        .all()
    )
    best_type = "carton"
    best_reason: str | None = "По умолчанию — картонная коробка"
    best_len = -1
    for rule in rules:
        if rule.is_default_rule:
            if best_len < 0:
                best_type = rule.packaging_type
                best_reason = rule.reason or None
            continue
        for chunk in (rule.hs_prefix or "").split(","):
            p = _norm_prefix(chunk)
            if p and hs.startswith(p) and len(p) > best_len:
                best_type = rule.packaging_type
                best_reason = rule.reason or None
                best_len = len(p)
    return best_type, best_reason


def _norm_prefix(raw: str) -> str:
    return re.sub(r"\D", "", (raw or "").strip())[:16]


def _resolve_pp2414_group(session: Session, packaging_type: str) -> int | None:
    if packaging_type == "none":
        return None
    row = (
        session.query(RopPackagingDefault)
        .filter(RopPackagingDefault.packaging_type == packaging_type)
        .filter(RopPackagingDefault.pp2414_group.isnot(None))
        .first()
    )
    if row and row.pp2414_group:
        return int(row.pp2414_group)
    fallback: dict[str, int] = {
        "carton": 46,
        "roll": 22,
        "bag": 45,
        "paper": 46,
        "polymer": 22,
        "glass": 50,
        "metal": 47,
        "wood": 48,
        "textile": 49,
        "combined": 52,
        "other": 27,
    }
    return fallback.get(packaging_type)


def get_goods_rate(session: Session, hs_code: str, calendar_year: int | None = None) -> RopGoodsRate | None:
    year = int(calendar_year or datetime.utcnow().year)
    return _match_goods_rate(session, hs_code, year)


def get_packaging_rate(
    session: Session,
    packaging_type: str,
    calendar_year: int | None = None,
) -> RopPackagingRate | None:
    year = int(calendar_year or datetime.utcnow().year)
    ptype = _normalize_packaging_type(packaging_type)
    if ptype in ("none", "auto"):
        return None
    group = _resolve_pp2414_group(session, ptype)
    if group is None:
        return None
    return (
        session.query(RopPackagingRate)
        .filter(RopPackagingRate.pp2414_group == group, RopPackagingRate.calendar_year == year)
        .one_or_none()
    )


def calculate_rop(
    session: Session,
    hs_code: str,
    weight_gross_kg: float,
    weight_net_kg: float,
    *,
    direction: str = "import",
    packaging_type: str = "auto",
    calendar_year: int | None = None,
) -> dict[str, Any]:
    """Расчёт РОП за товар и упаковку."""
    _ = direction  # зарезервировано для будущих правил импорт/ЕАЭС
    year = int(calendar_year or datetime.utcnow().year)
    packaging_weight = max(0.0, float(weight_gross_kg) - float(weight_net_kg))

    goods_rate = get_goods_rate(session, hs_code, year)
    if goods_rate is None:
        return {
            "calendar_year": year,
            "hs_code": _norm_hs(hs_code),
            "goods_rop_rub": 0.0,
            "packaging_rop_rub": 0.0,
            "total_rop_rub": 0.0,
            "goods_category": None,
            "goods_rate_per_ton": None,
            "goods_recycling_norm_pct": None,
            "packaging_type": _normalize_packaging_type(packaging_type),
            "packaging_weight_kg": round(packaging_weight, 3),
            "packaging_rate_per_ton": None,
            "legal_ref": LEGAL_REF,
            "not_subject_to_rop": True,
        }

    goods_rop = (
        float(weight_net_kg)
        * float(goods_rate.rate_per_ton)
        * float(goods_rate.recycling_norm)
        / 1000.0
    )

    ptype = _normalize_packaging_type(packaging_type)
    detect_reason: str | None = None
    if ptype == "auto":
        ptype, detect_reason = detect_packaging_type(session, hs_code)

    pkg_rate: RopPackagingRate | None = None
    packaging_rop = 0.0
    if ptype != "none" and packaging_weight > 0:
        pkg_rate = get_packaging_rate(session, ptype, year)
        if pkg_rate is not None:
            packaging_rop = (
                packaging_weight * float(pkg_rate.rate_per_ton) * float(pkg_rate.recycling_norm) / 1000.0
            )

    return {
        "calendar_year": year,
        "hs_code": _norm_hs(hs_code),
        "goods_rop_rub": round(goods_rop, 2),
        "packaging_rop_rub": round(packaging_rop, 2),
        "total_rop_rub": round(goods_rop + packaging_rop, 2),
        "goods_category": goods_rate.category_name,
        "goods_pp2414_group": goods_rate.pp2414_group,
        "goods_rate_per_ton": float(goods_rate.rate_per_ton),
        "goods_recycling_norm_pct": round(float(goods_rate.recycling_norm) * 100, 2),
        "packaging_type": ptype,
        "packaging_detect_reason": detect_reason,
        "packaging_weight_kg": round(packaging_weight, 3),
        "packaging_rate_per_ton": float(pkg_rate.rate_per_ton) if pkg_rate else None,
        "packaging_pp2414_group": pkg_rate.pp2414_group if pkg_rate else None,
        "legal_ref": LEGAL_REF,
        "not_subject_to_rop": False,
    }
