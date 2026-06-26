"""Сервис подтверждения классификации: feedback loop для RAG.

Идея: пользователь / декларант утверждает связку ``(описание товара) -> (10-знач. код ТН ВЭД)``.
Мы сохраняем её в ``declaration_examples`` с ``source='user_approved'`` и фоновой задачей
строим эмбеддинг + synthetic-карточку ``tnved_entries`` + ``tnved_entry_embeddings``
в формате, совместимом с :mod:`app.services.rag_retriever` (``precedent_embeddings_v1``).

Тогда в следующем инвойсе:
- :func:`rag_retriever.find_exact_precedent_matches` найдёт запись через LIKE+fuzzy
  (приоритет ``source='user_approved'`` через ``_USER_APPROVED_SOURCES``);
- :func:`rag_retriever.get_semantic_legal_context` / ``_vector_precedent_matches`` найдут
  её через семантический поиск по эмбеддингам.
"""

from __future__ import annotations

import re
from typing import Any

from loguru import logger
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db import SessionLocal
from ..models.core import DeclarationExample, TnvedEntry, TnvedEntryEmbedding

USER_APPROVED_SOURCE = "user_approved"
PRECEDENT_SOURCE_REVISION = "precedent_embeddings_v1"


def _norm_hs10(raw: str) -> str:
    return re.sub(r"\D", "", str(raw or ""))[:10]


def _synthetic_hs_code_for_example(example_id: int) -> str:
    """Синтетический hs_code для ``tnved_entries`` — совместим с generate_embeddings.py (D + 11 цифр)."""
    return f"D{int(example_id):011d}"[:12]


def _build_embedding_text(description: str, hs_code: str, user_note: str) -> str:
    """Текст для векторизации: то же пространство, что и в :mod:`scripts.generate_embeddings`."""
    parts: list[str] = []
    hs = _norm_hs10(hs_code)
    if hs:
        parts.append(f"HS: {hs}")
    parts.append(f"Источник: {USER_APPROVED_SOURCE}")
    if description:
        parts.append(str(description).strip())
    if user_note:
        parts.append(f"Примечание: {str(user_note).strip()}")
    return " | ".join(p for p in parts if p)[:16000]


def approve_classification(
    db: Session,
    *,
    description: str,
    approved_hs_code: str,
    user_note: str = "",
    user_id: str | None = None,
) -> dict[str, Any]:
    """Сохранить подтверждённую классификацию в ``declaration_examples`` (source='user_approved').

    Возвращает ``{"example_id", "hs_code", "description", "source", "created": bool}``.
    """
    clean_desc = (description or "").strip()
    hs = _norm_hs10(approved_hs_code)
    if not clean_desc:
        raise ValueError("description must be non-empty")
    if len(hs) != 10:
        raise ValueError("approved_hs_code must contain exactly 10 digits")

    snippet = clean_desc[:72]
    # Точный дубликат (description + hs_code) — обновляем user_note, не плодим мусор.
    existing = (
        db.query(DeclarationExample)
        .filter(DeclarationExample.source == USER_APPROVED_SOURCE)
        .filter(DeclarationExample.hs_code == hs)
        .filter(func.substr(DeclarationExample.description, 1, len(snippet)) == snippet)
        .order_by(DeclarationExample.id.desc())
        .first()
    )
    if existing is not None:
        if user_note:
            suffix = f"\n[note/{(user_id or 'anon')}] {user_note}".strip()
            if suffix not in (existing.description or ""):
                existing.description = (existing.description or "") + "\n" + suffix
        db.flush()
        logger.info(
            "approve_classification: updated user-approved precedent id={} hs={}",
            existing.id,
            hs,
        )
        return {
            "example_id": int(existing.id),
            "hs_code": hs,
            "description": str(existing.description or "")[:500],
            "source": existing.source,
            "created": False,
        }

    note_tail = f"\n[note/{(user_id or 'anon')}] {user_note.strip()}" if user_note and user_note.strip() else ""
    body = (clean_desc + note_tail)[:8000]
    row = DeclarationExample(hs_code=hs, description=body, source=USER_APPROVED_SOURCE)
    db.add(row)
    db.flush()
    logger.info(
        "approve_classification: stored new user-approved precedent id={} hs={} desc={!r}",
        row.id,
        hs,
        clean_desc[:120],
    )
    return {
        "example_id": int(row.id),
        "hs_code": hs,
        "description": body[:500],
        "source": USER_APPROVED_SOURCE,
        "created": True,
    }


