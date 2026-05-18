"""API подтверждения классификации (feedback loop для самообучения RAG).

Фронтенд присылает связку ``(описание -> утверждённый код ТН ВЭД)``. Бэкенд:

1) Сохраняет запись в ``declaration_examples`` с ``source='user_approved'``.
2) Фоновой задачей считает эмбеддинг и регистрирует synthetic-прецедент
   в ``tnved_entries`` + ``tnved_entry_embeddings`` (``precedent_embeddings_v1``).
3) В следующем разборе инвойса этот прецедент найдётся и в EXACT-MATCH блоке,
   и в векторном поиске :mod:`app.services.rag_retriever`.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import SessionLocal
from ..security import require_authenticated_user
from ..services.audit_log import request_audit_meta
from ..services.classification_feedback_service import (
    approve_classification,
    build_embedding_for_example,
)

router = APIRouter(dependencies=[Depends(require_authenticated_user)])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class ApproveClassificationRequest(BaseModel):
    """Тело запроса: утверждение соответствия «описание товара → 10-значный код ТН ВЭД»."""

    original_description: str = Field(
        ...,
        min_length=3,
        max_length=8000,
        description="Оригинальное описание товара из инвойса (как видел пользователь)",
    )
    approved_hs_code: str = Field(
        ...,
        description="Подтверждённый 10-значный код ТН ВЭД (только цифры или 10-значная форма с пробелами)",
    )
    user_note: str | None = Field(
        default=None,
        max_length=2000,
        description="Необязательный комментарий/обоснование (будет сохранено вместе с описанием)",
    )
    user_id: str | None = Field(
        default=None,
        max_length=128,
        description="Идентификатор пользователя/роли для аудит-лога (необязательный)",
    )
    invoice_context: str | None = Field(
        default=None,
        max_length=4000,
        description="Дополнительный контекст из инвойса (строка, бренд, артикул) — будет добавлен к описанию",
    )


class ApproveClassificationResponse(BaseModel):
    example_id: int
    hs_code: str
    description: str
    source: str
    created: bool
    embedding_scheduled: bool


@router.post(
    "/approve",
    status_code=status.HTTP_201_CREATED,
    response_model=ApproveClassificationResponse,
    summary="Подтвердить классификацию ТН ВЭД и обучить RAG",
)
def approve_classification_route(
    payload: ApproveClassificationRequest,
    background: BackgroundTasks,
    request: Request,
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Сохраняет утверждённую классификацию и планирует фоновую генерацию эмбеддинга."""
    hs_clean = re.sub(r"\D", "", payload.approved_hs_code or "")[:10]
    if len(hs_clean) != 10:
        raise HTTPException(
            status_code=400,
            detail="approved_hs_code должен содержать ровно 10 цифр",
        )

    # Объединяем описание + контекст из инвойса (бренд, артикул и пр.) в один текст для RAG.
    pieces: list[str] = [payload.original_description.strip()]
    if payload.invoice_context and payload.invoice_context.strip():
        pieces.append(f"[Контекст инвойса] {payload.invoice_context.strip()}")
    full_description = "\n".join(p for p in pieces if p)[:8000]

    meta = request_audit_meta(request)
    user_identifier = (payload.user_id or meta.get("client_id") or "").strip() or None

    try:
        result = approve_classification(
            db,
            description=full_description,
            approved_hs_code=hs_clean,
            user_note=payload.user_note or "",
            user_id=user_identifier,
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        db.rollback()
        logger.exception("approve_classification_route: persist failed")
        raise HTTPException(status_code=500, detail=f"persist failed: {exc!s}") from exc

    example_id = int(result["example_id"])
    # Генерация эмбеддинга — в фоне, чтобы не держать HTTP-клиент.
    scheduled = False
    try:
        background.add_task(build_embedding_for_example, example_id)
        scheduled = True
    except Exception as exc:
        logger.warning("approve_classification_route: failed to schedule embedding: {}", exc)

    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={
            "example_id": example_id,
            "hs_code": str(result["hs_code"]),
            "description": str(result["description"]),
            "source": str(result["source"]),
            "created": bool(result["created"]),
            "embedding_scheduled": scheduled,
        },
    )


@router.post(
    "/approve/rebuild-embedding/{example_id}",
    summary="Принудительно пересчитать эмбеддинг для ранее утверждённого прецедента",
)
def rebuild_embedding_route(example_id: int) -> JSONResponse:
    """Синхронно пересчитывает эмбеддинг для уже существующего примера."""
    try:
        res = build_embedding_for_example(int(example_id))
    except Exception as exc:
        logger.exception("rebuild_embedding_route failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    http_status = 200 if res.get("status") == "ok" else 202
    return JSONResponse(content=res, status_code=http_status)
