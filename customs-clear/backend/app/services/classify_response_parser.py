"""Разбор ответа LLM-классификатора ТН ВЭД (markdown, RU/EN ключи)."""

from __future__ import annotations

import json
import re
from typing import Any


def _strip_markdown_fences(raw: str) -> str:
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```\s*$", "", text)
    return text.strip()


def _load_json_object(raw: str) -> Any:
    text = _strip_markdown_fences(raw)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group())
        raise ValueError("Не удалось распарсить ответ LLM")


def _extract_results_list(data: Any) -> list[Any]:
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    for key in ("results", "варианты", "codes", "variants", "items"):
        val = data.get(key)
        if isinstance(val, list):
            return val
    return []


def _normalize_hs_code(raw: Any) -> str:
    hs = re.sub(r"\D", "", str(raw or ""))
    return hs if len(hs) == 10 else ""


def _item_confidence(item: dict[str, Any]) -> float:
    for key in ("confidence", "уверенность", "score"):
        val = item.get(key)
        if val is None:
            continue
        try:
            conf = float(val)
            return max(0.0, min(1.0, conf))
        except (TypeError, ValueError):
            continue
    if item.get("рекомендуемый") is True or item.get("recommended") is True:
        return 0.9
    return 0.8


def parse_classify_response(raw: str) -> list[dict[str, Any]]:
    """Нормализует ответ LLM к списку {hs_code, confidence, description, rationale}."""
    data = _load_json_object(raw)
    rows = _extract_results_list(data)
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()

    for row in rows:
        if not isinstance(row, dict):
            continue
        hs = _normalize_hs_code(
            row.get("hs_code")
            or row.get("код_тн_вед")
            or row.get("code")
            or row.get("код")
        )
        if not hs or hs in seen:
            continue
        seen.add(hs)
        normalized.append(
            {
                "hs_code": hs,
                "confidence": _item_confidence(row),
                "description": (
                    row.get("description")
                    or row.get("описание")
                    or row.get("наименование")
                    or row.get("name")
                    or ""
                ).strip(),
                "rationale": (
                    row.get("rationale")
                    or row.get("обоснование")
                    or row.get("reason")
                    or ""
                ).strip(),
            }
        )

    return normalized
