from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import func

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")
load_dotenv()

from app.db import SessionLocal, engine
from app.models.core import HsRate
from app.models.tnved import Commodity
from app.services.invoice_analyzer import _parse_duty_rate


def _fmt_percent(value: float) -> str:
    if value is None:
        return "0%"
    if abs(value - round(value)) < 1e-9:
        return f"{int(round(value))}%"
    txt = f"{value:.4f}".rstrip("0").rstrip(".")
    return f"{txt}%"


def _catalog_import_duty_text(duty_raw: str) -> str:
    """Текст для поля Commodity.import_duty: сложные формулировки как есть, иначе «N%»."""
    s = (duty_raw or "").strip() or "0"
    low = s.lower()
    if any(
        tok in low
        for tok in (
            "евро",
            "eur",
            "€",
            "не менее",
            "не меньше",
            "кг",
            "/кг",
            "руб",
            "плюс",
            "+",
        )
    ) or len(s) > 24:
        return s
    av = float(_parse_duty_rate(s).get("ad_valorem") or 0.0)
    return _fmt_percent(av)


def _pick_rate_for_code(
    code10: str,
    by_hs_code: dict[str, str],
    by_hs_prefix: dict[str, str],
) -> tuple[str, str]:
    if code10 in by_hs_code:
        return by_hs_code[code10], "exact_10"
    if code10 in by_hs_prefix:
        return by_hs_prefix[code10], "prefix_10"
    for ln in (8, 6, 4, 2):
        pref = code10[:ln]
        if pref in by_hs_code:
            return by_hs_code[pref], f"exact_{ln}"
        if pref in by_hs_prefix:
            return by_hs_prefix[pref], f"prefix_{ln}"
    return "0", "fallback_zero"


def _clean_desc(raw: str | None) -> str:
    return (raw or "").strip()


def _build_desc_fallbacks(rows: list[Commodity]) -> tuple[dict[str, str], dict[str, str]]:
    by6: dict[str, str] = {}
    by4: dict[str, str] = {}
    for item in rows:
        code = (item.code or "").strip()
        if len(code) != 10:
            continue
        desc = _clean_desc(item.description)
        if not desc:
            continue
        p6 = code[:6]
        p4 = code[:4]
        if p6 not in by6:
            by6[p6] = desc
        if p4 not in by4:
            by4[p4] = desc
    return by6, by4


def main() -> int:
    print("repair_tnved_catalog_data: старт")
    print(f"  dialect={engine.dialect.name}")
    with SessionLocal() as db:
        rates = db.query(HsRate).order_by(HsRate.id.desc()).all()
        by_hs_code: dict[str, str] = {}
        by_hs_prefix: dict[str, str] = {}
        for r in rates:
            hs_code = (r.hs_code or "").strip()
            hs_prefix = (r.hs_prefix or "").strip()
            dr = str(r.duty_rate if r.duty_rate is not None else "0").strip() or "0"
            if hs_code and hs_code not in by_hs_code:
                by_hs_code[hs_code] = dr
            if hs_prefix and hs_prefix not in by_hs_prefix:
                by_hs_prefix[hs_prefix] = dr

        items = (
            db.query(Commodity)
            .filter(func.length(Commodity.code) == 10)
            .order_by(Commodity.code.asc())
            .all()
        )
        by6_desc, by4_desc = _build_desc_fallbacks(items)

        duty_updated = 0
        desc_updated = 0
        source_stats: dict[str, int] = {}

        for item in items:
            code = (item.code or "").strip()
            raw_duty, source = _pick_rate_for_code(code, by_hs_code, by_hs_prefix)
            target_duty = _catalog_import_duty_text(raw_duty)
            if (item.import_duty or "").strip() != target_duty:
                item.import_duty = target_duty
                duty_updated += 1
            source_stats[source] = source_stats.get(source, 0) + 1

            desc = _clean_desc(item.description)
            if not desc:
                fallback = by6_desc.get(code[:6]) or by4_desc.get(code[:4]) or f"Товарная позиция {code}"
                item.description = fallback
                desc_updated += 1

        db.commit()

    print(f"  rows_10digit={len(items)}")
    print(f"  duty_updated={duty_updated}")
    print(f"  descriptions_filled={desc_updated}")
    for key in sorted(source_stats.keys()):
        print(f"  duty_source_{key}={source_stats[key]}")
    print("repair_tnved_catalog_data: успешно")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
