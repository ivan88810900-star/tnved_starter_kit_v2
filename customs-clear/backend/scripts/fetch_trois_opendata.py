#!/usr/bin/env python3
"""Скачать и импортировать реестр ТРОИС из opendata ФТС."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.opendata_trois import sync_trois_opendata  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--force", action="store_true")
    args = p.parse_args()
    print(json.dumps(sync_trois_opendata(force=args.force), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