def _embed_text(text: str) -> tuple[str, list[float]]:
    """Получить эмбеддинг для текста (Gemini REST с fallback)."""
    try:
        from .gemini_embedding_service import embed_texts_gemini

        model_name, vectors = embed_texts_gemini([text], batch_size=1, retries=3)
        return model_name, (vectors[0] if vectors else [])
    except Exception as e:
        logger.warning("_embed_text: gemini failed ({}), trying precedent_embedding_service fallback", e)
    try:
        from .precedent_embedding_service import embed_precedent_texts

        model_name, vectors = embed_precedent_texts([text])
        return model_name, (vectors[0] if vectors else [])
    except Exception as e:
        logger.warning("_embed_text: precedent embedding fallback failed: {}", e)
        return "", []


def _upsert_synthetic_entry_and_vector(
    db: Session,
    *,
    example_id: int,
    hs_code: str,
    description: str,
    model_name: str,
    vector: list[float],
) -> int:
    """Создать или обновить synthetic tnved_entries + tnved_entry_embeddings для RAG."""
    hs10 = _norm_hs10(hs_code)
    synth_hs = _synthetic_hs_code_for_example(example_id)
    title = f"[USER_APPROVED] HS {hs10 or '—'} | id={example_id}"[:1024]
    desc_blob = (
        f"SOURCE_TABLE=declaration_examples; SOURCE_ID={example_id}; "
        f"REAL_HS={hs10 or '—'}; TEXT={description}"
    )[:16000]

    entry = db.query(TnvedEntry).filter(TnvedEntry.hs_code == synth_hs).first()
    if entry is None:
        entry = TnvedEntry(
            hs_code=synth_hs,
            parent_hs=hs10[:6] if len(hs10) >= 6 else "",
            level=10,
            title=title,
            description=desc_blob,
            chapter=hs10[:2] if len(hs10) >= 2 else "",
            source_url="",
            source_revision=PRECEDENT_SOURCE_REVISION,
        )
        db.add(entry)
        db.flush()
    else:
        entry.parent_hs = hs10[:6] if len(hs10) >= 6 else (entry.parent_hs or "")
        entry.level = 10
        entry.title = title or entry.title
        entry.description = desc_blob
        entry.chapter = hs10[:2] if len(hs10) >= 2 else (entry.chapter or "")
        entry.source_revision = PRECEDENT_SOURCE_REVISION
        db.flush()

    emb = db.query(TnvedEntryEmbedding).filter(TnvedEntryEmbedding.tnved_entry_id == entry.id).first()
    if emb is None:
        emb = TnvedEntryEmbedding(tnved_entry_id=int(entry.id))
        db.add(emb)
    emb.embedding_model = (model_name or "unknown")[:128]
    emb.embedding_dim = int(len(vector))
    emb.embedding = list(vector)
    db.flush()
    return int(entry.id)


def build_embedding_for_example(example_id: int) -> dict[str, Any]:
    """Фоновая задача: считает эмбеддинг для ``declaration_examples`` и записывает в RAG-индекс.

    Запускается через :class:`fastapi.BackgroundTasks` из эндпоинта, чтобы HTTP-ответ не ждал Gemini.
    """
    with SessionLocal() as db:
        row = db.query(DeclarationExample).filter(DeclarationExample.id == int(example_id)).first()
        if row is None:
            logger.warning("build_embedding_for_example: example_id={} not found", example_id)
            return {"example_id": example_id, "status": "not_found"}
        text = _build_embedding_text(row.description or "", row.hs_code or "", "")
        model_name, vec = _embed_text(text)
        if not vec:
            logger.warning(
                "build_embedding_for_example: empty embedding for example_id={} (model={})",
                example_id,
                model_name,
            )
            return {"example_id": example_id, "status": "embedding_failed", "model": model_name}
        try:
            entry_id = _upsert_synthetic_entry_and_vector(
                db,
                example_id=int(row.id),
                hs_code=str(row.hs_code or ""),
                description=str(row.description or ""),
                model_name=model_name,
                vector=vec,
            )
            db.commit()
        except Exception as e:
            db.rollback()
            logger.exception("build_embedding_for_example: upsert failed: {}", e)
            return {"example_id": example_id, "status": "db_error", "error": str(e)[:200]}
        logger.info(
            "build_embedding_for_example: OK example_id={} entry_id={} model={} dim={}",
            example_id,
            entry_id,
            model_name,
            len(vec),
        )
        return {
            "example_id": example_id,
            "status": "ok",
            "tnved_entry_id": entry_id,
            "model": model_name,
            "dim": len(vec),
        }
