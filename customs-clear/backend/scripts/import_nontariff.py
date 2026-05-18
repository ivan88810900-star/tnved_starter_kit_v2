from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Iterable

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db import SessionLocal
from app.models.tnved import Commodity, NonTariffMeasure

REQUIRED_COLUMNS = {
    "hs_code",
    "measure_type",
    "description",
    "document_required",
    "regulatory_act",
}


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
        {
            "hs_code": "0101",
            "measure_type": "vet_control",
            "description": "Живые лошади подлежат ветеринарному контролю.",
            "document_required": "Ветеринарный сертификат",
            "regulatory_act": "Решение КТС № 317",
        },
        {
            "hs_code": "0101210000",
            "measure_type": "vet_control",
            "description": "Контроль здоровья животных перед выпуском.",
            "document_required": "Ветеринарный сертификат",
            "regulatory_act": "Решение КТС № 317",
        },
        {
            "hs_code": "8501",
            "measure_type": "certificate",
            "description": "Электромашины требуют подтверждения безопасности.",
            "document_required": "Декларация о соответствии ТР ТС",
            "regulatory_act": "ТР ТС 004/2011",
        },
        {
            "hs_code": "8501101000",
            "measure_type": "certificate",
            "description": "Подтверждение безопасности электрооборудования.",
            "document_required": "Сертификат соответствия ТР ТС 004/2011",
            "regulatory_act": "ТР ТС 004/2011, ТР ТС 020/2011",
        },
        {
            "hs_code": "8471300000",
            "measure_type": "license",
            "description": "Для отдельных поставок требуется разрешительный порядок.",
            "document_required": "Лицензия Минпромторга",
            "regulatory_act": "Единый перечень товаров с ограничениями ЕАЭС",
        },
        {
            "hs_code": "0306",
            "measure_type": "phyto_control",
            "description": "Контроль безопасности продукции животного происхождения.",
            "document_required": "Разрешение контролирующего органа",
            "regulatory_act": "Акты ЕАЭС по фитосанитарным мерам",
        },
        {
            "hs_code": "9301",
            "measure_type": "ban",
            "description": "Требуется отдельная правовая проверка на запреты и ограничения.",
            "document_required": "Разрешение уполномоченного органа",
            "regulatory_act": "Национальные меры экспортного/импортного контроля",
        },
    ]
    df = pd.DataFrame(rows)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(out_path, index=False)


def _expand_targets(hs_code: str, all_codes: set[str], leaf_codes: list[str]) -> list[str]:
    if hs_code in all_codes:
        return [hs_code]
    # Каскадное наследование для агрегированных кодов:
    # если 4/6-знак отсутствует как отдельная запись, привязываем к 10-значным дочерним.
    if len(hs_code) in (4, 6):
        return [c for c in leaf_codes if c.startswith(hs_code)]
    return []


def _iter_rows(df: pd.DataFrame) -> Iterable[dict[str, str]]:
    normalized = {c.strip().lower(): c for c in df.columns}
    missing = REQUIRED_COLUMNS - set(normalized.keys())
    if missing:
        missing_list = ", ".join(sorted(missing))
        raise ValueError(f"В файле отсутствуют обязательные колонки: {missing_list}")

    for _, row in df.iterrows():
        hs_code = _normalize_hs_code(row[normalized["hs_code"]])
        measure_type = _clean_text(row[normalized["measure_type"]]).lower()
        description = _clean_text(row[normalized["description"]])
        document_required = _clean_text(row[normalized["document_required"]])
        regulatory_act = _clean_text(row[normalized["regulatory_act"]])
        yield {
            "hs_code": hs_code,
            "measure_type": measure_type,
            "description": description,
            "document_required": document_required,
            "regulatory_act": regulatory_act,
        }


def import_file(path: Path) -> None:
    df = _read_input(path)
    created_batch: list[NonTariffMeasure] = []

    total_rows = 0
    invalid_rows = 0
    no_targets = 0
    duplicate_rows = 0
    expanded_rows = 0

    with SessionLocal() as db:
        all_codes = {c[0] for c in db.query(Commodity.code).all()}
        leaf_codes = [c for c in all_codes if len(c) == 10]
        existing_keys = {
            (
                m.commodity_code,
                (m.measure_type or "").strip().lower(),
                (m.regulatory_act or "").strip(),
            )
            for m in db.query(NonTariffMeasure).all()
        }
        staged_keys: set[tuple[str, str, str]] = set()

        for row in _iter_rows(df):
            total_rows += 1
            hs_code = row["hs_code"]
            measure_type = row["measure_type"]

            if not hs_code or not measure_type:
                invalid_rows += 1
                continue

            targets = _expand_targets(hs_code, all_codes, leaf_codes)
            if not targets:
                no_targets += 1
                continue

            if hs_code not in all_codes and len(hs_code) in (4, 6):
                expanded_rows += 1

            for target_code in targets:
                key = (
                    target_code,
                    measure_type,
                    row["regulatory_act"],
                )
                if key in existing_keys or key in staged_keys:
                    duplicate_rows += 1
                    continue
                staged_keys.add(key)
                created_batch.append(
                    NonTariffMeasure(
                        commodity_code=target_code,
                        measure_type=measure_type,
                        description=row["description"],
                        document_required=row["document_required"],
                        regulatory_act=row["regulatory_act"],
                    )
                )

        if created_batch:
            db.bulk_save_objects(created_batch)
            db.commit()

    print(f"import_nontariff: file={path}")
    print(f"  total_rows={total_rows}")
    print(f"  inserted={len(created_batch)}")
    print(f"  invalid_rows={invalid_rows}")
    print(f"  no_targets={no_targets}")
    print(f"  duplicates_skipped={duplicate_rows}")
    print(f"  expanded_prefix_rows={expanded_rows}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Импорт нетарифных мер из CSV/XLSX в таблицу non_tariff_measures."
    )
    parser.add_argument("--file", type=str, help="Путь к CSV/XLSX файлу для импорта")
    parser.add_argument(
        "--generate-sample",
        type=str,
        help="Создать sample XLSX файл по указанному пути и завершить работу",
    )
    args = parser.parse_args()

    if args.generate_sample:
        out_path = Path(args.generate_sample).resolve()
        generate_sample_xlsx(out_path)
        print(f"Sample file generated: {out_path}")
        return

    if not args.file:
        raise SystemExit("Нужно передать --file <path_to_csv_or_xlsx>")

    in_path = Path(args.file).resolve()
    if not in_path.exists():
        raise SystemExit(f"Файл не найден: {in_path}")

    import_file(in_path)


if __name__ == "__main__":
    main()

