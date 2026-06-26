#!/usr/bin/env python3
"""
Smoke-тест проверки ТРОИС/IP по бренду.

Проверяет 3 кейса:
1) точное совпадение (exact),
2) совпадение с опечаткой (fuzzy),
3) отсутствие риска.

Запуск (из customs-clear/backend):
  PYTHONPATH=. python3 scripts/test_trois_pipeline.py
"""

from __future__ import annotations

import pprint
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

load_dotenv(_ROOT / ".env")
load_dotenv()

from sqlalchemy import func  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models.tnved import IntellectualProperty, TroisRegistry  # noqa: E402
from app.services.trois_registry_sync import (  # noqa: E402
    normalize_trademark_for_registry,
    query_trois_matches_for_trademark,
)

EXACT_CANDIDATES: tuple[str, ...] = ("APPLE", "SAMSUNG", "XIAOMI", "HUAWEI", "NIKE", "ADIDAS")
ABSENT_BRAND = "SuperNonExistentBrand123"


def _fallback_holder_from_ip(db, norm_brand: str) -> str:
    if not norm_brand:
        return ""
    row = (
        db.query(IntellectualProperty)
        .filter(func.upper(func.trim(IntellectualProperty.brand_name)) == norm_brand)
        .first()
    )
    if not row:
        return ""
    return str(row.right_holder or "").strip()


def _check_brand(db, raw_brand: str) -> dict[str, Any]:
    norm = normalize_trademark_for_registry(raw_brand)
    hits = query_trois_matches_for_trademark(db, norm, max_results=5)

    if not hits:
        return {
            "input_brand": raw_brand,
            "normalized_brand": norm,
            "verdict": "ОТСУТСТВИЕ РИСКА",
            "risk_signal": "Бренд не найден в ТРОИС.",
            "hits": [],
        }

    out_hits: list[dict[str, Any]] = []
    top_score = 0.0
    for row in hits:
        score = float(getattr(row, "_trois_match_score", 1.0) or 0.0)
        top_score = max(top_score, score)
        holder = (row.right_holder or "").strip() or _fallback_holder_from_ip(db, norm) or "—"
        out_hits.append(
            {
                "brand": (getattr(row, "brand", "") or row.trademark or "").strip(),
                "trademark": (row.trademark or "").strip(),
                "reg_number": (row.reg_number or "").strip(),
                "right_holder": holder,
                "score": round(score, 4),
                "match_type": "exact" if score >= 0.999 else "fuzzy",
            }
        )

    first = out_hits[0]
    verdict = "ТОЧНОЕ СОВПАДЕНИЕ" if top_score >= 0.999 else "НЕЧЕТКОЕ СОВПАДЕНИЕ"
    risk_signal = (
        "[ТРОИС RISK] Бренд в ТРОИС! Требуется разрешение правообладателя: "
        f'{first["right_holder"]}. Бренд: "{first["brand"] or first["trademark"]}".'
    )
    if top_score < 0.999:
        risk_signal += f" Нечеткое совпадение: {top_score:.2f}, требуется ручная проверка."

    return {
        "input_brand": raw_brand,
        "normalized_brand": norm,
        "verdict": verdict,
        "risk_signal": risk_signal,
        "hits": out_hits,
    }


def _pick_exact_brand(db) -> str:
    for b in EXACT_CANDIDATES:
        nb = normalize_trademark_for_registry(b)
        exists = (
            db.query(TroisRegistry)
            .filter(
                (func.upper(func.trim(TroisRegistry.brand)) == nb)
                | (func.upper(func.trim(TroisRegistry.trademark)) == nb)
            )
            .first()
        )
        if exists:
            return b

    fallback = (
        db.query(TroisRegistry)
        .filter(func.length(func.trim(TroisRegistry.brand)) >= 5)
        .order_by(TroisRegistry.id.asc())
        .first()
    )
    if fallback and (fallback.brand or fallback.trademark):
        return str(fallback.brand or fallback.trademark).strip()
    return "APPLE"


def _build_typo_brand(base: str) -> str:
    b = (base or "").strip()
    if len(b) < 4:
        return b + "X"
    chars = list(b)
    i = len(chars) - 2
    chars[i], chars[i + 1] = chars[i + 1], chars[i]
    return "".join(chars)


def _print_rich(results: list[dict[str, Any]]) -> None:
    from rich.console import Console
    from rich.table import Table

    console = Console()
    console.rule("[bold cyan]TROIS PIPELINE TEST[/bold cyan]")

    summary = Table(show_header=True, header_style="bold magenta")
    summary.add_column("Кейс")
    summary.add_column("Ввод")
    summary.add_column("Нормализовано")
    summary.add_column("Вердикт")
    summary.add_column("Top score")
    for i, res in enumerate(results, start=1):
        top = f'{res["hits"][0]["score"]:.4f}' if res["hits"] else "—"
        summary.add_row(str(i), str(res["input_brand"]), str(res["normalized_brand"]), str(res["verdict"]), top)
    console.print(summary)

    for res in results:
        console.print(f'\n[bold]Кейс:[/bold] {res["input_brand"]}')
        console.print(f'[bold]Сигнал:[/bold] {res["risk_signal"]}')
        if not res["hits"]:
            continue
        hit_table = Table(show_header=True, header_style="bold green")
        hit_table.add_column("brand")
        hit_table.add_column("trademark")
        hit_table.add_column("reg_number")
        hit_table.add_column("right_holder")
        hit_table.add_column("score")
        hit_table.add_column("match_type")
        for hit in res["hits"]:
            hit_table.add_row(
                str(hit["brand"]),
                str(hit["trademark"]),
                str(hit["reg_number"]),
                str(hit["right_holder"]),
                f'{hit["score"]:.4f}',
                str(hit["match_type"]),
            )
        console.print(hit_table)


def main() -> int:
    with SessionLocal() as db:
        exact_brand = _pick_exact_brand(db)
        fuzzy_brand = _build_typo_brand(exact_brand)
        test_cases = [exact_brand, fuzzy_brand, ABSENT_BRAND]
        results = [_check_brand(db, brand) for brand in test_cases]

    try:
        _print_rich(results)
    except Exception:
        pprint.pprint(results, sort_dicts=False, width=140)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
