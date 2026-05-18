#!/usr/bin/env python3
"""
Эталонные прецеденты в ``classification_decisions`` для тестов RAG (без внешнего парсинга).

  cd customs-clear/backend
  alembic upgrade head
  python3 scripts/seed_precedents.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from app.db import SessionLocal
from app.models import ClassificationDecision

# Стабильные ``decision_number`` — повторный запуск обновляет те же строки (merge по id).
PRECEDENTS: list[dict[str, str]] = [
    {
        "decision_number": "RAG-SEED-6404110000",
        "hs_code": "6404110000",
        "product_name": "Кроссовки мужские (верх сетка, подошва резина)",
        "description": (
            "Обувь спортивная. Материал верха: 100% текстиль (полиэстеровая сетка). "
            "Материал подошвы: резина. Классификация по ОПИ 1 и 6. Код подобран для обуви "
            "с верхом из текстильных материалов. Ветеринарный контроль не требуется."
        ),
        "target_entity": "Кроссовки мужские",
        "issue_date": "",
    },
    {
        "decision_number": "RAG-SEED-6402999300",
        "hs_code": "6402999300",
        "product_name": "Туфли мужские (верх эко-кожа, подошва резина)",
        "description": (
            "Обувь мужская. Материал верха: искусственная кожа (эко-кожа, полиуретан). "
            "Подошва: резина. Товар не содержит элементов из натуральной кожи, ветеринарный "
            "контроль не требуется."
        ),
        "target_entity": "Туфли мужские",
        "issue_date": "",
    },
    {
        "decision_number": "RAG-SEED-6403999300",
        "hs_code": "6403999300",
        "product_name": "Ботинки мужские (верх натуральная кожа)",
        "description": (
            "Обувь с верхом из натуральной кожи крупного рогатого скота. "
            "Подлежит обязательному ветеринарному контролю."
        ),
        "target_entity": "Ботинки мужские",
        "issue_date": "",
    },
]


def main() -> None:
    with SessionLocal() as db:
        for spec in PRECEDENTS:
            existing = (
                db.query(ClassificationDecision)
                .filter(ClassificationDecision.decision_number == spec["decision_number"])
                .first()
            )
            row = ClassificationDecision(
                id=existing.id if existing else None,
                hs_code=spec["hs_code"],
                product_name=spec["product_name"],
                description=spec["description"],
                target_entity=spec["target_entity"],
                decision_number=spec["decision_number"],
                issue_date=spec["issue_date"],
            )
            db.merge(row)
        db.commit()

    print("Эталонные прецеденты успешно добавлены в базу данных.", flush=True)


if __name__ == "__main__":
    main()
