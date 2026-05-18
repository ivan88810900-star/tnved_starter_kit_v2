#!/usr/bin/env python3
"""Консольный запуск массового ИИ-импорта нормативных документов из data/raw_normative/."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
load_dotenv()

from app.services.bulk_normative_ai import (  # noqa: E402
    create_import_job,
    list_input_files,
    raw_normative_dir,
    run_bulk_import,
)
from app.db import SessionLocal  # noqa: E402
from app.models import BulkImportFileCheckpoint  # noqa: E402


def _print_progress(info: dict) -> None:
    pf = info.get("processed_files", 0)
    tf = info.get("total_files", 0)
    ma = info.get("measures_applied", 0)
    fn = info.get("file", "")
    extra = ""
    if info.get("skipped"):
        extra = " [пропуск — уже в чекпоинте]"
    if info.get("error"):
        extra = f" [ошибка: {info['error'][:120]}]"
    if info.get("llm_rows") is not None:
        extra += f" строк JSON от LLM: {info['llm_rows']}"
    print(f"[{pf}/{tf}] мер применено: {ma} · {fn}{extra}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Массовый ИИ-импорт PDF/DOCX/HTML из data/raw_normative/ в БД (Gemini, паузы, 429 backoff, чекпоинты)."
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=4.0,
        help="Минимальная пауза между запросами к LLM, сек (по умолчанию 4)",
    )
    parser.add_argument(
        "--reset-checkpoints",
        action="store_true",
        help="Очистить таблицу bulk_import_file_checkpoints перед запуском (все файлы обработаются заново)",
    )
    parser.add_argument(
        "--skip-checkpoint",
        action="store_true",
        help="Игнорировать чекпоинты (не удаляя их), обработать все файлы снова",
    )
    parser.add_argument("--list-only", action="store_true", help="Только перечислить файлы и выйти")
    args = parser.parse_args()

    raw = raw_normative_dir()
    files = list_input_files(raw)
    print(f"Каталог: {raw}", flush=True)
    print(f"Найдено файлов: {len(files)}", flush=True)
    if args.list_only:
        for p in files:
            print(f"  - {p.relative_to(raw)}")
        return

    if args.reset_checkpoints:
        with SessionLocal() as db:
            n = db.query(BulkImportFileCheckpoint).delete()
            db.commit()
            print(f"Сброшено чекпоинтов: {n}", flush=True)

    if not os.getenv("GEMINI_API_KEY") and not os.getenv("GOOGLE_API_KEY"):
        print("Предупреждение: не задан GEMINI_API_KEY / GOOGLE_API_KEY — LLM вызовы завершатся ошибкой.", flush=True)

    job_id = create_import_job()
    print(f"Создана задача bulk_import_jobs.id={job_id}", flush=True)

    async def _go() -> None:
        await run_bulk_import(
            job_id,
            delay_sec=args.delay,
            skip_checkpoint=args.skip_checkpoint,
            progress_cb=_print_progress,
        )

    asyncio.run(_go())
    print("Готово.", flush=True)


if __name__ == "__main__":
    main()
