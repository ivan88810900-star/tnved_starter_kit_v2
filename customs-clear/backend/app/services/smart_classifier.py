"""Мультимодальный классификатор для реальных пакинг-листов (перевод, vision, web, ТН ВЭД)."""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import ipaddress
import json
import re
import socket
import warnings
import zlib
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from loguru import logger
from PIL import Image

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

# Кэши для пакетной обработки пакинг-листов (перевод / vision / классификация по группе).
_translation_cache: dict[str, str] = {}
_translation_inflight: dict[
    tuple[asyncio.AbstractEventLoop, str],
    asyncio.Task[str],
] = {}
_translation_batch_inflight: dict[
    tuple[asyncio.AbstractEventLoop, tuple[str, ...]],
    asyncio.Task[None],
] = {}
_vision_cache: dict[tuple[str, str], str] = {}
_vision_image_fingerprints: dict[tuple[str, str], str] = {}
_vision_requested_fingerprints: dict[tuple[str, str], str | None] = {}
_vision_unavailable_cache: set[tuple[str, str]] = set()
_vision_inflight: dict[
    tuple[asyncio.AbstractEventLoop, tuple[str, str], str, str],
    asyncio.Task["_VisionAnalysis"],
] = {}
_classify_group_cache: dict[tuple[tuple[str, str], str], "ClassifyResult"] = {}
_classify_group_inflight: dict[
    tuple[
        asyncio.AbstractEventLoop,
        tuple[tuple[str, str], str],
    ],
    asyncio.Task["ClassifyResult"],
] = {}
_packing_cache_generation = 0
_vision_request_failures: ContextVar[dict[tuple[str, str], bool] | None] = ContextVar(
    "smart_classifier_vision_request_failures",
    default=None,
)
_BATCH_TRANSLATE_CHUNK = 45
_MAX_IMAGE_BYTES = 10 * 1024 * 1024
_MAX_IMAGE_FRAMES = 1000
_SUPPORTED_IMAGE_MEDIA_TYPES = frozenset(
    {"image/jpeg", "image/png", "image/gif", "image/webp"}
)

_WEB_SEARCH_MANUAL_REVIEW_NOTE = (
    "Поиск технических характеристик не дал подтверждённых данных. "
    "Варианты кода являются предварительными и требуют ручной проверки по документации товара."
)

_IMAGE_ANALYSIS_MANUAL_REVIEW_NOTE = (
    "Изображение не удалось безопасно получить или проанализировать. "
    "Результат по текстовым данным требует ручной проверки."
)


class _VisionAnalysis(str):
    """String-compatible vision result carrying its validated image identity."""

    image_fingerprint: str | None
    analysis_failed: bool

    def __new__(
        cls,
        value: str,
        image_fingerprint: str | None,
        *,
        analysis_failed: bool = False,
    ) -> "_VisionAnalysis":
        instance = super().__new__(cls, value)
        instance.image_fingerprint = image_fingerprint
        instance.analysis_failed = analysis_failed
        return instance


_UNAVAILABLE_VISION_ANALYSIS = _VisionAnalysis(
    "",
    None,
    analysis_failed=True,
)


