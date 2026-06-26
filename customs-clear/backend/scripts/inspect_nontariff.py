#!/usr/bin/env python3
"""
Аналитика и точечная проверка таблицы ``non_tariff_measures`` (связь код ТН ВЭД ↔ регламент).

  cd customs-clear/backend
  python3 scripts/inspect_nontariff.py
  python3 scripts/inspect_nontariff.py --code 6404110000

Сессия БД: ``SessionLocal`` из ``app.db`` (в проекте нет ``app.db.database``).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.exc import OperationalError

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from app.db import SessionLocal  # noqa: E402
from app.models.tnved import NonTariffMeasure  # noqa: E402


def _cell(s: object | None, *, max_len: int = 0) -> str:
    t = ("" if s is None else str(s)).replace("\r\n", "\n").replace("\r", "\n").strip()
    if max_len and len(t) > max_len:
        return t[: max_len - 1] + "…"
    return t or "—"


def print_top_regulatory_acts(db) -> None:
    print("\n" + "═" * 72)
    print("  Топ-15 регламентов (regulatory_act) по числу уникальных кодов ТН ВЭД")
    print("─" * 72)
    act_col = getattr(NonTariffMeasure, "regulatory_act", None)
    code_col = getattr(NonTariffMeasure, "commodity_code", None)
    if act_col is None or code_col is None:
        print("  Модель NonTariffMeasure: не найдены ожидаемые поля.")
        return

    q = (
        db.query(
            NonTariffMeasure.regulatory_act,
            func.count(func.distinct(NonTariffMeasure.commodity_code)).label("codes"),
            func.count(NonTariffMeasure.id).label("rows"),
        )
        .group_by(NonTariffMeasure.regulatory_act)
        .order_by(func.count(func.distinct(NonTariffMeasure.commodity_code)).desc())
        .limit(15)
    )
    for i, row in enumerate(q.all(), start=1):
        act = _cell(row[0], max_len=200)
        n_codes = int(row[1] or 0)
        n_rows = int(row[2] or 0)
        tail = f" ({n_rows} строк)" if n_rows != n_codes else ""
        print(f"  {i:2}. {_cell(act, max_len=120)} — {n_codes} кодов{tail}")


def print_measure_type_stats(db) -> None:
    print("\n" + "═" * 72)
    print("  Статистика по типу меры (measure_type)")
    print("─" * 72)
    if not hasattr(NonTariffMeasure, "measure_type"):
        print("  Поле measure_type не найдено в модели.")
        return
    q = (
        db.query(
            NonTariffMeasure.measure_type,
            func.count(func.distinct(NonTariffMeasure.commodity_code)).label("codes"),
            func.count(NonTariffMeasure.id).label("rows"),
        )
        .group_by(NonTariffMeasure.measure_type)
        .order_by(func.count(NonTariffMeasure.id).desc())
    )
    for row in q.all():
        mt = _cell(row[0])
        n_codes = int(row[1] or 0)
        n_rows = int(row[2] or 0)
        print(f"  • {mt}: уникальных кодов {n_codes}, строк {n_rows}")


def print_rows_for_code(db, raw_code: str) -> None:
    d = re.sub(r"\D", "", (raw_code or "").strip())
    if len(d) > 10:
        d = d[:10]
    print("\n" + "═" * 72)
    print(f"  Нетарифные меры для запроса: {raw_code!r} (цифры: {d or '—'})")
    print("─" * 72)

    rows: list[NonTariffMeasure] = []
    if len(d) == 10:
        rows = (
            db.query(NonTariffMeasure)
            .filter(NonTariffMeasure.commodity_code == d)
            .order_by(NonTariffMeasure.id.asc())
            .all()
        )
    if not rows and 4 <= len(d) <= 9:
        rows = (
            db.query(NonTariffMeasure)
            .filter(NonTariffMeasure.commodity_code.like(f"{d}%"))
            .order_by(NonTariffMeasure.commodity_code.asc(), NonTariffMeasure.id.asc())
            .limit(200)
            .all()
        )
        if rows:
            print(f"  (режим префикса: до 200 строк с commodity_code LIKE '{d}%')\n")

    if not rows:
        print("  Записей не найдено.")
        return

    for r in rows:
        code = _cell(getattr(r, "commodity_code", None))
        mt = _cell(getattr(r, "measure_type", None))
        act = _cell(getattr(r, "regulatory_act", None), max_len=500)
        desc = _cell(getattr(r, "description", None), max_len=600)
        doc = _cell(getattr(r, "document_required", None), max_len=300)
        print(f"  Код товара:        {code}")
        print(f"  Тип меры:         {mt}")
        print(f"  Нормативный акт:  {act}")
        print(f"  Требуемый документ: {doc}")
        print(f"  Описание:         {desc}")
        print("  " + "-" * 68)


def print_random_sample(db, n: int = 5) -> None:
    print("\n" + "═" * 72)
    print(f"  Демо-выборка: {n} случайных строк (код → регламент)")
    print("─" * 72)
    rows = db.query(NonTariffMeasure).order_by(func.random()).limit(n).all()
    if not rows:
        print("  Таблица пуста.")
        return
    for r in rows:
        code = _cell(getattr(r, "commodity_code", None))
        mt = _cell(getattr(r, "measure_type", None))
        act = _cell(getattr(r, "regulatory_act", None), max_len=160)
        desc = _cell(getattr(r, "description", None), max_len=120)
        print(f"  {code}  [{mt}]  {act}")
        if desc != "—":
            print(f"      └─ {desc}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Инспекция non_tariff_measures")
    parser.add_argument(
        "--code",
        type=str,
        default="",
        help="10-значный код ТН ВЭД (или 4–9 цифр — дополняются нулями справа до 10)",
    )
    args = parser.parse_args()

    try:
        with SessionLocal() as db:
            total = db.query(func.count(NonTariffMeasure.id)).scalar() or 0
            print(f"\nТаблица non_tariff_measures: всего строк: {int(total)}")
            if total == 0:
                print("(данных нет — аналитика пропущена)")
                return 0

            print_top_regulatory_acts(db)
            print_measure_type_stats(db)

            code_arg = (args.code or "").strip()
            if code_arg:
                digits = re.sub(r"\D", "", code_arg)
                if len(digits) < 4:
                    print(
                        "\nОшибка: укажите минимум 4 цифры кода, например --code 6404110000",
                        file=sys.stderr,
                    )
                    return 2
                print_rows_for_code(db, code_arg)
            else:
                print_random_sample(db, 5)

    except OperationalError as e:
        print(f"Ошибка БД: {e}", file=sys.stderr)
        return 1

    print("\n" + "═" * 72)
    print("  Готово.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
