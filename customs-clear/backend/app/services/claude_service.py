from __future__ import annotations

import os
import re
import json
from typing import Any, Dict, List, Optional

import httpx
from loguru import logger

from .decision_history import journal_hints_for_classifier
from .gemini_genai_configure import gemini_generate_content_rest_url, resolved_gemini_model_name

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_MODEL_NAME = os.getenv("ANTHROPIC_MODEL_NAME", "claude-3.7-sonnet-20250219")

SYSTEM_PROMPT = (
    "Ты — эксперт по таможенной классификации товаров согласно ТН ВЭД ЕАЭС.\n"
    "Пользователь предоставляет описание товара. Твоя задача:\n"
    "1. Определить 3 наиболее вероятных кода ТН ВЭД (10 знаков)\n"
    "2. Для каждого кода указать: код, краткое наименование, ставку ввозной пошлины,\n"
    "   необходимость разрешительных документов, краткое обоснование выбора\n"
    "3. Отметить наиболее рекомендуемый вариант\n"
    "Отвечай ТОЛЬКО в формате JSON без комментариев."
)


def _gemini_key_env() -> str:
    return (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()


def _anthropic_key_env() -> str:
    return (os.getenv("ANTHROPIC_API_KEY") or "").strip()


def _choose_provider() -> tuple[str, str | None]:
    """Только серверная конфигурация: Gemini (GEMINI_API_KEY / GOOGLE_API_KEY), затем Anthropic."""
    g = _gemini_key_env()
    if g:
        return "gemini", g
    a = _anthropic_key_env()
    if a:
        return "anthropic", a
    return "none", None


def is_llm_configured() -> bool:
    """True, если для REST-вызовов LLM в этом модуле задан хотя бы один серверный ключ."""
    provider, key = _choose_provider()
    return provider != "none" and bool(key)


async def _call_anthropic(system_prompt: str, user_text: str, key: str) -> dict[str, Any]:
    headers = {
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": ANTHROPIC_MODEL_NAME,
        "max_tokens": 1024,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_text}],
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(ANTHROPIC_URL, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    text = ""
    for part in data.get("content") or []:
        if isinstance(part, dict) and part.get("type") == "text":
            text += part.get("text", "")
    return {"provider": "anthropic", "text": text.strip(), "raw": data}


async def _call_gemini(system_prompt: str, user_text: str, key: str) -> dict[str, Any]:
    payload = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_text}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1200},
    }
    url = gemini_generate_content_rest_url(resolved_gemini_model_name())
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, params={"key": key}, json=payload)
        resp.raise_for_status()
        data = resp.json()
    text = ""
    for cand in data.get("candidates") or []:
        content = cand.get("content") or {}
        for part in content.get("parts") or []:
            if isinstance(part, dict) and part.get("text"):
                text += part["text"]
        if text:
            break
    return {"provider": "gemini", "text": text.strip(), "raw": data}


async def _ask_llm(system_prompt: str, user_text: str) -> dict[str, Any]:
    provider, key = _choose_provider()
    if provider == "none" or not key:
        return {"provider": "none", "text": "", "raw": {}}
    logger.info(f"Запрос к LLM провайдеру: {provider}")
    if provider == "gemini":
        return await _call_gemini(system_prompt, user_text, key)
    return await _call_anthropic(system_prompt, user_text, key)


DECLARATION_DRAFT_LINES_SYSTEM = (
    "Ты — ведущий специалист по заполнению декларации на товары ЕАЭС (ДТ).\n"
    "Во входе — JSON-массив строк инвойса. У каждой строки: line (номер), description "
    "(может быть на китайском, английском или русском), quantity, unit, weight_gross_kg.\n"
    "Для КАЖДОЙ строки, строго в том же порядке, что во входе, верни элемент массива:\n"
    '{"line": <int>, "hs_code": "<ровно 10 цифр ТН ВЭД ЕАЭС>", '
    '"graf31_ru": "<краткое наименование для графы 31 на русском, по правилам таможенного описания>", '
    '"permit_types": ["СС"|"ДС"|"СГР"|"РУ" ...], '
    '"tr_ts_short": ["004/2011", ...], '
    '"peculiarities": "<1–2 предложения: на что обратить внимание>"}\n'
    "permit_types и tr_ts_short ориентировочно по коду и практике, не как юридическая консультация.\n"
    "Ответ — ТОЛЬКО JSON-массив, без markdown и без текста вокруг."
)


