from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from sqlalchemy import delete, or_, text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db import SessionLocal, engine
from app.models.tnved import Commodity, NonTariffMeasure

TR_TS_ACT = "ТР ТС 008/2011"
DOC_REQUIRED = "Сертификат/декларация соответствия ТР ТС"
DESC_008 = "ТР ТС 008/2011 — безопасность игрушек (patch_qc_fails)."


def _load_final_qc():
    path = ROOT / "scripts" / "final_qc_check.py"
    spec = importlib.util.spec_from_file_location("final_qc_check", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Не удалось загрузить final_qc_check.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def patch1_delete_vet_phyto_cosmetics_soap(db) -> int:
    """Удалить vet/phyto для кодов, начинающихся с 33 или 34."""
    stmt = delete(NonTariffMeasure).where(
        NonTariffMeasure.measure_type.in_(("vet_control", "phyto_control")),
        or_(
            NonTariffMeasure.commodity_code.like("33%"),
            NonTariffMeasure.commodity_code.like("34%"),
        ),
    )
    res = db.execute(stmt)
    rc = res.rowcount
    return int(rc) if rc is not None and rc >= 0 else 0


def patch2_upsert_tr_ts_toys(db) -> tuple[int, int]:
    """
    Добавить tr_ts 008/2011 для всех 10-значных tnved_commodities с префиксом 9503.
    Возвращает (число целевых кодов, число попыток вставки; фактически вставленные = попытки минус конфликты).
    """
    codes = [
        c[0]
        for c in db.query(Commodity.code)
        .filter(Commodity.code.like("9503%"))
        .order_by(Commodity.code.asc())
        .all()
        if len((c[0] or "").strip()) == 10
    ]
    if not codes:
        return 0, 0

    dialect = engine.dialect.name
    if dialect == "sqlite":
        sql = text(
            """
            INSERT INTO non_tariff_measures
                (commodity_code, measure_type, description, document_required, regulatory_act)
            VALUES
                (:commodity_code, 'tr_ts', :description, :document_required, :regulatory_act)
            ON CONFLICT (commodity_code, measure_type, regulatory_act) DO NOTHING
            """
        )
    elif dialect == "postgresql":
        sql = text(
            """
            INSERT INTO non_tariff_measures
                (commodity_code, measure_type, description, document_required, regulatory_act)
            VALUES
                (:commodity_code, 'tr_ts', :description, :document_required, :regulatory_act)
            ON CONFLICT (commodity_code, measure_type, regulatory_act) DO NOTHING
            """
        )
    else:
        inserted = 0
        for code in codes:
            exists = (
                db.query(NonTariffMeasure)
                .filter(
                    NonTariffMeasure.commodity_code == code,
                    NonTariffMeasure.measure_type == "tr_ts",
                    NonTariffMeasure.regulatory_act == TR_TS_ACT,
                )
                .first()
            )
            if exists:
                continue
            db.add(
                NonTariffMeasure(
                    commodity_code=code,
                    measure_type="tr_ts",
                    description=DESC_008,
                    document_required=DOC_REQUIRED,
                    regulatory_act=TR_TS_ACT,
                )
            )
            inserted += 1
        return len(codes), inserted

    attempted = 0
    for code in codes:
        db.execute(
            sql,
            {
                "commodity_code": code,
                "description": DESC_008,
                "document_required": DOC_REQUIRED,
                "regulatory_act": TR_TS_ACT,
            },
        )
        attempted += 1
    return len(codes), attempted


def run_smoke_qc() -> list[str]:
    mod = _load_final_qc()
    fails: list[str] = []
    codes = ("3304990000", "9503004100")
    with SessionLocal() as db:
        for code10 in codes:
            _, _, rows, _ = mod._collect_effective_measures(db, code10)
            lines = mod._measure_display_lines(rows)
            fails.extend(mod._validate(code10, rows, lines))
    return fails


def main() -> int:
    print("patch_qc_fails: старт")
    with SessionLocal() as db:
        n_del = patch1_delete_vet_phyto_cosmetics_soap(db)
        print(f"  [патч 1] удалено записей non_tariff_measures (vet/phyto, префикс 33/34): {n_del}")

        n_targets, n_ins = patch2_upsert_tr_ts_toys(db)
        print(
            f"  [патч 2] кодов 9503 (10 знаков): {n_targets}; "
            f"выполнено UPSERT-вставок (ON CONFLICT DO NOTHING): {n_ins}"
        )
        db.commit()

    print("  [проверка] final_qc_check-валидация для 3304990000, 9503004100:")
    fails = run_smoke_qc()
    if fails:
        for f in fails:
            print(f"    {f}")
        print("patch_qc_fails: завершено с ошибками валидации")
        return 1
    print("    [OK] замечаний нет, [FAIL] нет")
    print("patch_qc_fails: успешно")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
