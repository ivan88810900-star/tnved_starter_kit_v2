from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import httpx
from loguru import logger

from ..api.v1.assistant import configure_gemini_sdk
from .claude_service import ANTHROPIC_MODEL_NAME, ANTHROPIC_URL, _choose_provider
from .gemini_genai_configure import resolved_gemini_model_name

_WARN_GENERIC = (
    "Консультант временно недоступен. Повторите запрос позже или обратитесь к администратору."
)
_WARN_QUOTA = (
    "Достигнут лимит запросов к облачному сервису ИИ. Повторите попытку позже или проверьте квоту в Google AI Studio."
)
_WARN_REGION = (
    "⚠️ ИИ недоступен из-за региональных ограничений Google API. "
    "Используйте VPN/прокси на стороне сервера."
)

BASE_SYSTEM = (
    "Ты — ведущий специалист по ВЭД компании-импортера. Ты получил данные из таможенного калькулятора. "
    "Твоя задача: на основе этих данных объяснить пользователю риски, необходимые документы и структуру платежей. "
    "Отвечай профессионально, но понятно. Используй СТРОГО данные из переданного контекста, не выдумывай ставки. "
    "Если в контексте нет нужной цифры или формулировки, прямо скажи, что её нет в переданных данных. "
    "Ответ носит справочный характер; окончательные решения принимает декларант и таможенный орган."
)


def _serialize_context(ctx: dict[str, Any] | None) -> str:
    if not ctx:
        return "Контекст текущего расчёта не передан."
    try:
        return json.dumps(ctx, ensure_ascii=False, indent=2, default=str)
    except TypeError:
        return str(ctx)


def _history_item_text(item: dict[str, Any]) -> str:
    """Поддержка полей text и content (как в OpenAI-совместимых клиентах)."""
    return (item.get("text") or item.get("content") or "").strip()


def _normalized_turns(history: list[dict[str, Any]], max_turns: int = 32) -> list[tuple[str, str]]:
    """Пары (role, text), role — user | assistant."""
    out: list[tuple[str, str]] = []
    for item in history[-max_turns:]:
        role_raw = (item.get("role") or "user").strip().lower()
        role = "user" if role_raw == "user" else "assistant"
        text = _history_item_text(item)
        if not text:
            continue
        out.append((role, text))
    return out


def _strip_leading_assistant(turns: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Gemini/чаты: нельзя начинать историю с ответа модели без user (например, приветствие из UI)."""
    i = 0
    while i < len(turns) and turns[i][0] == "assistant":
        i += 1
    return turns[i:]


def _system_with_context_only(current_context: dict[str, Any] | None) -> str:
    """Системный блок: роль + JSON контекста калькулятора (не дублирует историю диалога)."""
    ctx_text = _serialize_context(current_context)
    return f"{BASE_SYSTEM}\n\n---\nКонтекст текущего расчёта пользователя (JSON):\n{ctx_text}\n---"


def _gemini_content_history(turns: list[tuple[str, str]]) -> list[dict[str, Any]]:
    """История для Gemini: роли user | model."""
    hist: list[dict[str, Any]] = []
    for role, text in turns:
        gem_role = "user" if role == "user" else "model"
        hist.append({"role": gem_role, "parts": [text]})
    return hist


def _anthropic_messages(turns: list[tuple[str, str]], current_user_message: str) -> list[dict[str, str]]:
    """Сообщения для Anthropic: чередование user/assistant, текущий запрос — последний user."""
    merged: list[dict[str, str]] = []
    for role, text in turns:
        ar = "user" if role == "user" else "assistant"
        if merged and merged[-1]["role"] == ar:
            merged[-1]["content"] = (merged[-1]["content"] + "\n\n" + text).strip()
        else:
            merged.append({"role": ar, "content": text})
    cur = (current_user_message or "").strip()
    if not cur:
        return merged
    if merged and merged[-1]["role"] == "user":
        merged[-1]["content"] = (merged[-1]["content"] + "\n\n" + cur).strip()
    else:
        merged.append({"role": "user", "content": cur})
    # Anthropic: первое сообщение должно быть от user
    while merged and merged[0]["role"] != "user":
        merged.pop(0)
    return merged


async def _call_anthropic_messages(system: str, messages: list[dict[str, str]], key: str) -> str:
    headers = {
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload: dict[str, Any] = {
        "model": ANTHROPIC_MODEL_NAME,
        "max_tokens": 4096,
        "system": system,
        "messages": messages,
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(ANTHROPIC_URL, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    text = ""
    for part in data.get("content") or []:
        if isinstance(part, dict) and part.get("type") == "text":
            text += part.get("text", "")
    return text.strip()


async def run_assistant_chat(
    *,
    message: str,
    history: list[dict[str, Any]],
    current_context: dict[str, Any] | None,
) -> str:
    provider, api_key = _choose_provider()
    if provider == "none" or not api_key:
        return _WARN_GENERIC

    system_instruction = _system_with_context_only(current_context)
    turns = _strip_leading_assistant(_normalized_turns(history))
    user_msg = (message or "").strip()
    if not user_msg:
        return "Введите сообщение."

    if provider == "anthropic":
        try:
            msgs = _anthropic_messages(turns, user_msg)
            if not msgs:
                return _WARN_GENERIC
            return await _call_anthropic_messages(system_instruction, msgs, api_key) or _WARN_GENERIC
        except httpx.HTTPStatusError as exc:
            logger.warning(f"assistant_chat anthropic HTTP: {exc}")
            return _WARN_GENERIC
        except Exception as exc:
            logger.exception(f"assistant_chat anthropic: {exc}")
            return _WARN_GENERIC

    # Gemini (по умолчанию при наличии GOOGLE-ключа или не-ant ключе)
    try:
        import google.generativeai as genai
    except ModuleNotFoundError:
        return _WARN_GENERIC

    model_name = resolved_gemini_model_name()

    try:
        configure_gemini_sdk(genai, api_key=api_key)
        model = genai.GenerativeModel(
            model_name,
            system_instruction=system_instruction,
        )
        gem_hist = _gemini_content_history(turns)

        def _generate() -> str:
            chat = model.start_chat(history=gem_hist)
            resp = chat.send_message(
                user_msg,
                generation_config={"temperature": 0.2},
            )
            return (getattr(resp, "text", "") or "").strip()

        text = await asyncio.to_thread(_generate)
        return text or "Не удалось сформулировать ответ. Уточните вопрос."
    except Exception as exc:
        msg = str(exc).lower()
        if "429" in msg or "quota" in msg or "resource exhausted" in msg or "resourceexhausted" in msg:
            return _WARN_QUOTA
        if (
            "user location is not supported" in msg
            or "regional" in msg
            or "api_key_http_referrer_blocked" in msg
            or "forbidden" in msg
            or "403" in msg
        ):
            return _WARN_REGION
        if "404" in msg and "not found" in msg and "model" in msg:
            return (
                "Модель ИИ не найдена на стороне Google. Задайте актуальное имя в переменной окружения "
                "GEMINI_MODEL_NAME (например, gemini-1.5-flash)."
            )
        logger.exception(f"assistant_chat gemini: {exc}")
        return _WARN_GENERIC
