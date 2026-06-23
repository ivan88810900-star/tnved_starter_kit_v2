#!/usr/bin/env python3
"""Скачать и импортировать реестры СС/ДС Росаккредитации из opendata."""

from __future__ import annotations

import argparse
import atexit
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.opendata_fsa import sync_fsa_certificates  # noqa: E402

PID_FILE = ROOT / "logs" / "fsa_backfill.pid"


def _write_pid() -> None:
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")


def _remove_pid() -> None:
    try:
        PID_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--force", action="store_true")
    p.add_argument("--backfill-all", action="store_true", help="All monthly 7z from meta.xml")
    args = p.parse_args()
    if args.backfill_all:
        _write_pid()
        atexit.register(_remove_pid)
    print(json.dumps(sync_fsa_certificates(backfill_all=args.backfill_all, force=args.force), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
