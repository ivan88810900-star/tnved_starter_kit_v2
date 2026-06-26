"""Простой аудит событий в JSONL (включается переменной окружения)."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger

_ENABLED = os.getenv("AUDIT_LOG_ENABLED", "").lower() in ("1", "true", "yes")
_PATH = Path(os.getenv("AUDIT_LOG_PATH", "data/audit_events.jsonl"))


def request_audit_meta(request: Optional[Any] = None) -> Dict[str, Any]:
    """Опциональные заголовки для корреляции в JSONL: X-Client-Id, X-Audit-Subject."""
    if request is None:
        return {}
    try:
        headers = getattr(request, "headers", None)
        if headers is None:
            return {}
        cid = (headers.get("x-client-id") or headers.get("X-Client-Id") or "").strip()
        sub = (headers.get("x-audit-subject") or headers.get("X-Audit-Subject") or "").strip()
        out: Dict[str, Any] = {}
        if cid:
            out["client_id"] = cid[:128]
        if sub:
            out["audit_subject"] = sub[:512]
        return out
    except Exception:
        return {}


def append_audit(event: Dict[str, Any]) -> None:
    if not _ENABLED:
        return
    try:
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        row = dict(event)
        row["ts"] = datetime.now(timezone.utc).isoformat()
        with open(_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    except Exception as e:
        logger.warning(f"audit log: {e}")
