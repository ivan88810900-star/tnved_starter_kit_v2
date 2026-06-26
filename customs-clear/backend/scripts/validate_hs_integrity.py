#!/usr/bin/env python3
"""Проверка целостности ТН ВЭД: кодовая база + БД."""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db import SessionLocal
from app.models import HsRate, NonTariffRule, RegulatoryAiExtract, VatPreference
from app.models.tnved import Commodity, NonTariffMeasure


_DIG10_RE = re.compile(r"(?<!\d)(\d{10})(?!\d)")


def _norm_hs(raw: str) -> str:
    return re.sub(r"\D", "", str(raw or ""))[:10]


def _load_commodity_codes_and_prefixes() -> tuple[set[str], set[str]]:
    with SessionLocal() as db:
        codes = {_norm_hs(c or "") for (c,) in db.query(Commodity.code).all()}
    codes = {c for c in codes if len(c) == 10}
    prefixes: set[str] = set()
    for c in codes:
        for ln in range(2, 11):
            prefixes.add(c[:ln])
    return codes, prefixes


def _scan_source_literals(valid_codes: set[str], *, roots: list[Path]) -> dict[str, list[tuple[str, int]]]:
    bad: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for root in roots:
        for fp in root.rglob("*.py"):
            txt = fp.read_text(encoding="utf-8", errors="ignore")
            for m in _DIG10_RE.finditer(txt):
                code = m.group(1)
                if code == "0000000000":
                    continue
                if code not in valid_codes:
                    line = txt.count("\n", 0, m.start()) + 1
                    bad[code].append((str(fp), line))
    return bad


def _validate_db_refs(valid_codes: set[str], valid_prefixes: set[str]) -> list[str]:
    errs: list[str] = []
    with SessionLocal() as db:
        for row in db.query(HsRate).all():
            c = _norm_hs(row.hs_code or "")
            p = _norm_hs(row.hs_prefix or "")
            if c and len(c) == 10 and c not in valid_codes:
                errs.append(f"hs_rates.id={row.id}: hs_code={c} отсутствует в tnved_commodities")
            if p and p not in valid_prefixes:
                errs.append(f"hs_rates.id={row.id}: hs_prefix={p} не соответствует ни одному коду tnved_commodities")

        for row in db.query(VatPreference).all():
            p = _norm_hs(row.hs_code_prefix or "")
            if p and p not in valid_prefixes:
                errs.append(f"vat_preferences.id={row.id}: hs_code_prefix={p} не соответствует tnved_commodities")

        for row in db.query(NonTariffRule).all():
            p = _norm_hs(row.hs_prefix or "")
            if p and p not in valid_prefixes:
                errs.append(f"non_tariff_rules.id={row.id}: hs_prefix={p} не соответствует tnved_commodities")

        for row in db.query(NonTariffMeasure).all():
            c = _norm_hs(row.commodity_code or "")
            if c and len(c) == 10 and c not in valid_codes:
                errs.append(f"non_tariff_measures.id={row.id}: commodity_code={c} отсутствует в tnved_commodities")

        for row in db.query(RegulatoryAiExtract).all():
            p = _norm_hs(row.hs_code_norm or "")
            if p and p != "0000000000" and p not in valid_prefixes:
                errs.append(f"regulatory_ai_extracts.id={row.id}: hs_code_norm={p} не соответствует tnved_commodities")
    return errs


def main() -> int:
    ap = argparse.ArgumentParser(description="Валидация отсутствия несуществующих кодов ТН ВЭД.")
    ap.add_argument("--check-source", action="store_true", help="Проверить 10-значные литералы в app/ и scripts/.")
    ap.add_argument("--max-print", type=int, default=120, help="Сколько нарушений печатать в лог.")
    args = ap.parse_args()

    valid_codes, valid_prefixes = _load_commodity_codes_and_prefixes()
    print(f"VALID_CODES: {len(valid_codes)}")

    all_errors: list[str] = []
    db_errors = _validate_db_refs(valid_codes, valid_prefixes)
    all_errors.extend(db_errors)
    print(f"DB_ERRORS: {len(db_errors)}")

    if args.check_source:
        bad_literals = _scan_source_literals(valid_codes, roots=[ROOT / "app", ROOT / "scripts"])
        lit_count = sum(len(v) for v in bad_literals.values())
        print(f"SOURCE_LITERAL_ERRORS: {lit_count}")
        for code, refs in sorted(bad_literals.items()):
            all_errors.append(f"source literal {code}: {refs[:3]}")
    else:
        print("SOURCE_LITERAL_ERRORS: skipped")

    if all_errors:
        print("HS_INTEGRITY: FAILED")
        for e in all_errors[: max(1, int(args.max_print))]:
            print(f"- {e}")
        if len(all_errors) > int(args.max_print):
            print(f"... and {len(all_errors) - int(args.max_print)} more")
        return 1

    print("HS_INTEGRITY: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
