#!/usr/bin/env python3
"""Проверка или запуск безопасных автоматических обновлений нормативных источников."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.regulatory_source_updates import (  # noqa: E402
    build_update_plan,
    run_regulatory_update_cycle,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cadence", choices=("daily", "weekly", "monthly", "all"), default="daily")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check-only", action="store_true", help="Только проверить покрытие (режим по умолчанию)")
    mode.add_argument("--apply-safe", action="store_true", help="Обновить только структурированные официальные источники")
    parser.add_argument("--plan", action="store_true", help="Вывести полный план по всем источникам")
    parser.add_argument("--strict", action="store_true", help="Exit 1 при ошибке адаптера или неполном покрытии")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    if args.plan:
        report = build_update_plan()
        status = "ok" if report["coverage"]["valid"] else "error"
        report["status"] = status
    else:
        report = asyncio.run(
            run_regulatory_update_cycle(args.cadence, apply_safe=bool(args.apply_safe))
        )
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    if args.strict and report.get("status") != "ok":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
