#!/usr/bin/env python3
"""Аудит покрытия compliance-резолвера по всему каталогу ТН ВЭД."""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from sqlalchemy import func

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db import SessionLocal
from app.models import Commodity, TnvedEntry
from app.models.core import NonTariffRule, RegulatoryAiExtract
from app.models.tnved import NonTariffMeasure
from app.services.compliance_resolver import resolve_compliance_requirements


def _norm_hs(raw: str) -> str:
    return re.sub(r"\D", "", str(raw or ""))[:10]


def _load_hs_codes(db, *, min_len: int = 10) -> list[str]:
    # Основной справочник для прикладной работы — tnved_commodities.
    rows = db.query(Commodity.code).all()
    out = sorted({_norm_hs(r[0]) for r in rows if len(_norm_hs(r[0])) >= min_len})
    if out:
        return out
    # Резервный источник (если commodities не заполнен).
    rows2 = (
        db.query(TnvedEntry.hs_code)
        .filter(TnvedEntry.hs_code.isnot(None))
        .filter(func.length(TnvedEntry.hs_code) >= min_len)
        .all()
    )
    return sorted({_norm_hs(r[0]) for r in rows2 if len(_norm_hs(r[0])) >= min_len})


def _load_source_prefixes(db) -> set[str]:
    prefixes: set[str] = set()
    for (p,) in db.query(NonTariffRule.hs_prefix).all():
        d = _norm_hs(str(p or ""))
        if len(d) >= 2:
            prefixes.add(d)
    for (p,) in db.query(NonTariffMeasure.commodity_code).all():
        d = _norm_hs(str(p or ""))
        if len(d) >= 2:
            prefixes.add(d)
    for hs, mt in db.query(RegulatoryAiExtract.hs_code_norm, RegulatoryAiExtract.measure_type).all():
        d = _norm_hs(str(hs or ""))
        m = str(mt or "").strip().lower()
        if d and d != "0000000000" and len(d) >= 2 and m in {"tr_ts", "license", "vet_control", "ban", "export_control"}:
            prefixes.add(d)
    return prefixes


def _has_source_for_code(hs: str, source_prefixes: set[str]) -> bool:
    return any(hs.startswith(pref) for pref in source_prefixes)


def main() -> int:
    ap = argparse.ArgumentParser(description="Аудит покрытия compliance-резолвера по всей БД ТН ВЭД.")
    ap.add_argument("--min-len", type=int, default=10, help="Минимальная длина HS-кода для проверки (по умолчанию 10).")
    ap.add_argument("--limit", type=int, default=0, help="Ограничить число кодов (0 = все).")
    ap.add_argument("--show-missing", type=int, default=30, help="Сколько примеров отсутствующих покрытий показать.")
    args = ap.parse_args()

    with SessionLocal() as db:
        codes = _load_hs_codes(db, min_len=max(2, int(args.min_len)))
        if int(args.limit) > 0:
            codes = codes[: int(args.limit)]
        if not codes:
            print("Нет кодов ТН ВЭД для аудита.")
            return 1

        src_prefixes = _load_source_prefixes(db)
        total = len(codes)
        covered = 0
        covered_with_source = 0
        source_applicable = 0
        src_missing: list[str] = []
        chapter_total: Counter[str] = Counter()
        chapter_missing: Counter[str] = Counter()
        source_counter: Counter[str] = Counter()

        for hs in codes:
            chapter = hs[:2]
            chapter_total[chapter] += 1
            reqs = resolve_compliance_requirements(hs, None, db)
            if reqs:
                covered += 1
                for r in reqs:
                    source_counter[str(r.source or "unknown")] += 1

            applicable = _has_source_for_code(hs, src_prefixes)
            if applicable:
                source_applicable += 1
                if reqs:
                    covered_with_source += 1
                else:
                    chapter_missing[chapter] += 1
                    src_missing.append(hs)

        cov_all = (covered / total * 100.0) if total else 0.0
        cov_src = (covered_with_source / source_applicable * 100.0) if source_applicable else 0.0

        print("=== COMPLIANCE COVERAGE AUDIT ===")
        print(f"Проверено кодов: {total}")
        print(f"Кодов с любыми требованиями: {covered} ({cov_all:.2f}%)")
        print(f"Кодов, где есть исходные правила/меры: {source_applicable}")
        print(f"Покрытие для кодов с источниками: {covered_with_source}/{source_applicable} ({cov_src:.2f}%)")
        print("")
        print("Топ источников требований:")
        for src, cnt in source_counter.most_common(8):
            print(f"- {src}: {cnt}")

        if source_applicable:
            print("")
            print("Главы с пропусками при наличии исходных данных:")
            miss_rows = []
            for ch, miss in chapter_missing.most_common():
                ttl = chapter_total.get(ch, 0)
                pct = (miss / ttl * 100.0) if ttl else 0.0
                miss_rows.append((ch, miss, ttl, pct))
            if miss_rows:
                for ch, miss, ttl, pct in miss_rows[:12]:
                    print(f"- Глава {ch}: пропуски {miss}/{ttl} ({pct:.2f}%)")
            else:
                print("- Не обнаружено")

        if src_missing and int(args.show_missing) > 0:
            print("")
            print(f"Примеры кодов с пропусками (до {int(args.show_missing)}):")
            for hs in src_missing[: int(args.show_missing)]:
                print(f"- {hs}")

        print("")
        print("AUDIT_DONE")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
