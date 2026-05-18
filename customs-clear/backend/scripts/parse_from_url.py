from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import google.generativeai as genai

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db import SessionLocal
from app.models.tnved import Commodity, NonTariffMeasure
from app.services.gemini_genai_configure import configure_google_generativeai

LOGGER = logging.getLogger("parse_from_url")
ALLOWED_MEASURE_TYPES = {
    "ban",
    "license",
    "certificate",
    "vet_control",
    "phyto_control",
    "other",
}
PROMPT = (
    "Ты — парсер таможенных данных. Твоя задача — найти в тексте привязки кодов ТН ВЭД "
    "(4, 6 или 10 знаков) к мерам нетарифного регулирования (запреты, лицензии, сертификаты). "
    "Верни СТРОГО валидный JSON-массив объектов. Ключи объекта: hs_code (строка, только цифры), "
    "measure_type (одно из: 'ban', 'license', 'certificate', 'vet_control', 'phyto_control', 'other'), "
    "document_required (строка, название требуемого документа), description (краткое описание требования), "
    "regulatory_act (название документа/закона из текста). Если кодов нет, верни пустой массив []. "
    "Никакого текста кроме JSON!"
)
MODEL_CANDIDATES = [
    "gemini-1.5-flash",
    "gemini-1.5-flash-latest",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-1.5-pro",
]


def fetch_and_clean_html(url: str) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Connection": "keep-alive",
    }
    with httpx.Client(headers=headers, follow_redirects=True, timeout=45.0) as client:
        resp = client.get(url)
        resp.raise_for_status()
        html = resp.text

    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()

    for selector in ["header", "footer", "nav", "aside", ".menu", ".navbar", ".breadcrumbs", ".sidebar"]:
        for el in soup.select(selector):
            el.decompose()

    main_content = None
    for selector in ["article", "main", ".document-text", ".article-content", ".content", ".entry-content"]:
        candidate = soup.select_one(selector)
        if candidate and candidate.get_text(strip=True):
            main_content = candidate
            break
    if main_content is None:
        main_content = soup.body or soup

    text = main_content.get_text("\n", strip=True)
    text = re.sub(r"\n{2,}", "\n\n", text)
    return text.strip()


def _normalize_code(raw: object) -> str:
    code = re.sub(r"\D", "", str(raw or ""))
    return code if len(code) in (4, 6, 10) else ""


def _extract_json_payload(raw: str) -> str:
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    if text.startswith("[") and text.endswith("]"):
        return text
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    raise ValueError("В ответе Gemini не найден JSON-массив")


