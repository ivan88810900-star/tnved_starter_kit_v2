#!/usr/bin/env python3
"""
Дозагрузка отсутствующих в hs_rates кодов из последнего (или указанного) отчёта test_invoice_parsing.

  cd customs-clear/backend
  python3 scripts/sync_missing_codes.py              # последний processed_*.xlsx
  python3 scripts/sync_missing_codes.py --dry-run    # только список
  python3 scripts/sync_missing_codes.py --excel path/to.xlsx

Временная мера: для кодов без строки в hs_rates запрашивает у Gemini ориентировочные
duty_rate / vat_import_rate и делает upsert_hs_rate (source_revision=sync_missing_codes_gemini).

Нетарифные меры (non_tariff_measures) привязаны к tnved_commodities и не создаются этим скриптом —
для гр. 94 и др. используйте краулер (см. подсказку --print-tks94-command).
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv

load_dotenv(_ROOT / ".env")
load_dotenv()


def _latest_processed_excel() -> Path:
    d = _ROOT / "data" / "processed_invoices"
    if not d.is_dir():
        raise FileNotFoundError(f"Нет каталога {d}")
    files = sorted(d.glob("processed_*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        raise FileNotFoundError(f"В {d} нет processed_*.xlsx")
    return files[0].resolve()


def _codes_from_excel(path: Path) -> list[str]:
    import pandas as pd

    df = pd.read_excel(path)
    if "suggested_hs_code" not in df.columns:
        raise ValueError(f"В {path} нет колонки suggested_hs_code")
    first = df.columns[0]
    mask = df[first].astype(str).str.strip().str.upper() != "ИТОГО"
    df = df.loc[mask]
    raw = (
        df["suggested_hs_code"]
        .astype(str)
        .map(lambda x: re.sub(r"\D", "", x)[:10])
    )
    return sorted({c for c in raw if len(c) == 10})


def _missing_in_hs_rates(codes: list[str]) -> list[str]:
    from app.db import SessionLocal
    from app.models import HsRate

    missing: list[str] = []
    with SessionLocal() as db:
        for c in codes:
            row = db.query(HsRate).filter(HsRate.hs_code == c).first()
            if row is None:
                missing.append(c)
    return missing


def _gemini_rate_row(hs10: str) -> dict[str, object] | None:
    from app.services.invoice_analyzer import _extract_json_object, _gemini_generate

    prompt = (
        f"Десятизначный код ТН ВЭД ЕАЭС: {hs10}. Оцени для ввоза в ЕАЭС (ориентир, не юридическая консультация) "
        'ставки и верни один JSON-объект без markdown: '
        '{"duty_rate": <число, ввозная пошлина в процентах>, '
        '"vat_import_rate": <число, НДС при ввозе, часто 20 или 22>}. '
        "Только числа, без пояснительного текста вне JSON."
    )
    try:
        raw = _gemini_generate(prompt, max_output_tokens=256, temperature=0.05)
    except Exception as e:
        print(f"  Gemini ошибка для {hs10}: {e}", file=sys.stderr)
        return None
    data = _extract_json_object(raw)
    if not data:
        return None
    try:
        vr = float(data.get("vat_import_rate"))
    except (TypeError, ValueError):
        return None
    from app.services.normative_store import normalize_hs_duty_rate_string

    dr = normalize_hs_duty_rate_string(data.get("duty_rate"))
    return {
        "hs_code": hs10,
        "hs_prefix": hs10[:4],
        "duty_rate": dr,
        "vat_import_rate": vr,
        "source_url": "gemini-estimate:sync_missing_codes.py",
        "source_revision": "sync_missing_codes_gemini",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Дозагрузка кодов ТН ВЭД в hs_rates из отчёта инвойса")
    parser.add_argument("--excel", type=Path, default=None, help="Путь к processed_*.xlsx (по умолчанию — самый новый)")
    parser.add_argument("--dry-run", action="store_true", help="Только показать отсутствующие коды")
    parser.add_argument(
        "--print-tks94-command",
        action="store_true",
        help="Вывести рекомендуемую команду краулера для дерева ТКС гр. 94 и выйти",
    )
    args = parser.parse_args()

    if args.print_tks94_command:
        print(
            "Рекомендуемый запуск краулера (глубина и лимит страниц повышены; нужен GEMINI_API_KEY, "
            "для tks.ru желателен --use-playwright):\n\n"
            "  cd customs-clear/backend && \\\n"
            "  python3 scripts/historical_crawler.py \\\n"
            "    --seeds https://www.tks.ru/db/tnved/tree/94 \\\n"
            "    --allowed-hosts www.tks.ru tks.ru \\\n"
            "    --depth 6 \\\n"
            "    --max-pages 200 \\\n"
            "    --max-documents 400 \\\n"
            "    --use-playwright\n",
            flush=True,
        )
        return

    path = args.excel.resolve() if args.excel else _latest_processed_excel()
    if not path.is_file():
        print(f"Файл не найден: {path}", file=sys.stderr)
        raise SystemExit(1)

    codes = _codes_from_excel(path)
    missing = _missing_in_hs_rates(codes)
    print(f"Файл: {path.name}", flush=True)
    print(f"Уникальных 10-значных кодов в отчёте: {len(codes)}", flush=True)
    print(f"Отсутствуют в hs_rates (точное совпадение hs_code): {len(missing)}", flush=True)
    if not missing:
        return
    for c in missing:
        print(f"  - {c}", flush=True)

    if args.dry_run:
        print("\n--dry-run: запись в БД пропущена.", flush=True)
        return

    from app.services.normative_store import init_db, upsert_hs_rate

    init_db()
    ok = 0
    for i, hs10 in enumerate(missing):
        row = _gemini_rate_row(hs10)
        if row:
            upsert_hs_rate(row)
            ok += 1
            print(f"OK upsert {hs10} duty={row['duty_rate']}% VAT={row['vat_import_rate']}%", flush=True)
        if i + 1 < len(missing):
            time.sleep(1.2)
    print(f"\nГотово: записано {ok} из {len(missing)}.", flush=True)


if __name__ == "__main__":
    main()
