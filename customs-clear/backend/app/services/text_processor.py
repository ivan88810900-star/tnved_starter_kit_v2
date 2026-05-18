"""Нормализация сырых описаний товаров из инвойса для RAG и отчётов."""

from __future__ import annotations

import json
import os
import re
from typing import Any

from loguru import logger

from .gemini_genai_configure import configure_google_generativeai, resolved_gemini_model_name

GEMINI_NORMALIZE_PRODUCT_SYSTEM = (
    "Ты эксперт-переводчик в сфере ВЭД. Твоя задача — взять сырое описание товара из инвойса и перевести его "
    "в стандартизированный таможенный термин на русском языке. Убери маркетинговый мусор. Выдели ключевой материал "
    "и назначение. Верни ответ в формате JSON: {\"clean_russian_name\": \"...\", \"search_keywords\": \"...\"}"
)

_NORMALIZE_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "clean_russian_name": {
            "type": "string",
            "description": "Стандартизированное наименование на русском для таможни",
        },
        "search_keywords": {
            "type": "string",
            "description": "Ключевые слова для поиска по базе прецедентов (русский, через запятую или пробел)",
        },
    },
    "required": ["clean_russian_name", "search_keywords"],
}


def normalize_product_description(raw_text: str) -> dict[str, str]:
    """
    Быстрый вызов Gemini: сырой текст инвойса → ``clean_russian_name`` и ``search_keywords`` для RAG.

    Без API-ключа возвращает исходный текст в обоих полях (без сетевого запроса).
    При ошибке API — то же самое.
    """
    raw = (raw_text or "").strip()
    if not raw:
        return {"clean_russian_name": "", "search_keywords": ""}

    key = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
    if not key:
        return {"clean_russian_name": raw[:4000], "search_keywords": raw[:4000]}

    try:
        import google.generativeai as genai
    except ImportError:
        logger.warning("normalize_product_description: нет google-generativeai")
        return {"clean_russian_name": raw[:4000], "search_keywords": raw[:4000]}

    configure_google_generativeai(genai, api_key=key)
    gen_cfg = genai.GenerationConfig(
        temperature=0.1,
        max_output_tokens=512,
        response_mime_type="application/json",
        response_schema=_NORMALIZE_JSON_SCHEMA,
    )
    model = genai.GenerativeModel(
        resolved_gemini_model_name(),
        system_instruction=GEMINI_NORMALIZE_PRODUCT_SYSTEM,
    )
    user = f"Сырое описание товара из инвойса (может быть смесь языков и сокращений):\n\n{raw[:8000]}"
    try:
        resp = model.generate_content(user, generation_config=gen_cfg)
        text = (getattr(resp, "text", None) or "").strip()
    except Exception as e:
        logger.warning("normalize_product_description: Gemini: {}", e)
        return {"clean_russian_name": raw[:4000], "search_keywords": raw[:4000]}

    if not text:
        return {"clean_russian_name": raw[:4000], "search_keywords": raw[:4000]}

    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{[^{}]*\"clean_russian_name\"[^{}]*\}", text, re.DOTALL)
        if not m:
            return {"clean_russian_name": raw[:4000], "search_keywords": raw[:4000]}
        try:
            obj = json.loads(m.group(0))
        except json.JSONDecodeError:
            return {"clean_russian_name": raw[:4000], "search_keywords": raw[:4000]}

    if not isinstance(obj, dict):
        return {"clean_russian_name": raw[:4000], "search_keywords": raw[:4000]}

    clean = str(obj.get("clean_russian_name") or "").strip()[:4000]
    kw = str(obj.get("search_keywords") or "").strip()[:4000]
    if not clean and not kw:
        return {"clean_russian_name": raw[:4000], "search_keywords": raw[:4000]}
    if not clean:
        clean = kw
    if not kw:
        kw = clean
    return {"clean_russian_name": clean, "search_keywords": kw}