def _split_text_into_chunks(text: str, max_chars: int = 50_000) -> list[str]:
    source = (text or "").strip()
    if not source:
        return []
    if len(source) <= max_chars:
        return [source]

    chunks: list[str] = []
    start = 0
    total = len(source)
    while start < total:
        end = min(start + max_chars, total)
        if end < total:
            newline_pos = source.rfind("\n", start, end)
            if newline_pos != -1 and newline_pos > start + 5000:
                end = newline_pos
        chunk = source[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end
    return chunks


def extract_measures_with_ai(text: str, model_name: str = "gemini-1.5-flash") -> list[dict]:
    api_key = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("Не задан GEMINI_API_KEY или GOOGLE_API_KEY в окружении/.env")

    configure_google_generativeai(genai, api_key=api_key)
    candidates = [model_name] + [m for m in MODEL_CANDIDATES if m != model_name]
    chunks = _split_text_into_chunks(text, max_chars=50_000)
    if not chunks:
        return []

    all_items: list[dict] = []
    if len(chunks) > 1:
        LOGGER.info("Текст большой, включен чанкинг: %s частей", len(chunks))

    selected_model_name = candidates[0]
    model = genai.GenerativeModel(selected_model_name)

    for idx, chunk in enumerate(chunks, start=1):
        if len(chunks) > 1:
            LOGGER.info("[INFO] Обработка части %s из %s...", idx, len(chunks))
        response = None
        last_exc: Exception | None = None
        for candidate in candidates:
            try:
                if candidate != selected_model_name:
                    LOGGER.info("Switch model fallback: %s", candidate)
                    model = genai.GenerativeModel(candidate)
                    selected_model_name = candidate
                response = model.generate_content(
                    f"{PROMPT}\n\nЧасть {idx} из {len(chunks)}. Текст документа:\n{chunk}",
                    generation_config={"temperature": 0.0},
                )
                break
            except Exception as exc:
                last_exc = exc
                msg = str(exc).lower()
                if "not found" in msg or "not supported" in msg or "model" in msg:
                    continue
                raise
        if response is None:
            if last_exc is not None:
                raise last_exc
            raise RuntimeError("Не удалось получить ответ от Gemini")
        raw = (getattr(response, "text", "") or "").strip()
        payload = _extract_json_payload(raw)
        data = json.loads(payload)
        if not isinstance(data, list):
            raise ValueError(f"Gemini вернул не массив JSON в части {idx}")
        all_items.extend(data)

        if idx < len(chunks):
            # Пауза между запросами для снижения риска 429.
            time.sleep(3)

    return all_items


def extract_measures_fallback(text: str) -> list[dict]:
    """
    Аварийный режим без LLM:
    достаём встреченные 4/6/10-значные коды ТН ВЭД регулярным выражением.
    """
    pattern = re.compile(r"(?<!\d)(\d{4}(?:\s?\d{2})?(?:\s?\d{3}\s?\d)?)")
    seen: set[str] = set()
    items: list[dict] = []
    for m in pattern.finditer(text):
        raw = re.sub(r"\D", "", m.group(1))
        if len(raw) not in (4, 6, 10):
            continue
        if raw in seen:
            continue
        seen.add(raw)
        items.append(
            {
                "hs_code": raw,
                "measure_type": "certificate",
                "document_required": "Сертификат или декларация о соответствии",
                "description": "Извлечено в fallback-режиме без LLM; требуется валидация формулировки.",
                "regulatory_act": "Решение Коллегии ЕЭК № 30",
            }
        )
    return items


def _expand_targets(code: str, all_codes: set[str], leaf_codes: list[str]) -> list[str]:
    if code in all_codes:
        return [code]
    if len(code) in (4, 6):
        return [c for c in leaf_codes if c.startswith(code)]
    return []


def save_measures_to_db(items: list[dict], source_url: str) -> dict[str, int]:
    inserted = 0
    invalid = 0
    no_targets = 0
    duplicates = 0
    expanded = 0
    batch: list[NonTariffMeasure] = []

    with SessionLocal() as db:
        all_codes = {c[0] for c in db.query(Commodity.code).all()}
        leaf_codes = [c for c in all_codes if len(c) == 10]
        existing_keys = {
            (
                m.commodity_code,
                (m.measure_type or "").strip().lower(),
                (m.regulatory_act or "").strip(),
            )
            for m in db.query(NonTariffMeasure).all()
        }
        staged_keys: set[tuple[str, str, str]] = set()

        for obj in items:
            code = _normalize_code(obj.get("hs_code"))
            mtype = str(obj.get("measure_type", "")).strip().lower()
            doc = str(obj.get("document_required", "")).strip()
            desc = str(obj.get("description", "")).strip()
            act = str(obj.get("regulatory_act", "")).strip() or f"Источник: {source_url}"

            if not code or not mtype:
                invalid += 1
                continue
            if mtype not in ALLOWED_MEASURE_TYPES:
                mtype = "other"

            targets = _expand_targets(code, all_codes, leaf_codes)
            if not targets:
                no_targets += 1
                continue
            if code not in all_codes and len(code) in (4, 6):
                expanded += 1

            for target in targets:
                key = (target, mtype, act)
                if key in existing_keys or key in staged_keys:
                    duplicates += 1
                    continue
                staged_keys.add(key)
                batch.append(
                    NonTariffMeasure(
                        commodity_code=target,
                        measure_type=mtype,
                        document_required=doc,
                        description=desc,
                        regulatory_act=act,
                    )
                )

        if batch:
            db.bulk_save_objects(batch)
            db.commit()
            inserted = len(batch)

    return {
        "inserted": inserted,
        "invalid": invalid,
        "no_targets": no_targets,
        "duplicates": duplicates,
        "expanded": expanded,
    }


def _cache_raw_html(url: str, html: str, cache_dir: Path) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    slug = Path(urlparse(url).path).name or "document"
    safe_name = re.sub(r"[^a-zA-Z0-9._-]+", "_", slug)
    path = cache_dir / f"{safe_name}.html"
    path.write_text(html, encoding="utf-8")
    return path


def parse_url_to_db(url: str) -> None:
    LOGGER.info("Fetch URL: %s", url)
    clean_text = fetch_and_clean_html(url)
    LOGGER.info("Clean text length: %s chars", len(clean_text))

    if len(clean_text) < 200:
        LOGGER.warning("Очень короткий текст после очистки; проверьте селекторы страницы")

    items = extract_measures_with_ai(clean_text)
    LOGGER.info("AI extracted objects: %s", len(items))
    stats = save_measures_to_db(items, source_url=url)
    LOGGER.info("Saved to DB: %s", stats)


def main() -> None:
    parser = argparse.ArgumentParser(description="Парсинг нетарифных мер из URL через Gemini.")
    parser.add_argument("url", type=str, help="URL нормативного документа (например, alta.ru)")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    parser.add_argument(
        "--cache-html",
        action="store_true",
        help="Сохранить сырой HTML в downloads/url_cache",
    )
    parser.add_argument(
        "--save-raw-json",
        action="store_true",
        help="Сохранить JSON от ИИ в downloads/raw_extracted.json и не писать в БД",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    load_dotenv(ROOT / ".env")

    try:
        if args.cache_html:
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
            with httpx.Client(headers=headers, follow_redirects=True, timeout=45.0) as client:
                html_resp = client.get(args.url)
                html_resp.raise_for_status()
                saved = _cache_raw_html(args.url, html_resp.text, ROOT / "downloads" / "url_cache")
                LOGGER.info("Raw HTML cached to: %s", saved)

        clean_text = fetch_and_clean_html(args.url)
        LOGGER.info("Clean text length: %s chars", len(clean_text))
        if len(clean_text) < 200:
            LOGGER.warning("Очень короткий текст после очистки; проверьте селекторы страницы")

        try:
            items = extract_measures_with_ai(clean_text)
        except Exception as exc:
            LOGGER.warning(
                "Gemini недоступен (%s). Использую fallback-извлечение без LLM.",
                exc,
            )
            items = extract_measures_fallback(clean_text)
        LOGGER.info("AI extracted objects: %s", len(items))

        if args.save_raw_json:
            out = (ROOT / "downloads" / "raw_extracted.json").resolve()
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
            LOGGER.info("Raw JSON saved to: %s", out)
            return

        stats = save_measures_to_db(items, source_url=args.url)
        LOGGER.info("Saved to DB: %s", stats)
    except httpx.HTTPError as exc:
        LOGGER.error("Ошибка скачивания документа: %s", exc)
        raise SystemExit(1)
    except json.JSONDecodeError as exc:
        LOGGER.error("Gemini вернул невалидный JSON: %s", exc)
        raise SystemExit(1)
    except Exception as exc:
        LOGGER.exception("Ошибка выполнения parse_from_url: %s", exc)
        raise SystemExit(1)


if __name__ == "__main__":
    main()

