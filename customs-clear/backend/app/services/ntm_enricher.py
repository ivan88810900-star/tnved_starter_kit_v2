"""
AI-обогащение нетарифных мер по описанию товара.
Использует LLM для определения дополнительных требований,
которые зависят от характеристик товара.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Any

from loguru import logger

ENRICHMENT_PROMPT = """Ты эксперт по таможенному оформлению ЕАЭС.

Товар:
- Код ТН ВЭД: {hs_code}
- Описание: {description}

Уже определённые нетарифные меры:
{base_measures}

Проанализируй описание товара и определи КАКИЕ ДОПОЛНИТЕЛЬНЫЕ
нетарифные меры могут применяться из-за характеристик товара.

Учитывай типичные триггеры:
- Wi-Fi/Bluetooth/радиомодули → нотификация ФСБ + СЦК
- Шифрование → нотификация ФСБ
- Лазер → СЭЗ Роспотребнадзора
- Контакт с пищей → ТР ТС 005/2011
- Детский товар → ТР ТС 007/2011
- СГР только для детской косметики/детских товаров, если это явно следует из описания
- Оптика медицинская → РУ Росздравнадзора
- Точка доступа/роутер → нотификация
- Беспроводная гарнитура → нотификация

Верни JSON массив (или [] если ничего нет):
[
  {{
    "measure_type": "license|certificate|notification|sgr",
    "description": "Что требуется и почему",
    "document_required": "Точное название документа",
    "regulatory_act": "Правовое основание",
    "trigger": "Какая характеристика товара включила меру"
  }}
]

ТОЛЬКО JSON, без пояснений."""


async def _call_llm(prompt: str, temperature: float = 0.1) -> str:
    """Минимальный вызов LLM: Gemini при наличии ключа, иначе ошибка для fallback-логики."""
    api_key = (os.getenv("GEMINI_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("No GEMINI_API_KEY")
    import google.generativeai as genai

    from .gemini_genai_configure import configure_google_generativeai, resolved_gemini_model_name

    configure_google_generativeai(genai, api_key=api_key)
    model = genai.GenerativeModel(resolved_gemini_model_name())

    def _generate() -> str:
        resp = model.generate_content(prompt, generation_config={"temperature": temperature})
        return (getattr(resp, "text", "") or "").strip()

    return await asyncio.to_thread(_generate)


async def call_llm(prompt: str, temperature: float = 0.1) -> str:
    """Публичный вызов LLM для произвольного промпта (классификаторы, извлечение и т.п.)."""
    return await _call_llm(prompt, temperature=temperature)


async def enrich_measures_by_description(
    *,
    hs_code: str,
    description: str,
    base_measures: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Обогащает базовые меры через анализ описания товара."""
    try:
        base_summary = (
            "\n".join(
                f"- {m.get('measure_type')}: {str(m.get('description', ''))[:100]}"
                for m in base_measures[:5]
            )
            or "(базовых мер нет)"
        )

        prompt = ENRICHMENT_PROMPT.format(
            hs_code=hs_code,
            description=description,
            base_measures=base_summary,
        )

        response = await _call_llm(prompt, temperature=0.1)
        match = re.search(r"\[.*\]", response, re.DOTALL)
        if not match:
            return []

        items = json.loads(match.group(0))
        if not isinstance(items, list):
            return []

        result: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            result.append(
                {
                    "commodity_code": hs_code,
                    "measure_type": item.get("measure_type", "other"),
                    "description": item.get("description", ""),
                    "document_required": item.get("document_required", ""),
                    "legal_ref": item.get("regulatory_act", ""),
                    "permit_type": None,
                    "tr_ts_code": None,
                    "match_prefix_len": 10,
                    "source_level": "ai_enriched",
                    "trigger": item.get("trigger", ""),
                }
            )
        return result
    except Exception as e:
        logger.warning(f"AI обогащение мер не удалось: {e}")
        return []
