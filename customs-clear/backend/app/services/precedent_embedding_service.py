"""Вычисление эмбеддингов прецедентов: local sentence-transformers или OpenAI."""

from __future__ import annotations

import math
import os
from functools import lru_cache

from .embedding_service import embed_texts_openai


def _provider() -> str:
    return (os.getenv("PRECEDENT_EMBEDDING_PROVIDER") or "auto").strip().lower()


def _local_model_name() -> str:
    return (
        os.getenv("PRECEDENT_LOCAL_EMBEDDING_MODEL")
        or "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    ).strip()


@lru_cache(maxsize=1)
def _load_local_model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(_local_model_name())


def _embed_local(texts: list[str]) -> tuple[str, list[list[float]]]:
    if not texts:
        return _local_model_name(), []
    model = _load_local_model()
    vectors = model.encode(texts, normalize_embeddings=True).tolist()
    return _local_model_name(), [[float(x) for x in vec] for vec in vectors]


def _embed_openai(texts: list[str]) -> tuple[str, list[list[float]]]:
    model_name = (os.getenv("OPENAI_EMBEDDING_MODEL") or "text-embedding-3-small").strip()
    vectors = embed_texts_openai(texts)
    return model_name, vectors


def embed_precedent_texts(texts: list[str], *, provider: str | None = None) -> tuple[str, list[list[float]]]:
    """
    Эмбеддинги для прецедентов.

    provider:
    - ``auto`` (по умолчанию): local -> openai
    - ``local``: только sentence-transformers
    - ``openai``: только OpenAI embeddings API
    """
    p = (provider or _provider() or "auto").strip().lower()
    if not texts:
        return "", []

    if p == "local":
        return _embed_local(texts)
    if p == "openai":
        return _embed_openai(texts)

    # auto
    try:
        return _embed_local(texts)
    except Exception:
        return _embed_openai(texts)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))
