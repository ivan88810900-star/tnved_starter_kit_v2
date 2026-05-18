from fastapi import APIRouter, Query
from sqlalchemy import select
from ..db import SessionLocal
from ..models import TariffRate
from ..services import tariff_service

router = APIRouter(prefix="/tariff", tags=["tariff"])

@router.get("/{hs_code}")
def get_tariff(hs_code: str):
    data = tariff_service.lookup(hs_code)
    # подставим НДС по правилам (если в ЕТТ нет своего поля VAT)
    vat_rate, vat_source, vat_title = tariff_service.resolve_vat_for_code(hs_code)
    data["vat"] = vat_rate
    data["vat_source"] = vat_source
    data["vat_reason"] = vat_title
    return {"hs_code": hs_code.replace(".", ""), **data}

@router.get("/search")
def search_tariff(q: str = Query(..., min_length=1, max_length=10)):
    q = q.replace(".", "")
    db = SessionLocal()
    try:
        rows = (db.execute(
            select(TariffRate)
            .where(TariffRate.hs_code.like(f"{q}%"))
            .limit(100)
        ).scalars().all())
        return [
            {"hs_code": r.hs_code, "duty": r.duty, "vat": r.vat, "version": r.source_version}
            for r in rows
        ]
    finally:
        db.close()
