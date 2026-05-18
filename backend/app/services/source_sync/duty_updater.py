"""
Точечное обновление поля import_duty в tnved_commodities из PDF «Таможенный тариф ЕАЭС».

Запуск из каталога backend:
  PYTHONPATH=. python -m app.services.source_sync.duty_updater

Или:
  PYTHONPATH=. python app/services/source_sync/duty_updater.py

Переменная окружения DB_URL (по умолчанию sqlite:///./tnved.db) — та же БД, что у приложения.

Основной источник ставок: полный разбор ``parse_tariff_rows`` во временной SQLite по всем строкам PDF
(как при первичном импорте). Строки, где ``_parse_commodity_tail`` не находит ставку (часто «—»,
льготы, переносы), останутся с пустым import_duty — это те же ~3925 позиций, что и при импорте.
Для синхронизации уже заполненных полей из PDF: ``--force``.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, func, or_
from sqlalchemy.orm import Session, sessionmaker
from tqdm import tqdm

_BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.db import Base, SessionLocal  # noqa: E402
from app.models.tnved import Chapter, Commodity, Section  # noqa: F401, E402 — таблицы для create_all
from app.services.source_sync.pdf_parser import (  # noqa: E402
    discover_tariff_files,
    iter_lines_from_path,
    parse_tariff_rows,
)

DATA_DIR = Path(__file__).resolve().parent / "data"

BATCH_COMMIT = 500

# Строки без числовой ставки — пропускаем
_DUTY_SKIP = frozenset({"", "—", "-", "–", "−", "нет", "нет."})


def normalize_code(raw: str | None) -> str:
    """Только цифры, без пробелов и переносов."""
    return re.sub(r"\D", "", raw or "")


def normalize_duty(raw: str | None) -> str:
    if raw is None:
        return ""
    s = str(raw).replace("\n", " ").replace("\r", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def parse_table_row(row: list[Any] | None) -> tuple[str | None, str | None]:
    """
    Колонка 0 или 1 — код ТН ВЭД; последняя — ставка ввозной пошлины.
    Возвращает (10-значный код, текст ставки) или (None, None).
    """
    if not row or len(row) < 2:
        return None, None
    cells: list[str] = []
    for c in row:
        if c is None:
            cells.append("")
        else:
            cells.append(str(c).strip())
    while cells and not cells[-1]:
        cells.pop()
    if len(cells) < 2:
        return None, None

    duty_raw = cells[-1]
    duty = normalize_duty(duty_raw)
    if not duty or duty in _DUTY_SKIP:
        return None, None

    code: str | None = None
    for idx in (0, 1):
        if idx >= len(cells) - 1:
            break
        cand = normalize_code(cells[idx])
        if len(cand) == 10:
            code = cand
            break
    if code is None:
        return None, None
    return code, duty


def _duties_from_tables_only(pdf_path: Path, out: dict[str, str]) -> int:
    """Дополнение: extract_tables(), если сетка распозналась."""
    import pdfplumber

    n = 0
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables() or []:
                for row in table:
                    code, duty = parse_table_row(row)
                    if code and duty:
                        out[code] = duty
                        n += 1
    return n


def extract_duties_from_pdfs(data_dir: Path, *, include_table_cells: bool = False) -> dict[str, str]:
    """
    1) Полный разбор как при импорте: все строки PDF/DOCX → ``parse_tariff_rows`` во временной SQLite
       (тот же конечный автомат, что и у pdf_parser — не теряются многострочные и «ломаные» строки).
    2) Дополнительно merge из extract_tables() по строкам таблиц.

    Поздние источники перезаписывают значение для того же кода.
    """
    paths = discover_tariff_files(data_dir)
    if not paths:
        print(f"[duty_updater] В папке нет PDF/DOCX: {data_dir}", file=sys.stderr)
        return {}

    rows: list[tuple[int, str]] = []
    for p in paths:
        rows.extend(iter_lines_from_path(p))

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    mem = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    try:
        n_sec, n_ch, n_com = parse_tariff_rows(mem, rows)
        mem.commit()
        print(
            f"[duty_updater] Парсер (память): разделов={n_sec}, групп={n_ch}, позиций={n_com}"
        )
    except Exception:
        mem.rollback()
        raise
    finally:
        mem.close()

    mem2 = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    try:
        out: dict[str, str] = {}
        for c in mem2.query(Commodity).filter(func.length(Commodity.code) == 10).all():
            d = normalize_duty(c.import_duty)
            if d and d not in _DUTY_SKIP:
                out[c.code] = d
    finally:
        mem2.close()

    table_hits = 0
    if include_table_cells:
        pdfs_only = [p for p in paths if p.suffix.lower() == ".pdf"]
        for pdf_path in tqdm(pdfs_only, desc="Таблицы PDF (доп.)", unit="файл"):
            try:
                table_hits += _duties_from_tables_only(pdf_path, out)
            except Exception as e:
                print(f"[duty_updater] Таблицы {pdf_path.name}: {e}", file=sys.stderr)

    print(
        f"[duty_updater] Уникальных 10-зн. кодов со ставкой: {len(out)}"
        + (f" (+ merge из extract_tables: {table_hits} ячеек)" if include_table_cells else "")
    )
    return out


def apply_updates(
    session: Session,
    code_to_duty: dict[str, str],
    *,
    only_empty: bool,
    dry_run: bool,
    quiet: bool = False,
) -> tuple[int, int]:
    """
    Обновляет import_duty. Возвращает (число обновлённых строк, число пропусков без совпадения в БД).
    """
    total_rows = 0
    total_skipped_no_row = 0
    rows_since_commit = 0

    items = list(code_to_duty.items())
    for code, duty in tqdm(items, desc="UPDATE в БД", unit="код"):
        q = session.query(Commodity).filter(Commodity.code == code)
        if only_empty:
            q = q.filter(
                or_(
                    Commodity.import_duty.is_(None),
                    Commodity.import_duty == "",
                    func.trim(Commodity.import_duty) == "",
                )
            )

        if dry_run:
            n = q.count()
            if n:
                if not quiet:
                    tqdm.write(f"[dry-run] Обновил бы код {code} -> пошлина: {duty!r} ({n} строк)")
                total_rows += n
            else:
                total_skipped_no_row += 1
            continue

        n = q.update({Commodity.import_duty: duty}, synchronize_session=False)
        if n:
            if not quiet:
                tqdm.write(f"Обновлён код {code} -> пошлина: {duty}")
            total_rows += n
            rows_since_commit += n
            if rows_since_commit >= BATCH_COMMIT:
                session.commit()
                rows_since_commit = 0
        else:
            total_skipped_no_row += 1

    if not dry_run and rows_since_commit:
        session.commit()
    return total_rows, total_skipped_no_row


def main() -> int:
    parser = argparse.ArgumentParser(description="Заполнение import_duty из PDF в папке data/")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DATA_DIR,
        help=f"Каталог с PDF (по умолчанию: {DATA_DIR})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Перезаписать import_duty даже если поле уже заполнено (по умолчанию — только пустые)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Только показать, что было бы обновлено, без записи в БД",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Не печатать каждую строку обновления (только прогресс и итог)",
    )
    parser.add_argument(
        "--include-table-cells",
        action="store_true",
        help="Дополнительно merge из page.extract_tables() (дольше ~на все PDF; обычно мало даёт)",
    )
    args = parser.parse_args()

    data_dir: Path = args.data_dir
    if not data_dir.is_dir():
        print(f"[duty_updater] Каталог не найден: {data_dir}", file=sys.stderr)
        return 1

    only_empty = not args.force
    print(f"[duty_updater] Каталог PDF: {data_dir.resolve()}")
    print(f"[duty_updater] Режим: {'только пустые import_duty' if only_empty else 'принудительная перезапись'}")

    code_to_duty = extract_duties_from_pdfs(data_dir, include_table_cells=args.include_table_cells)
    if not code_to_duty:
        print("[duty_updater] Нечего применять — из PDF не извлечено ни одной ставки для 10-значных кодов.")
        return 0

    db = SessionLocal()
    try:
        updated, skipped = apply_updates(
            db,
            code_to_duty,
            only_empty=only_empty,
            dry_run=args.dry_run,
            quiet=args.quiet,
        )
        if args.dry_run:
            db.rollback()
        print(
            f"[duty_updater] Готово. Обновлено строк (сумма по Commodity): {updated}; "
            f"без изменений (нет подходящих строк или код не в БД): {skipped}"
        )
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
