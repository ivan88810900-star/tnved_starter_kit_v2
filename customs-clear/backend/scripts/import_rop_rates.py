#!/usr/bin/env python3
"""
Идемпотентный импорт ставок РОП из JSON в rop_goods_rates / rop_packaging_rates / rop_packaging_defaults.

Запуск из customs-clear/backend::

  PYTHONPATH=. python3 scripts/import_rop_rates.py
  PYTHONPATH=. python3 scripts/import_rop_rates.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from sqlalchemy.orm import Session  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models.rop import RopGoodsRate, RopPackagingDefault, RopPackagingRate  # noqa: E402

RATES_JSON = _ROOT / "data" / "rop_rates_2024.json"
DEFAULTS_JSON = _ROOT / "data" / "rop_packaging_defaults.json"

_TYPE_TO_GROUP: dict[str, int | None] = {}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _norm_prefix(raw: str) -> str:
    return re.sub(r"\D", "", (raw or "").strip())[:16]


def _upsert_goods(session: Session, doc: dict[str, Any], *, dry_run: bool) -> tuple[int, int]:
    legal = str(doc.get("legal_ref") or "")
    created = updated = 0
    for item in doc.get("goods") or []:
        group = int(item["pp2414_group"])
        hs_json = json.dumps(item.get("hs_prefixes") or [], ensure_ascii=False)
        for year_str, rates in (item.get("rates_by_year") or {}).items():
            year = int(year_str)
            row = (
                session.query(RopGoodsRate)
                .filter(RopGoodsRate.pp2414_group == group, RopGoodsRate.calendar_year == year)
                .one_or_none()
            )
            payload = {
                "category_code": item["category_code"],
                "category_name": item["category_name"],
                "hs_prefixes_json": hs_json,
                "base_rate_per_ton": float(rates["base_rate_per_ton"]),
                "ke_coefficient": float(rates["ke_coefficient"]),
                "rate_per_ton": float(rates["rate_per_ton"]),
                "recycling_norm": float(rates["recycling_norm"]),
                "legal_ref": legal,
                "notes": str(item.get("notes") or ""),
                "needs_verification": bool(item.get("needs_verification")),
            }
            if row is None:
                created += 1
                if not dry_run:
                    session.add(RopGoodsRate(pp2414_group=group, calendar_year=year, **payload))
            else:
                updated += 1
                if not dry_run:
                    for k, v in payload.items():
                        setattr(row, k, v)
    return created, updated


def _upsert_packaging(session: Session, doc: dict[str, Any], *, dry_run: bool) -> tuple[int, int]:
    legal = str(doc.get("legal_ref") or "")
    type_map = doc.get("packaging_type_to_group") or {}
    created = updated = 0
    for item in doc.get("packaging_groups") or []:
        group = int(item["pp2414_group"])
        pkg_type = ""
        for t, g in type_map.items():
            if g == group:
                pkg_type = str(t)
                break
        for year_str, rates in (item.get("rates_by_year") or {}).items():
            year = int(year_str)
            row = (
                session.query(RopPackagingRate)
                .filter(RopPackagingRate.pp2414_group == group, RopPackagingRate.calendar_year == year)
                .one_or_none()
            )
            payload = {
                "category_code": item["category_code"],
                "category_name": item["category_name"],
                "packaging_type": pkg_type,
                "base_rate_per_ton": float(rates["base_rate_per_ton"]),
                "ke_coefficient": float(rates["ke_coefficient"]),
                "rate_per_ton": float(rates["rate_per_ton"]),
                "recycling_norm": float(rates["recycling_norm"]),
                "legal_ref": legal,
                "notes": str(item.get("notes") or ""),
                "needs_verification": bool(item.get("needs_verification")),
            }
            if row is None:
                created += 1
                if not dry_run:
                    session.add(RopPackagingRate(pp2414_group=group, calendar_year=year, **payload))
            else:
                updated += 1
                if not dry_run:
                    for k, v in payload.items():
                        setattr(row, k, v)
    return created, updated


def _upsert_defaults(session: Session, doc: dict[str, Any], *, dry_run: bool) -> tuple[int, int]:
    global _TYPE_TO_GROUP
    _TYPE_TO_GROUP = {
        str(k): (int(v) if v is not None else None)
        for k, v in (doc.get("packaging_type_to_pp2414_group") or {}).items()
    }
    created = updated = 0
    priority = 100
    for rule in doc.get("rules") or []:
        if rule.get("default"):
            hs = ""
            is_def = True
        else:
            hs = ",".join(_norm_prefix(p) for p in rule.get("hs_prefixes") or [])
            is_def = False
        ptype = str(rule.get("packaging_type") or "carton")
        key = hs if not is_def else "__default__"
        row = session.query(RopPackagingDefault).filter(RopPackagingDefault.hs_prefix == key).one_or_none()
        payload = {
            "packaging_type": ptype,
            "pp2414_group": _TYPE_TO_GROUP.get(ptype),
            "is_default_rule": is_def,
            "reason": str(rule.get("reason") or ""),
            "priority": 0 if is_def else priority,
        }
        if not is_def:
            priority += 1
        if row is None:
            created += 1
            if not dry_run:
                session.add(RopPackagingDefault(hs_prefix=key, **payload))
        else:
            updated += 1
            if not dry_run:
                for k, v in payload.items():
                    setattr(row, k, v)
    return created, updated


def main() -> int:
    ap = argparse.ArgumentParser(description="Import ROP rates into DB")
    ap.add_argument("--rates-json", type=Path, default=RATES_JSON)
    ap.add_argument("--defaults-json", type=Path, default=DEFAULTS_JSON)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    rates_doc = _load_json(args.rates_json)
    defaults_doc = _load_json(args.defaults_json)

    session = SessionLocal()
    try:
        g_c, g_u = _upsert_goods(session, rates_doc, dry_run=args.dry_run)
        p_c, p_u = _upsert_packaging(session, rates_doc, dry_run=args.dry_run)
        d_c, d_u = _upsert_defaults(session, defaults_doc, dry_run=args.dry_run)
        if not args.dry_run:
            session.commit()
        print(
            f"goods: +{g_c}/~{g_u}, packaging: +{p_c}/~{p_u}, defaults: +{d_c}/~{d_u}"
            + (" (dry-run)" if args.dry_run else "")
        )
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
