"""Эмбеддинги ТН ВЭД (OpenAI) и семантический поиск по JSON-векторам в SQLite."""
from __future__ import annotations

import math
import os
from typing import Any, Optional

import httpx
from loguru import logger

from ..db import SessionLocal
from ..models import TnvedEntry, TnvedEntryEmbedding


def _openai_key() -> str:
    return (os.getenv("OPENAI_API_KEY") or "").strip()


def _embedding_model() -> str:
    return (os.getenv("OPENAI_EMBEDDING_MODEL") or "text-embedding-3-small").strip()


def embed_texts_openai(texts: list[str]) -> list[list[float]]:
    """Синхронный вызов OpenAI embeddings API (батч)."""
    key = _openai_key()
    if not key:
        raise RuntimeError("OPENAI_API_KEY не задан")
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
                # Validate provider JSON before conversion: bools and numeric
                # strings must never become apparently valid coordinates.
                out_vectors.append(_finite_vector(emb) or [])
    if len(out_vectors) != len(texts):
        raise RuntimeError("Размер ответа embeddings не совпадает с запросом")
    return out_vectors


def _cosine_score(a: list[float], b: list[float]) -> Optional[float]:
    if not a or not b or len(a) != len(b):
        return None
    if not all(math.isfinite(x) for x in a) or not all(math.isfinite(x) for x in b):
        return None
    # hypot avoids the intermediate x*x overflow of the naive norm. A norm
    # that still overflows is not comparable and must not become a score of 0.
    na = math.hypot(*a)
    nb = math.hypot(*b)
    if not all(math.isfinite(x) and x > 0 for x in (na, nb)):
        return None
    score = math.fsum((x / na) * (y / nb) for x, y in zip(a, b))
    if not math.isfinite(score):
        return None
    # Floating point round-off can exceed the mathematical range slightly.
    return max(-1.0, min(1.0, score))


def cosine_sim(a: list[float], b: list[float]) -> float:
    """Compatibility wrapper; semantic ranking uses the nullable score."""
    score = _cosine_score(a, b)
    return score if score is not None else 0.0


def _finite_vector(value: Any) -> Optional[list[float]]:
    """Return strict JSON numeric coordinates, or ``None`` for unsafe input."""
    if not isinstance(value, list) or not value:
        return None
    # JSON booleans are Python ints and numeric strings are float-coercible, but
    # neither is an embedding coordinate. Accept only plain JSON number types.
    if not all(type(item) in (int, float) for item in value):
        return None
    try:
        vector = [float(item) for item in value]
    except OverflowError:
        return None
    if not all(math.isfinite(item) for item in vector):
        return None
    return vector


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
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    model = _embedding_model()

    with SessionLocal() as db:
        q = db.query(TnvedEntry).order_by(TnvedEntry.id).offset(offset).limit(limit)
        entries = q.all()
        if only_missing:
            existing_ids = {
                int(r[0])
                for r in db.query(TnvedEntryEmbedding.tnved_entry_id)
                .filter(TnvedEntryEmbedding.embedding.isnot(None))
                .all()
            }
            entries = [e for e in entries if e.id not in existing_ids]

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
    """Поиск по косинусной близости (все строки эмбеддингов в памяти — для умеренных объёмов)."""
    top_k = max(1, min(top_k, 50))
    q = (query or "").strip()
    if len(q) < 2:
        return []

    query_vectors = embed_texts_openai([q])
    if len(query_vectors) != 1:
        return []
    qv = _finite_vector(query_vectors[0])
    if not qv or _cosine_score(qv, qv) is None:
        return []

    query_model = _embedding_model()

    with SessionLocal() as db:
        rows = (
            db.query(TnvedEntryEmbedding, TnvedEntry)
            .join(TnvedEntry, TnvedEntry.id == TnvedEntryEmbedding.tnved_entry_id)
            .filter(
                TnvedEntryEmbedding.embedding.isnot(None),
                TnvedEntryEmbedding.embedding_model == query_model,
                TnvedEntryEmbedding.embedding_dim == len(qv),
            )
            .all()
        )

    scored: list[tuple[float, Any, Any]] = []
    for emb_row, ent in rows:
        # Repeat compatibility checks after the SQL filter so malformed rows and
        # alternate storage backends can never enter a cross-model comparison.
        if emb_row.embedding_model != query_model or emb_row.embedding_dim != len(qv):
            continue
        vec = _finite_vector(emb_row.embedding)
        if vec is None or len(vec) != len(qv):
            continue
        s = _cosine_score(qv, vec)
        if s is None:
            continue
        scored.append((s, ent, emb_row))

    scored.sort(key=lambda x: -x[0])
    out: list[dict[str, Any]] = []
    for s, ent, emb_row in scored[:top_k]:
        out.append(
            {
                "score": round(s, 6),
                "hs_code": ent.hs_code,
                "title": (ent.title or "")[:500],
                "level": ent.level,
                "embedding_model": emb_row.embedding_model,
            }
        )
    return out


def embeddings_stats() -> dict[str, Any]:
    with SessionLocal() as db:
        total_e = db.query(TnvedEntryEmbedding).count()
        with_vec = db.query(TnvedEntryEmbedding).filter(TnvedEntryEmbedding.embedding.isnot(None)).count()
        tnved = db.query(TnvedEntry).count()
    return {
        "tnved_entries": tnved,
        "embedding_rows": total_e,
        "with_vectors": with_vec,
        "openai_configured": bool(_openai_key()),
        "model": _embedding_model(),
    }
