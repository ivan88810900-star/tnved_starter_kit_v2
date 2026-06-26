"""Сравнение tr_ts_catalog с данными в non_tariff_measures (исторически TKS)."""
from __future__ import annotations

import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.db import SessionLocal  # noqa: E402
from app.models.tnved import NonTariffMeasure  # noqa: E402
from app.services.tr_ts_catalog import get_tr_ts_requirements  # noqa: E402

CONTROL_CODES = [
    "8528721000",
    "8517110000",
    "8471300000",
    "8508110000",
    "8516710000",
    "6403990000",
    "6109100010",
    "9503007500",
    "3304990000",
    "9401310000",
    "8418102001",
    "8450110000",
    "9405100000",
    "8467210000",
    "8419812000",
]


def extract_tr_ts_codes(text: str) -> set[str]:
    pattern = re.compile(r"(\d{3}/\d{4})")
    return set(pattern.findall(text or ""))


def get_db_tr_ts_codes(hs_code: str) -> set[str]:
    found: set[str] = set()
    with SessionLocal() as db:
        for length in (10, 8, 6, 4):
            if len(hs_code) < length:
                continue
            prefix = hs_code[:length]
            rows = db.query(NonTariffMeasure).filter(
                NonTariffMeasure.commodity_code.like(f"{prefix}%"),
            )
            if hasattr(NonTariffMeasure, "quality"):
                rows = rows.filter(
                    (NonTariffMeasure.quality.is_(None)) | (NonTariffMeasure.quality != "noise")
                )
            row_list = rows.all()
            if row_list:
                for row in row_list:
                    text = " ".join(
                        [
                            row.description or "",
                            row.document_required or "",
                            row.regulatory_act or "",
                        ]
                    )
                    found |= extract_tr_ts_codes(text)
                if found:
                    break
    return found


def main() -> None:
    print(f"{'HS-код':<12} | {'Каталог':<35} | {'БД (из TKS)':<35} | Status")
    print("-" * 110)

    total_match = 0
    total_caused_by_catalog = 0
    total_caused_by_db = 0
    gaps_db_wider: list[str] = []

    for code in CONTROL_CODES:
        catalog = get_tr_ts_requirements(code)
        catalog_codes = {r["tr_ts"] for r in catalog if r.get("tr_ts")}
        db_codes = get_db_tr_ts_codes(code)

        only_catalog = catalog_codes - db_codes
        only_db = db_codes - catalog_codes

        if not only_catalog and not only_db:
            status = "✅ полное совпадение"
            total_match += 1
        elif only_catalog and not only_db:
            status = f"⚠️ каталог шире: +{','.join(sorted(only_catalog))}"
            total_caused_by_catalog += 1
        elif only_db and not only_catalog:
            status = f"⚠️ БД шире: +{','.join(sorted(only_db))}"
            total_caused_by_db += 1
            gaps_db_wider.append(f"{code}: {','.join(sorted(only_db))}")
        else:
            status = (
                f"⚠️ +кат:{','.join(sorted(only_catalog))} " f"+бд:{','.join(sorted(only_db))}"
            )
            gaps_db_wider.append(f"{code} (БД): {','.join(sorted(only_db))}")

        cat_str = ",".join(sorted(catalog_codes)) or "—"
        db_str = ",".join(sorted(db_codes)) or "—"
        print(f"{code:<12} | {cat_str[:35]:<35} | {db_str[:35]:<35} | {status}")

    print("-" * 110)
    print(f"\nПолных совпадений: {total_match}/{len(CONTROL_CODES)}")
    print(f"Каталог шире БД:   {total_caused_by_catalog}")
    print(f"БД шире каталога:  {total_caused_by_db}")
    if gaps_db_wider:
        print("\nПробелы каталога (коды ТР ТС есть в БД, нет в каталоге):")
        for line in gaps_db_wider:
            print(f"  - {line}")


if __name__ == "__main__":
    main()
