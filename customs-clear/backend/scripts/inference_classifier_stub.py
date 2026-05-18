#!/usr/bin/env python3
"""Минимальный HTTP-классификатор для проверки интеграции CUSTOM_CLASSIFIER_*.

Не для прода: эвристики по ключевым словам. Реальная модель — отдельный сервис (ONNX/Triton и т.д.).

Запуск из каталога backend::

    PYTHONPATH=. python scripts/inference_classifier_stub.py

По умолчанию: http://127.0.0.1:8765/classify

Переменные окружения:
  INFERENCE_STUB_HOST, INFERENCE_STUB_PORT
  INFERENCE_STUB_API_KEY — если задан, нужен заголовок Authorization: Bearer …
"""
from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException, Request
app = FastAPI(title="Inference classifier stub", version="0.1.0")


def _text_from_raw(raw: dict) -> str:
    if not isinstance(raw, dict):
        return ""
    for k in ("description", "query", "text"):
        v = raw.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _guess_codes(text: str) -> list[dict]:
    low = text.lower()
    out: list[dict] = []
    rules = [
        (("пылесос", "vacuum", "vacuum cleaner"), "8509400000", "Пылесосы электрические"),
        (("чайник", "kettle", "электрочайник"), "8516108000", "Электрочайники"),
        (("телефон", "smartphone", "смартфон"), "8517620003", "Телефоны"),
        (("пиво", "beer"), "2203001000", "Пиво"),
        (("кофе", "coffee"), "0901210001", "Кофе не жареный"),
    ]
    seen: set[str] = set()
    for keys, code, name in rules:
        if any(k in low for k in keys) and code not in seen:
            seen.add(code)
            conf = 0.75 + 0.05 * len(out)
            out.append(
                {
                    "code": code,
                    "name": name,
                    "duty_rate": "n/a",
                    "permits": [],
                    "confidence": min(conf, 0.95),
                    "recommended": len(out) == 0,
                    "reasoning": f"stub: совпадение по словарю ({keys[0]})",
                }
            )
    for i, r in enumerate(out):
        r["recommended"] = i == 0
    return out


@app.get("/health")
def health() -> dict:
    return {"status": "OK"}


@app.post("/classify")
async def classify(request: Request) -> dict:
    key = os.getenv("INFERENCE_STUB_API_KEY", "").strip()
    if key:
        auth = (request.headers.get("authorization") or "").strip()
        if auth != f"Bearer {key}":
            raise HTTPException(status_code=401, detail="Неверный или отсутствующий Bearer-токен")

    try:
        raw = await request.json()
    except Exception:
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    text = _text_from_raw(raw)

    if len(text) < 2:
        return {
            "status": "OK",
            "query": text,
            "results": [],
            "classifier_source": "stub",
            "note": "Пустой или слишком короткий запрос",
        }

    results = _guess_codes(text)
    return {
        "status": "OK",
        "query": text[:500],
        "results": results,
        "classifier_source": "stub",
        "note": None if results else "stub: нет совпадений по словарю",
    }


def main() -> None:
    import uvicorn

    host = os.getenv("INFERENCE_STUB_HOST", "127.0.0.1")
    port = int(os.getenv("INFERENCE_STUB_PORT", "8765"))
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
