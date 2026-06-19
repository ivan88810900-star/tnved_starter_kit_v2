"""Идемпотентный backfill нетарифных мер для главы 97 (культурные ценности).

Issue #109: глава 97 (произведения искусства, предметы коллекционирования,
антиквариат) была единственной с chapter-level пробелом NTM (clean < 10).

Реальное нетарифное требование для главы 97 — разрешительный (лицензионный)
порядок ввоза/вывоза культурных ценностей:
- ЕАЭС: Единый перечень товаров, к которым применяются меры нетарифного
  регулирования (раздел 2.20 «Культурные ценности…»), Решение Коллегии ЕЭК.
- РФ: Закон РФ № 4804-1 «О вывозе и ввозе культурных ценностей»; разрешительный
  документ (заключение) уполномоченного органа (Минкультуры России).

Скрипт идемпотентен: ключ (commodity_code, measure_type, regulatory_act).
Запуск:
    cd customs-clear/backend && ../../.venv/bin/python -m scripts.backfill_ch97_cultural_measures
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db import SessionLocal
from app.models.tnved import Commodity, NonTariffMeasure

# Заголовки товарных позиций главы 97 (10-значные коды-«нули» позиции).
CH97_HEADINGS = [
    ("9701000000", "Картины, рисунки, пастели; коллажи"),
    ("9702000000", "Подлинники гравюр, эстампов, литографий"),
    ("9703000000", "Подлинники скульптур и статуэток"),
    ("9704000000", "Марки почтовые, госпошлин; знаки почтовой оплаты, конверты первого дня"),
    ("9705000000", "Коллекции и предметы коллекционирования (зоология, история, нумизматика и др.)"),
    ("9706000000", "Антиквариат возрастом более 100 лет"),
]

# Две устойчивые нетарифные меры на каждую позицию культурных ценностей.
MEASURE_TEMPLATES = [
    {
        "measure_type": "license",
        "description": (
            "Культурные ценности подлежат разрешительному (лицензионному) порядку "
            "ввоза/вывоза. Требуется заключение (разрешительный документ) уполномоченного "
            "органа по сохранению культурных ценностей."
        ),
        "document_required": "Разрешительный документ (заключение) Минкультуры России на ввоз/вывоз культурных ценностей",
        "regulatory_act": "Закон РФ № 4804-1 «О вывозе и ввозе культурных ценностей»",
    },
    {
        "measure_type": "license",
        "description": (
            "Товар включён в Единый перечень товаров, к которым применяются меры "
            "нетарифного регулирования в торговле с третьими странами (раздел 2.20 "
            "«Культурные ценности, документы национальных архивных фондов, оригиналы "
            "архивных документов»)."
        ),
        "document_required": "Разрешительный документ уполномоченного органа государства — члена ЕАЭС",
        "regulatory_act": "Единый перечень товаров с мерами нетарифного регулирования ЕАЭС (разд. 2.20), Решение Коллегии ЕЭК",
    },
]


def build_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for code, _title in CH97_HEADINGS:
        for tpl in MEASURE_TEMPLATES:
            rows.append({"commodity_code": code, **tpl})
    return rows


def main() -> None:
    created = 0
    updated = 0
    skipped = 0

    rows = build_rows()
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

        for row in rows:
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
                db.add(NonTariffMeasure(quality="normal", **row))
                created += 1
            else:
                m.description = row["description"]
                m.document_required = row["document_required"]
                if (m.quality or "").strip().lower() == "noise":
                    m.quality = "normal"
                updated += 1

        db.commit()

    print(f"backfill_ch97_cultural_measures: created={created}, updated={updated}, skipped={skipped}")


if __name__ == "__main__":
    main()
