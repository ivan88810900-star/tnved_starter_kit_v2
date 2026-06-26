from __future__ import annotations

import asyncio
import os

import google.generativeai as genai

from .gemini_genai_configure import configure_google_generativeai, resolved_gemini_model_name

_NOTES_MAX_LEN = 15_000
_TRUNCATION_SUFFIX = (
    "\n\n... [Текст примечаний обрезан из-за превышения лимитов. "
    "Обратитесь к полному тексту документа.]"
)


SYSTEM_PROMPT_TEMPLATE = (
    "Ты строгий таможенный эксперт. Ответь на вопрос пользователя, опираясь ИСКЛЮЧИТЕЛЬНО "
    "на предоставленный текст примечаний к ТН ВЭД. Если в тексте нет ответа, прямо скажи: "
    "'В примечаниях к данной группе эта информация отсутствует'. Текст примечаний: {notes}"
)

_WARN_REGION = (
    "⚠️ ИИ-ассистент временно недоступен из-за региональных ограничений Google API. "
    "Пожалуйста, убедитесь, что ваш сервер использует VPN или прокси."
)
_WARN_GENERIC = (
    "⚠️ ИИ-ассистент временно недоступен. Повторите запрос позже или проверьте доступ к Google Gemini API."
)


def _limit_notes(raw_notes: str) -> str:
    notes = (raw_notes or "").strip()
    if len(notes) <= _NOTES_MAX_LEN:
        return notes
    return notes[:_NOTES_MAX_LEN] + _TRUNCATION_SUFFIX


async def ask_ai_assistant(question: str, code: str, notes: str) -> str:
    api_key = (os.getenv("GEMINI_API_KEY") or "").strip()
    if not api_key:
        return _WARN_GENERIC

    try:
        configure_google_generativeai(genai, api_key=api_key)
        model_name = resolved_gemini_model_name()
        model = genai.GenerativeModel(model_name)
        safe_notes = _limit_notes(notes)
        instruction = SYSTEM_PROMPT_TEMPLATE.format(notes=safe_notes or "Примечания отсутствуют.")
        question_block = (
            f"Код ТН ВЭД: {code or 'не указан'}\n"
            f"Вопрос пользователя: {question.strip()}"
        )

        def _generate() -> str:
            resp = model.generate_content(
                f"{instruction}\n\n{question_block}",
                generation_config={"temperature": 0.1},
            )
            return (getattr(resp, "text", "") or "").strip()

        text = await asyncio.to_thread(_generate)
        return text or "В примечаниях к данной группе эта информация отсутствует"
    except Exception as exc:
        msg = str(exc).lower()
        if (
            "user location is not supported" in msg
            or "regional" in msg
            or "api_key_http_referrer_blocked" in msg
            or "forbidden" in msg
            or "403" in msg
            or "proxy" in msg
        ):
            return _WARN_REGION
        return _WARN_GENERIC

