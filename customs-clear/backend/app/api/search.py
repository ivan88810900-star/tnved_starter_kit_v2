"""Поиск товаров по коду ТН ВЭД."""
from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from ..services.normative_store import search_hs_rates, search_hs_rates_enriched

router = APIRouter()


@router.get("/hs")
async def search_hs(
    q: str = Query(..., min_length=2, description="Код или префикс ТН ВЭД"),
    limit: int = Query(50, ge=1, le=200),
    enrich: bool = Query(True, description="Добавить наименование из tnved_entries, если есть"),
) -> JSONResponse:
    """Поиск по hs_rates; при enrich — подтягивается title из справочника ТН ВЭД."""
    results = search_hs_rates_enriched(q, limit=limit) if enrich else search_hs_rates(q, limit=limit)
    return JSONResponse({"status": "OK", "query": q, "items": results, "count": len(results)})
