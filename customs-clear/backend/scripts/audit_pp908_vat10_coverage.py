#!/usr/bin/env python3
"""Аудит покрытия льготной ставки НДС 10% по Постановлению Правительства РФ №908.

ПП РФ №908 от 31.12.2004 утверждает перечни кодов ТН ВЭД ЕАЭС:
  - Перечень I  — продовольственные товары,
  - Перечень II — товары для детей,
облагаемых НДС по ставке 10% при ввозе.

Скрипт НЕ мутирует БД. Для каждого заголовка ПП908 берётся представительный
10-значный код и проверяется фактическая ставка НДС:
  1) hs_rates (первичный источник, ``find_rate_for_hs``);
  2) при отсутствии 10% — справочник ``vat_preferences``.

Заголовки, целиком относящиеся к льготной группе, должны давать 10%.
Смешанные заголовки (содержащие как детские/продовольственные, так и
«взрослые»/непродовольственные товары) НЕ покрываются на уровне заголовка
во избежание over-claim — они помечены ``mixed_heading``.

Запуск из ``customs-clear/backend``::

  PYTHONPATH=. python3 scripts/audit_pp908_vat10_coverage.py
  PYTHONPATH=. python3 scripts/audit_pp908_vat10_coverage.py --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from sqlalchemy import text  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.services.compliance_resolver import pick_vat_preference_row  # noqa: E402
from app.services.normative_store import find_rate_for_hs  # noqa: E402

# Перечень I — продовольственные товары (заголовки ТН ВЭД, целиком 10%).
PP908_FOOD_HEADINGS: tuple[str, ...] = (
    "0102", "0103", "0104", "0105",
    "0201", "0202", "0203", "0204", "0205", "0206", "0207", "0208", "0209", "0210",
    "0301", "0302", "0303", "0304", "0305", "0306", "0307", "0308",
    "0401", "0402", "0403", "0404", "0405", "0406", "0407", "0408", "0409", "0410",
    "0701", "0702", "0703", "0704", "0705", "0706", "0707", "0708", "0709",
    "0710", "0711", "0712", "0713", "0714",
    "1001", "1002", "1003", "1004", "1005", "1006", "1007", "1008",
    "1101", "1102", "1103", "1104", "1105", "1106", "1108", "1109",
    "1201", "1208", "1212",
    "1501", "1502", "1507", "1508", "1509", "1510", "1511", "1512", "1513", "1514",
    "1515", "1516", "1517",
    "1601", "1602", "1603", "1604", "1605",
    "1701", "1702", "1703", "1704",
    "1806",
    "1901", "1902", "1903", "1904", "1905",
    "2001", "2002", "2003", "2004", "2005", "2006", "2007", "2008", "2009",
    "2101", "2102", "2103", "2104", "2105", "2106",
    "2501",
)

# Перечень II — товары для детей (заголовки, целиком детские → 10%).
PP908_CHILD_HEADINGS: tuple[str, ...] = (
    "6111", "6209",
    "6401", "6402", "6403", "6404", "6405",
    "8715",
    "950300",
)

# Смешанные заголовки ПП908: льготны лишь отдельные субпозиции (детские/
# продовольственные), поэтому на уровне заголовка 10% НЕ применяется
# (иначе over-claim для «взрослых»/непродовольственных позиций).
PP908_MIXED_HEADINGS: dict[str, str] = {
    "1107": "Солод — пивоваренный полупродукт, не относится к 10% продовольствию.",
    "9619": "Гигиенические изделия: детские подгузники (10%) + товары для взрослых (22%).",
    "9404": "Постельные принадлежности: детские (10%) + взрослые матрацы (22%).",
    "4820": "Бумажно-беловая продукция: школьные тетради (10%) + офисные регистры (22%).",
    "4817": "Конверты/карточки + детские изделия — смешанный заголовок.",
}


def _rep_code(db, heading: str) -> str | None:
    row = db.execute(
        text("SELECT hs_code FROM hs_rates WHERE hs_code LIKE :p AND length(hs_code)=10 LIMIT 1"),
        {"p": heading + "%"},
    ).fetchone()
    if row:
        return str(row[0])
    row = db.execute(
        text("SELECT code FROM tnved_commodities WHERE code LIKE :p AND length(code)=10 LIMIT 1"),
        {"p": heading + "%"},
    ).fetchone()
    return str(row[0]) if row else None


def _effective_vat(db, code: str) -> tuple[int | None, str]:
    rate_row, _ = find_rate_for_hs(code)
    if rate_row is not None and int(rate_row.vat_import_rate) == 10:
        return 10, "hs_rates"
    vp, _ = pick_vat_preference_row(code, db)
    if vp is not None and int(vp.vat_rate) == 10:
        return 10, "vat_preferences"
    eff = int(rate_row.vat_import_rate) if rate_row is not None else None
    return eff, "hs_rates" if rate_row is not None else "none"


def audit() -> dict:
    covered: list[dict] = []
    gaps: list[dict] = []
    no_code: list[str] = []
    with SessionLocal() as db:
        for heading in PP908_FOOD_HEADINGS + PP908_CHILD_HEADINGS:
            code = _rep_code(db, heading)
            if code is None:
                no_code.append(heading)
                continue
            eff, source = _effective_vat(db, code)
            entry = {"heading": heading, "sample_code": code, "vat_rate": eff, "source": source}
            if eff == 10:
                covered.append(entry)
            else:
                gaps.append(entry)

    total = len(PP908_FOOD_HEADINGS) + len(PP908_CHILD_HEADINGS)
    checked = total - len(no_code)
    return {
        "status": "OK",
        "summary": {
            "headings_total": total,
            "headings_checked": checked,
            "covered_10pct": len(covered),
            "gaps": len(gaps),
            "no_sample_code": len(no_code),
            "coverage_pct": round(100.0 * len(covered) / checked, 1) if checked else 0.0,
        },
        "gaps": gaps,
        "no_sample_code": no_code,
        "mixed_headings_excluded": PP908_MIXED_HEADINGS,
        "notes": [
            "Read-only audit: hs_rates / vat_preferences не мутируются.",
            "hs_rates — первичный источник; vat_preferences — курируемое дополнение.",
            "Смешанные заголовки не покрываются на уровне заголовка во избежание over-claim.",
        ],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Аудит покрытия НДС 10% по ПП РФ №908")
    ap.add_argument("--json", action="store_true", help="Вывести результат в JSON")
    args = ap.parse_args()
    result = audit()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    s = result["summary"]
    print(f"ПП908 НДС 10% — покрытие: {s['covered_10pct']}/{s['headings_checked']} ({s['coverage_pct']}%)")
    if result["gaps"]:
        print("Пробелы (заголовок → текущая ставка):")
        for g in result["gaps"]:
            print(f"  {g['heading']}  code={g['sample_code']}  vat={g['vat_rate']}")
    else:
        print("Пробелов нет — все целевые заголовки дают 10%.")
    print(f"Смешанные заголовки (исключены намеренно): {', '.join(result['mixed_headings_excluded'])}")


if __name__ == "__main__":
    main()
