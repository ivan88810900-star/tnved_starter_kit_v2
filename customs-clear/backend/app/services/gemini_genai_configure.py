"""Единая настройка google-generativeai: ключ и опционально GEMINI_BASE_URL (API-прокси)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from google.api_core.client_options import ClientOptions
from loguru import logger

_BACKEND_ROOT = Path(__file__).resolve().parents[2]

# Официальный REST-префикс до сегмента /models/…:generateContent
_DEFAULT_GENERATE_CONTENT_PREFIX = "https://generativelanguage.googleapis.com/v1beta"


def normalize_gemini_api_endpoint_for_sdk(raw: str) -> str:
    """
    Значение для ClientOptions.api_endpoint (google-generativeai, REST): host[:port] и опционально
    префикс пути (например api.proxyapi.ru/google). Схема и query убираются; ведущий/хвостовой / — нет.
    """
    s = (raw or "").strip()
    if not s:
        return ""
    low = s.lower()
    if low.startswith("https://"):
        s = s[8:]
    elif low.startswith("http://"):
        s = s[7:]
    s = s.split("?", 1)[0].strip().strip("/")
    return s


def _load_gemini_env() -> None:
    load_dotenv(_BACKEND_ROOT / ".env")
    load_dotenv()


def resolved_gemini_model_name() -> str:
    """Имя модели для Gemini API; по умолчанию gemini-1.5-flash (часто доступнее через прокси)."""
    _load_gemini_env()
    return (os.getenv("GEMINI_MODEL_NAME") or "gemini-1.5-flash").strip()


def configure_google_generativeai(genai: Any, *, api_key: str) -> None:
    """
    При GEMINI_BASE_URL: только REST (не gRPC) и кастомный api_endpoint — трафик через прокси.
    Без переменной — стандартный клиент Google (только api_key).
    """
    _load_gemini_env()
    base_url = normalize_gemini_api_endpoint_for_sdk(os.getenv("GEMINI_BASE_URL") or "")
    if base_url:
        client_options = ClientOptions(api_endpoint=base_url)
        # transport="rest" обязателен: иначе SDK часто уходит в gRPC на generativelanguage.googleapis.com.
        genai.configure(
            api_key=api_key,
            transport="rest",
            client_options=client_options,
        )
        logger.debug("google-generativeai: transport=rest, api_endpoint={}", base_url)
    else:
        genai.configure(api_key=api_key)


def gemini_generate_content_rest_url(model: str) -> str:
    """
    URL :generateContent для сырых HTTP-вызовов.
    Если GEMINI_BASE_URL начинается с http(s), он используется как префикс (как правило, …/v1beta).
    Иначе — официальный хост Google (поведение как раньше без прокси).
    """
    _load_gemini_env()
    m = (model or "").strip()
    raw = (os.getenv("GEMINI_BASE_URL") or "").strip()
    if not raw:
        return f"{_DEFAULT_GENERATE_CONTENT_PREFIX}/models/{m}:generateContent"
    # Полный URL в .env (редко): используем как префикс REST.
    if raw.lower().startswith(("http://", "https://")):
        return f"{raw.rstrip('/')}/models/{m}:generateContent"
    # Только домен (как для SDK): стандартный путь v1beta для сырых HTTP-вызовов.
    host = normalize_gemini_api_endpoint_for_sdk(raw)
    if host:
        return f"https://{host}/v1beta/models/{m}:generateContent"
    return f"{_DEFAULT_GENERATE_CONTENT_PREFIX}/models/{m}:generateContent"


def gemini_batch_embed_content_rest_url(model: str) -> str:
    """
    URL :batchEmbedContents для Gemini embeddings.
    Учитывает GEMINI_BASE_URL аналогично :func:`gemini_generate_content_rest_url`.
    """
    _load_gemini_env()
    m = (model or "").strip()
    raw = (os.getenv("GEMINI_BASE_URL") or "").strip()
    if not raw:
        return f"{_DEFAULT_GENERATE_CONTENT_PREFIX}/models/{m}:batchEmbedContents"
    if raw.lower().startswith(("http://", "https://")):
        return f"{raw.rstrip('/')}/models/{m}:batchEmbedContents"
    host = normalize_gemini_api_endpoint_for_sdk(raw)
    if host:
        return f"https://{host}/v1beta/models/{m}:batchEmbedContents"
    return f"{_DEFAULT_GENERATE_CONTENT_PREFIX}/models/{m}:batchEmbedContents"


def gemini_embed_content_rest_url(model: str) -> str:
    """
    URL :embedContent для одиночного запроса embedding.
    Нужен как fallback, если proxy/endpoint не поддерживает :batchEmbedContents.
    """
    _load_gemini_env()
    m = (model or "").strip()
    raw = (os.getenv("GEMINI_BASE_URL") or "").strip()
    if not raw:
        return f"{_DEFAULT_GENERATE_CONTENT_PREFIX}/models/{m}:embedContent"
    if raw.lower().startswith(("http://", "https://")):
        return f"{raw.rstrip('/')}/models/{m}:embedContent"
    host = normalize_gemini_api_endpoint_for_sdk(raw)
    if host:
        return f"https://{host}/v1beta/models/{m}:embedContent"
    return f"{_DEFAULT_GENERATE_CONTENT_PREFIX}/models/{m}:embedContent"
