from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db import SessionLocal
from app.models.tnved import Commodity, NonTariffMeasure


SEED_MEASURES = [
    {
        "commodity_code": "0101210000",
        "measure_type": "vet_control",
        "description": "Подлежит ветеринарному контролю при ввозе на территорию ЕАЭС.",
        "document_required": "Ветеринарный сертификат",
        "regulatory_act": "Решение КТС № 317",
    },
    {
        "commodity_code": "8501101000",
        "measure_type": "certificate",
        "description": "Требуется подтверждение безопасности продукции перед выпуском в обращение.",
        "document_required": "Сертификат соответствия ТР ТС 004/2011",
        "regulatory_act": "ТР ТС 004/2011, ТР ТС 020/2011",
    },
    {
        "commodity_code": "8501000000",
        "measure_type": "certificate",
        "description": "Для товарной позиции применяются общие требования подтверждения соответствия.",
        "document_required": "Декларация о соответствии ТР ТС",
        "regulatory_act": "ТР ТС 004/2011",
    },
    {
        "commodity_code": "8471300000",
        "measure_type": "license",
        "description": "Для отдельных поставок может требоваться лицензирование/разрешительный порядок.",
        "document_required": "Лицензия Минпромторга (при применимости)",
        "regulatory_act": "Единый перечень товаров с ограничениями ЕАЭС",
    },
]


def main() -> None:
    created = 0
    updated = 0
    skipped = 0

    with SessionLocal() as db:
        existing = {
            (
                m.commodity_code,
                (m.measure_type or "").strip().lower(),
                (m.regulatory_act or "").strip(),
            ): m
            for m in db.query(NonTariffMeasure).all()
        }
        commodity_codes = {c[0] for c in db.query(Commodity.code).all()}

        for row in SEED_MEASURES:
            code = row["commodity_code"]
            if code not in commodity_codes:
                skipped += 1
                continue
            key = (
                code,
                (row["measure_type"] or "").strip().lower(),
                (row["regulatory_act"] or "").strip(),
            )
            m = existing.get(key)
            if m is None:
                db.add(NonTariffMeasure(**row))
                created += 1
            else:
                m.description = row["description"]
                m.document_required = row["document_required"]
                updated += 1

        db.commit()

    print(f"populate_nontariff: created={created}, updated={updated}, skipped={skipped}")


if __name__ == "__main__":
    main()

