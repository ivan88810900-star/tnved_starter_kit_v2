#!/usr/bin/env python3
"""
Синхронизация кодов из последнего отчёта инвойса с БД customs.db.

  cd customs-clear/backend
  python3 scripts/sync_invoice_codes.py --dry-run
  python3 scripts/sync_invoice_codes.py

Шаги:
  1) Читает последний processed_*.xlsx в data/processed_invoices/, колонка suggested_hs_code.
  2) Находит 10-значные коды, которых нет в hs_rates (точное совпадение hs_code).
  3) Для каждого: запрос к Gemini (структурированный JSON) — пошлина %, НДС %, нетарифка
     в духе раздела «Особенности оформления» (ТР ТС, документы).
  4) upsert_hs_rate; при наличии главы в tnved_chapters — создаёт tnved_commodities (заглушка)
     и строки non_tariff_measures.

Прямой вызов historical_crawler.py на каждый код не выполняется (слишком тяжело); для массового
обхода ТКС используйте отдельный запуск scripts/historical_crawler.py с нужными --seeds.
HTTP к страницам tks.ru здесь не используется (часто 404/антибот); источник оценки — Gemini.
"""

from __future__ import annotations

import argparse
import os
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
    raw = df["suggested_hs_code"].astype(str).map(lambda x: re.sub(r"\D", "", x)[:10])
    return sorted({c for c in raw if len(c) == 10})


def _missing_hs_rate_codes(codes: list[str]) -> list[str]:
    from app.db import SessionLocal
    from app.models import HsRate

    out: list[str] = []
    with SessionLocal() as db:
        for c in codes:
            if db.query(HsRate).filter(HsRate.hs_code == c).first() is None:
                out.append(c)
    return out


def _resolve_chapter_id(db, hs10: str) -> int | None:
    from sqlalchemy import text

    row = db.execute(
        text("SELECT id FROM tnved_chapters WHERE :h LIKE code || '%' ORDER BY length(code) DESC LIMIT 1"),
        {"h": hs10},
    ).fetchone()
    if row:
        return int(row[0])
    row = db.execute(
        text("SELECT id FROM tnved_chapters WHERE code = :c LIMIT 1"),
        {"c": hs10[:2]},
    ).fetchone()
    return int(row[0]) if row else None


def _ensure_commodity(db, hs10: str, description: str) -> bool:
    from app.models.tnved import Commodity

    if db.query(Commodity).filter(Commodity.code == hs10).first():
        return True
    ch_id = _resolve_chapter_id(db, hs10)
    if ch_id is None:
        return False
    db.add(
        Commodity(
            chapter_id=ch_id,
            code=hs10,
            description=(description or f"Автозапись sync_invoice_codes для {hs10}")[:4000],
            unit="",
            import_duty="",
        )
    )
    db.commit()
    return True


def _gemini_payload(hs10: str) -> dict | None:
    from app.services.invoice_analyzer import GEMINI_PROJECT_VAT_RULES, _extract_json_object, _gemini_generate
    from app.services.vat_preferential_reference import match_preferential_vat_group

    pref = match_preferential_vat_group(hs10)
    vat_expert_block = ""
    if pref is not None:
        act = pref.get("act", "")
        cat = pref.get("category", "")
        vat_expert_block = (
            f"\n\nКод попадает в льготную группу по {act} ({cat}). Обязательно заполни поля vat_rate_final и vat_logic.\n"
            f"ЭКСПЕРТИЗА НДС: Этот код ({hs10}) может претендовать на ставку 10%. Проанализируй только по текстовому описанию товарной группы этого кода ТН ВЭД "
            "(фото нет):\n\n"
            "Является ли товар изделием именно для детей? (маркировка, дизайн, размер).\n\n"
            "Соответствует ли он техническим критериям (например, для мебели — ростовые группы, для одежды — рост/обхват).\n\n"
            "Если это мед. изделие — есть ли признаки профессионального использования?\n\n"
            "Верни JSON поле vat_rate_final (10 или 22) и vat_logic (краткое пояснение, почему выбрана эта ставка со ссылкой на критерии закона).\n"
        )

    prompt = (
        GEMINI_PROJECT_VAT_RULES
        + f"Код ТН ВЭД ЕАЭС (10 знаков): {hs10}. Подготовь данные для таможенной БД (ориентир, не юридическая консультация).\n"
        f"{vat_expert_block}"
        "Верни один JSON-объект без markdown:\n"
        "{\n"
        '  "duty_percent": <число, ввозная пошлина %>,\n'
        '  "vat_import_percent": <число, НДС при ввозе; базовый ориентир проекта 22%; если заполняешь vat_rate_final — согласуй с ним>,\n'
        '  "vat_rate_final": <10 или 22 только если выше дана экспертиза НДС; иначе опусти или null>,\n'
        '  "vat_logic": "<краткое пояснение по НДС при наличии экспертизы; иначе пустая строка>",\n'
        '  "processing_summary": "<кратко, как в блоке «Особенности оформления»: ТР ТС, сертификаты, вет/фито и т.п.>",\n'
        '  "non_tariff_items": [\n'
        "    {\n"
        '      "measure_type": "certificate|license|vet_control|phyto_control|ban|other",\n'
        '      "description": "<суть меры>",\n'
        '      "document_required": "<документы>",\n'
        '      "regulatory_act": "<ТР ТС / акт, до 240 символов>"\n'
        "    }\n"
        "  ]\n"
        "}\n"
        "non_tariff_items: 1–6 записей, типичные ТР ТС для товарной группы этого кода; если только общие ТР ТС — укажи их."
    )
    try:
        raw = _gemini_generate(prompt, max_output_tokens=1024, temperature=0.08)
    except Exception as e:
        print(f"  Gemini ошибка {hs10}: {e}", file=sys.stderr)
        return None
    data = _extract_json_object(raw)
    return data if isinstance(data, dict) else None


