from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db import SessionLocal
from app.models.tnved import Commodity, NonTariffMeasure

ALLOWED_MEASURE_TYPES = {
    "ban",
    "license",
    "certificate",
    "vet_control",
    "phyto_control",
    "other",
}


def _normalize_hs_code(raw: object) -> str:
    code = re.sub(r"\D", "", str(raw or ""))
    return code if len(code) in (4, 6, 10) else ""


def _expand_targets(code: str, all_codes: set[str], leaf_codes: list[str]) -> list[str]:
    if code in all_codes:
        return [code]
    if len(code) in (4, 6):
        return [c for c in leaf_codes if c.startswith(code)]
    return []


def import_raw_json(path: Path) -> dict[str, int]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("Ожидается JSON-массив объектов")

    total_rows = 0
    invalid_rows = 0
    no_targets = 0
    duplicates = 0
    expanded_rows = 0
    inserted = 0
    batch: list[NonTariffMeasure] = []

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

        for obj in data:
            total_rows += 1
            if not isinstance(obj, dict):
                invalid_rows += 1
                continue

            hs_code = _normalize_hs_code(obj.get("hs_code"))
            measure_type = str(obj.get("measure_type", "")).strip().lower()
            document_required = str(obj.get("document_required", "")).strip()
            description = str(obj.get("description", "")).strip()
            regulatory_act = str(obj.get("regulatory_act", "")).strip()

            if not hs_code:
                invalid_rows += 1
                continue
            if measure_type not in ALLOWED_MEASURE_TYPES:
                measure_type = "other"

            targets = _expand_targets(hs_code, all_codes, leaf_codes)
            if not targets:
                no_targets += 1
                continue
            if hs_code not in all_codes and len(hs_code) in (4, 6):
                expanded_rows += 1

            for code in targets:
                key = (code, measure_type, regulatory_act)
                if key in existing_keys or key in staged_keys:
                    duplicates += 1
                    continue
                staged_keys.add(key)
                batch.append(
                    NonTariffMeasure(
                        commodity_code=code,
                        measure_type=measure_type,
                        description=description,
                        document_required=document_required,
                        regulatory_act=regulatory_act,
                    )
                )

        if batch:
            db.bulk_save_objects(batch)
            db.commit()
            inserted = len(batch)

    return {
        "total_rows": total_rows,
        "inserted": inserted,
        "invalid_rows": invalid_rows,
        "no_targets": no_targets,
        "duplicates": duplicates,
        "expanded_rows": expanded_rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Импорт нетарифных мер из raw_extracted.json")
    parser.add_argument(
        "--file",
        default="downloads/raw_extracted.json",
        help="Путь к JSON-файлу с результатами парсинга",
    )
    args = parser.parse_args()

    path = Path(args.file)
    if not path.is_absolute():
        path = (ROOT / path).resolve()
    if not path.exists():
        raise SystemExit(f"Файл не найден: {path}")

    stats = import_raw_json(path)
    print(f"import_raw_json: file={path}")
    print(f"  total_rows={stats['total_rows']}")
    print(f"  inserted={stats['inserted']}")
    print(f"  invalid_rows={stats['invalid_rows']}")
    print(f"  no_targets={stats['no_targets']}")
    print(f"  duplicates={stats['duplicates']}")
    print(f"  expanded_rows={stats['expanded_rows']}")


if __name__ == "__main__":
    main()

