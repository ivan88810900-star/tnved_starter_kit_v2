#!/usr/bin/env python3
"""
Добавить демо-записи в журнал решений из customs-clear/docs/samples/user_decisions.jsonl.example.

  cd customs-clear/backend
  PYTHONPATH=. python3 scripts/seed_demo_journal.py --append

Переменная DECISIONS_LOG_PATH задаёт файл назначения (по умолчанию data/user_decisions.jsonl).
Каждая строка дополняется полем ts (UTC), если его ещё нет.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Сид демо-журнала подтверждений ТН ВЭД")
    parser.add_argument(
        "--append",
        action="store_true",
        help="Добавить строки в конец журнала (создать файл при отсутствии)",
    )
    args = parser.parse_args()
    if not args.append:
        parser.error("Укажите --append для записи (защита от случайного запуска)")

    backend_dir = Path(__file__).resolve().parents[1]
    customs_clear = backend_dir.parent
    sample = customs_clear / "docs" / "samples" / "user_decisions.jsonl.example"
    if not sample.is_file():
        print(f"Не найден файл примера: {sample}", file=sys.stderr)
        sys.exit(1)

    target = Path(os.getenv("DECISIONS_LOG_PATH", "data/user_decisions.jsonl"))
    if not target.is_absolute():
        target = backend_dir / target

    target.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    n = 0
    with open(sample, encoding="utf-8") as fin, open(target, "a", encoding="utf-8") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "ts" not in row:
                row["ts"] = now
            fout.write(json.dumps(row, ensure_ascii=False) + "\n")
            n += 1

    print(f"Добавлено записей: {n} → {target}")


if __name__ == "__main__":
    main()
