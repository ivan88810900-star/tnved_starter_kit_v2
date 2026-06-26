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

REQUIRED_COLUMNS = {"hs_code", "supp_unit", "weight_coeff"}


def _normalize_hs_code(raw: object) -> str:
    if raw is None:
        return ""
    code = re.sub(r"\D", "", str(raw))
    if len(code) not in (4, 6, 10):
        return ""
    return code


def _clean_text(raw: object) -> str:
    if raw is None:
        return ""
    text = str(raw).strip()
    return "" if text.lower() == "nan" else text


def _parse_coeff(raw: object) -> float | None:
    if raw is None:
        return None
    text = str(raw).strip().replace(",", ".")
    if not text:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    if value <= 0:
        return None
    return value


def _read_input(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xlsm", ".xltx", ".xltm"}:
        return pd.read_excel(path, engine="openpyxl", dtype=str, keep_default_na=False)
    if suffix == ".csv":
        try:
            return pd.read_csv(path, encoding="utf-8-sig", dtype=str, keep_default_na=False)
        except UnicodeDecodeError:
            return pd.read_csv(path, encoding="cp1251", dtype=str, keep_default_na=False)
    raise ValueError("Поддерживаются только .xlsx и .csv файлы")


def generate_sample_xlsx(out_path: Path) -> None:
    rows = [
        {"hs_code": "0101", "supp_unit": "шт", "weight_coeff": "450.0"},
        {"hs_code": "0101210000", "supp_unit": "шт", "weight_coeff": "420.0"},
        {"hs_code": "8516108000", "supp_unit": "шт", "weight_coeff": "1.8"},
        {"hs_code": "8517", "supp_unit": "шт", "weight_coeff": "0.25"},
        {"hs_code": "3923301090", "supp_unit": "л", "weight_coeff": "0.95"},
        {"hs_code": "6403", "supp_unit": "пары", "weight_coeff": "1.2"},
        {"hs_code": "4819200000", "supp_unit": "м2", "weight_coeff": "0.35"},
    ]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_excel(out_path, index=False)


def _expand_targets(hs_code: str, all_codes: set[str], leaf_codes: list[str]) -> list[str]:
    if hs_code in all_codes:
        return [hs_code]
    if len(hs_code) in (4, 6):
        return [c for c in leaf_codes if c.startswith(hs_code)]
    return []


def import_file(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Файл не найден: {path}")

    df = _read_input(path)
    normalized_cols = {c.strip().lower(): c for c in df.columns}
    missing = REQUIRED_COLUMNS - set(normalized_cols.keys())
    if missing:
        raise ValueError(f"В файле отсутствуют обязательные колонки: {', '.join(sorted(missing))}")

    with SessionLocal() as db:
        codes = [c for (c,) in db.query(Commodity.code).all()]
        all_codes = set(codes)
        leaf_codes = [c for c in codes if len(c) == 10]

        updated = 0
        invalid = 0
        cascaded = 0
        touched_codes: set[str] = set()

        for _, row in df.iterrows():
            hs_code = _normalize_hs_code(row[normalized_cols["hs_code"]])
            supp_unit = _clean_text(row[normalized_cols["supp_unit"]])
            coeff = _parse_coeff(row[normalized_cols["weight_coeff"]])
            if not hs_code or not supp_unit or coeff is None:
                invalid += 1
                continue

            targets = _expand_targets(hs_code, all_codes, leaf_codes)
            if len(targets) > 1:
                cascaded += len(targets)
            if not targets:
                invalid += 1
                continue

            rows_to_update = db.query(Commodity).filter(Commodity.code.in_(targets)).all()
            for item in rows_to_update:
                item.supp_unit = supp_unit
                item.weight_coeff = coeff
                touched_codes.add(item.code)
                updated += 1

        db.commit()

    print(
        f"[OK] Импорт завершен. обновлено={updated}, уникальных_кодов={len(touched_codes)}, "
        f"каскадных_попаданий={cascaded}, некорректных_строк={invalid}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Импорт supp_unit и weight_coeff в tnved_commodities из Excel/CSV",
    )
    parser.add_argument("input", nargs="?", help="Путь к .xlsx или .csv")
    parser.add_argument(
        "--generate-sample",
        default="sample_weight_coeffs.xlsx",
        help="Сгенерировать sample-файл и выйти (по умолчанию sample_weight_coeffs.xlsx)",
    )
    parser.add_argument(
        "--no-generate-sample",
        action="store_true",
        help="Не генерировать sample автоматически",
    )
    args = parser.parse_args()

    if not args.no_generate_sample:
        sample_path = Path(args.generate_sample)
        generate_sample_xlsx(sample_path)
        print(f"[OK] Sample создан: {sample_path}")

    if args.input:
        import_file(Path(args.input))
    elif args.no_generate_sample:
        raise SystemExit("Укажите путь к входному файлу: python scripts/import_weight_coeffs.py path/to/file.xlsx")


if __name__ == "__main__":
    main()
