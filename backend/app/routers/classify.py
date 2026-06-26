from fastapi import APIRouter
from pydantic import BaseModel
from typing import List
from ..services import tariff_service
from ..db import SessionLocal
from ..models_hs import HSCode, Note

router = APIRouter(prefix="/classify", tags=["classify"])

@router.get("/{hs_code}")
def classify(hs_code: str):
    code = hs_code.replace(".", "")
    db = SessionLocal()
    try:
        hs = db.query(HSCode).filter(HSCode.code == code).first()
        duty_info = tariff_service.lookup(code)
        vat_rate, vat_source, vat_title = tariff_service.resolve_vat_for_code(code)
        notes = db.query(Note).filter((Note.level == "chapter") & (Note.ref_id == code[:2])).all()
        out = {
            "hs_code": code,
            "title": hs.title_ru if hs else None,
            "duty": duty_info,
            "vat": {"rate": vat_rate, "source": vat_source},
            "notes": [{"level": n.level, "ref": n.ref_id, "text": n.text[:300]} for n in notes],
        }
        return out
    finally:
        db.close()

class CodesIn(BaseModel):
    codes: List[str]

@router.post("/batch")
def classify_batch(payload: CodesIn):
    db = SessionLocal()
    try:
        out = []
        for raw in payload.codes:
            code = (raw or "").replace(".", "").strip()
            hs = db.query(HSCode).filter(HSCode.code == code).first()
            duty_info = tariff_service.lookup(code)
            vat_rate, vat_source, vat_title = tariff_service.resolve_vat_for_code(code)
            notes = db.query(Note).filter((Note.level == "chapter") & (Note.ref_id == code[:2])).all()
            out.append({
                "hs_code": code,
                "title": hs.title_ru if hs else None,
                "duty": duty_info,
                "vat": {"rate": vat_rate, "source": vat_source},
                "notes": [{"level": n.level, "ref": n.ref_id} for n in notes],
            })
        return {"items": out, "count": len(out)}
    finally:
        db.close()



