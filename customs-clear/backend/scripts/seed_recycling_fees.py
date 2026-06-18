#!/usr/bin/env python3
"""Seed recycling_fees with vehicle recycling fee rates per ПП РФ №870.

Recycling fee = base_rate × coefficient
Base rates and coefficients vary by vehicle type, engine volume, and new/used status.

Usage:
    cd customs-clear/backend
    python3 -m scripts.seed_recycling_fees [--dry-run]
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import text
from app.db import SessionLocal, engine, Base

DRY_RUN = "--dry-run" in sys.argv

LEGAL_REF = "ПП РФ от 26.12.2013 № 1291 (ред. ПП РФ № 870)"

# ═══════════════════════════════════════════════════════════════════
# Recycling fee entries
# base_rate × coefficient = fee amount in RUB
# ═══════════════════════════════════════════════════════════════════
FEES = [
    # ─── 8703: Легковые автомобили ───
    # Новые
    {"hs": "8703", "type": "car_new_0_1000", "is_new": True, "base": 20000, "coeff": 0.17, "vol_from": 0, "vol_to": 1000, "desc": "Легковые новые, до 1000 куб.см"},
    {"hs": "8703", "type": "car_new_1000_2000", "is_new": True, "base": 20000, "coeff": 4.2, "vol_from": 1000, "vol_to": 2000, "desc": "Легковые новые, 1000-2000 куб.см"},
    {"hs": "8703", "type": "car_new_2000_3000", "is_new": True, "base": 20000, "coeff": 6.3, "vol_from": 2000, "vol_to": 3000, "desc": "Легковые новые, 2000-3000 куб.см"},
    {"hs": "8703", "type": "car_new_3000_3500", "is_new": True, "base": 20000, "coeff": 8.92, "vol_from": 3000, "vol_to": 3500, "desc": "Легковые новые, 3000-3500 куб.см"},
    {"hs": "8703", "type": "car_new_3500+", "is_new": True, "base": 20000, "coeff": 12.56, "vol_from": 3500, "vol_to": None, "desc": "Легковые новые, свыше 3500 куб.см"},
    {"hs": "8703", "type": "car_new_electric", "is_new": True, "base": 20000, "coeff": 0.17, "vol_from": None, "vol_to": None, "desc": "Электромобили легковые новые"},
    # Б/у (старше 3 лет)
    {"hs": "8703", "type": "car_used_0_1000", "is_new": False, "base": 20000, "coeff": 0.26, "vol_from": 0, "vol_to": 1000, "desc": "Легковые б/у, до 1000 куб.см"},
    {"hs": "8703", "type": "car_used_1000_2000", "is_new": False, "base": 20000, "coeff": 8.26, "vol_from": 1000, "vol_to": 2000, "desc": "Легковые б/у, 1000-2000 куб.см"},
    {"hs": "8703", "type": "car_used_2000_3000", "is_new": False, "base": 20000, "coeff": 16.12, "vol_from": 2000, "vol_to": 3000, "desc": "Легковые б/у, 2000-3000 куб.см"},
    {"hs": "8703", "type": "car_used_3000_3500", "is_new": False, "base": 20000, "coeff": 28.5, "vol_from": 3000, "vol_to": 3500, "desc": "Легковые б/у, 3000-3500 куб.см"},
    {"hs": "8703", "type": "car_used_3500+", "is_new": False, "base": 20000, "coeff": 35.01, "vol_from": 3500, "vol_to": None, "desc": "Легковые б/у, свыше 3500 куб.см"},
    {"hs": "8703", "type": "car_used_electric", "is_new": False, "base": 20000, "coeff": 0.26, "vol_from": None, "vol_to": None, "desc": "Электромобили легковые б/у"},

    # ─── 8701: Тракторы ───
    {"hs": "8701", "type": "tractor_new", "is_new": True, "base": 150000, "coeff": 1.0, "vol_from": None, "vol_to": None, "desc": "Тракторы новые (базовый)"},
    {"hs": "8701", "type": "tractor_used", "is_new": False, "base": 150000, "coeff": 3.0, "vol_from": None, "vol_to": None, "desc": "Тракторы б/у"},

    # ─── 8702: Автобусы (>10 чел) ───
    {"hs": "8702", "type": "bus_new_0_2500", "is_new": True, "base": 150000, "coeff": 1.0, "vol_from": 0, "vol_to": 2500, "desc": "Автобусы новые, до 2500 куб.см"},
    {"hs": "8702", "type": "bus_new_2500_5000", "is_new": True, "base": 150000, "coeff": 2.14, "vol_from": 2500, "vol_to": 5000, "desc": "Автобусы новые, 2500-5000 куб.см"},
    {"hs": "8702", "type": "bus_new_5000+", "is_new": True, "base": 150000, "coeff": 3.22, "vol_from": 5000, "vol_to": None, "desc": "Автобусы новые, свыше 5000 куб.см"},
    {"hs": "8702", "type": "bus_used_0_2500", "is_new": False, "base": 150000, "coeff": 2.0, "vol_from": 0, "vol_to": 2500, "desc": "Автобусы б/у, до 2500 куб.см"},
    {"hs": "8702", "type": "bus_used_2500_5000", "is_new": False, "base": 150000, "coeff": 4.56, "vol_from": 2500, "vol_to": 5000, "desc": "Автобусы б/у, 2500-5000 куб.см"},
    {"hs": "8702", "type": "bus_used_5000+", "is_new": False, "base": 150000, "coeff": 6.68, "vol_from": 5000, "vol_to": None, "desc": "Автобусы б/у, свыше 5000 куб.см"},

    # ─── 8704: Грузовые ───
    {"hs": "8704", "type": "truck_new_0_2500", "is_new": True, "base": 150000, "coeff": 0.5, "vol_from": 0, "vol_to": 2500, "desc": "Грузовые новые, до 2500 куб.см"},
    {"hs": "8704", "type": "truck_new_2500_5000", "is_new": True, "base": 150000, "coeff": 1.52, "vol_from": 2500, "vol_to": 5000, "desc": "Грузовые новые, 2500-5000 куб.см"},
    {"hs": "8704", "type": "truck_new_5000_8000", "is_new": True, "base": 150000, "coeff": 3.03, "vol_from": 5000, "vol_to": 8000, "desc": "Грузовые новые, 5000-8000 куб.см"},
    {"hs": "8704", "type": "truck_new_8000+", "is_new": True, "base": 150000, "coeff": 5.73, "vol_from": 8000, "vol_to": None, "desc": "Грузовые новые, свыше 8000 куб.см"},
    {"hs": "8704", "type": "truck_used_0_2500", "is_new": False, "base": 150000, "coeff": 1.0, "vol_from": 0, "vol_to": 2500, "desc": "Грузовые б/у, до 2500 куб.см"},
    {"hs": "8704", "type": "truck_used_2500_5000", "is_new": False, "base": 150000, "coeff": 4.56, "vol_from": 2500, "vol_to": 5000, "desc": "Грузовые б/у, 2500-5000 куб.см"},
    {"hs": "8704", "type": "truck_used_5000_8000", "is_new": False, "base": 150000, "coeff": 7.04, "vol_from": 5000, "vol_to": 8000, "desc": "Грузовые б/у, 5000-8000 куб.см"},
    {"hs": "8704", "type": "truck_used_8000+", "is_new": False, "base": 150000, "coeff": 12.2, "vol_from": 8000, "vol_to": None, "desc": "Грузовые б/у, свыше 8000 куб.см"},

    # ─── 8705: Спецтехника ───
    {"hs": "8705", "type": "special_new", "is_new": True, "base": 150000, "coeff": 1.0, "vol_from": None, "vol_to": None, "desc": "Спецтехника на шасси (новая)"},
    {"hs": "8705", "type": "special_used", "is_new": False, "base": 150000, "coeff": 3.0, "vol_from": None, "vol_to": None, "desc": "Спецтехника на шасси (б/у)"},

    # ─── 8711: Мотоциклы ───
    {"hs": "8711", "type": "moto_new_0_300", "is_new": True, "base": 9000, "coeff": 0.25, "vol_from": 0, "vol_to": 300, "desc": "Мотоциклы новые, до 300 куб.см"},
    {"hs": "8711", "type": "moto_new_300_500", "is_new": True, "base": 9000, "coeff": 0.68, "vol_from": 300, "vol_to": 500, "desc": "Мотоциклы новые, 300-500 куб.см"},
    {"hs": "8711", "type": "moto_new_500_800", "is_new": True, "base": 9000, "coeff": 1.13, "vol_from": 500, "vol_to": 800, "desc": "Мотоциклы новые, 500-800 куб.см"},
    {"hs": "8711", "type": "moto_new_800+", "is_new": True, "base": 9000, "coeff": 2.48, "vol_from": 800, "vol_to": None, "desc": "Мотоциклы новые, свыше 800 куб.см"},
    {"hs": "8711", "type": "moto_used_0_300", "is_new": False, "base": 9000, "coeff": 0.25, "vol_from": 0, "vol_to": 300, "desc": "Мотоциклы б/у, до 300 куб.см"},
    {"hs": "8711", "type": "moto_used_300_500", "is_new": False, "base": 9000, "coeff": 1.45, "vol_from": 300, "vol_to": 500, "desc": "Мотоциклы б/у, 300-500 куб.см"},
    {"hs": "8711", "type": "moto_used_500_800", "is_new": False, "base": 9000, "coeff": 2.26, "vol_from": 500, "vol_to": 800, "desc": "Мотоциклы б/у, 500-800 куб.см"},
    {"hs": "8711", "type": "moto_used_800+", "is_new": False, "base": 9000, "coeff": 5.23, "vol_from": 800, "vol_to": None, "desc": "Мотоциклы б/у, свыше 800 куб.см"},
    {"hs": "8711", "type": "moto_new_electric", "is_new": True, "base": 9000, "coeff": 0.25, "vol_from": None, "vol_to": None, "desc": "Электромотоциклы новые"},
    {"hs": "8711", "type": "moto_used_electric", "is_new": False, "base": 9000, "coeff": 0.25, "vol_from": None, "vol_to": None, "desc": "Электромотоциклы б/у"},
]


def seed() -> dict[str, int]:
    from app.models.tnved import RecyclingFee
    Base.metadata.create_all(engine, tables=[RecyclingFee.__table__])

    inserted = 0
    with SessionLocal() as db:
        for fee in FEES:
            exists = db.execute(
                text("SELECT 1 FROM recycling_fees WHERE hs_prefix = :hs AND vehicle_type = :vt AND is_new = :n"),
                {"hs": fee["hs"], "vt": fee["type"], "n": 1 if fee["is_new"] else 0},
            ).fetchone()
            if exists:
                continue
            row = RecyclingFee(
                hs_prefix=fee["hs"],
                vehicle_type=fee["type"],
                is_new=fee["is_new"],
                base_rate=fee["base"],
                coefficient=fee["coeff"],
                engine_volume_from=fee["vol_from"],
                engine_volume_to=fee["vol_to"],
                description=fee["desc"],
                legal_ref=LEGAL_REF,
            )
            db.add(row)
            inserted += 1

        if DRY_RUN:
            db.rollback()
            print(f"[DRY RUN] Would insert {inserted} recycling fee entries")
        else:
            db.commit()
            print(f"Inserted {inserted} recycling fee entries")

        total = db.execute(text("SELECT COUNT(*) FROM recycling_fees")).scalar()
        by_hs = db.execute(text(
            "SELECT hs_prefix, COUNT(*) FROM recycling_fees GROUP BY hs_prefix ORDER BY hs_prefix"
        )).fetchall()
        print(f"Total: {total}")
        for hs, c in by_hs:
            print(f"  {hs}: {c} rates")

    return {"inserted": inserted, "total": total}


if __name__ == "__main__":
    seed()
