"""Классификатор ТН ВЭД: локальный ONNX (опц.) и/или HTTP — до или вместо LLM."""
from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Any, Dict, List, Optional

import httpx
from loguru import logger

CUSTOM_CLASSIFIER_URL = os.getenv("CUSTOM_CLASSIFIER_URL", "").strip()
CUSTOM_CLASSIFIER_API_KEY = os.getenv("CUSTOM_CLASSIFIER_API_KEY", "").strip()
CUSTOM_CLASSIFIER_ENABLED = os.getenv("CUSTOM_CLASSIFIER_ENABLED", "").lower() in ("1", "true", "yes")
# first_custom | first_llm | custom_only
CUSTOM_CLASSIFIER_MODE = os.getenv("CUSTOM_CLASSIFIER_MODE", "first_custom").strip().lower()
CUSTOM_CLASSIFIER_TIMEOUT = float(os.getenv("CUSTOM_CLASSIFIER_TIMEOUT", "45"))
# JSON-шаблон тела POST: подставьте %s под JSON-строку описания, напр. {"text": %s}
CUSTOM_CLASSIFIER_BODY_TEMPLATE = os.getenv("CUSTOM_CLASSIFIER_BODY_TEMPLATE", "").strip()


def _onnx_ready() -> bool:
    try:
        from .onnx_hs_classifier import is_onnx_classifier_configured

        return bool(is_onnx_classifier_configured())
    except Exception:
        return False


def _digits_hs(s: str) -> str:
    return re.sub(r"\D", "", (s or ""))[:10]


def _normalize_external_response(data: Any, description: str) -> Optional[Dict[str, Any]]:
    """Преобразует типичные ответы API в формат UI (поле code в results)."""
    if not isinstance(data, dict):
        return None
    codes: List[tuple[str, float, str]] = []
    # Один код
    for key in ("hs_code", "code", "tnved", "recommended_hs"):
        raw = data.get(key)
        if raw is not None:
            d = _digits_hs(str(raw))
            if len(d) >= 4:
                codes.append((d.ljust(10, "0")[:10], 0.9, f"поле {key}"))
            break
    rec = data.get("recommended")
    if isinstance(rec, dict):
        d = _digits_hs(str(rec.get("hs_code") or rec.get("code") or ""))
        if len(d) >= 4:
            codes.append((d.ljust(10, "0")[:10], float(rec.get("confidence") or 0.95), "recommended"))
    for r in data.get("results") or data.get("variants") or []:
        if not isinstance(r, dict):
            continue
        d = _digits_hs(str(r.get("hs_code") or r.get("code") or ""))
        if len(d) >= 4:
            conf = float(r.get("confidence") or 0.7)
            codes.append((d.ljust(10, "0")[:10], conf, str(r.get("reasoning") or "")))
    if not codes:
        return None
    # уникальные по коду, лучший confidence
    best: dict[str, tuple[float, str]] = {}
    for c, conf, reason in codes:
        if c not in best or conf > best[c][0]:
            best[c] = (conf, reason)
    results = []
    for i, (code, (conf, reasoning)) in enumerate(sorted(best.items(), key=lambda x: -x[1][0])):
        results.append(
            {
                "code": code,
                "name": data.get("name") or "Внешний классификатор",
                "duty_rate": str(data.get("duty_rate") or "n/a"),
                "permits": data.get("permits") if isinstance(data.get("permits"), list) else [],
                "confidence": round(min(conf, 1.0), 3),
                "recommended": i == 0,
                "reasoning": reasoning or data.get("note") or "Ответ внешнего сервиса",
            }
        )
    return {
        "status": "OK",
        "query": description,
        "classifier_source": "custom_http",
        "results": results[:8],
        "note": data.get("note"),
    }


async def _call_onnx_classifier(description: str) -> Optional[Dict[str, Any]]:
    if not _onnx_ready():
        return None
    try:
        from .onnx_hs_classifier import run_classify
    except ImportError:
        return None
    return await asyncio.to_thread(run_classify, description)


async def call_custom_classifier(description: str) -> Optional[Dict[str, Any]]:
    """Сначала локальный ONNX (если настроен), затем HTTP POST на CUSTOM_CLASSIFIER_URL."""
    desc = (description or "").strip()
    if len(desc) < 3:
        return None
    onnx_out = await _call_onnx_classifier(desc)
    if onnx_out and onnx_out.get("results"):
        return onnx_out
    if not CUSTOM_CLASSIFIER_ENABLED or not CUSTOM_CLASSIFIER_URL:
        return None
    headers = {"Content-Type": "application/json"}
    if CUSTOM_CLASSIFIER_API_KEY:
        headers["Authorization"] = f"Bearer {CUSTOM_CLASSIFIER_API_KEY}"
    if CUSTOM_CLASSIFIER_BODY_TEMPLATE:
        try:
            if "%s" in CUSTOM_CLASSIFIER_BODY_TEMPLATE:
                body = json.loads(CUSTOM_CLASSIFIER_BODY_TEMPLATE % json.dumps(desc, ensure_ascii=False))
            else:
                body = json.loads(CUSTOM_CLASSIFIER_BODY_TEMPLATE)
        except (json.JSONDecodeError, TypeError, ValueError):
            body = {"description": desc, "query": desc, "text": desc}
    else:
        body = {"description": desc, "query": desc, "text": desc}
    try:
        async with httpx.AsyncClient(timeout=CUSTOM_CLASSIFIER_TIMEOUT) as client:
            r = await client.post(CUSTOM_CLASSIFIER_URL, json=body, headers=headers)
        r.raise_for_status()
        payload = r.json()
    except Exception as e:
        logger.warning(f"Custom classifier HTTP error: {e}")
        return None
    return _normalize_external_response(payload, desc)


def should_try_custom_before_llm() -> bool:
    if CUSTOM_CLASSIFIER_MODE not in ("first_custom", "custom_only"):
        return False
    return _onnx_ready() or (CUSTOM_CLASSIFIER_ENABLED and bool(CUSTOM_CLASSIFIER_URL))


def is_custom_only_mode() -> bool:
    if CUSTOM_CLASSIFIER_MODE != "custom_only":
        return False
    return _onnx_ready() or (CUSTOM_CLASSIFIER_ENABLED and bool(CUSTOM_CLASSIFIER_URL))


def should_try_custom_after_llm() -> bool:
    if CUSTOM_CLASSIFIER_MODE != "first_llm":
        return False
    return _onnx_ready() or (CUSTOM_CLASSIFIER_ENABLED and bool(CUSTOM_CLASSIFIER_URL))
