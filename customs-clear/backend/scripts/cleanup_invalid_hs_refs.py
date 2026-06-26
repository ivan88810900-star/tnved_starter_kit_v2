#!/usr/bin/env python3
"""Автосанация невалидных HS-кодов/префиксов в рабочих таблицах."""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db import SessionLocal
from app.models import HsRate, NonTariffRule, RegulatoryAiExtract, VatPreference
from app.models.tnved import Commodity


def _digits(raw: str) -> str:
    return re.sub(r"\D", "", str(raw or ""))[:10]


def _load_reference_sets() -> tuple[set[str], set[str]]:
    with SessionLocal() as db:
        codes = {_digits(c or "") for (c,) in db.query(Commodity.code).all()}
    codes = {c for c in codes if len(c) == 10}
    prefixes: set[str] = set()
    for c in codes:
        for ln in range(2, 11):
            prefixes.add(c[:ln])
    return codes, prefixes


def _resolve_code_10(raw: str, valid_codes: set[str], valid_prefixes: set[str]) -> str:
    d = _digits(raw)
    if len(d) != 10:
        return ""
    if d in valid_codes:
        return d
    # parent zero-pad
    for ln in range(9, 1, -1):
        cand = d[:ln] + ("0" * (10 - ln))
        if cand in valid_codes:
            return cand
    # nearest prefix to first leaf code lexicographically
    for ln in range(9, 1, -1):
        p = d[:ln]
        if p in valid_prefixes:
            return p + ("0" * (10 - ln)) if (p + ("0" * (10 - ln))) in valid_codes else ""
    return ""


def _resolve_prefix(raw: str, valid_prefixes: set[str], *, allow_zero_global: bool = False) -> str:
    d = _digits(raw)
    if not d:
        return ""
    if allow_zero_global and d == "0000000000":
        return d
    if d in valid_prefixes:
        return d
    for ln in range(min(10, len(d)), 1, -1):
        p = d[:ln]
        if p in valid_prefixes:
            return p
    return ""


def main() -> int:
    valid_codes, valid_prefixes = _load_reference_sets()
    stats = {
        "hs_rates_updated": 0,
        "hs_rates_deleted": 0,
        "vat_updated": 0,
        "vat_deleted": 0,
        "rules_updated": 0,
        "rules_deleted": 0,
        "rai_updated": 0,
        "rai_deleted": 0,
        "rai_dedup_deleted": 0,
    }

    with SessionLocal() as db:
        # hs_rates
        for row in db.query(HsRate).all():
            old_code = _digits(row.hs_code or "")
            old_pref = _digits(row.hs_prefix or "")
            new_code = old_code
            new_pref = old_pref

            if old_code and len(old_code) != 10:
                new_code = ""
            if old_code and len(old_code) == 10 and old_code not in valid_codes:
                new_code = _resolve_code_10(old_code, valid_codes, valid_prefixes)

            if new_code:
                if not new_pref or new_pref not in valid_prefixes:
                    new_pref = _resolve_prefix(new_pref or new_code, valid_prefixes) or new_code
            else:
                new_pref = _resolve_prefix(old_pref, valid_prefixes)

            # В строгом режиме hs_rates хранит только валидные 10-значные hs_code.
            if not new_code:
                db.delete(row)
                stats["hs_rates_deleted"] += 1
                continue

            changed = False
            if new_code and row.hs_code != new_code:
                row.hs_code = new_code
                changed = True
            if new_pref and row.hs_prefix != new_pref:
                row.hs_prefix = new_pref
                changed = True
            if changed:
                stats["hs_rates_updated"] += 1

        # vat_preferences
        for row in db.query(VatPreference).all():
            old = _digits(row.hs_code_prefix or "")
            new = _resolve_prefix(old, valid_prefixes)
            if not new:
                db.delete(row)
                stats["vat_deleted"] += 1
                continue
            if new != old:
                row.hs_code_prefix = new
                stats["vat_updated"] += 1

        # non_tariff_rules
        for row in db.query(NonTariffRule).all():
            old = _digits(row.hs_prefix or "")
            new = _resolve_prefix(old, valid_prefixes)
            if not new:
                db.delete(row)
                stats["rules_deleted"] += 1
                continue
            if new != old:
                row.hs_prefix = new
                stats["rules_updated"] += 1

        # regulatory_ai_extracts (сначала план, потом безопасное применение без коллизий uq)
        rai_rows = db.query(RegulatoryAiExtract).all()
        plan_new: dict[int, str] = {}
        for row in rai_rows:
            old = _digits(row.hs_code_norm or "")
            new = _resolve_prefix(old, valid_prefixes, allow_zero_global=True)
            if not new:
                db.delete(row)
                stats["rai_deleted"] += 1
            else:
                plan_new[int(row.id)] = new

        buckets: dict[tuple[str, str, str], list[RegulatoryAiExtract]] = defaultdict(list)
        for row in rai_rows:
            if row.id not in plan_new:
                continue
            new = plan_new[int(row.id)]
            key = (new, str(row.document_name or ""), str(row.measure_type or ""))
            buckets[key].append(row)

        keepers: list[tuple[RegulatoryAiExtract, str]] = []
        for key, rows in buckets.items():
            rows_sorted = sorted(rows, key=lambda x: int(x.id))
            keeper = rows_sorted[0]
            keepers.append((keeper, key[0]))
            for dup in rows_sorted[1:]:
                db.delete(dup)
                stats["rai_dedup_deleted"] += 1

        # Важно: сначала удалить конфликтующие строки, затем обновлять hs_code_norm.
        db.flush()

        for keeper, new_hs in keepers:
            old_hs = _digits(keeper.hs_code_norm or "")
            if new_hs != old_hs:
                keeper.hs_code_norm = new_hs
                stats["rai_updated"] += 1

        db.commit()

    print("CLEANUP_DONE")
    for k, v in stats.items():
        print(f"{k}={v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
