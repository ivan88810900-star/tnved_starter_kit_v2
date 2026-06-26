from __future__ import annotations

import json
from typing import Any

import httpx
from loguru import logger

from .claude_service import (
    ANTHROPIC_MODEL_NAME,
    ANTHROPIC_URL,
    _call_gemini,
    llm_provider_chain,
)

_NOT_CONFIGURED = "AI сервис не настроен. Добавьте ANTHROPIC_API_KEY в .env"
_UNAVAILABLE = "AI сервис временно недоступен. Повторите запрос через несколько минут."

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
    """Нельзя начинать историю с ответа модели без user (например, приветствие из UI)."""
    i = 0
    while i < len(turns) and turns[i][0] == "assistant":
        i += 1
    return turns[i:]


def _system_with_context_only(current_context: dict[str, Any] | None) -> str:
    """Системный блок: роль + JSON контекста калькулятора (не дублирует историю диалога)."""
    ctx_text = _serialize_context(current_context)
    return f"{BASE_SYSTEM}\n\n---\nКонтекст текущего расчёта пользователя (JSON):\n{ctx_text}\n---"


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
    while merged and merged[0]["role"] != "user":
        merged.pop(0)
    return merged


def _gemini_user_text(turns: list[tuple[str, str]], user_msg: str) -> str:
    """Плоский промпт для Gemini REST (fallback без multi-turn API)."""
    parts: list[str] = []
    for role, text in turns:
        label = "Пользователь" if role == "user" else "Ассистент"
        parts.append(f"{label}: {text}")
    parts.append(f"Пользователь: {user_msg}")
    return "\n\n".join(parts)


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
    chain = llm_provider_chain()
    if not chain:
        return _NOT_CONFIGURED

    system_instruction = _system_with_context_only(current_context)
    turns = _strip_leading_assistant(_normalized_turns(history))
    user_msg = (message or "").strip()
    if not user_msg:
        return "Введите сообщение."

    last_error: Exception | None = None
    for provider, api_key in chain:
        try:
            if provider == "anthropic":
                msgs = _anthropic_messages(turns, user_msg)
                if not msgs:
                    continue
                text = await _call_anthropic_messages(system_instruction, msgs, api_key)
                if text:
                    return text
            elif provider == "gemini":
                llm_resp = await _call_gemini(
                    system_instruction,
                    _gemini_user_text(turns, user_msg),
                    api_key,
                )
                text = (llm_resp.get("text") or "").strip()
                if text:
                    return text
        except Exception as exc:
            last_error = exc
            logger.warning(f"assistant_chat {provider} error: {exc}")
            continue

    logger.error(f"assistant_chat: все провайдеры недоступны. Последняя ошибка: {last_error}")
    return _UNAVAILABLE
