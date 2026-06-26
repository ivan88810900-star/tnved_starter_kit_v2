"""Простые счётчики вызовов проверки разрешений (для мониторинга / алертов)."""
from __future__ import annotations

import threading
import time
from typing import Any, Dict

_lock = threading.Lock()
_stats: Dict[str, Any] = {
    "verify_requests_total": 0,
    "verify_documents_total": 0,
    "started_at": time.time(),
}


def record_verify_batch(doc_count: int) -> None:
    with _lock:
        _stats["verify_requests_total"] += 1
        _stats["verify_documents_total"] += max(0, int(doc_count))


def get_permits_metrics() -> Dict[str, Any]:
    with _lock:
        return {
            "verify_requests_total": int(_stats["verify_requests_total"]),
            "verify_documents_total": int(_stats["verify_documents_total"]),
            "uptime_seconds": round(time.time() - float(_stats["started_at"]), 1),
        }
