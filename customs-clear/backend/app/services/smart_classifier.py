"""Мультимодальный классификатор для реальных пакинг-листов (перевод, vision, web, ТН ВЭД)."""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field
from typing import Any

import httpx
from loguru import logger

from .classify_response_parser import parse_classify_response
from .claude_service import (
    ANTHROPIC_MODEL_NAME,
    ANTHROPIC_VISION_MODEL,
    SYSTEM_PROMPT,
    _anthropic_key_env,
    _ask_llm,
    _extract_anthropic_text,
    anthropic_messages_request,
    complete_text,
    is_llm_configured,
)
from .safe_http_errors import safe_ai_error_note


_EQUIPMENT_KEYWORDS = (
    "двигатель",
    "мотор",
    "насос",
    "компрессор",
    "генератор",
    "трансформатор",
    "редуктор",
    "motor",
    "pump",
    "engine",
    "compressor",
    "电机",
    "泵",
    "压缩机",
)

_CLASSIFY_WITH_CONTEXT_PROMPT = """Ты эксперт по классификации товаров по ТН ВЭД ЕАЭС.

{context}

На основе всей информации выше определи код ТН ВЭД.
Если анализ фото расходится с текстовым описанием — укажи это в rationale и классифицируй по фото и техническим данным.
Отвечай ТОЛЬКО валидным JSON без markdown:
{{
  "results": [
    {{
      "hs_code": "8501101000",
      "confidence": 0.9,
      "description": "Двигатели электрические однофазные мощностью не более 37.5 Вт",
      "rationale": "По фото и характеристикам — однофазный электродвигатель малой мощности"
    }}
  ]
}}
Топ-3 варианта. hs_code — 10 цифр без пробелов."""


@dataclass
class ClassifyResult:
    results: list[dict[str, Any]]
    translation_used: str = ""
    visual_analysis: str | None = None
    web_search_used: bool = False
    web_context: str | None = None
    status: str = "OK"
    classifier_source: str = "smart_classifier"
    provider: str | None = None
    note: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_api_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "status": self.status,
            "results": self.results,
            "translation_used": self.translation_used,
            "visual_analysis": self.visual_analysis,
            "web_search_used": self.web_search_used,
            "classifier_source": self.classifier_source,
        }
        if self.web_context:
            out["web_context"] = self.web_context
        if self.provider:
            out["provider"] = self.provider
        if self.note:
            out["note"] = self.note
        out.update(self.extra)
        return out


