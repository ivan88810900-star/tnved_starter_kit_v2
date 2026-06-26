"""Удаление тестовой строки спецпошлины из БД (не импортируется из sample после правки JSON)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import delete

from app.db import SessionLocal
from app.models.tnved import SpecialDuty
from app.services.preview_cache_revision import bump_preview_cache_revision

TEST_ACT = "Пример спецмеры для теста UI"


def main() -> None:
    with SessionLocal() as db:
        stmt = delete(SpecialDuty).where(SpecialDuty.regulatory_act == TEST_ACT)
        res = db.execute(stmt)
        db.commit()
        n = res.rowcount if res.rowcount is not None else 0
    bump_preview_cache_revision("remove_test_special_duty")
    print(f"Удалено строк special_duties с regulatory_act={TEST_ACT!r}: {n}")


if __name__ == "__main__":
    main()
