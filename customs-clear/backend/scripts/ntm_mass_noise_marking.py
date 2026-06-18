#!/usr/bin/env python3
"""Mass noise marking for non_tariff_measures using principle-based classifier.

Marks measures as quality='noise' when their (commodity_code, measure_type)
falls outside the official regulatory scope defined in ntm_layers.py.

Usage:
    cd customs-clear/backend
    python3 -m scripts.ntm_mass_noise_marking [--dry-run] [--revert]

    --dry-run  Show what would change without modifying the database
    --revert   Reset all noise-marked rows back to quality='normal'
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import text

from app.db import SessionLocal
from app.services.ntm_noise_classifier import is_measure_noise

DRY_RUN = "--dry-run" in sys.argv
REVERT = "--revert" in sys.argv


def show_stats(session, label: str) -> dict[str, dict[str, int]]:
    rows = session.execute(text("""
        SELECT measure_type, quality, COUNT(*) as cnt
        FROM non_tariff_measures
        GROUP BY measure_type, quality
        ORDER BY measure_type, quality
    """)).fetchall()

    stats: dict[str, dict[str, int]] = {}
    for mtype, quality, cnt in rows:
        if mtype not in stats:
            stats[mtype] = {"normal": 0, "noise": 0}
        q = quality if quality in ("normal", "noise") else "normal"
        stats[mtype][q] += cnt

    print(f"\n{'=' * 60}")
    print(f"  {label}")
    print(f"{'=' * 60}")
    print(f"  {'measure_type':<20} {'normal':>8} {'noise':>8} {'total':>8}")
    print(f"  {'-' * 48}")
    total_n, total_ns = 0, 0
    for k in sorted(stats):
        n = stats[k]["normal"]
        ns = stats[k]["noise"]
        total_n += n
        total_ns += ns
        print(f"  {k:<20} {n:>8} {ns:>8} {n + ns:>8}")
    print(f"  {'-' * 48}")
    print(f"  {'TOTAL':<20} {total_n:>8} {total_ns:>8} {total_n + total_ns:>8}")
    return stats


def run():
    session = SessionLocal()
    try:
        if REVERT:
            print("REVERT MODE: resetting all noise rows to normal")
            before = show_stats(session, "Before revert")
            if not DRY_RUN:
                result = session.execute(
                    text("UPDATE non_tariff_measures SET quality = 'normal' WHERE quality = 'noise'")
                )
                session.commit()
                print(f"\nReverted {result.rowcount} rows to normal")
            else:
                cnt = session.execute(
                    text("SELECT COUNT(*) FROM non_tariff_measures WHERE quality = 'noise'")
                ).scalar()
                print(f"\nDRY-RUN: would revert {cnt} rows")
            show_stats(session, "After revert")
            return

        before = show_stats(session, "BEFORE noise marking")

        rows = session.execute(text(
            "SELECT id, commodity_code, measure_type FROM non_tariff_measures WHERE quality = 'normal'"
        )).fetchall()

        noise_ids: list[int] = []
        for rid, code, mtype in rows:
            if is_measure_noise(code, mtype):
                noise_ids.append(rid)

        print(f"\nClassifier found {len(noise_ids)} noise measures out of {len(rows)} normal")

        if noise_ids and not DRY_RUN:
            batch_size = 500
            for i in range(0, len(noise_ids), batch_size):
                batch = noise_ids[i : i + batch_size]
                placeholders = ",".join(str(x) for x in batch)
                session.execute(
                    text(f"UPDATE non_tariff_measures SET quality = 'noise' WHERE id IN ({placeholders})")
                )
            session.commit()
            print(f"Marked {len(noise_ids)} measures as noise")
        elif noise_ids:
            print(f"DRY-RUN: would mark {len(noise_ids)} measures as noise")

        after = show_stats(session, "AFTER noise marking")

        print(f"\n{'=' * 60}")
        print("  DELTA (noise added per measure_type)")
        print(f"{'=' * 60}")
        for k in sorted(set(list(before.keys()) + list(after.keys()))):
            b_noise = before.get(k, {}).get("noise", 0)
            a_noise = after.get(k, {}).get("noise", 0)
            delta = a_noise - b_noise
            if delta:
                print(f"  {k:<20} +{delta}")

    finally:
        session.close()


if __name__ == "__main__":
    run()
