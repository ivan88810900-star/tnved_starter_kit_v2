"""RAG: .txt / .md / .pdf, токены + окна; опц. TF‑IDF rerank; опц. Chroma (rag_chroma)."""
from __future__ import annotations

import asyncio
import math
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

RAG_DOCS_DIR = os.getenv("RAG_DOCS_DIR", "").strip()
RAG_CHUNK_SIZE = int(os.getenv("RAG_CHUNK_SIZE", "480"))
RAG_CHUNK_STEP = int(os.getenv("RAG_CHUNK_STEP", "240"))
RAG_MAX_PER_FILE = int(os.getenv("RAG_MAX_PER_FILE", "2"))
RAG_USE_TFIDF = os.getenv("RAG_USE_TFIDF", "").lower() in ("1", "true", "yes")
RAG_TFIDF_POOL = int(os.getenv("RAG_TFIDF_POOL", "64"))
RAG_MAX_CHUNKS_PER_FILE = int(os.getenv("RAG_MAX_CHUNKS_PER_FILE", "48"))
LAW_RAG_POOL = int(os.getenv("LAW_RAG_POOL", "400"))
LAW_RAG_LAW_PORTAL = os.getenv("LAW_RAG_LAW_PORTAL", "1").lower() in ("1", "true", "yes")


def _query_tokens(query: str, min_len: int = 3) -> List[str]:
    q = (query or "").lower()
    raw = re.findall(r"[\w\d]+", q, flags=re.UNICODE)
    seen: Set[str] = set()
    out: List[str] = []
    for w in raw:
        if len(w) < min_len:
            continue
        if w not in seen:
            seen.add(w)
            out.append(w)
    return out[:24]


def _tokenize(s: str) -> List[str]:
    return re.findall(r"[\w\d]+", (s or "").lower(), flags=re.UNICODE)


def _read_pdf_text(path: Path) -> str:
    try:
        import fitz  # PyMuPDF

        doc = fitz.open(str(path))
        try:
            parts: List[str] = []
            for page in doc:
                parts.append(page.get_text() or "")
            return "\n".join(parts)
        finally:
            doc.close()
    except Exception:
        pass
    try:
        import pdfplumber

        with pdfplumber.open(str(path)) as pdf:
            return "\n".join((p.extract_text() or "") for p in pdf.pages)
    except Exception:
        return ""


def _read_document_text(path: Path) -> str:
    suf = path.suffix.lower()
    if suf in (".txt", ".md"):
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return ""
    if suf == ".pdf":
        return _read_pdf_text(path)
    return ""


def _iter_doc_paths(root: Path) -> List[Path]:
    exts = {".txt", ".md", ".pdf"}
    out: List[Path] = []
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in exts:
            out.append(p)
    return sorted(out)


def _score_chunk(low_text: str, tokens: List[str]) -> int:
    if not tokens:
        return 0
    return sum(low_text.count(t) for t in tokens)


def _chunks_from_text(text: str, name: str) -> List[Tuple[int, str, str]]:
    """Список (token_score, name, snippet) для скользящего окна — score посчитаем снаружи."""
    if not text.strip():
        return []
    size = max(RAG_CHUNK_SIZE, 200)
    step = max(RAG_CHUNK_STEP, 100)
    low_full = text.lower()
    out: List[Tuple[int, str, str]] = []
    pos = 0
    while pos < len(text):
        chunk = text[pos : pos + size]
        low_chunk = low_full[pos : pos + size]
        snippet = chunk.replace("\n", " ").strip()
        if len(snippet) > 520:
            snippet = snippet[:517] + "…"
        out.append((_score_chunk(low_chunk, []), name, snippet))  # score placeholder
        pos += step
    return out


def _fill_token_scores(chunks: List[Tuple[int, str, str]], tokens: List[str]) -> List[Tuple[int, str, str]]:
    res: List[Tuple[int, str, str]] = []
    for _, name, snip in chunks:
        sc = _score_chunk(snip.lower(), tokens)
        res.append((sc, name, snip))
    return res


def _tfidf_cosine_rerank(query: str, candidates: List[Tuple[int, str, str]], top_k: int) -> List[Tuple[str, str]]:
    """Возвращает [(name, snippet), ...] по косинусу TF‑IDF (запрос как один «документ»)."""
    if not candidates:
        return []
    q_terms = _tokenize(query)
    if not q_terms:
        return [(n, s) for _, n, s in candidates[:top_k]]

    doc_tokens = [_tokenize(s) for _, _, s in candidates]
    N = len(doc_tokens)
    df: Dict[str, int] = {}
    for toks in doc_tokens:
        for t in set(toks):
            df[t] = df.get(t, 0) + 1

    def idf(t: str) -> float:
        return math.log((N + 1) / (df.get(t, 0) + 1)) + 1.0

    def bow_vec(toks: List[str]) -> Dict[str, float]:
        c = Counter(toks)
        total = len(toks) or 1
        return {t: (cnt / total) * idf(t) for t, cnt in c.items()}

    qv = bow_vec(q_terms)

    def cosine(a: Dict[str, float], b: Dict[str, float]) -> float:
        keys = set(a) | set(b)
        dot = sum(a.get(k, 0) * b.get(k, 0) for k in keys)
        na = math.sqrt(sum(v * v for v in a.values()))
        nb = math.sqrt(sum(v * v for v in b.values()))
        if na * nb == 0:
            return 0.0
        return dot / (na * nb)

    scored: List[Tuple[float, str, str]] = []
    for toks, (_, name, snip) in zip(doc_tokens, candidates):
        scored.append((cosine(qv, bow_vec(toks)), name, snip))
    scored.sort(key=lambda x: -x[0])
    return [(n, s) for _, n, s in scored[:top_k]]


