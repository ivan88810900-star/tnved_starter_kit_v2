#!/usr/bin/env python3
"""Verify semantic-search and optional-LLM readiness without exposing secrets."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.optional_ai_readiness import build_optional_ai_readiness_report  # noqa: E402


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, help="Write the aggregate JSON report here.")
    parser.add_argument(
        "--live-llm",
        action="store_true",
        help="Make one synthetic external LLM request (may consume provider quota).",
    )
    parser.add_argument(
        "--live-embedding",
        action="store_true",
        help="Make one synthetic OpenAI embedding request (may consume provider quota).",
    )
    parser.add_argument(
        "--allow-external-ai",
        action="store_true",
        help="Required acknowledgement for either live check.",
    )
    return parser.parse_args(argv)


async def _run(args: argparse.Namespace) -> int:
    live_requested = bool(args.live_llm or args.live_embedding)
    if live_requested and not args.allow_external_ai:
        print("Live checks require --allow-external-ai; no external request was made.", file=sys.stderr)
        return 2
    report = await build_optional_ai_readiness_report(
        live_llm=bool(args.live_llm),
        live_embedding=bool(args.live_embedding),
    )
    output = json.dumps(report, ensure_ascii=False, indent=2)
    print(output)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(output + "\n", encoding="utf-8")
    return 0 if report["ok"] else 1


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_run(_parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
