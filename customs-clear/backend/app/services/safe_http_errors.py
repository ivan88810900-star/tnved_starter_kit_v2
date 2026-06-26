"""Безопасные сообщения об ошибках для HTTP-ответов (без утечки ключей и URL провайдеров)."""

from __future__ import annotations

import re

AI_SERVICE_UNAVAILABLE = "AI сервис временно недоступен"

_SENSITIVE_RE = re.compile(
    r"proxyapi|api\.proxyapi|sk-[A-Za-z0-9_-]{8,}|key=|api_key|apikey|"
    r"GEMINI_API_KEY|GOOGLE_API_KEY|ANTHROPIC_API_KEY|Authorization",
    re.IGNORECASE,
)


def contains_sensitive_error_text(text: str) -> bool:
    return bool(_SENSITIVE_RE.search(text or ""))


def safe_ai_unavailable_message(exc: BaseException | None = None) -> str:
    """Возвращает безопасное сообщение; никогда не пробрасывает URL/ключи провайдера."""
    if exc is not None and not contains_sensitive_error_text(str(exc)):
        # Нечувствительные ошибки (валидация и т.п.) можно вернуть как есть только вне AI-контекста.
        return str(exc)
    return AI_SERVICE_UNAVAILABLE


def safe_ai_error_note(exc: BaseException | None = None) -> str:
    """Короткая заметка для JSON-тела (classify / assistant), без секретов."""
    _ = exc
    return AI_SERVICE_UNAVAILABLE
