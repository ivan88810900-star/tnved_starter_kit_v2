from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.exchange_rates import update_exchange_rates_from_cbrf


async def _main() -> None:
    result = await update_exchange_rates_from_cbrf()
    print(
        "update_rates:",
        f"status={result.get('status')}",
        f"source={result.get('source')}",
        f"date={result.get('date')}",
        f"updated={result.get('updated')}",
    )


if __name__ == "__main__":
    asyncio.run(_main())

