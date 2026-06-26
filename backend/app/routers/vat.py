from fastapi import APIRouter, HTTPException
from ..services import tariff_service

router = APIRouter(prefix="/vat", tags=["vat"])

@router.get("/{hs_code}")
def vat_for(hs_code: str):
    rate, source, title = tariff_service.resolve_vat_for_code(hs_code)
    return {"hs_code": hs_code.replace(".", ""), "vat": rate, "source": source, "reason": title}



