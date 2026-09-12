#!/usr/bin/env python3
"""Read-only commercial TWS candidate inspection.

  python3 scripts/sync_tws_data.py --dry-run --limit 500

The default historical apply invocation returns manual_review_required with exit
code 2, before download, DB initialization or writes. A dry-run retains technical
counts only; missing rates are unavailable and never receive an invented default.
Original official artifacts and manifest-bound review are still required.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv

load_dotenv(_ROOT / ".env")
load_dotenv()


def main() -> int:
    parser = argparse.ArgumentParser(description="Технический разбор tws.by; применение legacy ставок закрыто")
    parser.add_argument("--dry-run", action="store_true", help="Скачать и разобрать, без записи в БД")
    parser.add_argument("--limit", type=int, default=None, help="Максимум строк для технического разбора")
    args = parser.parse_args()

    from app.services.regulatory_sync import run_tws_tariff_sync

    out = run_tws_tariff_sync(dry_run=args.dry_run, limit=args.limit)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if args.dry_run else 2


if __name__ == "__main__":
    raise SystemExit(main())
