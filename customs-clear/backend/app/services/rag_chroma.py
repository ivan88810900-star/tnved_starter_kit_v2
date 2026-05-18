"""Опциональный векторный поиск через ChromaDB (pip install chromadb). Путь хранилища: RAG_CHROMA_PATH."""
from __future__ import annotations

import asyncio
import os
from functools import partial
from typing import Any, Dict, List

from loguru import logger

_CHROMA_PATH = os.getenv("RAG_CHROMA_PATH", "").strip()
_COLLECTION = os.getenv("RAG_CHROMA_COLLECTION", "customs_clear_rag")


def chroma_available() -> bool:
    return bool(_CHROMA_PATH)


def _query_sync(query: str, limit: int) -> List[Dict[str, Any]]:
    try:
        import chromadb
    except ImportError:
        return []
    try:
        client = chromadb.PersistentClient(path=_CHROMA_PATH)
        coll = client.get_collection(name=_COLLECTION)
        if coll.count() == 0:
            return []
        res = coll.query(query_texts=[query], n_results=min(limit, max(1, coll.count())))
        docs = (res.get("documents") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        dists = (res.get("distances") or [[]])[0] if res.get("distances") else []
        out: List[Dict[str, Any]] = []
        for i, text in enumerate(docs or []):
            if not text:
                continue
            meta = metas[i] if i < len(metas) and isinstance(metas[i], dict) else {}
            src = str(meta.get("source") or meta.get("file") or "chroma")
            snippet = text.replace("\n", " ").strip()
            if len(snippet) > 520:
                snippet = snippet[:517] + "…"
            item: Dict[str, Any] = {"source": src, "snippet": snippet, "rag_chroma": True}
            if dists and i < len(dists):
                item["distance"] = float(dists[i])
            out.append(item)
        return out
    except Exception as e:
        logger.debug(f"rag_chroma query: {e}")
        return []


async def retrieve_chroma_snippets(query: str, limit: int = 4) -> List[Dict[str, Any]]:
    if not chroma_available() or not (query or "").strip():
        return []
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(_query_sync, query.strip(), limit))
