#!/usr/bin/env python3
"""CLI: системный краулер решений ФТС (Issue #143).

Запуск из customs-clear/backend::

  PYTHONPATH=. python3 scripts/crawl_fts_rulings.py
  PYTHONPATH=. python3 scripts/crawl_fts_rulings.py --dry-run --max-pages 3
  PYTHONPATH=. python3 scripts/crawl_fts_rulings.py --start-url https://customs.gov.ru/folder/519
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from app.services.fts_rulings_crawler import DEFAULT_START_URL, run_fts_crawl  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Crawl FTS rulings from customs.gov.ru folder")
    ap.add_argument("--start-url", default=DEFAULT_START_URL)
    ap.add_argument("--max-pages", type=int, default=20)
    ap.add_argument("--max-documents", type=int, default=200)
    ap.add_argument("--no-ai", action="store_true", help="Disable AI HS fallback")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    result = asyncio.run(
        run_fts_crawl(
            start_url=args.start_url,
            max_pages=args.max_pages,
            max_documents=args.max_documents,
            use_ai_fallback=not args.no_ai,
            dry_run=args.dry_run,
        )
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") in ("OK", "PARTIAL") else 1


if __name__ == "__main__":
    raise SystemExit(main())
