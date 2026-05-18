#!/usr/bin/env python3
"""
Автономный асинхронный краулер исторической нормативной базы ВЭД.

- Обходит открытые страницы (по умолчанию хосты из seed URL), пагинация через BFS.
- Находит ссылки на приказы / решения / письма / PDF / DOCX / HTML.
- Скачивает документ, извлекает текст (httpx или Playwright), передаёт в Gemini и UPSERT в БД
  (тот же пайплайн, что и bulk_ai_importer: apply_structured_rows).

Паузы:
- между HTTP-запросами: --http-delay (по умолчанию из HISTORICAL_CRAWLER_HTTP_DELAY или 2 с);
- между вызовами LLM: --llm-delay / HISTORICAL_CRAWLER_LLM_DELAY (по умолчанию 4 с);
- при 429 / google.api_core.exceptions.ResourceExhausted от Gemini — пауза минимум 60 с и повтор
  внутри call_gemini_with_throttle (app.services.bulk_normative_ai), скрипт не падает на rate limit.

Перед первым использованием Playwright:
  pip install playwright && playwright install chromium

Примеры:
  python3 scripts/historical_crawler.py --year-from 2018 --year-to 2024 --max-pages 15
  python3 scripts/historical_crawler.py --seeds https://eec.eaeunion.org/comission/department/catr/ett/ \\
      --allowed-hosts eec.eaeunion.org --use-playwright
  python3 scripts/historical_crawler.py --seeds 'https://docs.eaeunion.org/ru-ru/' \\
      --require-path '/ru-ru/' --allowed-hosts docs.eaeunion.org --use-playwright
"""

from __future__ import annotations

# Загрузка .env до любых импортов приложения (GEMINI_API_KEY и др.)
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_ROOT / ".env")
load_dotenv()

import argparse
import asyncio
import os
import sys

ROOT = _ROOT
sys.path.insert(0, str(ROOT))

from app.db import SessionLocal  # noqa: E402
from app.models import HistoricalCrawlCheckpoint  # noqa: E402
from app.services.historical_crawler_engine import (  # noqa: E402
    CrawlerSettings,
    run_historical_crawl,
    settings_from_env,
)


def _print_progress(info: dict) -> None:
    idx = info.get("document_index", 0)
    url = info.get("url", "")
    m = info.get("measures", 0)
    st = info.get("last_status", "")
    err = (info.get("last_error") or "")[:160]
    extra = f" [{err}]" if err else ""
    print(f"#{idx} {st} measures_total={m} {url}{extra}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Исторический краулер нормативки + ИИ в БД")
    parser.add_argument("--year-from", type=int, default=None)
    parser.add_argument("--year-to", type=int, default=None)
    parser.add_argument("--http-delay", type=float, default=None)
    parser.add_argument("--llm-delay", type=float, default=None)
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument("--max-documents", type=int, default=None)
    parser.add_argument("--depth", type=int, default=None)
    parser.add_argument("--strict-years", action="store_true", help="Отбирать только ссылки, где в тексте/URL есть год из диапазона")
    parser.add_argument("--use-playwright", action="store_true")
    parser.add_argument("--seeds", nargs="*", default=None, help="Стартовые URL (иначе HISTORICAL_CRAWLER_SEEDS или встроенные)")
    parser.add_argument(
        "--allowed-hosts",
        nargs="*",
        default=None,
        help="Ограничить обход этими хостами (без схемы), иначе только хосты из seeds",
    )
    parser.add_argument(
        "--require-path",
        default=None,
        metavar="SUBSTRING",
        help='Игнорировать ссылки, в URL-пути которых нет подстроки (например: "/ru-ru/")',
    )
    parser.add_argument("--reset-checkpoints", action="store_true", help="Очистить historical_crawl_checkpoints перед запуском")
    parser.add_argument("--skip-checkpoint", action="store_true", help="Игнорировать чекпоинты для документов")
    args = parser.parse_args()

    if args.reset_checkpoints:
        with SessionLocal() as db:
            n = db.query(HistoricalCrawlCheckpoint).delete()
            db.commit()
            print(f"Удалено чекпоинтов краулера: {n}", flush=True)

    allowed: set[str] | None = None
    if args.allowed_hosts:
        allowed = {h.strip().lower().split(":")[0] for h in args.allowed_hosts if h.strip()}

    base = settings_from_env(
        year_from=args.year_from,
        year_to=args.year_to,
        http_delay=args.http_delay,
        llm_delay=args.llm_delay,
        max_pages=args.max_pages,
        max_documents=args.max_documents,
        depth=args.depth,
        strict_years=True if args.strict_years else None,
        use_playwright=True if args.use_playwright else None,
        seeds=list(args.seeds) if args.seeds else None,
        require_path=args.require_path,
    )
    settings = CrawlerSettings(
        year_from=base.year_from,
        year_to=base.year_to,
        http_delay_sec=base.http_delay_sec,
        llm_delay_sec=base.llm_delay_sec,
        max_pages=base.max_pages,
        max_documents=base.max_documents,
        crawl_depth=base.crawl_depth,
        strict_years=base.strict_years,
        use_playwright=args.use_playwright or base.use_playwright,
        seed_urls=base.seed_urls,
        allowed_hosts=allowed if allowed is not None else base.allowed_hosts,
        require_path=base.require_path,
    )

    if not os.getenv("GEMINI_API_KEY") and not os.getenv("GOOGLE_API_KEY"):
        print("Ошибка: задайте GEMINI_API_KEY или GOOGLE_API_KEY для вызова LLM.", flush=True)
        raise SystemExit(2)

    print(
        "LLM: при 429/ResourceExhausted — ожидание ≥60 с и повтор (bulk_normative_ai.call_gemini_with_throttle).",
        flush=True,
    )
    print(
        f"Параметры: years={settings.year_from}-{settings.year_to}, http_delay={settings.http_delay_sec}s, "
        f"llm_delay={settings.llm_delay_sec}s, max_pages={settings.max_pages}, max_docs={settings.max_documents}, "
        f"depth={settings.crawl_depth}, playwright={settings.use_playwright}, strict_years={settings.strict_years}, "
        f"require_path={settings.require_path or '—'}",
        flush=True,
    )
    print(f"Seeds: {settings.seed_urls or '(defaults)'}", flush=True)

    summary = asyncio.run(
        run_historical_crawl(settings, skip_checkpoint=args.skip_checkpoint, progress_cb=_print_progress)
    )
    print("Итог:", summary, flush=True)


if __name__ == "__main__":
    main()
