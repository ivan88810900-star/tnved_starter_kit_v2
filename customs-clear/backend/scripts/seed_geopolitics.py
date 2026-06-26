#!/usr/bin/env python3
"""
Очистка и заполнение справочников геополитики: country_risks, geo_special_duties.

  cd customs-clear/backend
  alembic upgrade head
  python3 scripts/seed_geopolitics.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from sqlalchemy import delete

from app.db import SessionLocal
from app.models import CountryRisk, GeoSpecialDuty, HsRate


def _ensure_hs_rate(db, hs_code: str, *, duty_rate: str | float = 6.0) -> None:
    p = re.sub(r"\D", "", hs_code)[:10]
    if len(p) != 10:
        return
    if db.query(HsRate).filter(HsRate.hs_code == p).first() is not None:
        return
    db.add(
        HsRate(
            hs_code=p,
            hs_prefix=p[:6],
            duty_rate=str(duty_rate).strip() if str(duty_rate).strip() else "0",
            vat_import_rate=22.0,
            source_revision="seed_geopolitics_demo",
        )
    )


def main() -> None:
    unfriendly = [
        ("US", "США"),
        ("GB", "Великобритания"),
        ("CA", "Канада"),
        ("AU", "Австралия"),
        ("JP", "Япония"),
        ("DE", "Германия"),
        ("FR", "Франция"),
        ("IT", "Италия"),
        ("PL", "Польша"),
        ("ES", "Испания"),
        ("NL", "Нидерланды"),
        ("SE", "Швеция"),
        ("BE", "Бельгия"),
        ("AT", "Австрия"),
        ("IE", "Ирландия"),
        ("PT", "Португалия"),
        ("FI", "Финляндия"),
        ("DK", "Дания"),
        ("CZ", "Чехия"),
        ("HU", "Венгрия"),
        ("RO", "Румыния"),
        ("GR", "Греция"),
    ]
    preferential_eaeu = [
        ("BY", "Беларусь", "СТ-1"),
        ("KZ", "Казахстан", "СТ-1"),
        ("AM", "Армения", "СТ-1"),
        ("KG", "Кыргызстан", "СТ-1"),
    ]
    neutral = [
        ("CN", "Китай", "Непреференциальный"),
        ("VN", "Вьетнам", "Form A / СТ-1"),
        ("RU", "Россия", "—"),
    ]

    duties = [
        ("3304", "US", 35.0, "Повышенная пошлина: косметика (пример ПП РФ №2140)", "increased_duty", ""),
        ("3305", "US", 35.0, "Повышенная пошлина: средства для волос (пример ПП РФ №2140)", "increased_duty", ""),
        ("3304", "DE", 35.0, "Повышенная пошлина: косметика из ЕС (пример ПП РФ №2140)", "increased_duty", ""),
        ("9303", "ALL_UNFRIENDLY", 35.0, "Повышенная пошлина: оружие и части (пример ПП РФ №2140)", "increased_duty", ""),
        ("8457", "US", 30.0, "Повышенная пошлина: обрабатывающие центры (пример ПП РФ №2140)", "increased_duty", ""),
        (
            "0406",
            "IT",
            0.0,
            "Демо: запрет ввоза (test_sanctions — сыр из Италии)",
            "embargo",
            "https://www.consultant.ru/document/cons_doc_LAW_498604/",
        ),
    ]

    with SessionLocal() as db:
        db.execute(delete(GeoSpecialDuty))
        db.execute(delete(CountryRisk))
        db.commit()

        for iso, name in unfriendly:
            db.add(
                CountryRisk(
                    iso_code=iso,
                    name_ru=name,
                    is_unfriendly=True,
                    has_preference=False,
                    required_cert="Непреференциальный",
                )
            )
        for iso, name, cert in preferential_eaeu:
            db.add(
                CountryRisk(
                    iso_code=iso,
                    name_ru=name,
                    is_unfriendly=False,
                    has_preference=True,
                    required_cert=cert,
                )
            )
        for iso, name, cert in neutral:
            db.add(
                CountryRisk(
                    iso_code=iso,
                    name_ru=name,
                    is_unfriendly=False,
                    has_preference=False,
                    required_cert=cert,
                )
            )
        for pref, ciso, rate, basis, measure_type, document_link in duties:
            db.add(
                GeoSpecialDuty(
                    hs_code_prefix=pref,
                    country_iso=ciso,
                    duty_rate=str(rate).strip() if str(rate).strip() else "0",
                    document_basis=basis,
                    measure_type=measure_type,
                    document_link=document_link,
                )
            )
        _ensure_hs_rate(db, "3304990000", duty_rate=5.0)
        _ensure_hs_rate(db, "3305100000", duty_rate=5.0)
        _ensure_hs_rate(db, "0406909900", duty_rate=8.0)
        db.commit()

    print("OK: country_risks, geo_special_duties и демо hs_rates обновлены.", flush=True)


if __name__ == "__main__":
    main()
