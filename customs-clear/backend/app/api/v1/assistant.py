"""
Настройка Gemini для префикса /api/v1/assistant (чат).
До configure вызывается load_dotenv; эндпоинт задаётся через ClientOptions (прокси).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from google.api_core.client_options import ClientOptions

from ...services.gemini_genai_configure import normalize_gemini_api_endpoint_for_sdk

_BACKEND_ROOT = Path(__file__).resolve().parents[3]


def _load_gemini_env() -> None:
    load_dotenv(_BACKEND_ROOT / ".env")
    load_dotenv()


def configure_gemini_sdk(genai: Any, *, api_key: str) -> None:
    """Жёстко задаёт api_endpoint из GEMINI_BASE_URL, иначе — стандартный хост Google."""
    _load_gemini_env()
    base_url = normalize_gemini_api_endpoint_for_sdk(os.getenv("GEMINI_BASE_URL") or "")
    if base_url:
        client_options = ClientOptions(api_endpoint=base_url)
        genai.configure(
            api_key=api_key,
            transport="rest",
            client_options=client_options,
        )
    else:
        genai.configure(api_key=api_key)
