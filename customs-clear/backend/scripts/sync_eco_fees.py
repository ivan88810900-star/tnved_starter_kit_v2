#!/usr/bin/env python3
"""
Синхронизация тарифов экологического сбора (РОП) в ``eco_fee_rates``.

1. Базовый сид (ориентировочные коэффициенты для работы калькулятора; замените выгрузкой из официальных ПП РФ).
2. Опционально: JSON по URL ``ECO_FEE_JSON_URL`` или файл ``--import-json`` — массив объектов:
   ``{"hs_code_prefix":"","material_type":"товар","rate_rub_per_kg":2.2,"normative_percent":15,"valid_from_year":2027}``
3. Опционально: ``--html-file`` — извлечение годов ``20xx`` из текста (для привязки новых ставок к году документа).

Запуск из ``customs-clear/backend``::

  PYTHONPATH=. python3 scripts/sync_eco_fees.py
  PYTHONPATH=. python3 scripts/sync_eco_fees.py --import-json data/eco_fee_rates.json
  PYTHONPATH=. python3 scripts/sync_eco_fees.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from sqlalchemy.orm import Session

from app.db import SessionLocal  # noqa: E402
from app.models.core import EcoFeeRate  # noqa: E402

# Ориентир для разработки; для продакшена подставьте утверждённые ставки из нормативных актов.
DEFAULT_SEED: list[dict[str, Any]] = [
    {"hs_code_prefix": "", "material_type": "товар", "rate_rub_per_kg": 2.2, "normative_percent": 15.0, "valid_from_year": 2026},
    {"hs_code_prefix": "84", "material_type": "товар", "rate_rub_per_kg": 3.5, "normative_percent": 18.0, "valid_from_year": 2026},
    {"hs_code_prefix": "85", "material_type": "товар", "rate_rub_per_kg": 3.5, "normative_percent": 18.0, "valid_from_year": 2026},
    {"hs_code_prefix": "", "material_type": "бумага", "rate_rub_per_kg": 1.5, "normative_percent": 20.0, "valid_from_year": 2026},
    {"hs_code_prefix": "", "material_type": "картон", "rate_rub_per_kg": 1.5, "normative_percent": 20.0, "valid_from_year": 2026},
    {"hs_code_prefix": "", "material_type": "картон гофрированный", "rate_rub_per_kg": 1.4, "normative_percent": 20.0, "valid_from_year": 2026},
    {"hs_code_prefix": "", "material_type": "пластик", "rate_rub_per_kg": 4.5, "normative_percent": 25.0, "valid_from_year": 2026},
    {"hs_code_prefix": "", "material_type": "полимерная пленка", "rate_rub_per_kg": 4.5, "normative_percent": 25.0, "valid_from_year": 2026},
]


def _norm_prefix(p: str) -> str:
    return re.sub(r"\D", "", (p or "").strip())[:16]


def extract_years_from_text(text: str) -> set[int]:
    out: set[int] = set()
    for m in re.finditer(r"\b(20[2-9]\d)\b", text or ""):
        try:
            y = int(m.group(1))
            if 2020 <= y <= 2099:
                out.add(y)
        except ValueError:
            continue
    return out


def _rows_from_json(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, list):
        return []
    rows: list[dict[str, Any]] = []
    for it in data:
        if not isinstance(it, dict):
            continue
        try:
            rows.append(
                {
                    "hs_code_prefix": _norm_prefix(str(it.get("hs_code_prefix", ""))),
                    "material_type": str(it.get("material_type", "")).strip()[:64],
                    "rate_rub_per_kg": float(it.get("rate_rub_per_kg", 0)),
                    "normative_percent": float(it.get("normative_percent", 0)),
                    "valid_from_year": int(it.get("valid_from_year", 0)),
                }
            )
        except (TypeError, ValueError):
            continue
    return [r for r in rows if r["material_type"] and r["valid_from_year"] > 0]


def upsert_rows(session: Session, rows: list[dict[str, Any]], *, dry_run: bool) -> int:
    n = 0
    for r in rows:
        pfx = r["hs_code_prefix"]
        mat = r["material_type"]
        year = int(r["valid_from_year"])
        rate = float(r["rate_rub_per_kg"])
        norm = float(r["normative_percent"])
        if dry_run:
            n += 1
            continue
        ex = (
            session.query(EcoFeeRate)
            .filter(
                EcoFeeRate.hs_code_prefix == pfx,
                EcoFeeRate.material_type == mat,
                EcoFeeRate.valid_from_year == year,
            )
            .first()
        )
        if ex:
            ex.rate_rub_per_kg = rate
            ex.normative_percent = norm
        else:
            session.add(
                EcoFeeRate(
                    hs_code_prefix=pfx,
                    material_type=mat,
                    rate_rub_per_kg=rate,
                    normative_percent=norm,
                    valid_from_year=year,
                )
            )
        n += 1
    if not dry_run:
        session.commit()
    return n


def load_json_file(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return _rows_from_json(raw)


def load_json_url(url: str) -> list[dict[str, Any]]:
    import httpx

    r = httpx.get(url, timeout=60.0, follow_redirects=True)
    r.raise_for_status()
    return _rows_from_json(r.json())


def main() -> int:
    ap = argparse.ArgumentParser(description="Синхронизация eco_fee_rates (РОП / экосбор)")
    ap.add_argument("--dry-run", action="store_true", help="Только показать, сколько строк было бы записано")
    ap.add_argument("--import-json", type=Path, help="Файл JSON: массив тарифов")
    ap.add_argument("--html-file", type=Path, help="Файл HTML/текста: вывести найденные годы 20xx и выйти")
    ap.add_argument("--no-seed", action="store_true", help="Не подмешивать DEFAULT_SEED")
    args = ap.parse_args()

    if args.html_file:
        text = args.html_file.read_text(encoding="utf-8", errors="ignore")
        years = sorted(extract_years_from_text(text))
        print("Найденные годы в документе:", years or "(нет)")
        return 0

    rows: list[dict[str, Any]] = []
    if not args.no_seed:
        rows.extend(DEFAULT_SEED)
    if args.import_json:
        rows.extend(load_json_file(args.import_json))
    url = (os.environ.get("ECO_FEE_JSON_URL") or "").strip()
    if url:
        try:
            rows.extend(load_json_url(url))
        except Exception as e:
            print(f"Предупреждение: не удалось загрузить ECO_FEE_JSON_URL: {e}", file=sys.stderr)

    # дедуп по тройке (последняя запись побеждает)
    merged: dict[tuple[str, str, int], dict[str, Any]] = {}
    for r in rows:
        key = (r["hs_code_prefix"], r["material_type"], int(r["valid_from_year"]))
        merged[key] = r
    final_rows = list(merged.values())

    with SessionLocal() as s:
        n = upsert_rows(s, final_rows, dry_run=args.dry_run)
    print(f"Готово. Строк тарифа: {n} (dry_run={args.dry_run})", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
