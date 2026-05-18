from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db import SessionLocal
from app.models.tnved import IntellectualProperty
from app.services.preview_cache_revision import bump_preview_cache_revision

REQUIRED_COLUMNS = {"brand_name", "hs_code_prefix", "reg_number", "right_holder"}


def _clean_text(raw: object) -> str:
    if raw is None:
        return ""
    text = str(raw).strip()
    return "" if text.lower() == "nan" else text


def _normalize_prefix(raw: object) -> str:
    if raw is None:
        return ""
    digits = re.sub(r"\D", "", str(raw))
    if len(digits) in (4, 6):
        return digits
    return ""


def _read_input(path: Path) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xlsm", ".xltx", ".xltm"}:
        df = pd.read_excel(path, engine="openpyxl", dtype=str, keep_default_na=False)
        _validate_columns(df.columns)
        return [_normalize_row(r) for _, r in df.iterrows()]
    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError("JSON должен быть массивом объектов")
        rows: list[dict[str, Any]] = []
        for item in payload:
            if isinstance(item, dict):
                rows.append(_normalize_row(item))
        return rows
    raise ValueError("Поддерживаются только .xlsx и .json")


def _validate_columns(columns: Any) -> None:
    normalized = {str(c).strip().lower() for c in columns}
    missing = REQUIRED_COLUMNS - normalized
    if missing:
        raise ValueError(f"Отсутствуют обязательные колонки: {', '.join(sorted(missing))}")


def _normalize_row(row: Any) -> dict[str, str]:
    if hasattr(row, "to_dict"):
        src = row.to_dict()
    elif isinstance(row, dict):
        src = row
    else:
        src = {}
    lowered = {str(k).strip().lower(): v for k, v in src.items()}
    return {
        "brand_name": _clean_text(lowered.get("brand_name")),
        "hs_code_prefix": _normalize_prefix(lowered.get("hs_code_prefix")),
        "reg_number": _clean_text(lowered.get("reg_number")),
        "right_holder": _clean_text(lowered.get("right_holder")),
    }


def import_trois(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Файл не найден: {path}")

    rows = _read_input(path)
    created = 0
    updated = 0
    skipped = 0

    with SessionLocal() as db:
        for row in rows:
            brand = row["brand_name"]
            pref = row["hs_code_prefix"]
            if not brand or not pref:
                skipped += 1
                continue
            existing = (
                db.query(IntellectualProperty)
                .filter(
                    IntellectualProperty.brand_name == brand,
                    IntellectualProperty.hs_code_prefix == pref,
                    IntellectualProperty.reg_number == row["reg_number"],
                )
                .first()
            )
            if existing:
                existing.right_holder = row["right_holder"]
                updated += 1
                continue
            db.add(
                IntellectualProperty(
                    brand_name=brand,
                    hs_code_prefix=pref,
                    reg_number=row["reg_number"],
                    right_holder=row["right_holder"],
                )
            )
            created += 1
        db.commit()
    bump_preview_cache_revision("import_trois")

    print(f"[OK] ТРОИС импорт завершен: created={created}, updated={updated}, skipped={skipped}")


def generate_sample(path: Path) -> None:
    sample = [
        {
            "brand_name": "APPLE",
            "hs_code_prefix": "8517",
            "reg_number": "ТРОИС-10001",
            "right_holder": "Apple Inc.",
        },
        {
            "brand_name": "SAMSUNG",
            "hs_code_prefix": "8517",
            "reg_number": "ТРОИС-10002",
            "right_holder": "Samsung Electronics Co., Ltd.",
        },
        {
            "brand_name": "NIKE",
            "hs_code_prefix": "6403",
            "reg_number": "ТРОИС-20001",
            "right_holder": "Nike Innovate C.V.",
        },
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".json":
        path.write_text(json.dumps(sample, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        pd.DataFrame(sample).to_excel(path, index=False)
    print(f"[OK] Sample ТРОИС создан: {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Импорт ТРОИС брендов из Excel/JSON")
    parser.add_argument("input", nargs="?", help="Путь к .xlsx или .json")
    parser.add_argument("--generate-sample", default="", help="Создать sample-файл и выйти")
    args = parser.parse_args()

    if args.generate_sample:
        generate_sample(Path(args.generate_sample))
        return

    if not args.input:
        raise SystemExit("Укажите путь к файлу или используйте --generate-sample")
    import_trois(Path(args.input))


if __name__ == "__main__":
    main()
