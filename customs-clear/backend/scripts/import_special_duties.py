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
from app.models.tnved import SpecialDuty
from app.services.preview_cache_revision import bump_preview_cache_revision

REQUIRED_COLUMNS = {
    "hs_code_prefix",
    "origin_country",
    "rate_percent",
    "rate_specific",
    "currency_code",
    "regulatory_act",
}


def _clean_text(raw: object) -> str:
    if raw is None:
        return ""
    text = str(raw).strip()
    return "" if text.lower() == "nan" else text


def _normalize_prefix(raw: object) -> str:
    digits = re.sub(r"\D", "", str(raw or ""))
    if len(digits) < 2:
        return ""
    return digits[:10]


def _normalize_country(raw: object) -> str:
    return _clean_text(raw).upper()[:8]


def _to_float(raw: object, default: float = 0.0) -> float:
    txt = str(raw or "").strip().replace(",", ".")
    if not txt:
        return default
    try:
        return float(txt)
    except ValueError:
        return default


def _read_table(path: Path) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xls", ".xlsm", ".xltx", ".xltm"}:
        df = pd.read_excel(path, engine="openpyxl", dtype=str, keep_default_na=False)
        return _from_df(df)
    if suffix == ".csv":
        try:
            df = pd.read_csv(path, encoding="utf-8-sig", dtype=str, keep_default_na=False)
        except UnicodeDecodeError:
            df = pd.read_csv(path, encoding="cp1251", dtype=str, keep_default_na=False)
        return _from_df(df)
    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            for key in ("items", "data", "special_duties"):
                if isinstance(payload.get(key), list):
                    payload = payload.get(key)
                    break
        if not isinstance(payload, list):
            raise ValueError("JSON должен быть массивом объектов или содержать ключ items/data/special_duties")
        rows: list[dict[str, Any]] = []
        for it in payload:
            if isinstance(it, dict):
                rows.append(_normalize_row(it))
        return rows
    raise ValueError("Поддерживаются файлы: .json, .csv, .xlsx")


def _from_df(df: pd.DataFrame) -> list[dict[str, Any]]:
    normalized = {str(c).strip().lower(): c for c in df.columns}
    missing = REQUIRED_COLUMNS - set(normalized.keys())
    if missing:
        raise ValueError(f"Отсутствуют обязательные колонки: {', '.join(sorted(missing))}")
    rows: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        src = {k: row[normalized[k]] for k in normalized if k in REQUIRED_COLUMNS}
        rows.append(_normalize_row(src))
    return rows


def _normalize_row(src: dict[str, Any]) -> dict[str, Any]:
    low = {str(k).strip().lower(): v for k, v in src.items()}
    return {
        "hs_code_prefix": _normalize_prefix(low.get("hs_code_prefix")),
        "origin_country": _normalize_country(low.get("origin_country")),
        "rate_percent": _to_float(low.get("rate_percent"), 0.0),
        "rate_specific": _to_float(low.get("rate_specific"), 0.0),
        "currency_code": (_clean_text(low.get("currency_code")) or "RUB").upper()[:8],
        "regulatory_act": _clean_text(low.get("regulatory_act")),
    }


def import_special_duties(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Файл не найден: {path}")
    rows = _read_table(path)
    if not rows:
        raise ValueError("Во входном файле нет валидных записей")

    created = 0
    updated = 0
    skipped = 0
    with SessionLocal() as db:
        for row in rows:
            if not row["hs_code_prefix"] or not row["origin_country"]:
                skipped += 1
                continue
            if (row["rate_percent"] <= 0.0) and (row["rate_specific"] <= 0.0):
                skipped += 1
                continue
            existing = (
                db.query(SpecialDuty)
                .filter(
                    SpecialDuty.hs_code_prefix == row["hs_code_prefix"],
                    SpecialDuty.origin_country == row["origin_country"],
                    SpecialDuty.regulatory_act == row["regulatory_act"],
                )
                .first()
            )
            if existing:
                existing.rate_percent = row["rate_percent"]
                existing.rate_specific = row["rate_specific"]
                existing.currency_code = row["currency_code"]
                updated += 1
            else:
                db.add(
                    SpecialDuty(
                        hs_code_prefix=row["hs_code_prefix"],
                        origin_country=row["origin_country"],
                        rate_percent=row["rate_percent"],
                        rate_specific=row["rate_specific"],
                        currency_code=row["currency_code"],
                        regulatory_act=row["regulatory_act"],
                    )
                )
                created += 1
        db.commit()
    bump_preview_cache_revision("import_special_duties")
    print(f"[OK] Special duties import: created={created}, updated={updated}, skipped={skipped}")


def generate_sample(path: Path) -> None:
    rows = [
        {
            "hs_code_prefix": "7214",
            "origin_country": "CN",
            "rate_percent": 18.0,
            "rate_specific": 0.0,
            "currency_code": "RUB",
            "regulatory_act": "Решение Коллегии ЕЭК № 186",
        },
        {
            "hs_code_prefix": "7214",
            "origin_country": "MY",
            "rate_percent": 12.5,
            "rate_specific": 0.0,
            "currency_code": "RUB",
            "regulatory_act": "Решение Коллегии ЕЭК № 186",
        },
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".json":
        path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        pd.DataFrame(rows).to_excel(path, index=False)
    print(f"[OK] Sample special duties создан: {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Импорт спецпошлин (антидемпинговых/защитных/компенсационных)")
    parser.add_argument("input", nargs="?", help="Путь к .json/.csv/.xlsx")
    parser.add_argument("--generate-sample", default="", help="Создать sample файл (.json/.xlsx)")
    args = parser.parse_args()

    if args.generate_sample:
        generate_sample(Path(args.generate_sample))
        return
    if not args.input:
        raise SystemExit("Укажите входной файл или используйте --generate-sample")
    import_special_duties(Path(args.input))


if __name__ == "__main__":
    main()
