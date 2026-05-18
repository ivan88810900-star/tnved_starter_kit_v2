from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db import SessionLocal
from app.models.tnved import Commodity


def _normalize_hs_code(raw: object) -> str:
    if raw is None:
        return ""
    code = re.sub(r"\D", "", str(raw))
    if len(code) not in (4, 6, 10):
        return ""
    return code


def _parse_coeff(raw: object) -> float | None:
    if raw is None:
        return None
    txt = str(raw).strip().replace(",", ".")
    if not txt:
        return None
    try:
        val = float(txt)
    except ValueError:
        return None
    if val <= 0:
        return None
    return val


def _read_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        try:
            return pd.read_csv(path, encoding="utf-8-sig", dtype=str, keep_default_na=False)
        except UnicodeDecodeError:
            return pd.read_csv(path, encoding="cp1251", dtype=str, keep_default_na=False)
    if suffix in {".xlsx", ".xls", ".xlsm", ".xltx", ".xltm"}:
        return pd.read_excel(path, engine="openpyxl", dtype=str, keep_default_na=False)
    raise ValueError("Поддерживаются файлы: .csv, .xlsx, .xls, .xlsm")


def _pick_column(columns: list[str], title: str) -> str:
    print(f"\n{title}")
    for idx, col in enumerate(columns, start=1):
        print(f"  {idx:>2}. {col}")
    while True:
        raw = input("Введите номер колонки или точное имя: ").strip()
        if not raw:
            print("Пустой ввод, попробуйте снова.")
            continue
        if raw.isdigit():
            i = int(raw)
            if 1 <= i <= len(columns):
                return columns[i - 1]
            print("Номер вне диапазона.")
            continue
        if raw in columns:
            return raw
        print("Колонка не найдена. Введите номер из списка или точное имя.")


def _expand_targets(hs_code: str, all_codes: set[str], leaf_codes: list[str]) -> list[str]:
    if hs_code in all_codes:
        return [hs_code]
    if len(hs_code) in (4, 6):
        return [c for c in leaf_codes if c.startswith(hs_code)]
    return []


def import_table(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Файл не найден: {path}")

    df = _read_table(path)
    if df.empty:
        raise ValueError("Файл пустой")

    columns = [str(c) for c in df.columns]
    print(f"\nФайл: {path}")
    print(f"Найдено колонок: {len(columns)}, строк: {len(df)}")
    print("\nПервые 5 строк:")
    print(df.head(5).to_string(index=False))

    code_col = _pick_column(columns, "Какую колонку привязать к полю code?")
    coeff_col = _pick_column(columns, "Какую колонку привязать к полю weight_coeff?")

    print("\nВыбрано:")
    print(f"  code         <- {code_col}")
    print(f"  weight_coeff <- {coeff_col}")
    confirm = input("Продолжить импорт? [y/N]: ").strip().lower()
    if confirm not in ("y", "yes", "д", "да"):
        print("Импорт отменён.")
        return

    with SessionLocal() as db:
        codes = [c for (c,) in db.query(Commodity.code).all()]
        all_codes = set(codes)
        leaf_codes = [c for c in codes if len(c) == 10]

        updated = 0
        invalid = 0
        cascaded_hits = 0
        touched_codes: set[str] = set()

        for _, row in df.iterrows():
            hs_code = _normalize_hs_code(row.get(code_col))
            coeff = _parse_coeff(row.get(coeff_col))
            if not hs_code or coeff is None:
                invalid += 1
                continue

            targets = _expand_targets(hs_code, all_codes, leaf_codes)
            if not targets:
                invalid += 1
                continue
            if len(targets) > 1:
                cascaded_hits += len(targets)

            rows_to_update = db.query(Commodity).filter(Commodity.code.in_(targets)).all()
            for item in rows_to_update:
                item.weight_coeff = coeff
                touched_codes.add(item.code)
                updated += 1

        db.commit()

    print(
        "\n[OK] Импорт завершён."
        f"\n  обновлено_строк: {updated}"
        f"\n  уникальных_кодов: {len(touched_codes)}"
        f"\n  каскадных_попаданий: {cascaded_hits}"
        f"\n  некорректных/пропущенных: {invalid}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Интерактивный импорт weight_coeff из CSV/XLSX/XLS",
    )
    parser.add_argument("table_path", help="Путь к .csv/.xlsx/.xls файлу")
    args = parser.parse_args()
    import_table(Path(args.table_path))


if __name__ == "__main__":
    main()
