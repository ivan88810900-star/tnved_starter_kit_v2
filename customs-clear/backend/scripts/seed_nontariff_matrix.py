#!/usr/bin/env python3
"""
Базовая rule-based матрица нетарифных мер по главам ТН ВЭД 01–97 (для RAG).

Подключение к SQLite через ``SessionLocal`` из ``app.db`` (в репозитории нет ``database.py``).

  cd customs-clear/backend
  alembic upgrade head
  python3 scripts/seed_nontariff_matrix.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from app.db import SessionLocal
from app.models import Commodity, NonTariffMeasure


def _anchor_commodity_for_chapter(db, chapter: str) -> str | None:
    """Минимальный существующий 10-значный код ТН ВЭД с префиксом главы (FK в non_tariff_measures)."""
    return (
        db.query(Commodity.code)
        .filter(Commodity.code.like(f"{chapter}%"))
        .order_by(Commodity.code)
        .limit(1)
        .scalar()
    )


def _measures_for_chapter(chapter: str, n: int) -> list[dict[str, str]]:
    """Правила по номеру главы (две цифры)."""
    if 1 <= n <= 5:
        return [
            {
                "measure_type": "vet_control",
                "description": (
                    "Базовая матрица: ветеринарный контроль при перемещении через таможенную границу Союза "
                    "(продукция животного происхождения)."
                ),
                "document_required": "Ветеринарные сертификаты и сопроводительные документы по перечню КТС.",
                "regulatory_act": "Решение КТС № 317",
            }
        ]
    if 6 <= n <= 14:
        return [
            {
                "measure_type": "phyto_control",
                "description": (
                    "Базовая матрица: фитосанитарный контроль подкарантинной продукции при ввозе на таможенную "
                    "территорию Союза."
                ),
                "document_required": "Фитосанитарный сертификат (или карантинный) в соответствии с перечнем КТС.",
                "regulatory_act": "Решение КТС № 318",
            }
        ]
    if n in (61, 62, 64):
        return [
            {
                "measure_type": "certificate",
                "description": (
                    "Базовая матрица: подтверждение соответствия требованиям технического регламента на продукцию "
                    "лёгкой промышленности (декларация или сертификат)."
                ),
                "document_required": "Декларация о соответствии / сертификат соответствия ТР ТС 017/2011.",
                "regulatory_act": "ТР ТС 017/2011 О безопасности продукции легкой промышленности",
            }
        ]
    if n in (84, 85):
        return [
            {
                "measure_type": "tr_ts",
                "description": "Базовая матрица: безопасность низковольтного оборудования.",
                "document_required": "Подтверждение соответствия ТР ТС 004/2011 (при распространении на товар).",
                "regulatory_act": "ТР ТС 004/2011 (Низковольтное оборудование)",
            },
            {
                "measure_type": "tr_ts",
                "description": "Базовая матрица: электромагнитная совместимость технических средств.",
                "document_required": "Подтверждение соответствия ТР ТС 020/2011 (при распространении на товар).",
                "regulatory_act": "ТР ТС 020/2011 (Электромагнитная совместимость)",
            },
            {
                "measure_type": "tr_ts",
                "description": "Базовая матрица: ограничение содержания опасных веществ в электротехнике.",
                "document_required": "Подтверждение соответствия ТР ЕАЭС 037/2016 (при распространении на товар).",
                "regulatory_act": "ТР ЕАЭС 037/2016 (Ограничение опасных веществ)",
            },
        ]
    if n == 87:
        return [
            {
                "measure_type": "tr_ts",
                "description": "Базовая матрица: безопасность колёсных транспортных средств.",
                "document_required": "Сертификат / декларация соответствия ТР ТС 018/2011 (при распространении).",
                "regulatory_act": "ТР ТС 018/2011 (Безопасность колесных транспортных средств)",
            }
        ]
    if n == 95:
        return [
            {
                "measure_type": "tr_ts",
                "description": "Базовая матрица: безопасность игрушек для детей.",
                "document_required": "Сертификат / декларация соответствия ТР ТС 008/2011 (при распространении).",
                "regulatory_act": "ТР ТС 008/2011 (О безопасности игрушек)",
            }
        ]
    return [
        {
            "measure_type": "license",
            "description": (
                "Базовая матрица: проверка на применение мер нетарифного регулирования по Единому перечню "
                "ЕЭК (лицензирование, количественные ограничения, разрешительные и иные меры)."
            ),
            "document_required": "Сверка с актуальным Единым перечнём; при необходимости — разрешительные документы.",
            "regulatory_act": "Решение ЕЭК № 30 / Решение КТС № 620 (Единый перечень мер нетарифного регулирования)",
        }
    ]


def _merge_measure(db, commodity_code: str, spec: dict[str, str]) -> None:
    existing = (
        db.query(NonTariffMeasure)
        .filter(
            NonTariffMeasure.commodity_code == commodity_code,
            NonTariffMeasure.measure_type == spec["measure_type"],
            NonTariffMeasure.regulatory_act == spec["regulatory_act"],
        )
        .first()
    )
    row = NonTariffMeasure(
        id=existing.id if existing else None,
        commodity_code=commodity_code,
        measure_type=spec["measure_type"],
        description=spec["description"],
        document_required=spec["document_required"][:255],
        regulatory_act=spec["regulatory_act"][:255],
    )
    db.merge(row)


def main() -> None:
    try:
        from tqdm import tqdm
    except ImportError:
        tqdm = None  # type: ignore[misc, assignment]

    total_rows = 0
    with SessionLocal() as db:
        rng = range(1, 98)
        it: Any = tqdm(rng, desc="Главы ТН ВЭД", unit="гл") if tqdm else rng
        for n in it:
            chapter = f"{n:02d}"
            anchor = _anchor_commodity_for_chapter(db, chapter)
            if not anchor:
                print(f"  [пропуск] нет кодов ТН ВЭД для главы {chapter}", file=sys.stderr, flush=True)
                continue
            for spec in _measures_for_chapter(chapter, n):
                _merge_measure(db, anchor, spec)
                total_rows += 1
        db.commit()

    print(
        f"Базовая матрица нетарифных мер для глав 01-97 успешно загружена в БД. Добавлено {total_rows} записей.",
        flush=True,
    )


if __name__ == "__main__":
    main()
