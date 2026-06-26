"""API эндпоинты расчёта и справочника ставок РОП (экосбор)."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import SessionLocal
from ..models.rop import RopGoodsRate, RopPackagingRate
from ..services.rop_calculator import (
    calculate_rop,
    detect_packaging_type,
    get_goods_rate,
    get_packaging_rate,
)

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class RopCalculateRequest(BaseModel):
    hs_code: str
    weight_gross_kg: float = Field(..., ge=0)
    weight_net_kg: float = Field(..., ge=0)
    direction: str = "import"
    packaging_type: str = "auto"
    calendar_year: int | None = None


@router.get("/coverage/chapters")
def rop_chapter_coverage(
    calendar_year: int = Query(2026),
    db: Session = Depends(get_db),
) -> dict:
    from ..services.rop_coverage_audit import build_rop_chapter_coverage, coverage_summary

    matrix = build_rop_chapter_coverage(db, calendar_year=calendar_year)
    return {"summary": coverage_summary(matrix), "chapters": matrix}


@router.post("/calculate")
def rop_calculate(body: RopCalculateRequest, db: Session = Depends(get_db)) -> dict:
    if body.weight_gross_kg < body.weight_net_kg:
        raise HTTPException(status_code=422, detail="weight_gross_kg must be >= weight_net_kg")
    return calculate_rop(
        db,
        body.hs_code,
        body.weight_gross_kg,
        body.weight_net_kg,
        direction=body.direction,
        packaging_type=body.packaging_type,
        calendar_year=body.calendar_year,
    )


@router.get("/rates/goods")
def rop_rates_goods(
    calendar_year: int | None = Query(None),
    db: Session = Depends(get_db),
) -> dict:
    q = db.query(RopGoodsRate)
    if calendar_year is not None:
        q = q.filter(RopGoodsRate.calendar_year == calendar_year)
    rows = q.order_by(RopGoodsRate.calendar_year, RopGoodsRate.pp2414_group).all()
    return {
        "count": len(rows),
        "items": [
            {
                "category_code": r.category_code,
                "pp2414_group": r.pp2414_group,
                "category_name": r.category_name,
                "hs_prefixes": json.loads(r.hs_prefixes_json or "[]"),
                "base_rate_per_ton": r.base_rate_per_ton,
                "ke_coefficient": r.ke_coefficient,
                "rate_per_ton": r.rate_per_ton,
                "recycling_norm": r.recycling_norm,
                "calendar_year": r.calendar_year,
                "needs_verification": r.needs_verification,
            }
            for r in rows
        ],
    }


@router.get("/rates/packaging")
def rop_rates_packaging(
    calendar_year: int | None = Query(None),
    db: Session = Depends(get_db),
) -> dict:
    q = db.query(RopPackagingRate)
    if calendar_year is not None:
        q = q.filter(RopPackagingRate.calendar_year == calendar_year)
    rows = q.order_by(RopPackagingRate.calendar_year, RopPackagingRate.pp2414_group).all()
    return {
        "count": len(rows),
        "items": [
            {
                "category_code": r.category_code,
                "pp2414_group": r.pp2414_group,
                "category_name": r.category_name,
                "packaging_type": r.packaging_type,
                "base_rate_per_ton": r.base_rate_per_ton,
                "ke_coefficient": r.ke_coefficient,
                "rate_per_ton": r.rate_per_ton,
                "recycling_norm": r.recycling_norm,
                "calendar_year": r.calendar_year,
            }
            for r in rows
        ],
    }


@router.get("/rates/goods/{hs_code}")
def rop_rate_for_hs(
    hs_code: str,
    calendar_year: int | None = Query(None),
    db: Session = Depends(get_db),
) -> dict:
    row = get_goods_rate(db, hs_code, calendar_year)
    if row is None:
        return {"hs_code": hs_code, "found": False, "not_subject_to_rop": True}
    return {
        "hs_code": hs_code,
        "found": True,
        "not_subject_to_rop": False,
        "category_code": row.category_code,
        "pp2414_group": row.pp2414_group,
        "category_name": row.category_name,
        "rate_per_ton": row.rate_per_ton,
        "recycling_norm": row.recycling_norm,
        "calendar_year": row.calendar_year,
    }


@router.get("/packaging-type/{hs_code}")
def rop_packaging_type(hs_code: str, db: Session = Depends(get_db)) -> dict:
    ptype, reason = detect_packaging_type(db, hs_code)
    rate = get_packaging_rate(db, ptype, None)
    return {
        "hs_code": hs_code,
        "packaging_type": ptype,
        "reason": reason,
        "pp2414_group": rate.pp2414_group if rate else None,
        "rate_per_ton": rate.rate_per_ton if rate else None,
    }
