"""Optional TN VED embeddings with an always-available lexical fallback.

This is a legacy vector contour over ``tnved_entries``.  It is deliberately
kept behind default-OFF read/ingest flags until the product catalogue
(``tnved_commodities``) gets its own versioned vector index.
"""
from __future__ import annotations

import heapq
import math
import os
from typing import Any

import httpx
from sqlalchemy import or_

from ..db import SessionLocal
from ..models import TnvedEntry, TnvedEntryEmbedding
from ..models.tnved import Commodity


_TRUTHY = frozenset({"1", "true", "yes", "on"})


def _env_truthy(name: str) -> bool:
    return (os.getenv(name) or "").strip().lower() in _TRUTHY


def semantic_search_enabled() -> bool:
    """Whether paid request-time vector search is explicitly enabled."""
    return _env_truthy("TNVED_SEMANTIC_SEARCH_ENABLED")


def semantic_ingest_enabled() -> bool:
    """Whether the mutating/paid vector ingestion operation is enabled."""
    return _env_truthy("TNVED_SEMANTIC_INGEST_ENABLED")


def _openai_key() -> str:
    return (os.getenv("OPENAI_API_KEY") or "").strip()


def _embedding_model() -> str:
    return (os.getenv("OPENAI_EMBEDDING_MODEL") or "text-embedding-3-small").strip()


def embed_texts_openai(texts: list[str]) -> list[list[float]]:
    """Синхронный вызов OpenAI embeddings API (батч)."""
    key = _openai_key()
    if not key:
        raise RuntimeError("embedding_provider_not_configured")
    if not texts:
        return []
    model = _embedding_model()
    url = "https://api.openai.com/v1/embeddings"
    out_vectors: list[list[float]] = []
    # API допускает несколько inputs; режем по 64 строки
    batch_size = 64
    with httpx.Client(timeout=120.0) as client:
        for i in range(0, len(texts), batch_size):
            chunk = texts[i : i + batch_size]
            resp = client.post(
                url,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={"model": model, "input": chunk},
            )
            resp.raise_for_status()
            data = resp.json()
            items = sorted(data.get("data") or [], key=lambda x: x.get("index", 0))
            for it in items:
                emb = it.get("embedding")
                if isinstance(emb, list):
                    out_vectors.append([float(x) for x in emb])
                else:
                    out_vectors.append([])
    if len(out_vectors) != len(texts):
        raise RuntimeError("Размер ответа embeddings не совпадает с запросом")
    return out_vectors


