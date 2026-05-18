from __future__ import annotations

import os
import time
from pathlib import Path


_DEFAULT_REVISION_FILE = (
    Path(__file__).resolve().parents[2] / "data" / "tnved_preview_cache_revision.txt"
)


def _revision_file_path() -> Path:
    configured = (os.getenv("TNVED_PREVIEW_CACHE_REVISION_FILE") or "").strip()
    if configured:
        return Path(configured).expanduser()
    return _DEFAULT_REVISION_FILE


def read_preview_cache_revision_marker() -> str:
    path = _revision_file_path()
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def bump_preview_cache_revision(reason: str = "") -> str:
    ts = int(time.time() * 1000)
    safe_reason = "".join(ch for ch in reason if ch.isalnum() or ch in "-_.:")[:64]
    marker = f"{ts}:{safe_reason}" if safe_reason else str(ts)
    path = _revision_file_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(marker, encoding="utf-8")
    except OSError:
        # Не блокируем импорт/синхронизацию из-за проблем с файловой меткой.
        return marker
    return marker
