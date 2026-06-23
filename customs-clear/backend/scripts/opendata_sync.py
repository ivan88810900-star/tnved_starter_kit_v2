#!/usr/bin/env python3
"""Единый загрузчик официальных открытых данных: TROIS, ФСА, справочники ФТС."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.opendata_customs import sync_customs_catalog, sync_mask44  # noqa: E402
from app.services.opendata_fsa import sync_fsa_certificates  # noqa: E402
from app.services.opendata_trois import sync_trois_opendata  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync official opendata registries into local DB")
    parser.add_argument(
        "--source",
        choices=("trois", "fsa", "customs", "all"),
        default="all",
        help="Which source to sync",
    )
    parser.add_argument("--all", action="store_true", help="Alias for --source all")
    parser.add_argument("--force", action="store_true", help="Re-import even if snapshot already loaded")
    parser.add_argument(
        "--fsa-backfill",
        action="store_true",
        help="Import all monthly FSA 7z archives from meta.xml (large, slow)",
    )
    args = parser.parse_args()
    source = "all" if args.all else args.source
    out: dict = {}

    if source in ("trois", "all"):
        out["trois"] = sync_trois_opendata(force=args.force)
    if source in ("fsa", "all"):
        out["fsa"] = sync_fsa_certificates(backfill_all=args.fsa_backfill, force=args.force)
    if source in ("customs", "all"):
        out["mask44"] = sync_mask44(force=args.force)
        out["catalog"] = sync_customs_catalog()

    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
