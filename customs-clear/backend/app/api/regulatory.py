"""API ведомственных документов."""
from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from ..services.regulatory_layer import get_regulatory_documents_for_hs

router = APIRouter()


@router.get("/documents/for-hs/{hs_code}")
async def documents_for_hs(
    hs_code: str,
    only_approved: bool = Query(False),
    min_confidence: float = Query(0.5, ge=0.0, le=1.0),
    max_results: int = Query(10, ge=1, le=50),
) -> JSONResponse:
    docs = get_regulatory_documents_for_hs(
        hs_code,
        only_approved=only_approved,
        min_confidence=min_confidence,
        max_results=max_results,
    )
    return JSONResponse(
        {
            "status": "OK",
            "hs_code": hs_code,
            "count": len(docs),
            "documents": docs,
        }
    )
