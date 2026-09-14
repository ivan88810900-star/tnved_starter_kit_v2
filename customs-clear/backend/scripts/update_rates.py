from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.exchange_rates import update_exchange_rates_from_cbrf, validate_cbr_rates_source


async def _main() -> int:
    parser = argparse.ArgumentParser(description="Update official CBR exchange rates")
    parser.add_argument("--strict", action="store_true", help="Fail instead of applying fallback constants")
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Fetch and validate the canonical CBR payload without database writes",
    )
    parser.add_argument("--json", action="store_true", help="Emit the adapter result contract")
    args = parser.parse_args()
    result = (
        await validate_cbr_rates_source()
        if args.validate_only
        else await update_exchange_rates_from_cbrf(allow_fallback=not args.strict)
    )
    official_ok = (
        result.get("status") == "OK"
        and result.get("source") == "CBRF"
        and (args.validate_only or result.get("provenance_recorded") is True)
    )
    payload = {
        "status": "ok" if official_ok else "error",
        "source_ids": ["cbr_exchange_rates"],
        "official_source": bool(official_ok),
        "date": result.get("date"),
        "rows_applied": int(result.get("updated") or 0),
        "rows_validated": int(result.get("validated") or 0),
        "execution_mode": "validation_only" if args.validate_only else "apply",
        "details": result,
    }
    print(
        "update_rates:",
        f"status={result.get('status')}",
        f"source={result.get('source')}",
        f"date={result.get('date')}",
        f"updated={result.get('updated')}",
    )
    if args.json:
        print("REGULATORY_SYNC_RESULT=" + json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    fail_closed = args.strict or args.validate_only
    return 0 if official_ok or not fail_closed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
