#!/usr/bin/env python3
"""Загрузка открытого реестра ТРОИС (#151): customs.gov.ru/folder/14344 + alta fallback."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv

load_dotenv(_ROOT / ".env")
load_dotenv()


def main() -> None:
    from loguru import logger

    from app.services.trois_fts_fetch import fetch_fts_trois_open_data
    from app.services.trois_registry_loader import export_db_brands_json, sync_db_to_local_cache
    from app.services.trois_registry_sync import sync_alta_trois_registry
    from app.services.trois_service import get_trois_local_cache_stats

    p = argparse.ArgumentParser(description="Fetch TROIS open data → trois_registry + in-memory cache")
    p.add_argument("--skip-fts", action="store_true", help="Не обращаться к customs.gov.ru")
    p.add_argument("--alta", action="store_true", help="Дополнительно синхронизировать alta.ru/rois")
    p.add_argument("--alta-max-pages", type=int, default=10)
    args = p.parse_args()

    if not args.skip_fts:
        fts = fetch_fts_trois_open_data()
        logger.info("FTS fetch: {}", fts)

    if args.alta:
        alta = sync_alta_trois_registry(max_pages=args.alta_max_pages)
        logger.info("Alta sync: {}", alta)

    added = sync_db_to_local_cache(force=True)
    exported = export_db_brands_json()
    stats = get_trois_local_cache_stats()
    logger.info(
        "TROIS registry reload: cache_added={} exported={} stats={}",
        added,
        exported,
        stats,
    )
    print(stats)


if __name__ == "__main__":
    main()