class SmartClassifier:
    """
    Классификатор товаров для реальных пакинг-листов.

    Цепочка:
    1. Перевести описание если не на русском
    2. Проанализировать фото через Claude Vision
    3. Если данных недостаточно — поискать в интернете
    4. Объединить всё и классифицировать
    """

    async def classify(
        self,
        description: str | None,
        image_base64: str | None = None,
        image_url: str | None = None,
        article: str | None = None,
        manufacturer: str | None = None,
    ) -> ClassifyResult:
        if not is_llm_configured():
            return ClassifyResult(
                results=[],
                status="ERROR",
                note="ИИ-классификатор не настроен (ANTHROPIC_API_KEY или GEMINI_API_KEY).",
                extra={"error_code": "llm_not_configured"},
            )

        translated = await self._translate_if_needed(description)
        article_s = (article or "").strip()
        manufacturer_s = (manufacturer or "").strip()

        visual_context: str | None = None
        if image_base64 or image_url:
            try:
                visual_context = await self._analyze_image(image_base64, image_url, translated)
            except Exception as exc:
                logger.warning(f"Vision analysis failed: {exc}")
                visual_context = None

        web_context: str | None = None
        web_used = False
        if self._needs_web_search(translated, visual_context, article_s, manufacturer_s):
            web_context = await self._search_web(translated, article_s, manufacturer_s)
            web_used = bool(web_context)

        try:
            return await self._classify_with_context(
                description=translated,
                visual_context=visual_context,
                web_context=web_context,
                article=article_s,
                manufacturer=manufacturer_s,
                web_search_used=web_used,
            )
        except Exception as exc:
            logger.exception("SmartClassifier final classify failed")
            return ClassifyResult(
                results=[],
                translation_used=translated,
                visual_analysis=visual_context,
                web_search_used=web_used,
                web_context=web_context,
                status="ERROR",
                note=safe_ai_error_note(exc),
                extra={"error_code": "llm_unavailable"},
            )

    def _needs_web_search(
        self,
        description: str,
        visual: str | None,
        article: str,
        manufacturer: str,
    ) -> bool:
        if article and manufacturer and len(description.split()) < 3:
            return True
        if not description and (article or manufacturer):
            return True
        if not description:
            return bool(visual)

        words = description.lower().split()
        if len(words) < 3:
            return True

        desc_lower = description.lower()
        needs_specs = any(kw in desc_lower for kw in _EQUIPMENT_KEYWORDS)
        has_specs = any(c.isdigit() for c in description)
        return needs_specs and not has_specs

    async def _translate_if_needed(self, text: str | None) -> str:
        if not text:
            return ""

        has_chinese = any("\u4e00" <= c <= "\u9fff" for c in text)
        has_cyrillic = any("\u0400" <= c <= "\u04ff" for c in text)

        if has_chinese or (not has_cyrillic and len(text.strip()) > 5):
            prompt = (
                "Переведи на русский язык описание товара для таможенного декларирования.\n"
                "Сохрани технические характеристики точно.\n"
                f"Описание: {text}\n"
                "Ответь только переводом, без пояснений."
            )
            try:
                return (await complete_text(prompt, max_tokens=512)).strip() or text
            except Exception as exc:
                logger.warning(f"Translation failed, using original: {exc}")
                return text

        return text.strip()

    async def _analyze_image(
        self,
        image_base64: str | None,
        image_url: str | None,
        description: str,
    ) -> str:
        content: list[dict[str, Any]] = []

        if image_base64:
            raw, media_type = _normalize_image_base64(image_base64)
            content.append(
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": media_type, "data": raw},
                }
            )
        elif image_url:
            url = image_url.strip()
            try:
                b64, media_type = await _fetch_image_as_base64(url)
                content.append(
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": media_type, "data": b64},
                    }
                )
            except Exception:
                content.append({"type": "image", "source": {"type": "url", "url": url}})

        content.append(
            {
                "type": "text",
                "text": (
                    "Ты эксперт по классификации товаров по ТН ВЭД ЕАЭС.\n"
                    f"Описание товара: {description or '(не указано)'}\n\n"
                    "Проанализируй фото и определи:\n"
                    "1. Что изображено на фото (точное описание товара)\n"
                    "2. Видимые технические характеристики\n"
                    "3. Материал изготовления\n"
                    "4. Назначение товара\n"
                    "5. Есть ли расхождение между фото и описанием\n\n"
                    "Отвечай конкретно, без лишних слов."
                ),
            }
        )

        key = _anthropic_key_env()
        if key:
            for model in (ANTHROPIC_VISION_MODEL, ANTHROPIC_MODEL_NAME):
                if not model:
                    continue
                try:
                    data = await anthropic_messages_request(
                        {
                            "model": model,
                            "max_tokens": 600,
                            "messages": [{"role": "user", "content": content}],
                        },
                        key=key,
                    )
                    return _extract_anthropic_text(data)
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code == 404 and model != ANTHROPIC_MODEL_NAME:
                        logger.warning(f"Vision model {model} unavailable, fallback to {ANTHROPIC_MODEL_NAME}")
                        continue
                    raise

        # Fallback: Gemini multimodal через текстовый промпт без фото
        llm_resp = await _ask_llm(
            "Опиши типичный товар по краткому описанию для таможенной классификации.",
            f"Описание: {description}. URL фото: {image_url or '(base64)'}",
        )
        return (llm_resp.get("text") or "").strip()

    async def _search_web(
        self,
        description: str,
        article: str | None,
        manufacturer: str | None,
    ) -> str:
        queries: list[str] = []
        if article and manufacturer:
            queries.append(f"{manufacturer} {article} технические характеристики")
        if description:
            queries.append(f"{description} технические характеристики ТН ВЭД")
        elif article:
            queries.append(f"{article} specifications datasheet")

        results: list[str] = []
        for query in queries[:2]:
            try:
                search_result = await self._claude_web_search(query)
                if search_result:
                    results.append(search_result)
            except Exception as exc:
                logger.warning(f"Web search failed for {query!r}: {exc}")

        if results:
            return "\n".join(results)

        # Fallback: LLM inference по артикулу/производителю
        if article or manufacturer:
            fallback_prompt = (
                "По артикулу и производителю восстанови типичные технические характеристики товара "
                "для таможенной классификации (мощность, тип, материал, назначение). "
                "Если данных недостаточно — укажи наиболее вероятные параметры.\n"
                f"Производитель: {manufacturer or 'не указан'}\n"
                f"Артикул: {article or 'не указан'}\n"
                f"Описание: {description or 'не указано'}"
            )
            try:
                inferred = await complete_text(fallback_prompt, max_tokens=400)
                if inferred:
                    return inferred
            except Exception:
                pass
        return ""

    async def _claude_web_search(self, query: str) -> str:
        key = _anthropic_key_env()
        if not key:
            return ""

        payload: dict[str, Any] = {
            "model": ANTHROPIC_VISION_MODEL,
            "max_tokens": 500,
            "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 1}],
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Найди технические характеристики товара для таможенной классификации: "
                        f"{query}. Укажи ключевые параметры: мощность, тип, материал, назначение."
                    ),
                }
            ],
        }
        try:
            data = await anthropic_messages_request(payload, key=key)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (400, 403, 404, 422):
                return ""
            raise

        from .claude_service import _extract_anthropic_text

        return _extract_anthropic_text(data)

    async def _classify_with_context(
        self,
        *,
        description: str,
        visual_context: str | None,
        web_context: str | None,
        article: str,
        manufacturer: str,
        web_search_used: bool,
    ) -> ClassifyResult:
        context_parts: list[str] = []
        if description:
            context_parts.append(f"Описание товара: {description}")
        if article:
            context_parts.append(f"Артикул: {article}")
        if manufacturer:
            context_parts.append(f"Производитель: {manufacturer}")
        if visual_context:
            context_parts.append(f"Анализ фото: {visual_context}")
        if web_context:
            context_parts.append(f"Дополнительные характеристики из интернета: {web_context}")

        full_context = "\n\n".join(context_parts) or "Данных мало — классифицируй по имеющимся признакам."
        prompt = _CLASSIFY_WITH_CONTEXT_PROMPT.format(context=full_context)

        llm_resp = await _ask_llm(SYSTEM_PROMPT, prompt)
        raw = llm_resp.get("text") or ""
        results = parse_classify_response(raw)

        return ClassifyResult(
            results=results,
            translation_used=description,
            visual_analysis=visual_context,
            web_search_used=web_search_used,
            web_context=web_context,
            provider=llm_resp.get("provider"),
            extra={"query": description},
        )


def _normalize_image_base64(image_b64: str) -> tuple[str, str]:
    raw = image_b64.strip()
    media_type = "image/jpeg"
    if raw.startswith("data:"):
        header, _, payload = raw.partition(",")
        raw = payload
        m = re.search(r"data:([^;]+)", header)
        if m:
            media_type = m.group(1).strip()
    return raw, media_type


async def _fetch_image_as_base64(url: str) -> tuple[str, str]:
    headers = {"User-Agent": "CustomsClear/1.0 (VED classification; +https://github.com/)"}
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True, headers=headers) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        content_type = (resp.headers.get("content-type") or "image/jpeg").split(";")[0].strip()
        if not content_type.startswith("image/"):
            content_type = "image/jpeg"
        return base64.standard_b64encode(resp.content).decode("ascii"), content_type


_default_classifier: SmartClassifier | None = None


def get_smart_classifier() -> SmartClassifier:
    global _default_classifier
    if _default_classifier is None:
        _default_classifier = SmartClassifier()
    return _default_classifier