def _group_classification_fingerprint(
    group_key: tuple[str, str],
    *,
    description: str,
    translated: str,
    visual_context: str | None,
    article: str,
    image_analysis_failed: bool,
) -> str:
    """Identify every input that can change a cached group classification."""
    payload = json.dumps(
        {
            "group_key": group_key,
            "description": description,
            "translated": translated,
            "visual_context": visual_context,
            "image_fingerprint": getattr(visual_context, "image_fingerprint", None),
            "article": article,
            "image_analysis_failed": image_analysis_failed,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _set_request_image_analysis_failed(
    group_key: tuple[str, str],
    failed: bool,
) -> None:
    # Context variables are copied into child tasks.  Copy the mapping before
    # every write so sibling tasks never mutate the same inherited object.
    states = dict(_vision_request_failures.get() or {})
    states[group_key] = failed
    _vision_request_failures.set(states)


def _get_request_image_analysis_failed(group_key: tuple[str, str]) -> bool | None:
    states = _vision_request_failures.get()
    if states is None or group_key not in states:
        return None
    return states[group_key]


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


def _clone_classify_result(source: ClassifyResult) -> ClassifyResult:
    """Copy mutable classification payloads across the group-cache boundary."""
    return ClassifyResult(
        results=deepcopy(source.results),
        translation_used=source.translation_used,
        # Vision analysis is string-compatible and carries an immutable image
        # identity, so preserve it rather than asking deepcopy to reconstruct
        # the custom str subclass.
        visual_analysis=source.visual_analysis,
        web_search_used=source.web_search_used,
        web_context=deepcopy(source.web_context),
        status=source.status,
        classifier_source=source.classifier_source,
        provider=source.provider,
        note=source.note,
        extra=deepcopy(source.extra),
    )


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
        normalized_image_base64 = (image_base64 or "").strip() or None
        normalized_image_url = (image_url or "").strip() or None
        image_field_supplied = image_base64 is not None or image_url is not None
        blank_image_field_supplied = any(
            value is not None and not value.strip()
            for value in (image_base64, image_url)
        )

        visual_context: str | None = None
        image_requested = bool(normalized_image_base64 or normalized_image_url)
        image_analysis_failed = image_field_supplied and (blank_image_field_supplied or not image_requested)
        if image_requested:
            try:
                visual_context = await self._analyze_image(
                    normalized_image_base64,
                    normalized_image_url,
                    translated,
                )
            except Exception as exc:
                logger.warning(f"Vision analysis failed: {exc}")
                visual_context = None
                image_analysis_failed = True
            else:
                image_analysis_failed = image_analysis_failed or not bool(visual_context.strip())

        if image_analysis_failed and not (translated or article_s or manufacturer_s):
            return ClassifyResult(
                results=[],
                status="ERROR",
                note=_IMAGE_ANALYSIS_MANUAL_REVIEW_NOTE,
                extra={
                    "error_code": "image_unavailable",
                    "manual_review_required": True,
                    "image_analysis_status": "unavailable",
                },
            )

        web_context: str | None = None
        web_used = False
        web_search_needed = self._needs_web_search(translated, visual_context, article_s, manufacturer_s)
        if web_search_needed:
            web_context = await self._search_web(translated, article_s, manufacturer_s)
            web_used = bool(web_context)

        try:
            result = await self._classify_with_context(
                description=translated,
                visual_context=visual_context,
                web_context=web_context,
                article=article_s,
                manufacturer=manufacturer_s,
                web_search_used=web_used,
            )
            result = self._with_web_search_status(
                result,
                attempted=web_search_needed,
                confirmed=web_used,
            )
            return self._with_image_analysis_status(
                result,
                failed=image_analysis_failed,
            )
        except Exception as exc:
            logger.exception("SmartClassifier final classify failed")
            result = ClassifyResult(
                results=[],
                translation_used=translated,
                visual_analysis=visual_context,
                web_search_used=web_used,
                web_context=web_context,
                status="ERROR",
                note=safe_ai_error_note(exc),
                extra={
                    "error_code": "llm_unavailable",
                    **self._web_search_metadata(attempted=web_search_needed, confirmed=web_used),
                },
            )
            return self._with_image_analysis_status(
                result,
                failed=image_analysis_failed,
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
        key = text.strip()
        if key in _translation_cache:
            return _translation_cache[key]
        if not self._text_needs_translation(key):
            _translation_cache[key] = key
            return key

        loop = asyncio.get_running_loop()
        inflight_key = (loop, key)
        task = _translation_inflight.get(inflight_key)
        if task is not None and task.done():
            # The callback is scheduled for the next loop turn.  A failed or
            # empty translation is deliberately not cached, so an immediate
            # sequential call must start a fresh provider attempt.
            if _translation_inflight.get(inflight_key) is task:
                _translation_inflight.pop(inflight_key, None)
            cached = _translation_cache.get(key)
            if cached is not None:
                return cached
            task = None

        if task is None:
            cache_generation = _packing_cache_generation
            task = loop.create_task(
                self._translate_uncached(
                    key,
                    cache_generation=cache_generation,
                )
            )
            _translation_inflight[inflight_key] = task

            def remove_completed(
                completed: asyncio.Task[str],
                *,
                registry_key: tuple[asyncio.AbstractEventLoop, str] = inflight_key,
            ) -> None:
                if _translation_inflight.get(registry_key) is completed:
                    _translation_inflight.pop(registry_key, None)

            task.add_done_callback(remove_completed)

        # One cancelled packing row must not cancel the shared provider call.
        return await asyncio.shield(task)

    async def translate_cached(self, text: str | None) -> str:
        """Перевод с кэшем (после prepare_translations)."""
        if not text:
            return ""
        key = text.strip()
        if key in _translation_cache:
            return _translation_cache[key]
        return await self._translate_if_needed(key)

    @staticmethod
    def _text_needs_translation(text: str) -> bool:
        has_chinese = any("\u4e00" <= c <= "\u9fff" for c in text)
        has_cyrillic = any("\u0400" <= c <= "\u04ff" for c in text)
        return bool(has_chinese or (not has_cyrillic and len(text.strip()) > 5))

    async def _do_translate(self, text: str) -> str:
        translated, _cacheable = await self._translate_attempt(text)
        return translated

    async def _translate_attempt(self, text: str) -> tuple[str, bool]:
        """Return a fallback value and whether it is safe to cache globally."""
        if not self._text_needs_translation(text):
            return text.strip(), True
        prompt = (
            "Переведи на русский язык описание товара для таможенного декларирования.\n"
            "Сохрани технические характеристики точно.\n"
            f"Описание: {text}\n"
            "Ответь только переводом, без пояснений."
        )
        try:
            translated = (await complete_text(prompt, max_tokens=512)).strip()
            if not translated:
                logger.warning("Translation returned empty text, using original")
                return text, False
            return translated, True
        except Exception as exc:
            logger.warning(f"Translation failed, using original: {exc}")
            return text, False

    async def _translate_uncached(
        self,
        text: str,
        *,
        cache_generation: int,
    ) -> str:
        translated, cacheable = await self._translate_attempt(text)
        if cacheable and cache_generation == _packing_cache_generation:
            _translation_cache[text] = translated
        return translated

    async def prepare_translations(self, texts: list[str]) -> dict[str, str]:
        """Батч-перевод уникальных строк (один LLM-запрос на чанк)."""
        pending: list[str] = []
        for raw in texts:
            t = (raw or "").strip()
            if not t or t in _translation_cache:
                continue
            if not self._text_needs_translation(t):
                _translation_cache[t] = t
                continue
            if t not in pending:
                pending.append(t)

        # Canonical order keeps chunk boundaries stable when concurrent
        # uploads contain the same logical set in a different row order.
        pending.sort()
        for i in range(0, len(pending), _BATCH_TRANSLATE_CHUNK):
            chunk = pending[i : i + _BATCH_TRANSLATE_CHUNK]
            await self._translate_batch_chunk(chunk)

        return dict(_translation_cache)

    async def _translate_batch_chunk(self, texts: list[str]) -> None:
        if not texts:
            return
        if len(texts) == 1:
            t = texts[0]
            await self._translate_if_needed(t)
            return

        # Two packing uploads can prepare the same cold batch concurrently.
        # Share one provider request for the same set of source strings while
        # keeping distinct batches independent.  prepare_translations uses a
        # canonical order so chunk boundaries are stable above the chunk cap.
        loop = asyncio.get_running_loop()
        inflight_key = (loop, tuple(sorted(texts)))
        task = _translation_batch_inflight.get(inflight_key)
        if task is not None and task.done():
            if _translation_batch_inflight.get(inflight_key) is task:
                _translation_batch_inflight.pop(inflight_key, None)
            task = None

        if task is None:
            task = loop.create_task(self._translate_batch_chunk_uncached(texts))
            _translation_batch_inflight[inflight_key] = task

            def remove_completed(
                completed: asyncio.Task[None],
                *,
                registry_key: tuple[
                    asyncio.AbstractEventLoop,
                    tuple[str, ...],
                ] = inflight_key,
            ) -> None:
                if _translation_batch_inflight.get(registry_key) is completed:
                    _translation_batch_inflight.pop(registry_key, None)

            task.add_done_callback(remove_completed)

        # Cancelling one upload must not cancel the translation shared by
        # another concurrent upload.
        await asyncio.shield(task)

    async def _translate_batch_chunk_uncached(self, texts: list[str]) -> None:
        """Populate translations for one provider batch without dedup setup."""

        cache_generation = _packing_cache_generation
        requested = set(texts)
        lines = "\n".join(f"- {t}" for t in texts)
        prompt = (
            "Переведи на русский язык названия товаров для таможенного декларирования.\n"
            "Сохрани технические характеристики точно.\n"
            "Отвечай ТОЛЬКО валидным JSON без markdown:\n"
            '{"translations": {"оригинал": "перевод"}}\n\n'
            f"Товары:\n{lines}"
        )
        try:
            raw = (await complete_text(prompt, max_tokens=4096)).strip()
            raw = re.sub(r"^```json\s*", "", raw)
            raw = re.sub(r"^```\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                data = json.loads(match.group())
                mapping = data.get("translations") or data.get("переводы") or {}
                if isinstance(mapping, dict):
                    for src, dst in mapping.items():
                        src_s = str(src).strip()
                        dst_s = str(dst).strip() if dst is not None else ""
                        if (
                            src_s in requested
                            and dst_s
                            and cache_generation == _packing_cache_generation
                        ):
                            _translation_cache[src_s] = dst_s
        except Exception as exc:
            logger.warning(f"Batch translation parse failed: {exc}")

        # A cache clear detaches this old batch.  Do not let its fallback path
        # start fresh-generation single-item tasks and repopulate the new cache.
        if cache_generation != _packing_cache_generation:
            return

        for t in texts:
            # clear_packing_caches can run while an earlier single-item
            # fallback is awaiting the provider.  Recheck before every later
            # fallback so the detached old batch cannot start work in the new
            # generation.
            if cache_generation != _packing_cache_generation:
                return
            if t not in _translation_cache:
                await self._translate_if_needed(t)

    async def get_or_analyze_vision(
        self,
        group_key: tuple[str, str],
        *,
        image_base64: str | None,
        description: str,
    ) -> str | None:
        image_fingerprint: str | None = None
        if image_base64 is not None:
            try:
                normalized_image, media_type = _normalize_image_base64(image_base64)
            except ValueError as exc:
                logger.warning(f"Vision input validation failed: {exc}")
                # Supersede any older producer for this product.  Its result
                # may still be returned to its own caller, but must not erase
                # this newer fail-closed state when it completes late.
                _vision_requested_fingerprints[group_key] = None
                _set_request_image_analysis_failed(group_key, True)
                _vision_unavailable_cache.add(group_key)
                _vision_cache.pop(group_key, None)
                _vision_image_fingerprints.pop(group_key, None)
                return _UNAVAILABLE_VISION_ANALYSIS
            digest = hashlib.sha256()
            digest.update(media_type.encode("ascii"))
            digest.update(b"\0")
            digest.update(normalized_image.encode("ascii"))
            image_fingerprint = digest.hexdigest()
            # The group identifies a product, while this value identifies its
            # newest validated image request.  Older different-image producers
            # are fenced from overwriting or clearing the newer cache state.
            _vision_requested_fingerprints[group_key] = image_fingerprint

        if group_key in _vision_cache:
            cached_fingerprint = _vision_image_fingerprints.get(group_key)
            if image_fingerprint is None or image_fingerprint == cached_fingerprint:
                _set_request_image_analysis_failed(group_key, False)
                if group_key in _vision_unavailable_cache:
                    _vision_unavailable_cache.discard(group_key)
                return _vision_cache[group_key]

            # A group key describes the product, not the image.  A later row
            # may carry different valid evidence for that same product; never
            # reuse either its old visual analysis or derived classification.
            _vision_cache.pop(group_key, None)
            _vision_image_fingerprints.pop(group_key, None)
        if image_base64 is None:
            _set_request_image_analysis_failed(group_key, False)
            return None
        assert image_fingerprint is not None
        loop = asyncio.get_running_loop()
        inflight_key = (loop, group_key, image_fingerprint, description)
        task = _vision_inflight.get(inflight_key)
        if task is not None and task.done():
            # A failed provider call is retryable.  A successful producer has
            # already populated the cache unless a cache clear detached it.
            if _vision_inflight.get(inflight_key) is task:
                _vision_inflight.pop(inflight_key, None)
            cached = _vision_cache.get(group_key)
            if (
                cached is not None
                and _vision_image_fingerprints.get(group_key) == image_fingerprint
            ):
                _set_request_image_analysis_failed(group_key, False)
                return cached
            task = None

        if task is None:
            cache_generation = _packing_cache_generation
            task = loop.create_task(
                self._analyze_group_image_uncached(
                    group_key=group_key,
                    image_base64=image_base64,
                    image_fingerprint=image_fingerprint,
                    description=description,
                    cache_generation=cache_generation,
                )
            )
            _vision_inflight[inflight_key] = task

            def remove_completed(
                completed: asyncio.Task[_VisionAnalysis],
                *,
                key: tuple[
                    asyncio.AbstractEventLoop,
                    tuple[str, str],
                    str,
                    str,
                ] = inflight_key,
            ) -> None:
                if _vision_inflight.get(key) is completed:
                    _vision_inflight.pop(key, None)

            task.add_done_callback(remove_completed)

        # A row cancellation must not cancel the shared provider request for
        # other rows that carry the same validated image.
        visual = await asyncio.shield(task)
        failed = visual.analysis_failed
        _set_request_image_analysis_failed(group_key, failed)
        return visual

    async def _analyze_group_image_uncached(
        self,
        *,
        group_key: tuple[str, str],
        image_base64: str,
        image_fingerprint: str,
        description: str,
        cache_generation: int,
    ) -> _VisionAnalysis:
        try:
            visual = await self._analyze_image(image_base64, None, description)
        except Exception as exc:
            logger.warning(f"Vision analysis failed: {exc}")
            visual = ""

        if not visual.strip():
            if (
                cache_generation == _packing_cache_generation
                and _vision_requested_fingerprints.get(group_key) == image_fingerprint
            ):
                _vision_unavailable_cache.add(group_key)
                _vision_cache.pop(group_key, None)
                _vision_image_fingerprints.pop(group_key, None)
            return _UNAVAILABLE_VISION_ANALYSIS

        analysis = _VisionAnalysis(visual, image_fingerprint)
        if (
            cache_generation == _packing_cache_generation
            and _vision_requested_fingerprints.get(group_key) == image_fingerprint
        ):
            _vision_unavailable_cache.discard(group_key)
            _vision_image_fingerprints[group_key] = image_fingerprint
            _vision_cache[group_key] = analysis
        return analysis

    async def get_or_classify_group(
        self,
        group_key: tuple[str, str],
        *,
        description: str,
        translated: str,
        visual_context: str | None,
        article: str | None,
    ) -> ClassifyResult:
        analysis_token_failure = getattr(visual_context, "analysis_failed", None)
        if analysis_token_failure is not None:
            image_analysis_failed = analysis_token_failure
        else:
            request_failure = _get_request_image_analysis_failed(group_key)
            image_analysis_failed = (
                group_key in _vision_unavailable_cache
                if request_failure is None
                else request_failure
            )
        article_s = (article or "").strip()
        classification_fingerprint = _group_classification_fingerprint(
            group_key,
            description=description,
            translated=translated,
            visual_context=visual_context,
            article=article_s,
            image_analysis_failed=image_analysis_failed,
        )
        cache_key = (group_key, classification_fingerprint)
        if cache_key in _classify_group_cache:
            cached = _classify_group_cache[cache_key]
            return self._group_result_snapshot(
                cached,
                translated=translated,
                visual_context=visual_context,
                image_analysis_failed=image_analysis_failed,
            )

        loop = asyncio.get_running_loop()
        inflight_key = (loop, cache_key)
        task = _classify_group_inflight.get(inflight_key)
        if task is not None and task.done():
            # A done callback runs on the next loop turn.  Do not let that
            # scheduling detail retain a transient ERROR/exception for an
            # immediate sequential retry.
            if _classify_group_inflight.get(inflight_key) is task:
                _classify_group_inflight.pop(inflight_key, None)
            cached = _classify_group_cache.get(cache_key)
            if cached is not None:
                return self._group_result_snapshot(
                    cached,
                    translated=translated,
                    visual_context=visual_context,
                    image_analysis_failed=image_analysis_failed,
                )
            task = None

        if task is None:
            cache_generation = _packing_cache_generation
            task = loop.create_task(
                self._classify_group_uncached(
                    cache_key=cache_key,
                    cache_generation=cache_generation,
                    translated=translated,
                    visual_context=visual_context,
                    article=article_s,
                    image_analysis_failed=image_analysis_failed,
                )
            )
            _classify_group_inflight[inflight_key] = task

            def remove_completed(
                completed: asyncio.Task[ClassifyResult],
                *,
                key: tuple[
                    asyncio.AbstractEventLoop,
                    tuple[tuple[str, str], str],
                ] = inflight_key,
            ) -> None:
                if _classify_group_inflight.get(key) is completed:
                    _classify_group_inflight.pop(key, None)

            task.add_done_callback(remove_completed)

        # Shield the shared producer from cancellation by any one row/caller.
        # Every waiter receives its own deep snapshot below.
        result = await asyncio.shield(task)
        return self._group_result_snapshot(
            result,
            translated=translated,
            visual_context=visual_context,
            image_analysis_failed=image_analysis_failed,
        )

    async def _classify_group_uncached(
        self,
        *,
        cache_key: tuple[tuple[str, str], str],
        cache_generation: int,
        translated: str,
        visual_context: str | None,
        article: str,
        image_analysis_failed: bool,
    ) -> ClassifyResult:
        web_context: str | None = None
        web_used = False
        web_search_needed = self._needs_web_search(translated, visual_context, article, "")
        if web_search_needed:
            web_context = await self._search_web(translated, article, None)
            web_used = bool(web_context)

        try:
            result = await self._classify_with_context(
                description=translated,
                visual_context=visual_context,
                web_context=web_context,
                article=article,
                manufacturer="",
                web_search_used=web_used,
            )
            result = self._with_web_search_status(
                result,
                attempted=web_search_needed,
                confirmed=web_used,
            )
            result = self._with_image_analysis_status(
                result,
                failed=image_analysis_failed,
            )
        except Exception as exc:
            logger.exception("SmartClassifier group classify failed")
            result = ClassifyResult(
                results=[],
                translation_used=translated,
                visual_analysis=visual_context or None,
                web_search_used=web_used,
                web_context=web_context,
                status="ERROR",
                note=safe_ai_error_note(exc),
                extra={
                    "error_code": "llm_unavailable",
                    **self._web_search_metadata(attempted=web_search_needed, confirmed=web_used),
                },
            )
            result = self._with_image_analysis_status(
                result,
                failed=image_analysis_failed,
            )

        # Provider/network and grounding failures are transient.  Returning
        # fail-closed ERROR/MANUAL_REVIEW is correct for this request, but
        # caching either failure would prevent an identical later request from
        # retrying after the provider or web evidence recovers.
        transient_grounding_gap = web_search_needed and not web_used
        if (
            result.status != "ERROR"
            and not transient_grounding_gap
            and cache_generation == _packing_cache_generation
        ):
            # The caller owns the object returned below.  Keep a private deep
            # snapshot so later mutations cannot poison subsequent rows, and
            # clone that snapshot again for every cache hit above.
            _classify_group_cache[cache_key] = _clone_classify_result(result)
        return result

    @classmethod
    def _group_result_snapshot(
        cls,
        source: ClassifyResult,
        *,
        translated: str,
        visual_context: str | None,
        image_analysis_failed: bool,
    ) -> ClassifyResult:
        result = _clone_classify_result(source)
        result.translation_used = translated
        result.visual_analysis = visual_context or source.visual_analysis
        return cls._with_image_analysis_status(
            result,
            failed=image_analysis_failed,
        )

    @staticmethod
    def clear_packing_caches() -> None:
        global _packing_cache_generation

        _packing_cache_generation += 1
        _translation_cache.clear()
        # Do not cancel tasks owned by another running loop.  The generation
        # fence prevents their late completion from repopulating this cache.
        _translation_inflight.clear()
        _translation_batch_inflight.clear()
        _vision_cache.clear()
        _vision_image_fingerprints.clear()
        _vision_requested_fingerprints.clear()
        _vision_unavailable_cache.clear()
        # Detach old producers without cancelling tasks owned by active
        # callers.  Their generation fence prevents late cache repopulation.
        _vision_inflight.clear()
        _classify_group_cache.clear()
        # Do not cancel tasks owned by another running loop.  Clearing the
        # registry detaches them, while the generation fence above prevents a
        # late completion from repopulating the freshly cleared cache.
        _classify_group_inflight.clear()
        _vision_request_failures.set(None)

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
            except Exception as exc:
                # Never pass a URL which failed our network boundary to an AI
                # provider: provider-side URL fetching would bypass the SSRF
                # checks performed by this service.
                raise ValueError("image URL could not be fetched safely") from exc

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

        # Text-only completion cannot analyze the image bytes.  Treat missing
        # vision capability as unavailable instead of manufacturing visual
        # context from the product description.
        raise ValueError("vision-capable provider is not configured")

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

        # Fail closed: модельная реконструкция без результата web tool не является web context.
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

        if not _has_web_search_result(data):
            return ""

        from .claude_service import _extract_anthropic_text

        return _extract_anthropic_text(data)

    @staticmethod
    def _web_search_metadata(*, attempted: bool, confirmed: bool) -> dict[str, Any]:
        if not attempted:
            return {"web_search_attempted": False, "web_search_status": "not_needed"}
        return {
            "web_search_attempted": True,
            "web_search_status": "confirmed" if confirmed else "unavailable",
        }

    @classmethod
    def _with_web_search_status(
        cls,
        result: ClassifyResult,
        *,
        attempted: bool,
        confirmed: bool,
    ) -> ClassifyResult:
        result.extra.update(cls._web_search_metadata(attempted=attempted, confirmed=confirmed))
        if not attempted or confirmed:
            return result

        result.status = "MANUAL_REVIEW"
        result.note = _WEB_SEARCH_MANUAL_REVIEW_NOTE
        result.extra["manual_review_required"] = True
        result.results = [{**item, "recommended": False} for item in result.results]
        return result

    @staticmethod
    def _with_image_analysis_status(
        result: ClassifyResult,
        *,
        failed: bool,
    ) -> ClassifyResult:
        if not failed:
            return result

        result.extra["manual_review_required"] = True
        result.extra["image_analysis_status"] = "unavailable"
        if result.status != "ERROR":
            result.status = "MANUAL_REVIEW"
            result.note = _IMAGE_ANALYSIS_MANUAL_REVIEW_NOTE
        result.results = [{**item, "recommended": False} for item in result.results]
        return result

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
            visual_analysis=visual_context or None,
            web_search_used=web_search_used,
            web_context=web_context,
            provider=llm_resp.get("provider"),
            extra={"query": description},
        )


def _normalize_image_base64(image_b64: str) -> tuple[str, str]:
    raw = image_b64.strip()
    media_type: str | None = None
    payload = raw
    if raw[:5].lower() == "data:":
        match = re.fullmatch(
            r"data:([^;,]+);base64,(.*)",
            raw,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not match:
            raise ValueError("invalid base64 image data URI")
        declared_media_type = match.group(1)
        if declared_media_type != declared_media_type.strip():
            raise ValueError("invalid base64 image media type")
        media_type = declared_media_type.lower()
        payload = match.group(2)

    if media_type is not None and media_type not in _SUPPORTED_IMAGE_MEDIA_TYPES:
        raise ValueError("unsupported base64 image media type")
    if not payload:
        raise ValueError("base64 image payload is empty")

    max_encoded_bytes = 4 * ((_MAX_IMAGE_BYTES + 2) // 3)
    if len(payload) > max_encoded_bytes:
        raise ValueError("base64 image exceeds maximum allowed size")
    try:
        decoded = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("invalid base64 image payload") from exc
    if not decoded:
        raise ValueError("base64 image payload is empty")
    if len(decoded) > _MAX_IMAGE_BYTES:
        raise ValueError("base64 image exceeds maximum allowed size")
    media_type = _validate_raster_image_bytes(decoded, media_type)

    normalized = base64.standard_b64encode(decoded).decode("ascii")
    return normalized, media_type


def _detect_raster_media_type(decoded: bytes) -> str | None:
    if decoded.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if decoded.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if decoded.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(decoded) >= 12 and decoded.startswith(b"RIFF") and decoded[8:12] == b"WEBP":
        return "image/webp"
    return None


def _jpeg_container_end(image_bytes: bytes) -> int | None:
    """Return the first structural JPEG EOI boundary, skipping marker payloads."""
    position = 2
    in_scan = False
    while position < len(image_bytes):
        if in_scan:
            marker_start = image_bytes.find(b"\xff", position)
            if marker_start < 0 or marker_start + 1 >= len(image_bytes):
                return None
            marker_position = marker_start + 1
            while marker_position < len(image_bytes) and image_bytes[marker_position] == 0xFF:
                marker_position += 1
            if marker_position >= len(image_bytes):
                return None
            marker = image_bytes[marker_position]
            if marker == 0x00 or 0xD0 <= marker <= 0xD7:
                position = marker_position + 1
                continue
            if marker == 0xD9:
                return marker_position + 1
            position = marker_start
            in_scan = False
            continue

        if image_bytes[position] != 0xFF:
            return None
        while position < len(image_bytes) and image_bytes[position] == 0xFF:
            position += 1
        if position >= len(image_bytes):
            return None
        marker = image_bytes[position]
        position += 1
        if marker == 0xD9:
            return position
        if marker in {0x01, 0xD8} or 0xD0 <= marker <= 0xD7:
            continue
        if marker == 0x00 or position + 2 > len(image_bytes):
            return None
        segment_length = int.from_bytes(image_bytes[position : position + 2], "big")
        if segment_length < 2 or position + segment_length > len(image_bytes):
            return None
        position += segment_length
        if marker == 0xDA:
            in_scan = True
    return None


def _png_container_end(image_bytes: bytes) -> int | None:
    position = 8
    while position < len(image_bytes):
        if position + 12 > len(image_bytes):
            return None
        chunk_length = int.from_bytes(image_bytes[position : position + 4], "big")
        chunk_type = image_bytes[position + 4 : position + 8]
        chunk_end = position + 12 + chunk_length
        if chunk_end > len(image_bytes):
            return None
        chunk_data_end = position + 8 + chunk_length
        expected_crc = int.from_bytes(image_bytes[chunk_data_end:chunk_end], "big")
        actual_crc = zlib.crc32(chunk_type)
        actual_crc = zlib.crc32(image_bytes[position + 8 : chunk_data_end], actual_crc)
        if actual_crc & 0xFFFFFFFF != expected_crc:
            return None
        if chunk_type == b"IEND":
            return chunk_end if chunk_length == 0 else None
        position = chunk_end
    return None


def _gif_container_end(image_bytes: bytes) -> int | None:
    if len(image_bytes) < 13:
        return None
    position = 13
    packed_fields = image_bytes[10]
    if packed_fields & 0x80:
        position += 3 * (2 ** ((packed_fields & 0x07) + 1))

    def skip_sub_blocks(offset: int) -> int | None:
        while offset < len(image_bytes):
            block_size = image_bytes[offset]
            offset += 1
            if block_size == 0:
                return offset
            if offset + block_size > len(image_bytes):
                return None
            offset += block_size
        return None

    while position < len(image_bytes):
        introducer = image_bytes[position]
        position += 1
        if introducer == 0x3B:
            return position
        if introducer == 0x21:
            if position >= len(image_bytes):
                return None
            position += 1  # extension label
            next_position = skip_sub_blocks(position)
            if next_position is None:
                return None
            position = next_position
            continue
        if introducer != 0x2C or position + 9 > len(image_bytes):
            return None
        descriptor_packed_fields = image_bytes[position + 8]
        position += 9
        if descriptor_packed_fields & 0x80:
            position += 3 * (2 ** ((descriptor_packed_fields & 0x07) + 1))
        if position >= len(image_bytes):
            return None
        position += 1  # LZW minimum code size
        next_position = skip_sub_blocks(position)
        if next_position is None:
            return None
        position = next_position
    return None


def _has_exact_raster_container_end(image_bytes: bytes, media_type: str) -> bool:
    if media_type == "image/jpeg":
        container_end = _jpeg_container_end(image_bytes)
    elif media_type == "image/png":
        container_end = _png_container_end(image_bytes)
    elif media_type == "image/gif":
        container_end = _gif_container_end(image_bytes)
    else:
        container_end = (
            int.from_bytes(image_bytes[4:8], "little") + 8
            if len(image_bytes) >= 12
            else None
        )
    return container_end == len(image_bytes)


def _validate_raster_image_bytes(
    image_bytes: bytes,
    declared_media_type: str | None,
) -> str:
    detected_media_type = _detect_raster_media_type(image_bytes)
    if detected_media_type is None:
        raise ValueError("image payload is not a supported raster image")
    if declared_media_type is not None:
        normalized_media_type = declared_media_type.strip().lower()
        if normalized_media_type not in _SUPPORTED_IMAGE_MEDIA_TYPES:
            raise ValueError("unsupported image media type")
        if detected_media_type != normalized_media_type:
            raise ValueError("image media type does not match its bytes")

    # Signatures alone are not evidence that bytes form an image.  Reject
    # truncated containers and payloads appended after the format's canonical
    # end before asking Pillow to decode the raster.  This also keeps
    # image-plus-HTML/script polyglots away from external providers.
    if not _has_exact_raster_container_end(image_bytes, detected_media_type):
        raise ValueError("image payload is not a complete raster image")

    pillow_media_types = {
        "JPEG": "image/jpeg",
        "PNG": "image/png",
        "GIF": "image/gif",
        "WEBP": "image/webp",
    }
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(image_bytes)) as image:
                decoded_media_type = pillow_media_types.get(image.format or "")
                image.verify()
            # verify() deliberately does not decode pixels.  Reopen and load
            # every reported frame so malformed compressed data in a later
            # GIF/WebP/APNG frame is rejected as well.
            with Image.open(BytesIO(image_bytes)) as image:
                frame_count = getattr(image, "n_frames", 1)
                if not isinstance(frame_count, int) or frame_count < 1:
                    raise ValueError("image reports an invalid frame count")
                if frame_count > _MAX_IMAGE_FRAMES:
                    raise ValueError("image exceeds maximum allowed frame count")
                for frame_index in range(frame_count):
                    image.seek(frame_index)
                    image.load()
    except (
        OSError,
        EOFError,
        SyntaxError,
        ValueError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise ValueError("image payload is not a decodable raster image") from exc

    if decoded_media_type != detected_media_type:
        raise ValueError("decoded image format does not match its bytes")
    return detected_media_type


def _has_web_search_result(data: dict[str, Any]) -> bool:
    """Return true only when Anthropic reports at least one actual web result."""
    content = data.get("content")
    if not isinstance(content, list):
        return False
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "web_search_tool_result":
            continue
        result_content = block.get("content")
        if not isinstance(result_content, list):
            continue
        if any(_is_valid_web_search_result(item) for item in result_content):
            return True
    return False


def _is_valid_web_search_result(item: Any) -> bool:
    if not isinstance(item, dict) or item.get("type") != "web_search_result":
        return False
    url = item.get("url")
    if not isinstance(url, str):
        return False
    url = url.strip()
    if not url or any(char.isspace() for char in url):
        return False
    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
    except ValueError:
        return False
    return parsed.scheme.lower() in {"http", "https"} and bool(hostname)


async def _fetch_image_as_base64(url: str) -> tuple[str, str]:
    headers = {"User-Agent": "CustomsClear/1.0 (VED classification; +https://github.com/)"}
    current_url = url
    for redirect_count in range(6):
        destination = await _validate_public_image_url(current_url)
        # Connect to the address that was actually validated.  Resolving the
        # hostname again inside the HTTP client would leave a DNS-rebinding
        # window between validation and connection.  Host and SNI preserve
        # normal virtual-host and TLS certificate behavior.
        async with httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=False,
            headers=headers,
            trust_env=False,
        ) as client:
            async with client.stream(
                "GET",
                destination.request_url,
                headers={"Host": destination.host_header},
                extensions={"sni_hostname": destination.sni_hostname},
            ) as resp:
                if resp.status_code in {301, 302, 303, 307, 308}:
                    if redirect_count == 5:
                        raise ValueError("too many image URL redirects")
                    location = resp.headers.get("location")
                    if not location:
                        raise ValueError("image redirect has no destination")
                    current_url = urljoin(current_url, location)
                    # The next loop validates the resolved redirect destination
                    # before issuing another request.
                    continue

                resp.raise_for_status()
                content_type = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
                if content_type not in _SUPPORTED_IMAGE_MEDIA_TYPES:
                    raise ValueError("image URL did not return a supported image content type")

                declared_length = resp.headers.get("content-length")
                if declared_length is not None:
                    try:
                        declared_bytes = int(declared_length)
                    except ValueError as exc:
                        raise ValueError("invalid image content length") from exc
                    if declared_bytes < 0 or declared_bytes > _MAX_IMAGE_BYTES:
                        raise ValueError("image exceeds maximum allowed size")

                chunks: list[bytes] = []
                received_bytes = 0
                async for chunk in resp.aiter_bytes():
                    received_bytes += len(chunk)
                    if received_bytes > _MAX_IMAGE_BYTES:
                        raise ValueError("image exceeds maximum allowed size")
                    chunks.append(chunk)
                image_bytes = b"".join(chunks)
                media_type = _validate_raster_image_bytes(image_bytes, content_type)
                return base64.standard_b64encode(image_bytes).decode("ascii"), media_type

    raise ValueError("image URL could not be fetched")


@dataclass(frozen=True)
class _ValidatedImageDestination:
    request_url: str
    host_header: str
    sni_hostname: str


async def _validate_public_image_url(url: str) -> _ValidatedImageDestination:
    """Reject image URLs that could reach a local or non-public destination."""
    if not url or url != url.strip() or any(char.isspace() for char in url):
        raise ValueError("invalid image URL")
    if "\\" in url or any(ord(char) < 0x20 or ord(char) == 0x7F for char in url):
        raise ValueError("invalid image URL")

    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid image URL") from exc

    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc or not hostname:
        raise ValueError("image URL must use http or https")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("image URL credentials are not allowed")
    if "%" in hostname:
        # Reject percent-encoded numeric hosts and IPv6 zone identifiers.  They
        # are interpreted inconsistently across URL parsers and HTTP clients.
        raise ValueError("encoded image URL host is not allowed")

    normalized_host = hostname.rstrip(".").lower()
    if not normalized_host or normalized_host == "localhost" or normalized_host.endswith(".localhost"):
        raise ValueError("local image URL host is not allowed")

    addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    is_literal = False
    try:
        literal = ipaddress.ip_address(normalized_host)
    except ValueError:
        try:
            lookup_host = normalized_host.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise ValueError("invalid image URL host") from exc
    else:
        _require_public_ip(literal)
        addresses.append(literal)
        lookup_host = normalized_host
        is_literal = True

    if not addresses:
        lookup_port = port or (443 if parsed.scheme.lower() == "https" else 80)
        try:
            answers = await asyncio.to_thread(
                socket.getaddrinfo,
                lookup_host,
                lookup_port,
                type=socket.SOCK_STREAM,
            )
        except OSError as exc:
            raise ValueError("image URL host could not be resolved") from exc
        if not answers:
            raise ValueError("image URL host could not be resolved")

        addresses = []
        for answer in answers:
            try:
                resolved = ipaddress.ip_address(answer[4][0])
            except (IndexError, TypeError, ValueError) as exc:
                raise ValueError("invalid image URL DNS answer") from exc
            _require_public_ip(resolved)
            if resolved not in addresses:
                addresses.append(resolved)

    selected = addresses[0]
    pinned_host = f"[{selected}]" if isinstance(selected, ipaddress.IPv6Address) else str(selected)
    pinned_netloc = f"{pinned_host}:{port}" if port is not None else pinned_host
    host_name = f"[{lookup_host}]" if is_literal and isinstance(selected, ipaddress.IPv6Address) else lookup_host
    host_header = f"{host_name}:{port}" if port is not None else host_name
    return _ValidatedImageDestination(
        request_url=urlunsplit(
            (
                parsed.scheme.lower(),
                pinned_netloc,
                parsed.path or "/",
                parsed.query,
                "",
            )
        ),
        host_header=host_header,
        sni_hostname=lookup_host,
    )


def _require_public_ip(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    if (
        not address.is_global
        or address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_unspecified
        or address.is_multicast
    ):
        raise ValueError("image URL resolved to a non-public address")


_default_classifier: SmartClassifier | None = None


def get_smart_classifier() -> SmartClassifier:
    global _default_classifier
    if _default_classifier is None:
        _default_classifier = SmartClassifier()
    return _default_classifier
