#!/usr/bin/env python3
"""
Преобразование журнала решений в пары для внешнего обучения (JSONL).

Форматы:
  default: {"text": "<описание>", "label": "<код ТН ВЭД>", "meta": {...}}
  openai-chat: {"messages": [system, user, assistant]} для fine-tune чат-моделей

  cd customs-clear/backend
  PYTHONPATH=. python3 scripts/export_training_pairs.py [вход.jsonl] [выход.jsonl] [--format openai-chat]

По умолчанию: DECISIONS_LOG_PATH → data/training_pairs.jsonl

См. docs/ML_TRAINING_PIPELINE.md
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

SYSTEM_PROMPT = (
    "Ты помощник таможенного декларанта ЕАЭС. По описанию товара верни только "
    "10-значный код ТН ВЭД ЕАЭС цифрами, без пояснений."
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Экспорт журнала в пары для ML")
    parser.add_argument("src", nargs="?", default=None, help="Входной JSONL журнала")
    parser.add_argument("dst", nargs="?", default=None, help="Выходной JSONL")
    parser.add_argument(
        "--format",
        choices=("default", "openai-chat"),
        default="default",
        help="Формат строки выхода",
    )
    args = parser.parse_args()

    default_in = Path(os.getenv("DECISIONS_LOG_PATH", "data/user_decisions.jsonl"))
    src = Path(args.src) if args.src else default_in
    dst = Path(args.dst) if args.dst else src.parent / (
        "openai_ft.jsonl" if args.format == "openai-chat" else "training_pairs.jsonl"
    )

    if not src.is_file():
        print(f"Нет файла: {src}", file=sys.stderr)
        sys.exit(1)

    n_in = 0
    n_out = 0
    dst.parent.mkdir(parents=True, exist_ok=True)

    with open(src, encoding="utf-8", errors="ignore") as fin, open(dst, "w", encoding="utf-8") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            n_in += 1
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            desc = (row.get("description") or "").strip()
            conf = re.sub(r"\D", "", str(row.get("confirmed_hs") or ""))[:10]
            if len(conf) < 4 or len(desc) < 4:
                continue
            if args.format == "openai-chat":
                user_content = f"Определи код ТН ВЭД ЕАЭС для товара:\n{desc[:4000]}"
                rec = {
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_content},
                        {"role": "assistant", "content": conf.ljust(10, "0")[:10]},
                    ]
                }
            else:
                rec = {
                    "text": desc[:4000],
                    "label": conf,
                    "meta": {
                        "ts": row.get("ts"),
                        "source": row.get("source"),
                        "client_id": row.get("client_id"),
                        "suggested_hs": row.get("suggested_hs"),
                    },
                }
            fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n_out += 1

    print(f"Прочитано строк: {n_in}, записано пар: {n_out} → {dst} (format={args.format})")


if __name__ == "__main__":
    main()