async def retrieve_snippets(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Фрагменты из каталога: токены + окна; при RAG_USE_TFIDF — переранжирование."""
    if not RAG_DOCS_DIR:
        return []
    root = Path(RAG_DOCS_DIR)
    if not root.is_dir():
        return []
    tokens = _query_tokens(query or "")
    pool_max = max(RAG_TFIDF_POOL, limit * 8, 32)

    all_scored: List[Tuple[int, str, str]] = []
    for path in _iter_doc_paths(root):
        text = _read_document_text(path)
        if not text.strip():
            continue
        raw_chunks = _chunks_from_text(text, path.name)
        cap = max(8, RAG_MAX_CHUNKS_PER_FILE)
        if len(raw_chunks) > cap:
            step = max(1, len(raw_chunks) // cap)
            raw_chunks = raw_chunks[::step][:cap]
        scored = _fill_token_scores(raw_chunks, tokens)
        for sc, name, snip in scored:
            if RAG_USE_TFIDF or sc > 0:
                all_scored.append((sc, name, snip))

    all_scored.sort(key=lambda x: (-x[0], x[1]))

    if RAG_USE_TFIDF and all_scored:
        pool = all_scored[:pool_max]
        if len(pool) < limit and all_scored:
            pool = all_scored[: max(pool_max, len(all_scored))]
        ranked = _tfidf_cosine_rerank(query or "", pool, limit)
        return [{"source": n, "snippet": s, "rag_tfidf": True} for n, s in ranked]

    per_file: Dict[str, int] = {}
    out: List[Dict[str, Any]] = []
    for sc, name, snippet in all_scored:
        if sc <= 0:
            continue
        if per_file.get(name, 0) >= RAG_MAX_PER_FILE:
            continue
        per_file[name] = per_file.get(name, 0) + 1
        out.append({"source": name, "snippet": snippet})
        if len(out) >= limit:
            break
    return out


def retrieve_law_portal_snippets_from_db(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    """
    Фрагменты из ``ingested_documents``, загруженных краулером law.tks.ru (все категории разделов).
    Ранжирование: пересечение токенов запроса с ``raw_text`` (последние записи в пуле).
    """
    if not LAW_RAG_LAW_PORTAL or not (query or "").strip():
        return []
    try:
        from ..db import SessionLocal
        from ..models import IngestedDocument
    except Exception:
        return []

    tokens = _query_tokens(query or "", min_len=3)
    if not tokens:
        return []

    with SessionLocal() as db:
        rows = (
            db.query(IngestedDocument)
            .order_by(IngestedDocument.updated_at.desc())
            .limit(max(LAW_RAG_POOL, 50))
            .all()
        )

    scored: List[Tuple[int, str, str, str]] = []
    for row in rows:
        pl = row.structured_payload if isinstance(row.structured_payload, dict) else {}
        if not pl.get("law_portal"):
            continue
        text = (row.raw_text or "")[:12000]
        low = text.lower()
        sc = sum(low.count(t) for t in tokens)
        if sc <= 0:
            continue
        cat = (getattr(row, "category", None) or str(pl.get("category") or "")).strip()
        title = str(pl.get("title") or row.original_filename or "")[:160]
        snip = text.replace("\n", " ").strip()[:520]
        source = f"law_portal/{cat}/{title}".replace("//", "/")
        scored.append((sc, source, snip, cat))

    scored.sort(key=lambda x: -x[0])
    out: List[Dict[str, Any]] = []
    for sc, source, snip, cat in scored[:limit]:
        out.append(
            {
                "source": source[:220],
                "snippet": snip,
                "law_portal": True,
                "law_category": cat,
            }
        )
    return out


async def rag_context_for_copilot(description: str) -> Dict[str, Any]:
    """Контекст для конвейера: law.tks.ru (БД) + Chroma + файловый RAG."""
    from .rag_chroma import retrieve_chroma_snippets

    q = (description or "").strip()
    law_snips = await asyncio.to_thread(retrieve_law_portal_snippets_from_db, q, 5)
    file_snips = await retrieve_snippets(q, limit=4)
    chroma_snips = await retrieve_chroma_snippets(q, limit=3)

    merged: List[Dict[str, Any]] = []
    seen_snip: Set[str] = set()
    for item in law_snips + chroma_snips + file_snips:
        key = (item.get("source"), (item.get("snippet") or "")[:80])
        if key in seen_snip:
            continue
        seen_snip.add(key)
        merged.append(item)
        if len(merged) >= 8:
            break

    return {
        "rag_snippets": merged[:6],
        "rag_enabled": bool(merged),
        "rag_chroma_used": bool(chroma_snips),
        "rag_law_portal_used": bool(law_snips),
    }
