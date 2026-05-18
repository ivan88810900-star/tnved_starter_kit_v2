"""Gemini embeddings (text-embedding-004) для векторного поиска."""

from __future__ import annotations

import os
import time
from urllib.parse import urlparse
from typing import Any

import httpx
from loguru import logger

from .gemini_genai_configure import gemini_batch_embed_content_rest_url, gemini_embed_content_rest_url


def _gemini_key() -> str:
    return (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()


def _embedding_model() -> str:
    return (os.getenv("GEMINI_EMBEDDING_MODEL") or "text-embedding-004").strip()


def _normalize_model_for_request(model: str) -> str:
    m = (model or "").strip()
    if not m:
        m = "text-embedding-004"
    if m.startswith("models/"):
        return m
    return f"models/{m}"


def _proxy_openai_embeddings_url() -> str:
    """
    Возвращает OpenAI-compatible endpoint для embedding через proxyapi (если доступен).
    """
    raw = (os.getenv("GEMINI_BASE_URL") or "").strip()
    if not raw:
        return ""
    if not raw.lower().startswith(("http://", "https://")):
        raw = f"https://{raw}"
    parsed = urlparse(raw)
    host = (parsed.netloc or "").strip().lower()
    if "proxyapi.ru" not in host:
        return ""
    return f"{parsed.scheme or 'https'}://{parsed.netloc}/openai/v1/embeddings"


def _proxy_openai_embedding_model() -> str:
    return (os.getenv("OPENAI_EMBEDDING_MODEL") or os.getenv("PROXY_EMBEDDING_MODEL") or "text-embedding-3-small").strip()


def _embed_chunk_via_proxy_openai(
    client: httpx.Client,
    *,
    texts: list[str],
    api_key: str,
    timeout_sec: float,
    retries: int,
) -> tuple[str, list[list[float]]]:
    url = _proxy_openai_embeddings_url()
    if not url:
        raise RuntimeError("Proxy OpenAI embeddings endpoint is not configured")

    payload = {
        "model": _proxy_openai_embedding_model(),
        "input": [(str(t or "").strip() or " ")[:16000] for t in texts],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    data: dict[str, Any] | None = None
    for attempt in range(1, max(1, retries) + 1):
        try:
            r = client.post(url, json=payload, headers=headers, timeout=timeout_sec)
            if r.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(min(2.0 * attempt, 8.0))
                continue
            r.raise_for_status()
            data = r.json()
            break
        except Exception:
            if attempt >= retries:
                raise
            time.sleep(min(2.0 * attempt, 8.0))

    rows = (data or {}).get("data") or []
    if not isinstance(rows, list):
        raise RuntimeError("Proxy OpenAI embeddings: unexpected response shape")

    rows_sorted = sorted(
        [row for row in rows if isinstance(row, dict)],
        key=lambda row: int(row.get("index", 0)),
    )
    vectors: list[list[float]] = []
    for row in rows_sorted:
        emb = row.get("embedding")
        if isinstance(emb, list) and emb:
            vectors.append([float(x) for x in emb])
        else:
            vectors.append([])
    if len(vectors) != len(texts):
        raise RuntimeError("Proxy OpenAI embeddings: response size mismatch")
    return payload["model"], vectors


def embed_texts_gemini(
    texts: list[str],
    *,
    batch_size: int = 16,
    timeout_sec: float = 120.0,
    retries: int = 3,
) -> tuple[str, list[list[float]]]:
    """
    Возвращает (model_name, vectors) для списка текстов.
    Использует Gemini REST batchEmbedContents.
    """
    if not texts:
        return _embedding_model(), []
    key = _gemini_key()
    if not key:
        raise RuntimeError("Не задан GEMINI_API_KEY или GOOGLE_API_KEY")

    model_name = _embedding_model()
    model_ref = _normalize_model_for_request(model_name)
    batch_url = gemini_batch_embed_content_rest_url(model_name)
    single_url = gemini_embed_content_rest_url(model_name)

    out: list[list[float]] = []
    chunk_size = max(1, min(64, int(batch_size)))

    with httpx.Client(timeout=timeout_sec) as client:
        for i in range(0, len(texts), chunk_size):
            chunk = texts[i : i + chunk_size]
            requests = [
                {
                    "model": model_ref,
                    "content": {"parts": [{"text": (str(t or "").strip() or " ")[:16000]}]},
                }
                for t in chunk
            ]
            payload = {"requests": requests}

            data: dict[str, Any] | None = None
            fallback_single = False
            for attempt in range(1, max(1, retries) + 1):
                try:
                    r = client.post(
                        batch_url,
                        params={"key": key},
                        json=payload,
                        headers={"Content-Type": "application/json"},
                    )
                    if r.status_code == 404:
                        # Некоторые прокси поддерживают только :embedContent.
                        fallback_single = True
                        break
                    if r.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                        time.sleep(min(2.0 * attempt, 8.0))
                        continue
                    r.raise_for_status()
                    data = r.json()
                    break
                except Exception:
                    if attempt >= retries:
                        raise
                    time.sleep(min(2.0 * attempt, 8.0))

            if fallback_single:
                logger.warning("Gemini batch embeddings unavailable at {}, fallback to single embedContent", batch_url)
                openai_proxy_url = _proxy_openai_embeddings_url()
                if openai_proxy_url:
                    logger.warning(
                        "Gemini embedContent unavailable via proxy; fallback to OpenAI-compatible endpoint {}",
                        openai_proxy_url,
                    )
                    proxy_model, proxy_vectors = _embed_chunk_via_proxy_openai(
                        client,
                        texts=chunk,
                        api_key=key,
                        timeout_sec=timeout_sec,
                        retries=retries,
                    )
                    out.extend(proxy_vectors)
                    # При mixed provider укажем фактическую модель источника.
                    model_name = proxy_model
                    continue
                for txt in chunk:
                    body = {
                        "model": model_ref,
                        "content": {"parts": [{"text": (str(txt or "").strip() or " ")[:16000]}]},
                    }
                    resp_data: dict[str, Any] | None = None
                    for attempt in range(1, max(1, retries) + 1):
                        try:
                            r = client.post(
                                single_url,
                                params={"key": key},
                                json=body,
                                headers={"Content-Type": "application/json"},
                            )
                            if r.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                                time.sleep(min(2.0 * attempt, 8.0))
                                continue
                            r.raise_for_status()
                            resp_data = r.json()
                            break
                        except Exception:
                            if attempt >= retries:
                                raise
                            time.sleep(min(2.0 * attempt, 8.0))
                    emb = (resp_data or {}).get("embedding") or {}
                    values = emb.get("values") if isinstance(emb, dict) else None
                    if isinstance(values, list) and values:
                        out.append([float(x) for x in values])
                    else:
                        out.append([])
                continue

            embeddings = (data or {}).get("embeddings") or []
            if not isinstance(embeddings, list) or len(embeddings) != len(chunk):
                raise RuntimeError("Gemini embeddings: размер ответа не совпадает с запросом")

            for emb in embeddings:
                values = (emb or {}).get("values") if isinstance(emb, dict) else None
                if isinstance(values, list) and values:
                    out.append([float(x) for x in values])
                else:
                    out.append([])

    return model_name, out
