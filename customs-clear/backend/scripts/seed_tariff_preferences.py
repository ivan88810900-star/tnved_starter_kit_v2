#!/usr/bin/env python3
"""Seed country_tariff_preferences with duty coefficients by preference type.

Preference types and coefficients:
  eaeu      — EAEU members (BY, KZ, AM, KG): 0.0 (zero duty within union)
  sng       — CIS FTA countries: 0.0 (free trade agreement)
  gsp       — GSP beneficiaries (developing): 0.75 (75% of base rate)
  ldc       — Least Developed Countries: 0.0 (zero duty per EAEU Decision)
  mfn       — MFN/WTO members (default): 1.0 (full base rate)
  non_mfn   — Non-MFN countries: 2.0 (double rate)

Usage:
    cd customs-clear/backend
    python3 -m scripts.seed_tariff_preferences [--dry-run]
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import text
from app.db import SessionLocal, engine, Base

DRY_RUN = "--dry-run" in sys.argv

# ═══════════════════════════════════════════════════════════════════
# EAEU members — zero customs duty within the Eurasian Economic Union
# Договор о ЕАЭС от 29.05.2014
# ═══════════════════════════════════════════════════════════════════
EAEU_COUNTRIES = {
    "BY": "Беларусь",
    "KZ": "Казахстан",
    "AM": "Армения",
    "KG": "Кыргызстан",
}

# ═══════════════════════════════════════════════════════════════════
# CIS Free Trade Area — zero/reduced duty
# Договор о зоне свободной торговли СНГ от 18.10.2011
# ═══════════════════════════════════════════════════════════════════
SNG_FTA_COUNTRIES = {
    "UZ": "Узбекистан",
    "TJ": "Таджикистан",
    "MD": "Молдова",
    "AZ": "Азербайджан",
}

# ═══════════════════════════════════════════════════════════════════
# GSP beneficiaries — developing countries, 75% of base rate
# Решение Комиссии ТС № 130 от 27.11.2009
# ═══════════════════════════════════════════════════════════════════
GSP_COUNTRIES = {
    "CN": "Китай",
    "BR": "Бразилия",
    "IN": "Индия",
    "TR": "Турция",
    "AR": "Аргентина",
    "MX": "Мексика",
    "CL": "Чили",
    "MY": "Малайзия",
    "TH": "Таиланд",
    "ID": "Индонезия",
    "PH": "Филиппины",
    "VN": "Вьетнам",
    "EG": "Египет",
    "ZA": "ЮАР",
    "PE": "Перу",
    "CO": "Колумбия",
    "EC": "Эквадор",
    "UY": "Уругвай",
    "PY": "Парагвай",
    "CR": "Коста-Рика",
    "PA": "Панама",
    "JO": "Иордания",
    "LB": "Ливан",
    "TN": "Тунис",
    "MA": "Марокко",
    "DZ": "Алжир",
    "LK": "Шри-Ланка",
    "PK": "Пакистан",
    "KW": "Кувейт",
    "QA": "Катар",
    "AE": "ОАЭ",
    "SA": "Саудовская Аравия",
    "OM": "Оман",
    "BH": "Бахрейн",
    "IR": "Иран",
    "IQ": "Ирак",
    "SY": "Сирия",
    "GH": "Гана",
    "NG": "Нигерия",
    "KE": "Кения",
    "SN": "Сенегал",
    "CI": "Кот-д'Ивуар",
    "CM": "Камерун",
    "GA": "Габон",
    "CG": "Конго",
    "RS": "Сербия",
    "BA": "Босния и Герцеговина",
    "MK": "Северная Македония",
    "ME": "Черногория",
    "AL": "Албания",
    "GE": "Грузия",
    "MN": "Монголия",
    "FJ": "Фиджи",
    "CU": "Куба",
    "DO": "Доминиканская Республика",
    "GT": "Гватемала",
    "HN": "Гондурас",
    "SV": "Сальвадор",
    "NI": "Никарагуа",
    "BO": "Боливия",
    "GY": "Гайана",
    "SR": "Суринам",
    "JM": "Ямайка",
    "TT": "Тринидад и Тобаго",
    "BZ": "Белиз",
    "NA": "Намибия",
    "BW": "Ботсвана",
    "MU": "Маврикий",
}

# ═══════════════════════════════════════════════════════════════════
# LDC — Least Developed Countries, zero duty
# Решение Совета ЕЭК от 13.01.2017 № 8
# ═══════════════════════════════════════════════════════════════════
LDC_COUNTRIES = {
    "AF": "Афганистан",
    "BD": "Бангладеш",
    "BJ": "Бенин",
    "BF": "Буркина-Фасо",
    "BI": "Бурунди",
    "KH": "Камбоджа",
    "CF": "ЦАР",
    "TD": "Чад",
    "KM": "Коморы",
    "CD": "ДР Конго",
    "DJ": "Джибути",
    "GQ": "Экваториальная Гвинея",
    "ER": "Эритрея",
    "ET": "Эфиопия",
    "GM": "Гамбия",
    "GN": "Гвинея",
    "GW": "Гвинея-Бисау",
    "HT": "Гаити",
    "LA": "Лаос",
    "LS": "Лесото",
    "LR": "Либерия",
    "MG": "Мадагаскар",
    "MW": "Малави",
    "ML": "Мали",
    "MR": "Мавритания",
    "MZ": "Мозамбик",
    "MM": "Мьянма",
    "NP": "Непал",
    "NE": "Нигер",
    "RW": "Руанда",
    "ST": "Сан-Томе и Принсипи",
    "SL": "Сьерра-Леоне",
    "SB": "Соломоновы Острова",
    "SO": "Сомали",
    "SS": "Южный Судан",
    "SD": "Судан",
    "TZ": "Танзания",
    "TG": "Того",
    "TL": "Тимор-Лесте",
    "UG": "Уганда",
    "YE": "Йемен",
    "ZM": "Замбия",
}

# ═══════════════════════════════════════════════════════════════════
# MFN — Most Favoured Nation (WTO members, standard rate)
# Major trading partners not in GSP/LDC/EAEU/SNG
# ═══════════════════════════════════════════════════════════════════
MFN_COUNTRIES = {
    "US": "США",
    "DE": "Германия",
    "FR": "Франция",
    "IT": "Италия",
    "GB": "Великобритания",
    "JP": "Япония",
    "KR": "Южная Корея",
    "CA": "Канада",
    "AU": "Австралия",
    "NZ": "Новая Зеландия",
    "CH": "Швейцария",
    "NO": "Норвегия",
    "SE": "Швеция",
    "FI": "Финляндия",
    "DK": "Дания",
    "NL": "Нидерланды",
    "BE": "Бельгия",
    "AT": "Австрия",
    "ES": "Испания",
    "PT": "Португалия",
    "PL": "Польша",
    "CZ": "Чехия",
    "HU": "Венгрия",
    "RO": "Румыния",
    "BG": "Болгария",
    "HR": "Хорватия",
    "SK": "Словакия",
    "SI": "Словения",
    "LT": "Литва",
    "LV": "Латвия",
    "EE": "Эстония",
    "IE": "Ирландия",
    "LU": "Люксембург",
    "MT": "Мальта",
    "CY": "Кипр",
    "GR": "Греция",
    "IL": "Израиль",
    "SG": "Сингапур",
    "TW": "Тайвань",
    "HK": "Гонконг",
    "IS": "Исландия",
    "UA": "Украина",
}

# ═══════════════════════════════════════════════════════════════════
# Non-MFN — countries without trade agreements, double rate
# ═══════════════════════════════════════════════════════════════════
NON_MFN_COUNTRIES = {
    "KP": "КНДР",
}

LEGAL_REFS = {
    "eaeu": "Договор о ЕАЭС от 29.05.2014, Приложение № 6",
    "sng": "Договор о зоне свободной торговли СНГ от 18.10.2011",
    "gsp": "Решение Комиссии ТС № 130 от 27.11.2009 (ЕТТ ТС, Единая система преференций)",
    "ldc": "Решение Совета ЕЭК № 8 от 13.01.2017 (преференции для НРС)",
    "mfn": "ЕТТ ЕАЭС — базовая ставка РНБ",
    "non_mfn": "Приложение к ЕТТ ЕАЭС — удвоенная ставка при отсутствии РНБ",
}

EFFECTIVE_DATES = {
    "eaeu": "2015-01-01",
    "sng": "2012-09-20",
    "gsp": "2010-01-01",
    "ldc": "2017-06-01",
    "mfn": "2015-01-01",
    "non_mfn": "2015-01-01",
}

COEFFICIENTS = {
    "eaeu": 0.0,
    "sng": 0.0,
    "gsp": 0.75,
    "ldc": 0.0,
    "mfn": 1.0,
    "non_mfn": 2.0,
}

ALL_GROUPS = [
    ("eaeu", EAEU_COUNTRIES),
    ("sng", SNG_FTA_COUNTRIES),
    ("gsp", GSP_COUNTRIES),
    ("ldc", LDC_COUNTRIES),
    ("mfn", MFN_COUNTRIES),
    ("non_mfn", NON_MFN_COUNTRIES),
]


def seed() -> dict[str, int]:
    from app.models.tnved import CountryTariffPreference
    Base.metadata.create_all(engine, tables=[CountryTariffPreference.__table__])

    stats: dict[str, int] = {}
    total = 0

    with SessionLocal() as db:
        for pref_type, countries in ALL_GROUPS:
            count = 0
            for iso, name_ru in sorted(countries.items()):
                exists = db.execute(
                    text("SELECT 1 FROM country_tariff_preferences WHERE country_code = :cc"),
                    {"cc": iso},
                ).fetchone()
                if exists:
                    continue
                row = CountryTariffPreference(
                    country_code=iso,
                    preference_type=pref_type,
                    duty_coefficient=COEFFICIENTS[pref_type],
                    legal_ref=LEGAL_REFS[pref_type],
                    effective_from=EFFECTIVE_DATES[pref_type],
                )
                db.add(row)
                count += 1
            stats[pref_type] = count
            total += count

        if DRY_RUN:
            db.rollback()
            print(f"[DRY RUN] Would insert {total} country preferences")
        else:
            db.commit()
            print(f"Inserted {total} country tariff preferences")

        for pref_type, count in stats.items():
            coeff = COEFFICIENTS[pref_type]
            print(f"  {pref_type:10s}: {count:3d} countries, coefficient={coeff}")

    return stats


if __name__ == "__main__":
    seed()