def cosine_sim(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / (na * nb)


def ingest_tnved_embeddings_batch(
    *,
    limit: int = 200,
    offset: int = 0,
    only_missing: bool = True,
) -> dict[str, Any]:
    """
    Заполняет tnved_entry_embeddings для позиций ТН ВЭД.
    Текст для эмбеддинга: hs_code + title + description (обрезка).
    """
    if not semantic_ingest_enabled():
        raise RuntimeError(
            "semantic_ingest_disabled: set TNVED_SEMANTIC_INGEST_ENABLED=1 for an explicit batch run"
        )

    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    model = _embedding_model()

    with SessionLocal() as db:
        q = db.query(TnvedEntry)
        if only_missing:
            q = q.outerjoin(
                TnvedEntryEmbedding,
                TnvedEntryEmbedding.tnved_entry_id == TnvedEntry.id,
            ).filter(
                or_(
                    TnvedEntryEmbedding.id.is_(None),
                    TnvedEntryEmbedding.embedding.is_(None),
                    TnvedEntryEmbedding.embedding_model != model,
                )
            )
        q = q.order_by(TnvedEntry.id).offset(offset).limit(limit)
        entries = q.all()

    if not entries:
        return {"status": "OK", "processed": 0, "message": "Нет записей для обработки"}

    texts: list[str] = []
    for e in entries:
        parts = [e.hs_code or "", (e.title or "")[:1200], (e.description or "")[:800]]
        texts.append(" | ".join(p for p in parts if p).strip() or e.hs_code)

    vectors = embed_texts_openai(texts)
    processed = 0
    with SessionLocal() as db:
        for ent, vec in zip(entries, vectors):
            if not vec:
                continue
            row = db.query(TnvedEntryEmbedding).filter(TnvedEntryEmbedding.tnved_entry_id == ent.id).first()
            if row is None:
                row = TnvedEntryEmbedding(tnved_entry_id=ent.id)
                db.add(row)
            row.embedding_model = model[:128]
            row.embedding_dim = len(vec)
            row.embedding = vec
            processed += 1
        db.commit()

    return {"status": "OK", "processed": processed, "model": model, "offset": offset, "limit": limit}


def semantic_search_tnved(query: str, top_k: int = 15) -> list[dict[str, Any]]:
    """Return top-k legacy semantic matches without loading the full index at once."""
    top_k = max(1, min(top_k, 50))
    q = (query or "").strip()
    if len(q) < 2:
        return []
    if not semantic_search_enabled():
        raise RuntimeError(
            "semantic_search_disabled: set TNVED_SEMANTIC_SEARCH_ENABLED=1 to allow request-time embeddings"
        )

    qv = embed_texts_openai([q])[0]
    if not qv:
        return []

    # A bounded heap avoids retaining every ORM row/vector.  Filtering by the
    # configured model and dimension also prevents incomparable vectors from
    # silently entering the ranking after a model migration.
    best: list[tuple[float, int, dict[str, Any]]] = []
    model = _embedding_model()
    with SessionLocal() as db:
        rows = (
            db.query(TnvedEntryEmbedding, TnvedEntry)
            .join(TnvedEntry, TnvedEntry.id == TnvedEntryEmbedding.tnved_entry_id)
            .filter(
                TnvedEntryEmbedding.embedding.isnot(None),
                TnvedEntryEmbedding.embedding_model == model,
                TnvedEntryEmbedding.embedding_dim == len(qv),
            )
            .yield_per(256)
        )
        for emb_row, ent in rows:
            vec = emb_row.embedding
            if not isinstance(vec, list) or len(vec) != len(qv):
                continue
            score = cosine_sim(qv, [float(x) for x in vec])
            item = {
                "score": round(score, 6),
                "hs_code": ent.hs_code,
                "title": (ent.title or "")[:500],
                "level": ent.level,
                "embedding_model": emb_row.embedding_model,
            }
            candidate = (score, int(ent.id), item)
            if len(best) < top_k:
                heapq.heappush(best, candidate)
            elif candidate[:2] > best[0][:2]:
                heapq.heapreplace(best, candidate)

    return [row[2] for row in sorted(best, key=lambda item: (-item[0], item[1]))]


def embeddings_stats() -> dict[str, Any]:
    with SessionLocal() as db:
        total_e = db.query(TnvedEntryEmbedding).count()
        with_vec = db.query(TnvedEntryEmbedding).filter(TnvedEntryEmbedding.embedding.isnot(None)).count()
        compatible = (
            db.query(TnvedEntryEmbedding)
            .filter(
                TnvedEntryEmbedding.embedding.isnot(None),
                TnvedEntryEmbedding.embedding_model == _embedding_model(),
            )
            .count()
        )
        tnved = db.query(TnvedEntry).count()
        catalogue = db.query(Commodity).count()
    coverage_pct = round((compatible / tnved * 100.0), 2) if tnved else 0.0
    configured = bool(_openai_key())
    enabled = semantic_search_enabled()
    return {
        "source_table": "tnved_entries",
        "product_catalogue_table": "tnved_commodities",
        "tnved_entries": tnved,
        "product_catalogue_entries": catalogue,
        "embedding_rows": total_e,
        "with_vectors": with_vec,
        "compatible_vectors": compatible,
        "coverage_pct": coverage_pct,
        "provider": "openai",
        "provider_configured": configured,
        "openai_configured": configured,
        "search_enabled": enabled,
        "ingest_enabled": semantic_ingest_enabled(),
        "search_ready": bool(enabled and configured and tnved > 0 and compatible == tnved),
        "fallback": "/api/v1/tnved/search",
        "limitation": "legacy_vector_source_not_product_catalogue",
        "model": _embedding_model(),
    }