def _apply_payload(hs10: str, data: dict) -> None:
    from app.db import SessionLocal
    from app.models.tnved import NonTariffMeasure
    from app.services.invoice_analyzer import _parse_vat_rate_final_value
    from app.services.normative_store import normalize_hs_duty_rate_string, upsert_hs_rate
    from app.services.vat_preferential_reference import match_preferential_vat_group

    duty_raw = data.get("duty_percent") if data.get("duty_percent") is not None else data.get("duty_rate")
    duty = normalize_hs_duty_rate_string(duty_raw if duty_raw is not None else "0")
    vat = float(data.get("vat_import_percent") or data.get("vat_import_rate") or 22)
    summary = str(data.get("processing_summary") or "").strip()

    pref = match_preferential_vat_group(hs10)
    vat_logic = str(data.get("vat_logic") or "").strip()
    vf = _parse_vat_rate_final_value(data.get("vat_rate_final")) if pref is not None else None
    if vf is not None:
        vat = float(vf)

    row_hs: dict = {
        "hs_code": hs10,
        "hs_prefix": hs10[:4],
        "duty_rate": duty,
        "vat_import_rate": vat,
        "source_url": "gemini:sync_invoice_codes.py",
        "source_revision": "sync_invoice_codes_v1",
    }
    if vf is not None:
        row_hs["vat_rule"] = "reduced10" if vf == 10.0 else "none"
        row_hs["vat_rule_basis"] = (
            vat_logic or f"Экспертиза НДС ({pref.get('act', '')}: {pref.get('category', '')})"
        )[:8000]

    upsert_hs_rate(row_hs)

    items = data.get("non_tariff_items") or data.get("non_tariff") or []
    if not isinstance(items, list) or not items:
        if summary:
            items = [
                {
                    "measure_type": "other",
                    "description": summary[:2000],
                    "document_required": "",
                    "regulatory_act": "Сводно: особенности оформления (Gemini)",
                }
            ]
        else:
            return

    with SessionLocal() as db:
        if not _ensure_commodity(db, hs10, summary):
            print(f"  Предупреждение: нет tnved_chapters для {hs10}, non_tariff пропущены", file=sys.stderr)
            return

        allowed_mt = frozenset({"certificate", "license", "vet_control", "phyto_control", "ban", "other"})
        for raw in items:
            if not isinstance(raw, dict):
                continue
            mt = str(raw.get("measure_type") or "other").strip().lower()
            if mt not in allowed_mt:
                mt = "other"
            desc = str(raw.get("description") or summary or "—")[:5000]
            doc = str(raw.get("document_required") or "")[:255]
            act = str(raw.get("regulatory_act") or "ТР ТС / нормативка (оценка)")[:255]

            dup = (
                db.query(NonTariffMeasure)
                .filter(
                    NonTariffMeasure.commodity_code == hs10,
                    NonTariffMeasure.measure_type == mt,
                    NonTariffMeasure.regulatory_act == act,
                )
                .first()
            )
            if dup:
                continue
            db.add(
                NonTariffMeasure(
                    commodity_code=hs10,
                    measure_type=mt,
                    description=desc,
                    document_required=doc,
                    regulatory_act=act,
                )
            )
        db.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Синхронизация кодов из отчёта инвойса → hs_rates + non_tariff_measures")
    parser.add_argument("--excel", type=Path, default=None, help="processed_*.xlsx (по умолчанию — самый новый)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    path = args.excel.resolve() if args.excel else _latest_processed_excel()
    if not path.is_file():
        print(f"Файл не найден: {path}", file=sys.stderr)
        raise SystemExit(1)

    codes = _codes_from_excel(path)
    missing = _missing_hs_rate_codes(codes)
    print(f"Файл: {path.name}", flush=True)
    print(f"Уникальных 10-значных кодов: {len(codes)}", flush=True)
    print(f"Нет в hs_rates (hs_code): {len(missing)}", flush=True)
    for c in missing:
        print(f"  - {c}", flush=True)

    if not missing:
        return

    if not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")):
        print("Задайте GEMINI_API_KEY или GOOGLE_API_KEY.", file=sys.stderr)
        raise SystemExit(2)

    if args.dry_run:
        print("\n--dry-run: запись в БД не выполнялась.", flush=True)
        return

    from app.services.normative_store import init_db

    init_db()
    ok = 0
    for i, hs10 in enumerate(missing):
        data = _gemini_payload(hs10)
        if not data:
            continue
        try:
            _apply_payload(hs10, data)
            ok += 1
            dr = data.get("duty_percent", data.get("duty_rate"))
            vr = data.get("vat_import_percent", data.get("vat_import_rate"))
            print(f"OK {hs10} duty={dr}% VAT={vr}%", flush=True)
        except Exception as e:
            print(f"  DB ошибка {hs10}: {e}", file=sys.stderr)
        if i + 1 < len(missing):
            time.sleep(1.2)
    print(f"\nГотово: обработано {ok} из {len(missing)}.", flush=True)


if __name__ == "__main__":
    main()
