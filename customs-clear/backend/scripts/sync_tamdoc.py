from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.normative_store import init_db
from app.services.preview_cache_revision import bump_preview_cache_revision
from app.services.tamdoc_sync import (
    approve_tamdoc_candidates_batch,
    sync_tamdoc_archive,
    sync_tamdoc_documents,
    sync_tamdoc_targeted,
)


def _is_success_status(data: dict) -> bool:
    """OK/SKIPPED/NOT_FOUND — успех; WARNING/ERROR — провал (удобно для cron/CI)."""
    return (data.get("status") or "").upper() in {"OK", "SKIPPED", "NOT_FOUND"}


def _has_error_status(payload: object) -> bool:
    """Рекурсивно ищет status=ERROR в вложенном результате."""
    if isinstance(payload, dict):
        status = str(payload.get("status") or "").upper()
        if status == "ERROR":
            return True
        return any(_has_error_status(v) for v in payload.values())
    if isinstance(payload, (list, tuple)):
        return any(_has_error_status(v) for v in payload)
    return False


async def _run(max_docs: int, targeted: bool, staging_only: bool) -> dict:
    max_docs_arg: int | None = None if int(max_docs) <= 0 else int(max_docs)
    result = await (
        sync_tamdoc_targeted(max_docs=max_docs_arg, staging_only=staging_only)
        if targeted
        else sync_tamdoc_documents(max_docs=max_docs_arg)
    )
    print(result)
    return result


def main() -> None:
    default_archive_dir = (ROOT / "downloads" / "tamdoc_archive").resolve()
    parser = argparse.ArgumentParser(description="Синхронизация нормативки из alta.ru/tamdoc в БД")
    parser.add_argument("--max-docs", type=int, default=0, help="Лимит документов за запуск (0 = обработать все)")
    parser.add_argument("--targeted", action="store_true", help="Целевой режим для НДС-льгот и спецпошлин")
    parser.add_argument(
        "--staging-only",
        action="store_true",
        help="Только staging-кандидаты (без записи в vat_preferences/special_duties)",
    )
    parser.add_argument(
        "--approve-pending",
        action="store_true",
        help="После sync автоматически применить pending-кандидаты из staging",
    )
    parser.add_argument(
        "--approve-limit",
        type=int,
        default=0,
        help="Лимит batch approve при --approve-pending (0 = обработать все pending)",
    )
    parser.add_argument(
        "--include-non-tariff",
        action="store_true",
        help="При approve добавлять generic non-tariff запись",
    )
    parser.add_argument(
        "--archive",
        action="store_true",
        help="Синхронизация из локального архива документов",
    )
    parser.add_argument(
        "--archive-dir",
        default=str(default_archive_dir),
        help="Путь к папке локального архива документов (по умолчанию backend/downloads/tamdoc_archive)",
    )
    parser.add_argument(
        "--archive-max-files",
        type=int,
        default=0,
        help="Лимит файлов архива за запуск (0 = обработать все файлы)",
    )
    args = parser.parse_args()

    init_db()
    final_status_ok = True
    has_error_status = False
    if args.archive:
        archive_path = Path(args.archive_dir or default_archive_dir).expanduser().resolve()
        archive_path.mkdir(parents=True, exist_ok=True)
        result = sync_tamdoc_archive(
            archive_dir=str(archive_path),
            max_files=int(args.archive_max_files),
            staging_only=bool(args.staging_only),
            include_non_tariff=True,
            auto_approve_pending=bool(args.approve_pending),
        )
        print(result)
        final_status_ok = final_status_ok and _is_success_status(result)
        has_error_status = has_error_status or _has_error_status(result)
    else:
        result = asyncio.run(
            _run(
                max_docs=int(args.max_docs),
                targeted=bool(args.targeted),
                staging_only=bool(args.staging_only),
            )
        )
        final_status_ok = final_status_ok and _is_success_status(result)
        has_error_status = has_error_status or _has_error_status(result)
    if args.approve_pending and not args.archive:
        result = approve_tamdoc_candidates_batch(
            limit=int(args.approve_limit),
            status="pending",
            include_non_tariff=bool(args.include_non_tariff),
        )
        print(result)
        # batch: status WARNING при ошибках approve; дополнительно смотрим счётчик errors
        final_status_ok = final_status_ok and (result.get("status") == "OK") and ((result.get("errors") or 0) == 0)
        has_error_status = has_error_status or _has_error_status(result)
    bump_preview_cache_revision("sync_tamdoc")
    if has_error_status or not final_status_ok:
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:
        print(f"[ERROR] sync_tamdoc failed: {exc}", file=sys.stderr)
        sys.exit(1)
