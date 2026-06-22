"""История и расширенная классификация (#147)."""

from __future__ import annotations

import json
import os
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_HISTORY_PATH = Path(os.getenv("CLASSIFY_HISTORY_PATH") or (_BACKEND_ROOT / "data" / "classify_history.jsonl"))
_MAX_HISTORY = 20


def _append_history(entry: dict[str, Any]) -> None:
    _HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _HISTORY_PATH.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(entry, ensure_ascii=False) + "\n")


def list_classification_history(*, limit: int = 20) -> list[dict[str, Any]]:
    if not _HISTORY_PATH.is_file():
        return []
    lines = _HISTORY_PATH.read_text(encoding="utf-8").splitlines()
    out: list[dict[str, Any]] = []
    for ln in reversed(lines[-limit:]):
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return out


def record_classification(
    *,
    query: str,
    results: list[dict[str, Any]],
    source: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    entry = {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "query": query[:2000],
        "source": source,
        "top_codes": [r.get("hs_code") or r.get("code") for r in results[:5]],
        "results_count": len(results),
        **(extra or {}),
    }
    _append_history(entry)
    return entry


async def classify_by_image_base64(image_b64: str, *, hint: str = "") -> dict[str, Any]:
    """Классификация по фото через Gemini multimodal (suggest_hs_code)."""
    import base64
    import tempfile
    from pathlib import Path

    from .invoice_analyzer import suggest_hs_code

    raw = image_b64.strip()
    if raw.startswith("data:"):
        raw = raw.split(",", 1)[-1]
    try:
        img_bytes = base64.b64decode(raw, validate=True)
    except Exception as exc:
        return {"status": "ERROR", "error": f"Invalid base64 image: {exc}", "results": []}

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        tmp.write(img_bytes)
        path = Path(tmp.name)

    try:
        desc = hint or "Товар на фото для классификации ТН ВЭД"
        result = suggest_hs_code(description=desc, image_path=str(path))
        results = result.get("results") or result.get("candidates") or []
        if isinstance(results, dict):
            results = results.get("items") or []
        record_classification(query=desc, results=results if isinstance(results, list) else [], source="image")
        return {"status": "OK", "results": (results if isinstance(results, list) else [])[:5], "classifier_source": "gemini_vision"}
    except Exception as exc:
        return {"status": "ERROR", "error": str(exc), "results": []}
    finally:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


async def classify_by_characteristics(payload: dict[str, Any]) -> dict[str, Any]:
    """Структурированная форма → текстовый запрос → классификация."""
    from .claude_service import classify_hs_code

    parts = []
    for key in ("material", "purpose", "principle", "function", "description"):
        val = str(payload.get(key) or "").strip()
        if val:
            parts.append(f"{key}: {val}")
    if not parts:
        return {"status": "ERROR", "error": "Заполните хотя бы одно поле характеристик", "results": []}
    query = "; ".join(parts)
    result = await classify_hs_code(query, use_journal_hints=True)
    results = result.get("results") or []
    record_classification(query=query, results=results, source="characteristics")
    return {**result, "query_built": query, "results": results[:5]}
