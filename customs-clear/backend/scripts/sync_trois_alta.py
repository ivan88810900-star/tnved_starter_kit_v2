#!/usr/bin/env python3
"""Синхронизация реестра ТРОИС с https://www.alta.ru/rois/all/ → таблица ``trois_registry`` (upsert по reg_number)."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv

load_dotenv(_ROOT / ".env")
load_dotenv()


def main() -> None:
    from loguru import logger

    from app.services.trois_registry_sync import sync_alta_trois_registry

    p = argparse.ArgumentParser(description="Парсинг alta.ru/rois/all и запись в БД trois_registry")
    p.add_argument(
        "--url",
        default=os.getenv("TROIS_ALTA_LIST_URL", "https://www.alta.ru/rois/all/"),
        help="URL списка ТРОИС",
    )
    p.add_argument("--max-pages", type=int, default=int(os.getenv("TROIS_ALTA_MAX_PAGES", "30")), metavar="N")
    p.add_argument("--playwright", action="store_true", help="Сразу использовать Playwright (если anti-bot режет httpx)")
    p.add_argument(
        "--proxy",
        type=str,
        default="",
        help="Опциональный HTTP(S) прокси для загрузки alta.ru (например, http://user:pass@host:port)",
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=float(os.getenv("TROIS_ALTA_TIMEOUT", "90") or "90"),
        help="Таймаут HTTP-запроса (секунды)",
    )
    p.add_argument(
        "--retries",
        type=int,
        default=int(os.getenv("TROIS_ALTA_HTTP_RETRIES", "3") or "3"),
        help="Количество повторов HTTP-запроса",
    )
    args = p.parse_args()

    try:
        stats = sync_alta_trois_registry(
            base_url=args.url,
            max_pages=max(1, args.max_pages),
            prefer_playwright=bool(args.playwright),
            proxy=(args.proxy or "").strip(),
            timeout_sec=max(5.0, float(args.timeout)),
            retries=max(1, int(args.retries)),
        )
    except Exception as e:
        logger.exception("sync_trois_alta: {}", e)
        sys.exit(1)

    print(stats)


if __name__ == "__main__":
    main()
