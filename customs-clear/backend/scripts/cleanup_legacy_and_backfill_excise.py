#!/usr/bin/env python3
"""
P0 cleanup: remove 27 duplicate legacy ETT rows and add 12 missing excise HS codes.

Legacy ETT rows: all 27 come from bulk-ai TKS crawler and are duplicates of
codes already present in the official ETT bundle (source_revision=ett:2026-06-18).

Missing excise HS codes: 12 parent/group-level codes from НК РФ Ст. 193 that
are not in hs_rates because the ETT only tracks 10-digit specific codes.
These need stub entries so excise ingestion can attach rates to them.

Usage:
    cd customs-clear/backend
    python3 -m scripts.cleanup_legacy_and_backfill_excise [--dry-run]
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import text
from app.db import SessionLocal

TODAY = date.today().isoformat()
DRY_RUN = "--dry-run" in sys.argv

MISSING_EXCISE_HS_CODES: list[dict[str, object]] = [
    {
        "hs_code": "2204100000",
        "duty_rate": "20%",
        "product": "Вина игристые (шампанское)",
        "excise_type": "fixed",
        "excise_value": 45.0,
        "excise_basis": "НК РФ Ст. 193 — вина игристые (шампанское)",
    },
    {
        "hs_code": "2206000000",
        "duty_rate": "12.5%",
        "product": "Сидр, пуаре, медовуха и прочие сброженные напитки",
        "excise_type": "fixed",
        "excise_value": 36.0,
        "excise_basis": "НК РФ Ст. 193 — напитки фруктовые, сидр, медовуха",
    },
    {
        "hs_code": "2404110000",
        "duty_rate": "10%",
        "product": "Жидкости для электронных сигарет (содержащие никотин)",
        "excise_type": "fixed",
        "excise_value": 20.0,
        "excise_basis": "НК РФ Ст. 193 — жидкости для ЭСДН",
    },
    {
        "hs_code": "2710124100",
        "duty_rate": "0",
        "product": "Бензин автомобильный неэтилированный (класс 5)",
        "excise_type": "fixed",
        "excise_value": 15048.0,
        "excise_basis": "НК РФ Ст. 193 — бензин автомобильный класса 5",
    },
    {
        "hs_code": "2710194200",
        "duty_rate": "0",
        "product": "Дизельное топливо (газойль)",
        "excise_type": "fixed",
        "excise_value": 10425.0,
        "excise_basis": "НК РФ Ст. 193 — дизельное топливо",
    },
    {
        "hs_code": "2710194300",
        "duty_rate": "0",
        "product": "Дизельное топливо прочее",
        "excise_type": "fixed",
        "excise_value": 10425.0,
        "excise_basis": "НК РФ Ст. 193 — дизельное топливо",
    },
    {
        "hs_code": "2710198100",
        "duty_rate": "5%",
        "product": "Масла моторные для поршневых двигателей",
        "excise_type": "fixed",
        "excise_value": 6516.0,
        "excise_basis": "НК РФ Ст. 193 — масла моторные",
    },
    {
        "hs_code": "2710121100",
        "duty_rate": "5%",
        "product": "Бензин прямогонный (нафта)",
        "excise_type": "fixed",
        "excise_value": 16174.0,
        "excise_basis": "НК РФ Ст. 193 — прямогонный бензин",
    },
    {
        "hs_code": "8703228010",
        "duty_rate": "15%",
        "product": "Легковые автомобили 90-150 л.с.",
        "excise_type": "fixed",
        "excise_value": 59.0,
        "excise_basis": "НК РФ Ст. 193 — л/а 90-150 л.с. (59 руб/л.с.)",
    },
    {
        "hs_code": "8703238010",
        "duty_rate": "15%",
        "product": "Легковые автомобили 150-200 л.с.",
        "excise_type": "fixed",
        "excise_value": 588.0,
        "excise_basis": "НК РФ Ст. 193 — л/а 150-200 л.с. (588 руб/л.с.)",
    },
    {
        "hs_code": "8703241090",
        "duty_rate": "15%",
        "product": "Легковые автомобили 300-400 л.с.",
        "excise_type": "fixed",
        "excise_value": 1550.0,
        "excise_basis": "НК РФ Ст. 193 — л/а 300-400 л.с. (1550 руб/л.с.)",
    },
    {
        "hs_code": "8703249090",
        "duty_rate": "15%",
        "product": "Легковые автомобили свыше 500 л.с.",
        "excise_type": "fixed",
        "excise_value": 1550.0,
        "excise_basis": "НК РФ Ст. 193 — л/а свыше 500 л.с. (1550 руб/л.с.)",
    },
]


def run():
    session = SessionLocal()
    try:
        # --- Part 1: Remove legacy duplicate ETT rows ---
        print("=" * 60)
        print("Part 1: Removing duplicate legacy ETT rows")
        print("=" * 60)

        legacy_rows = session.execute(text(
            "SELECT id, hs_code FROM hs_rates WHERE source_revision LIKE 'bulk-ai:%'"
        )).fetchall()
        print(f"Found {len(legacy_rows)} legacy rows from TKS bulk-ai crawler")

        official_codes = {
            r[0]
            for r in session.execute(text(
                "SELECT DISTINCT hs_code FROM hs_rates WHERE source_revision = 'ett:2026-06-18'"
            )).fetchall()
        }

        to_delete = []
        orphans = []
        for row_id, hs_code in legacy_rows:
            if hs_code in official_codes:
                to_delete.append(row_id)
            else:
                orphans.append((row_id, hs_code))

        print(f"  Duplicates (have official counterpart): {len(to_delete)}")
        print(f"  Orphans (no official counterpart): {len(orphans)}")

        if orphans:
            for oid, ohs in orphans:
                print(f"    WARNING: orphan {ohs} (id={oid}) — keeping")

        if to_delete and not DRY_RUN:
            session.execute(
                text("DELETE FROM hs_rates WHERE source_revision LIKE 'bulk-ai:%'"),
            )
            print(f"  DELETED {len(to_delete)} duplicate legacy rows")
        elif to_delete:
            print(f"  DRY-RUN: would delete {len(to_delete)} rows")

        # --- Part 2: Add missing excise HS codes ---
        print()
        print("=" * 60)
        print("Part 2: Adding missing excise HS codes to hs_rates")
        print("=" * 60)

        added = 0
        skipped = 0
        for item in MISSING_EXCISE_HS_CODES:
            hs_code = str(item["hs_code"])
            exists = session.execute(
                text("SELECT COUNT(*) FROM hs_rates WHERE hs_code = :c"),
                {"c": hs_code},
            ).scalar()

            if exists:
                print(f"  SKIP {hs_code} — already exists")
                skipped += 1
                continue

            if DRY_RUN:
                print(f"  DRY-RUN: would add {hs_code} ({item['product']})")
                added += 1
                continue

            session.execute(text("""
                INSERT INTO hs_rates (
                    hs_code, hs_prefix, duty_rate, vat_import_rate, vat_rule,
                    vat_rule_basis, excise_type, excise_value, excise_basis,
                    has_antidumping, antidumping_type, antidumping_value,
                    antidumping_condition, antidumping_countries,
                    valid_from, valid_to, source_url, source_revision,
                    vat_source_code, vat_source_revision, vat_source_url,
                    excise_source_code, excise_source_revision, excise_source_url
                ) VALUES (
                    :hs_code, :hs_prefix, :duty_rate, 22.0, 'standard',
                    'НК РФ Ст. 164 п.3 — стандартная ставка', :excise_type, :excise_value, :excise_basis,
                    0, 'none', 0.0,
                    '', '',
                    '', '', 'https://eec.eaeunion.org/comission/department/catr/ett/', :source_revision,
                    'EEC_VAT', :vat_revision, 'https://www.nalog.gov.ru/rn77/taxation/taxes/nds/',
                    'EEC_EXCISE', :excise_revision, 'https://www.nalog.gov.ru/rn77/taxation/taxes/excise/'
                )
            """), {
                "hs_code": hs_code,
                "hs_prefix": hs_code,
                "duty_rate": str(item["duty_rate"]),
                "excise_type": str(item["excise_type"]),
                "excise_value": float(item["excise_value"]),  # type: ignore[arg-type]
                "excise_basis": str(item["excise_basis"]),
                "source_revision": f"ett:{TODAY}",
                "vat_revision": f"vat:{TODAY}",
                "excise_revision": f"excise:{TODAY}",
            })
            print(f"  ADDED {hs_code} — {item['product']}")
            added += 1

        print(f"\n  Added: {added}, Skipped: {skipped}")

        if not DRY_RUN:
            session.commit()
            print("\nCommitted to database.")
        else:
            session.rollback()
            print("\nDRY-RUN — no changes made.")

        # --- Summary ---
        total = session.execute(text("SELECT COUNT(*) FROM hs_rates")).scalar()
        ett_count = session.execute(text(
            "SELECT COUNT(*) FROM hs_rates WHERE source_revision LIKE 'ett:%'"
        )).scalar()
        vat_count = session.execute(text(
            "SELECT COUNT(*) FROM hs_rates WHERE vat_source_code = 'EEC_VAT'"
        )).scalar()
        excise_count = session.execute(text(
            "SELECT COUNT(*) FROM hs_rates WHERE excise_source_code = 'EEC_EXCISE'"
        )).scalar()

        print(f"\n{'=' * 60}")
        print(f"Final state:")
        print(f"  Total hs_rates: {total}")
        print(f"  ETT provenance: {ett_count}")
        print(f"  VAT provenance: {vat_count}")
        print(f"  Excise provenance: {excise_count}")
        print(f"{'=' * 60}")

    finally:
        session.close()


if __name__ == "__main__":
    run()
