"""Справочник ТН ВЭД, примечания и контекст для кода (локальная БД после импорта пакета)."""
from __future__ import annotations
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from loguru import logger

from ..services.embedding_service import embeddings_stats, ingest_tnved_embeddings_batch, semantic_search_tnved
from ..security import require_admin_token, require_authenticated_user
from ..services.normative_store import (
    find_normative_notes_for_hs,
    get_integrated_data_stats,
    get_tnved_breadcrumb,
    get_tnved_context_for_hs,
    search_tnved,
)

router = APIRouter()

@router.get("/stats")
async def tnved_stats() -> JSONResponse:
    s = get_integrated_data_stats()
    return JSONResponse(
        {
            "status": "OK",
            "tnved_entries_count": s.get("tnved_entries_count", 0),
            "normative_notes_count": s.get("normative_notes_count", 0),
            "hs_rates_count": s.get("hs_rates_count", 0),
            "non_tariff_rules_count": s.get("non_tariff_rules_count", 0),
            "ingested_documents_count": s.get("ingested_documents_count", 0),
            "tnved_embeddings_count": s.get("tnved_embeddings_count", 0),
            "customs_calculation_history_count": s.get("customs_calculation_history_count", 0),
        }
    )


@router.get("/embeddings/status")
async def tnved_embeddings_status() -> JSONResponse:
    """Сводка по векторам семантического поиска (без секретов)."""
    return JSONResponse({"status": "OK", **embeddings_stats()})


@router.post("/embeddings/ingest")
async def tnved_embeddings_ingest(
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    only_missing: bool = Query(True),
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
) -> JSONResponse:
    """
    Пакетная индексация описаний ТН ВЭД через OpenAI embeddings.
    Требует заголовок X-Admin-Token.
    """
    require_admin_token(x_admin_token)
    try:
        result = ingest_tnved_embeddings_batch(limit=limit, offset=offset, only_missing=only_missing)
        return JSONResponse(result)
    except RuntimeError as e:
        logger.warning(f"embeddings ingest: {e}")
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.exception("embeddings ingest")
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/search/semantic")
async def tnved_search_semantic(
    q: str = Query(..., min_length=2, description="Текстовый запрос (товар, описание)"),
    limit: int = Query(15, ge=1, le=50),
    _user: dict = Depends(require_authenticated_user),
) -> JSONResponse:
    """Семантический top-k по загруженным эмбеддингам (нужен OPENAI_API_KEY для вектора запроса)."""
    try:
        results = semantic_search_tnved(q, top_k=limit)
        return JSONResponse({"status": "OK", "query": q, "results": results})
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.exception("semantic search")
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/search")
async def tnved_search(
    q: str = Query(..., min_length=2, description="Код или фрагмент наименования"),
    limit: int = Query(40, ge=1, le=200),
) -> JSONResponse:
    return JSONResponse({"status": "OK", "results": search_tnved(q, limit=limit)})


@router.get("/lookup/{hs_code:path}")
async def tnved_lookup(hs_code: str) -> JSONResponse:
    ctx = get_tnved_context_for_hs(hs_code)
    return JSONResponse({"status": "OK", **ctx})


@router.get("/breadcrumb/{hs_code:path}")
async def tnved_breadcrumb(hs_code: str) -> JSONResponse:
    return JSONResponse({"status": "OK", "breadcrumb": get_tnved_breadcrumb(hs_code)})


@router.get("/notes/{hs_code:path}")
async def tnved_notes(
    hs_code: str,
    category: Optional[str] = Query(None, description="Фильтр: tnved, ett, non_tariff, general"),
) -> JSONResponse:
    notes = find_normative_notes_for_hs(hs_code)
    if category:
        cat = category.strip().lower()
        notes = [n for n in notes if (n.get("category") or "") == cat]
    return JSONResponse({"status": "OK", "hs_code": hs_code, "notes": notes})
