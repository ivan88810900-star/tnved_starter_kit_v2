#!/usr/bin/env python3
"""
Индексация RAG_DOCS_DIR в ChromaDB (векторный поиск в copilot).

  export RAG_DOCS_DIR=./docs/rag_sources
  export RAG_CHROMA_PATH=./data/chroma_rag
  pip install chromadb
  cd customs-clear/backend && PYTHONPATH=. python3 scripts/ingest_rag_chroma.py

Пересоздаёт коллекцию RAG_CHROMA_COLLECTION (по умолчанию customs_clear_rag).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> None:
    docs = os.getenv("RAG_DOCS_DIR", "").strip()
    chroma_path = os.getenv("RAG_CHROMA_PATH", "").strip()
    coll_name = os.getenv("RAG_CHROMA_COLLECTION", "customs_clear_rag")

    if not docs or not chroma_path:
        print("Задайте RAG_DOCS_DIR и RAG_CHROMA_PATH", file=sys.stderr)
        sys.exit(1)

    try:
        import chromadb
    except ImportError:
        print("Установите chromadb: pip install chromadb", file=sys.stderr)
        sys.exit(1)

    backend_dir = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(backend_dir))

    from app.services.rag_service import (  # noqa: E402
        RAG_CHUNK_SIZE,
        RAG_CHUNK_STEP,
        _chunks_from_text,
        _iter_doc_paths,
        _read_document_text,
    )

    root = Path(docs)
    if not root.is_dir():
        print(f"Нет каталога RAG_DOCS_DIR: {root}", file=sys.stderr)
        sys.exit(1)

    client = chromadb.PersistentClient(path=chroma_path)
    try:
        client.delete_collection(coll_name)
    except Exception:
        pass
    coll = client.create_collection(
        name=coll_name,
        metadata={"ingest": "ingest_rag_chroma", "docs_root": str(root.resolve())},
    )

    ids: list[str] = []
    documents: list[str] = []
    metadatas: list[dict] = []
    n = 0

    for path in _iter_doc_paths(root):
        text = _read_document_text(path)
        if not text.strip():
            continue
        raw = _chunks_from_text(text, path.name)
        cap = 64
        if len(raw) > cap:
            step = max(1, len(raw) // cap)
            raw = raw[::step][:cap]
        for i, (_, name, snip) in enumerate(raw):
            if not snip.strip():
                continue
            uid = f"{path.name}#{i}"
            ids.append(uid)
            documents.append(snip)
            metadatas.append({"source": name, "path": str(path.relative_to(root))})
            n += 1

    batch = 80
    for i in range(0, len(ids), batch):
        coll.add(
            ids=ids[i : i + batch],
            documents=documents[i : i + batch],
            metadatas=metadatas[i : i + batch],
        )

    print(f"Проиндексировано чанков: {n}, коллекция {coll_name!r}, путь {chroma_path!r}")


if __name__ == "__main__":
    main()
