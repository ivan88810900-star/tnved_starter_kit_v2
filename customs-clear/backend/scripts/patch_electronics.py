from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import and_, delete, func, or_, text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db import SessionLocal, engine
from app.models.tnved import Commodity, NonTariffMeasure


ELECTRONICS_PREFIXES = ("84", "85", "86", "87", "88", "89", "90")
SMARTPHONE_PREFIXES = ("851713", "851714")

ACT_ENCRYPTION = "Решение Коллегии ЕЭК № 30 (Шифровальные средства)"
ACT_RADIO = "Решение Коллегии ЕЭК № 30 (РЭС и ВЧУ)"


def _prefix_filter(column, prefixes: tuple[str, ...]):
    return or_(*[column.like(f"{p}%") for p in prefixes])


def _sanitize_condition():
    # Удаляем только то, что явно связано с Решением КТС № 299 (санитарный контроль).
    act_l = func.lower(func.coalesce(NonTariffMeasure.regulatory_act, ""))
    desc_l = func.lower(func.coalesce(NonTariffMeasure.description, ""))
    doc_l = func.lower(func.coalesce(NonTariffMeasure.document_required, ""))
    return and_(
        act_l.like("%ктс%"),
        act_l.like("%299%"),
        or_(
            act_l.like("%санитар%"),
            desc_l.like("%санитар%"),
            doc_l.like("%санитар%"),
            desc_l.like("%эпид%"),
            doc_l.like("%эпид%"),
        ),
    )


def delete_false_sanitary_measures(db) -> tuple[int, int]:
    rows = (
        db.query(NonTariffMeasure.id, NonTariffMeasure.commodity_code)
        .filter(
            func.length(NonTariffMeasure.commodity_code) == 10,
            _prefix_filter(NonTariffMeasure.commodity_code, ELECTRONICS_PREFIXES),
            _sanitize_condition(),
        )
        .all()
    )
    ids = [r.id for r in rows]
    if not ids:
        return 0, 0

    unique_codes = {r.commodity_code for r in rows}
    db.execute(delete(NonTariffMeasure).where(NonTariffMeasure.id.in_(ids)))
    return len(ids), len(unique_codes)


def _smartphone_codes(db) -> list[str]:
    rows = (
        db.query(Commodity.code)
        .filter(
            func.length(Commodity.code) == 10,
            _prefix_filter(Commodity.code, SMARTPHONE_PREFIXES),
        )
        .order_by(Commodity.code.asc())
        .all()
    )
    return [r[0] for r in rows if (r[0] or "").strip()]


def upsert_smartphone_measures(db) -> tuple[int, int, int]:
    codes = _smartphone_codes(db)
    if not codes:
        return 0, 0, 0

    acts = (ACT_ENCRYPTION, ACT_RADIO)
    before = (
        db.query(func.count(NonTariffMeasure.id))
        .filter(
            NonTariffMeasure.commodity_code.in_(codes),
            NonTariffMeasure.measure_type == "other",
            NonTariffMeasure.regulatory_act.in_(acts),
        )
        .scalar()
        or 0
    )

    sql = text(
        """
        INSERT INTO non_tariff_measures
            (commodity_code, measure_type, description, document_required, regulatory_act)
        VALUES
            (:commodity_code, 'other', :description, :document_required, :regulatory_act)
        ON CONFLICT (commodity_code, measure_type, regulatory_act)
        DO UPDATE SET
            description = excluded.description,
            document_required = excluded.document_required
        """
    )

    payloads = (
        {
            "regulatory_act": ACT_ENCRYPTION,
            "document_required": "Нотификация ФСБ / Лицензия Минпромторга",
            "description": "Проверка требований по шифровальным (криптографическим) средствам.",
        },
        {
            "regulatory_act": ACT_RADIO,
            "document_required": "Заключение РЧЦ / Лицензия / Сведения из Реестра РЭС",
            "description": "Проверка требований по радиоэлектронным средствам и ВЧУ.",
        },
    )

    attempted = 0
    for code in codes:
        for item in payloads:
            db.execute(
                sql,
                {
                    "commodity_code": code,
                    "regulatory_act": item["regulatory_act"],
                    "document_required": item["document_required"],
                    "description": item["description"],
                },
            )
            attempted += 1

    after = (
        db.query(func.count(NonTariffMeasure.id))
        .filter(
            NonTariffMeasure.commodity_code.in_(codes),
            NonTariffMeasure.measure_type == "other",
            NonTariffMeasure.regulatory_act.in_(acts),
        )
        .scalar()
        or 0
    )
    inserted = max(0, int(after) - int(before))
    return len(codes), attempted, inserted


def verify_sanitary_removed(db) -> int:
    return int(
        db.query(func.count(NonTariffMeasure.id))
        .filter(
            func.length(NonTariffMeasure.commodity_code) == 10,
            _prefix_filter(NonTariffMeasure.commodity_code, ELECTRONICS_PREFIXES),
            _sanitize_condition(),
        )
        .scalar()
        or 0
    )


def main() -> int:
    print("patch_electronics: старт")
    print(f"  dialect={engine.dialect.name}")
    with SessionLocal() as db:
        deleted_rows, affected_codes = delete_false_sanitary_measures(db)
        smartphone_codes, upsert_attempts, inserted = upsert_smartphone_measures(db)
        db.commit()

        still_bad = verify_sanitary_removed(db)

    print(
        "  [delete] удалено ложных санитарных мер "
        f"(Решение КТС № 299, префиксы 84-90): rows={deleted_rows}, codes={affected_codes}"
    )
    print(
        "  [upsert] меры для смартфонов 851713/851714: "
        f"codes={smartphone_codes}, attempts={upsert_attempts}, inserted_new={inserted}"
    )
    print(f"  [verify] остаток ложных записей после патча: {still_bad}")

    if still_bad != 0:
        print("patch_electronics: завершено с ошибкой (ложные записи остались)")
        return 1

    print("patch_electronics: успешно")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
