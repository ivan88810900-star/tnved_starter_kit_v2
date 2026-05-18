from __future__ import annotations

import asyncio
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.normative_store import init_db
from app.services.preview_cache_revision import bump_preview_cache_revision
from app.services.trois_sync import sync_trois_sources


async def _run(*, proxy: str = "") -> None:
    result = await sync_trois_sources(proxy=proxy)
    print(result)
    bump_preview_cache_revision("sync_trois")


def main() -> None:
    ap = argparse.ArgumentParser(description="Синхронизация ТРОИС (alta + customs) в intellectual_properties")
    ap.add_argument(
        "--proxy",
        type=str,
        default="",
        help="Опциональный HTTP(S) прокси для загрузки источников ТРОИС",
    )
    args = ap.parse_args()
    init_db()
    asyncio.run(_run(proxy=(args.proxy or "").strip()))


if __name__ == "__main__":
    main()