async def enrich_declaration_draft_lines(
    lines: List[Dict[str, Any]],
    *,
    prefer_client_id: Optional[str] = None,
) -> Optional[List[Dict[str, Any]]]:
    """ИИ: ТН ВЭД, графа 31, типы документов по строкам инвойса. Без ключа — None."""
    _ = prefer_client_id  # зарезервировано
    if not lines:
        return None
    provider, key = _choose_provider()
    if not key or provider == "none":
        return None
    user_content = json.dumps(lines, ensure_ascii=False)
    llm_resp = await _ask_llm(DECLARATION_DRAFT_LINES_SYSTEM, user_content)
    text = (llm_resp.get("text") or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```\w*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
    except Exception as e:
        logger.warning(f"Не разобрали JSON черновика ДТ от ИИ: {e}")
    return None


async def classify_hs_code(
    description: str,
    *,
    use_journal_hints: bool = True,
    prefer_client_id: str | None = None,
) -> Dict[str, Any]:
    """Вызов Claude API для классификации ТН ВЭД.

    В ответе ожидается JSON вида раздела 5.3 ТЗ.
    При отсутствии серверного ключа возвращается явная ошибка конфигурации (см. error_code).
    """
    provider, key = _choose_provider()
    if not key or provider == "none":
        logger.warning("Ключ ИИ не задан в окружении (GEMINI_API_KEY/GOOGLE_API_KEY/ANTHROPIC_API_KEY)")
        return {
            "status": "ERROR",
            "error_code": "llm_not_configured",
            "query": description,
            "results": [],
            "note": (
                "ИИ-классификатор не настроен на сервере: задайте GEMINI_API_KEY или GOOGLE_API_KEY "
                "(Gemini) либо ANTHROPIC_API_KEY (Claude)."
            ),
        }
    prefix = (
        journal_hints_for_classifier(description.strip(), prefer_client_id=prefer_client_id)
        if use_journal_hints
        else ""
    )
    user_text = f"{prefix}{description}" if prefix else description
    llm_resp = await _ask_llm(SYSTEM_PROMPT, user_text)
    text = llm_resp.get("text", "").strip()
    data = llm_resp.get("raw", {})

    try:
        parsed = json.loads(text)
        parsed.setdefault("query", description)
        parsed.setdefault("status", "OK")
        parsed.setdefault("provider", llm_resp.get("provider"))
        return parsed
    except Exception as exc:
        logger.exception("Не удалось разобрать ответ LLM, возвращаем сырые данные")
        return {
            "status": "ERROR",
            "query": description,
            "provider": llm_resp.get("provider"),
            "raw_response": data,
            "error": str(exc),
        }


ASSISTANT_SYSTEM_PROMPT = (
    "Ты — эксперт-декларант по таможенному оформлению и нетарифному регулированию ЕАЭС.\n"
    "Во входном JSON поле items — результаты проверки по позициям (ТН ВЭД, описание, ТР ТС, документы).\n"
    "Если есть similar_past_decisions — прошлые подтверждения по похожим товарам; ориентир, не норма права.\n"
    "Твоя задача:\n"
    "1. Оценить корректность кода ТН ВЭД под описание.\n"
    "2. Указать релевантные техрегламенты и нетарифные меры.\n"
    "3. Оценить достаточность приложенных документов.\n"
    "4. Выдать краткое заключение и список рисков.\n"
    "Отвечай ТОЛЬКО в формате JSON без комментариев. Структура:\n"
    '{"hs_code_ok": bool, "tr_ts": [строка], "documents_sufficient": bool, "risks": [строка], "conclusion": "строка"}'
)


COPILOT_SYSTEM_PROMPT = (
    "Ты — ведущий консультант по таможенному оформлению в ЕАЭС.\n"
    "Ниже JSON с результатами автоматического конвейера: код ТН ВЭД (возможно подобран ИИ),\n"
    "нетарифные требования, ориентировочный расчёт платежей, сводка по разрешительным документам.\n"
    "Если в JSON есть поле positions (массив) и positions_count > 1 — дай общую сводку по декларации,\n"
    "сопоставь риски по позициям и укажь приоритетные действия.\n"
    "Поле rag_snippets (если есть) — выдержки из внутренних документов; используй как подсказку, не как норму права.\n"
    "Поле similar_past_decisions (если есть) — прошлые подтверждения экспертом по похожим описаниям товаров;\n"
    "учитывай как справочный опыт, но итог должен соответствовать текущему описанию и актуальным правилам.\n"
    "Задача:\n"
    "1) Кратко объяснить ситуацию декларанту простым языком.\n"
    "2) Оценить согласованность кода и описания (осторожно, если код из ИИ).\n"
    "3) Комментарий по платежам — только как ориентир, не нормативный акт.\n"
    "4) Документы и риски.\n"
    "5) next_steps — конкретные шаги (что проверить, что запросить у поставщика).\n"
    "Отвечай ТОЛЬКО JSON без markdown:\n"
    '{"summary":"", "classification_advice":"", "payment_comment":"", "non_tariff_comment":"", '
    '"documents_comment":"", "risks":[], "next_steps":[], '
    '"disclaimer":"Расчёты и ИИ не заменяют юридическую экспертизу и актуальные справочники."}'
)


async def analyze_copilot_bundle(
    bundle_slim: dict[str, Any],
) -> dict[str, Any]:
    """ИИ-сводка по полному контексту конвейера ассистента."""
    provider, key = _choose_provider()
    if not key or provider == "none":
        return {
            "status": "OK",
            "note": "Ключ ИИ не задан на сервере (GEMINI_API_KEY/GOOGLE_API_KEY или ANTHROPIC_API_KEY).",
            "summary": "Данные конвейера доступны в блоках «Платежи» и «Нетарифка» без ИИ-сводки.",
        }
    user_content = json.dumps(bundle_slim, ensure_ascii=False, indent=2)
    llm_resp = await _ask_llm(COPILOT_SYSTEM_PROMPT, user_content)
    text = llm_resp.get("text", "").strip()
    try:
        parsed = json.loads(text)
        parsed.setdefault("status", "OK")
        parsed.setdefault("provider", llm_resp.get("provider"))
        return parsed
    except Exception:
        return {
            "status": "OK",
            "provider": llm_resp.get("provider"),
            "raw": text,
            "summary": text[:2000],
        }


async def analyze_non_tariff(
    items: list[dict[str, Any]],
    extra_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """ИИ-анализ нетарифных требований по позициям."""
    provider, key = _choose_provider()
    if not key or provider == "none":
        return {
            "status": "OK",
            "items": [],
            "note": "Ключ ИИ не настроен на сервере (GEMINI_API_KEY/GOOGLE_API_KEY или ANTHROPIC_API_KEY).",
        }

    payload: dict[str, Any] = {"items": items}
    if extra_context:
        for k, v in extra_context.items():
            if k == "similar_decisions_enabled":
                continue
            if v is not None and v != []:
                payload[k] = v
    user_content = json.dumps(payload, ensure_ascii=False, indent=2)
    llm_resp = await _ask_llm(ASSISTANT_SYSTEM_PROMPT, user_content)
    text = llm_resp.get("text", "").strip()
    try:
        parsed = json.loads(text)
        parsed.setdefault("status", "OK")
        parsed.setdefault("provider", llm_resp.get("provider"))
        return parsed
    except Exception:
        return {
            "status": "OK",
            "provider": llm_resp.get("provider"),
            "raw": text,
            "conclusion": text,
        }

