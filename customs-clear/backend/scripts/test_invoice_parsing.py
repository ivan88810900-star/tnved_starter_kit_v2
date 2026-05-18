#!/usr/bin/env python3
"""Спецификация из data/raw_invoices → invoice_analyzer → отчёт Excel в data/processed_invoices/.

Маппинг колонок: ``map_columns`` в ``app.services.invoice_analyzer`` поднимает шапку из пустых верхних
строк Excel (``_promote_actual_headers``), добавляет колонки ``[RAW] …`` с копиями исходных полей для
отчёта декларанту, затем вызывает семантический ``_ai_map_columns`` (Gemini JSON), при сбое —
эвристический fallback. В ``write_invoice_report_excel`` колонки ``[RAW]`` выводятся первыми.

Инкрементальный чекпоинт (массовая обработка):
  data/processed_invoices/temp_checkpoint.csv
  data/processed_invoices/temp_checkpoint.meta.json

Сохранение каждые N строк (--checkpoint-every, по умолчанию 5) и в конце полного прогона.
Итоговый .xlsx собирается из накопленных строк в памяти (после возобновления — из чекпоинта + новые строки).
При успешном завершении временные файлы чекпоинта удаляются.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

warnings.filterwarnings("ignore", category=FutureWarning)

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv

load_dotenv(_ROOT / ".env")
load_dotenv()


def _ai_map_columns(df):
    """Семантический маппинг заголовков через Gemini; реализация в ``app.services.invoice_analyzer``."""
    from app.services.invoice_analyzer import _ai_map_columns as _impl

    return _impl(df)


def _silence_noisy_http_loggers() -> None:
    """Отключает DEBUG от httpx/urllib3/httpcore в консоли."""
    for name in (
        "urllib3",
        "urllib3.connectionpool",
        "httpx",
        "httpcore",
        "httpcore.connection",
        "httpcore.http11",
        "h11",
    ):
        logging.getLogger(name).setLevel(logging.WARNING)


def _processed_checkpoint_paths(root: Path) -> tuple[Path, Path]:
    d = root / "data" / "processed_invoices"
    d.mkdir(parents=True, exist_ok=True)
    return d / "temp_checkpoint.csv", d / "temp_checkpoint.meta.json"


def _configure_console(*, verbose: bool, print_console: bool) -> None:
    if print_console:
        os.environ.setdefault("LOGURU_LEVEL", "WARNING")
        _silence_noisy_http_loggers()
    elif not verbose:
        os.environ.setdefault("LOGURU_LEVEL", "WARNING")
    else:
        os.environ.setdefault("LOGURU_LEVEL", "INFO")


def _prompt_resume_interactive() -> bool:
    try:
        print(
            "Найден temp_checkpoint (processed_invoices). Продолжить с места обрыва? [Y/n]: ",
            file=sys.stderr,
            end="",
            flush=True,
        )
        line = input().strip().lower()
    except EOFError:
        return True
    return line in ("", "y", "yes", "д", "да")


def main() -> None:
    import re

    import pandas as pd
    from tqdm import tqdm

    from app.db import SessionLocal
    from app.services.currency_sync import CurrencyService
    from app.services.eco_calculator import EcoFeeCalculator
    from app.services.invoice_analyzer import (
        DEFAULT_VAT_RATE,
        InvoiceAnalyzer,
        analyze_item_risks,
        cleanup_temp_invoice_images,
        enrich_with_customs_data,
        apply_smart_net_weight_to_line_item,
        format_duty,
        format_non_tariff,
        format_warning_cell,
        format_electronics_excel_cells,
        invoice_checkpoint_matches_source,
        iter_item_rows,
        load_invoice_checkpoint_meta,
        load_invoice_checkpoint_rows,
        load_specification_table,
        map_columns,
        save_invoice_checkpoint,
        write_invoice_report_excel,
        _parse_number,
    )
    from app.services.state_registry_match import format_registry_check_excel

    parser = argparse.ArgumentParser(description="Разбор инвойса и отчёт Excel")
    parser.add_argument(
        "--input",
        "--invoice",
        type=Path,
        dest="input",
        default=None,
        help="Путь к CSV/XLSX (по умолчанию — первый *.xlsx в data/raw_invoices/)",
    )
    parser.add_argument(
        "--max-rows",
        type=int,
        default=5,
        metavar="N",
        help="Сколько строк обработать; 0 = все строки файла",
    )
    parser.add_argument(
        "--checkpoint-every",
        type=int,
        default=5,
        metavar="N",
        help="Сохранять чекпоинт в data/processed_invoices/temp_checkpoint.* каждые N строк (минимум 1)",
    )
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Не спрашивать про чекпоинт: сразу продолжить, если он подходит",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Игнорировать чекпоинт и начать заново (удалить temp_checkpoint.csv / .meta.json)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Подробный вывод по строкам (tqdm.write)",
    )
    parser.add_argument(
        "--print-console",
        action="store_true",
        help="Только tqdm + итоговая таблица (наименование, код, НДС); без лишних DEBUG от HTTP",
    )
    parser.add_argument(
        "--fast-mode",
        action="store_true",
        help=(
            "Ускоренный прогон: отключает web-search в классификаторе, пропускает AI risk-notes и "
            "включает мягкие fallback-метки в отчёте."
        ),
    )
    _INCOTERMS_CHOICES = (
        "EXW",
        "FCA",
        "FOB",
        "FAS",
        "CFR",
        "CIF",
        "CPT",
        "CIP",
        "DAP",
        "DPU",
        "DDP",
    )
    parser.add_argument(
        "--freight-usd",
        type=float,
        default=0.0,
        help="Фрахт в USD (распределяется по строкам; курс USD→RUB — ЦБ РФ)",
    )
    parser.add_argument(
        "--incoterms",
        type=str,
        default="EXW",
        choices=_INCOTERMS_CHOICES,
        help="Базис поставки: от этого зависит, входит ли фрахт в таможенную стоимость строки",
    )
    args = parser.parse_args()

    if args.checkpoint_every < 1:
        print("--checkpoint-every должен быть >= 1", file=sys.stderr)
        sys.exit(2)

    verbose = bool(args.verbose)
    print_console = bool(args.print_console)
    _configure_console(verbose=verbose, print_console=print_console)

    ck_csv, ck_meta = _processed_checkpoint_paths(_ROOT)

    if args.input and args.input.is_file():
        path = args.input.resolve()
    else:
        from glob import glob

        pattern = str(_ROOT / "data" / "raw_invoices" / "*.xlsx")
        paths = sorted(glob(pattern))
        if not paths:
            print("Нет файлов *.xlsx в data/raw_invoices/ и не задан --input", file=sys.stderr)
            sys.exit(1)
        path = Path(paths[0])

    if args.fresh:
        for p in (ck_csv, ck_meta):
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass

    rows_out: list[dict[str, Any]] = []
    total = 0
    limit = 0
    meta_run: dict[str, Any] = {}
    pbar: Any = None

    try:
        df, images_by_excel_row = load_specification_table(path)
        # map_columns: колонка Image_Path → image_path в строках (iter_item_rows → suggest_hs_code_for_item).
        mapped = map_columns(df)
        usd_rate = CurrencyService.get_usd_rate()
        rag_db = SessionLocal()
        try:
            inv_an = InvoiceAnalyzer(
                freight_usd=float(args.freight_usd),
                incoterms=str(args.incoterms),
                db_session=rag_db,
            )
            eco_calc = EcoFeeCalculator(rag_db)
            mapped = inv_an.apply_financial_columns(mapped, usd_rate)
            if mapped.empty:
                print("Пустая таблица после чтения.", file=sys.stderr)
                sys.exit(1)

            total = len(mapped)
            limit = total if args.max_rows == 0 else min(args.max_rows, total)
    
            meta_run = {
                "source_path": str(path.resolve()),
                "max_rows": int(args.max_rows),
                "planned_total": int(limit),
            }
    
            start_i = 0
            if ck_csv.is_file() and ck_csv.stat().st_size > 0 and not args.fresh:
                meta = load_invoice_checkpoint_meta(ck_meta)
                if meta and invoice_checkpoint_matches_source(
                    meta, source=path, max_rows=int(args.max_rows), planned_total=limit
                ):
                    resume = False
                    if args.yes:
                        resume = True
                    elif not sys.stdin.isatty():
                        resume = True
                    else:
                        resume = _prompt_resume_interactive()
                    if resume:
                        rows_out = load_invoice_checkpoint_rows(ck_csv)
                        start_i = len(rows_out)
                        if start_i > limit:
                            rows_out = rows_out[:limit]
                            start_i = limit
    
            if start_i < limit:
                pbar = tqdm(
                    total=limit,
                    initial=start_i,
                    desc="Разбор инвойса",
                    unit="стр",
                    file=sys.stderr,
                    dynamic_ncols=True,
                    disable=not sys.stderr.isatty(),
                )
    
            for i, item in enumerate(iter_item_rows(mapped, images_by_excel_row=images_by_excel_row)):
                if i >= limit:
                    break
                if i < start_i:
                    continue
    
                name_ru = (item.get("name_ru") or "").strip()
                material = (item.get("material") or "").strip()
                usage = (item.get("usage") or "").strip()
                total_cost = (item.get("total_cost_estimate") or "").strip()
                quantity = (item.get("quantity") or "").strip()
                unit_price = (item.get("unit_price") or "").strip()
    
                hs_payload = inv_an.suggest_hs_code_for_item(item, fast_mode=bool(args.fast_mode))
                hs = (hs_payload.get("hs_code") or "").strip()
                fallback_status = str(hs_payload.get("fallback_status") or "").strip()
                if not hs and not fallback_status:
                    fallback_status = "hs_not_determined"
                ec_cells = format_electronics_excel_cells(
                    hs_code=hs,
                    electronics_compliance=hs_payload.get("electronics_compliance"),
                )
                registry_cells = format_registry_check_excel(hs_payload.get("registry_check"))
                net_auto_note = apply_smart_net_weight_to_line_item(item, hs, df=mapped, row_index=i)
                vision_insights = (hs_payload.get("Vision_Insights") or "").strip()
                if net_auto_note:
                    vision_insights = f"{vision_insights} {net_auto_note}".strip() if vision_insights else net_auto_note
                weight_net = (item.get("weight_net") or "").strip()
                classification_precedent = (hs_payload.get("classification_precedent") or "").strip()
                justification = (hs_payload.get("justification") or "").strip()
                desc31 = (
                    (hs_payload.get("Description_31") or hs_payload.get("suggested_description_31") or "")
                    .strip()
                )
                box31_ready = (hs_payload.get("box_31_description") or "").strip()
                conf_hs = hs_payload.get("confidence_score")
                opi_steps_raw = hs_payload.get("opi_reasoning_steps")
                if not isinstance(opi_steps_raw, list):
                    opi_steps_raw = hs_payload.get("reasoning_steps")
                if isinstance(opi_steps_raw, list):
                    opi_steps = "\n".join(str(x).strip() for x in opi_steps_raw if str(x).strip())
                else:
                    opi_steps = ""
                mi_raw = hs_payload.get("missing_info")
                if isinstance(mi_raw, list):
                    supplier_ask = ", ".join(str(x).strip() for x in mi_raw if str(x).strip())
                elif isinstance(mi_raw, str) and mi_raw.strip():
                    supplier_ask = mi_raw.strip()
                else:
                    supplier_ask = ""
                supplier_question_en = str(hs_payload.get("supplier_question_en") or "").strip()
                try:
                    conf_pct_cell = int(round(float(conf_hs))) if conf_hs is not None else ""
                except (TypeError, ValueError):
                    conf_pct_cell = ""
                compliance_raw = hs_payload.get("compliance_warnings") or []
                vat_logic_cell = (hs_payload.get("vat_logic") or "").strip()
                pref_g = hs_payload.get("preferential_vat_group")
                vat_override: float | None = None
                if pref_g is not None:
                    vf = hs_payload.get("vat_rate_final")
                    try:
                        if vf is not None and float(vf) in (10.0, float(DEFAULT_VAT_RATE)):
                            vat_override = float(vf)
                    except (TypeError, ValueError):
                        pass
    
                enr = (
                    enrich_with_customs_data(hs, item, vat_import_override=vat_override)
                    if hs
                    else enrich_with_customs_data("", item)
                )
                if args.fast_mode:
                    risks = "FAST-MODE: AI-анализ рисков пропущен (включить без --fast-mode для полного отчёта)."
                else:
                    risks = analyze_item_risks(item, hs) if hs else analyze_item_risks(item, "")
    
                duty = enr.get("duty_rate")
                vat = enr.get("vat_import_rate")
                nt_text = format_non_tariff(enr, max_items=None) if enr else "—"
    
                compliance_cell = format_warning_cell(compliance_raw) if compliance_raw else ""
                risks_cell = format_warning_cell(risks) if risks else ""
    
                cvn = _parse_number(item.get("customs_value"))
                qn = _parse_number(item.get("quantity"))
                addon_n = _parse_number(item.get("landed_cost_freight_addon"))
                if addon_n is None:
                    addon_n = 0.0
                bd_amt = enr.get("base_duty_amount")
                va_amt = enr.get("vat_amount")
                unit_landed = ""
                if (
                    cvn is not None
                    and qn is not None
                    and qn > 0
                    and isinstance(bd_amt, (int, float))
                    and isinstance(va_amt, (int, float))
                ):
                    unit_landed = round((float(cvn) + float(bd_amt) + float(va_amt) + float(addon_n)) / float(qn), 4)

                wn_f = _parse_number(item.get("weight_net"))
                if wn_f is None:
                    wn_f = _parse_number(item.get("Weight_Net_kg"))
                wg_f = _parse_number(item.get("weight_gross"))
                if wg_f is None:
                    wg_f = _parse_number(item.get("Weight_Gross_kg"))
                hs_digits = re.sub(r"\D", "", hs or "")[:10]
                eco_w_pack = ""
                eco_rate_txt = ""
                eco_sum = ""
                if len(hs_digits) == 10 and wn_f is not None and wg_f is not None:
                    desc_blob = " ".join(
                        x for x in (name_ru, (item.get("name_cn") or ""), material, usage) if (x or "").strip()
                    ).strip()
                    exp_pack = (item.get("packaging_material") or item.get("packaging") or "").strip() or None
                    eco_out = eco_calc.calculate_fee(
                        hs_digits,
                        float(wn_f),
                        float(wg_f),
                        packaging_material=exp_pack,
                        product_description=desc_blob or None,
                    )
                    pw = eco_out.get("packaging_weight_kg")
                    if pw is not None and isinstance(pw, (int, float)):
                        eco_w_pack = f"{float(pw):g}"
                    pr = eco_out.get("product") or {}
                    pk = eco_out.get("packaging") or {}
                    bits: list[str] = []
                    if isinstance(pr.get("rate"), dict):
                        r = pr["rate"]
                        bits.append(
                            f"Товар: {r.get('rate_rub_per_kg')} руб/кг × {r.get('normative_percent')}% "
                            f"(ТН преф. «{r.get('hs_code_prefix') or '—'}», {r.get('valid_from_year')} г.)"
                        )
                    if isinstance(pk.get("rate"), dict):
                        r = pk["rate"]
                        bits.append(
                            f"Упак.({eco_out.get('packaging_material')}): {r.get('rate_rub_per_kg')} руб/кг × "
                            f"{r.get('normative_percent')}% ({r.get('valid_from_year')} г.)"
                        )
                    for w in eco_out.get("warnings") or []:
                        if w:
                            bits.append(w)
                    eco_rate_txt = " ".join(bits).strip()
                    tr = eco_out.get("total_eco_fee_rub")
                    if isinstance(tr, (int, float)):
                        eco_sum = f"{float(tr):.2f}"
    
                rows_out.append(
                    {
                        "name_ru": name_ru,
                        "Нормализованное наименование": (hs_payload.get("normalized_product_name") or "").strip(),
                        "Фото": (hs_payload.get("photo_for_analysis") or "Нет").strip(),
                        **ec_cells,
                        **registry_cells,
                        "material": material,
                        "usage": usage,
                        "weight_net": weight_net,
                        "quantity": quantity,
                        "unit_price": unit_price,
                        "total_cost_estimate": total_cost,
                        "item_price_rub": item.get("item_price_rub") or "",
                        "allocated_freight_rub": item.get("allocated_freight_rub") or "",
                        "customs_value": item.get("customs_value") or "",
                        "landed_cost_freight_addon": item.get("landed_cost_freight_addon") or "",
                        "incoterms": item.get("incoterms") or str(args.incoterms),
                        "unit_landed_cost": unit_landed,
                        "suggested_hs_code": hs,
                        "classification_precedent": classification_precedent,
                        "ОПИ шаги (LLM)": opi_steps,
                        "justification": justification,
                        "ГРАФА_31": desc31,
                        "Description_31": desc31,
                        "Графа 31 (Готовое описание)": box31_ready,
                        "Vision_Insights": vision_insights,
                        "Calculation_Notes": net_auto_note,
                        "confidence_score": conf_hs if conf_hs is not None else "",
                        "Уверенность ИИ (%)": conf_pct_cell,
                        "Вопрос поставщику (EN)": supplier_question_en,
                        "Запросить у поставщика": supplier_ask,
                        "compliance_warnings": compliance_cell,
                        "Trois_Control": (hs_payload.get("Trois_Control") or "").strip(),
                        "Fallback_Status": fallback_status,
                        "Run_Mode": "FAST" if args.fast_mode else "FULL",
                        "Country_Risk_Status": enr.get("Country_Risk_Status") or "",
                        "Applied_Special_Duty": enr.get("Applied_Special_Duty") or "",
                        "Required_Certificates": enr.get("Required_Certificates") or "",
                        "Sanction_Status": enr.get("Sanction_Status") or "",
                        "sanction_risk": (enr.get("sanction_risk") or "").strip(),
                        "geopolitical_duty_note": (enr.get("geopolitical_duty_note") or "").strip(),
                        "duty_rate": duty if duty is not None else "",
                        "vat_rate": vat if vat is not None else "",
                        "ОБОСНОВАНИЕ_НДС": vat_logic_cell,
                        "customs_value_base": enr.get("customs_value_base")
                        if enr.get("customs_value_base") is not None
                        else "",
                        "base_duty_amount": enr.get("base_duty_amount")
                        if enr.get("base_duty_amount") is not None
                        else "",
                        "vat_amount": enr.get("vat_amount") if enr.get("vat_amount") is not None else "",
                        "total_tax_pay": enr.get("total_tax_pay") if enr.get("total_tax_pay") is not None else "",
                        "non_tariff_measures": nt_text,
                        "ai_risk_notes": risks_cell,
                        "Вес упаковки (кг)": eco_w_pack,
                        "Ставка экосбора": eco_rate_txt,
                        "Сумма экосбора (руб)": eco_sum,
                    }
                )
    
                if verbose and not print_console:
                    name = name_ru or (item.get("name_cn") or "").strip() or "(без названия)"
                    tqdm.write(f"— {i + 1}. {name[:80]}")
                    tqdm.write(f"    Код: {hs or '—'} | пошлина: {format_duty(enr)} | нетарифка: {format_non_tariff(enr)}")
                    if justification:
                        tqdm.write(
                            f"    Обоснование: {justification[:200]}…"
                            if len(justification) > 200
                            else f"    Обоснование: {justification}"
                        )
                    if desc31:
                        tqdm.write(f"    ГРАФА_31: {desc31[:160]}…" if len(desc31) > 160 else f"    ГРАФА_31: {desc31}")
                    if compliance_cell:
                        tqdm.write(
                            f"    Предупреждения: {compliance_cell[:200]}…"
                            if len(compliance_cell) > 200
                            else f"    Предупреждения: {compliance_cell}"
                        )
                    if risks_cell:
                        tqdm.write(
                            f"    Риски (ИИ): {risks_cell[:200]}…" if len(risks_cell) > 200 else f"    Риски (ИИ): {risks_cell}"
                        )
                    tqdm.write("")
    
                if pbar is not None:
                    pbar.update(1)
    
                if rows_out and (
                    len(rows_out) % int(args.checkpoint_every) == 0 or len(rows_out) == limit
                ):
                    save_invoice_checkpoint(rows_out, csv_path=ck_csv, meta_path=ck_meta, meta=meta_run)
    
            if pbar is not None:
                pbar.close()
        finally:
            rag_db.close()

    except KeyboardInterrupt:
        if rows_out:
            save_invoice_checkpoint(rows_out, csv_path=ck_csv, meta_path=ck_meta, meta=meta_run)
            print(
                f"\nПрервано. Сохранено строк в чекпоинт: {len(rows_out)} → {ck_csv}",
                file=sys.stderr,
            )
        raise
    finally:
        cleanup_temp_invoice_images()

    out_df = pd.DataFrame(rows_out)
    out_dir = _ROOT / "data" / "processed_invoices"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    stem = path.stem
    out_path = out_dir / f"processed_{stem}_{ts}.xlsx"
    write_invoice_report_excel(out_df, out_path, include_summary_row=True)

    for p in (ck_csv, ck_meta):
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass

    if print_console:
        print(
            "\nНаименование\tКод ТН ВЭД\tПошлина %\tApplied_Special_Duty\tsanction_risk (фрагмент)\tНДС %",
            flush=True,
        )
        print("-" * 120, flush=True)
        for row in rows_out:
            n = (row.get("name_ru") or "")[:40]
            h = row.get("suggested_hs_code") or "—"
            dr = row.get("duty_rate")
            drs = f"{float(dr):g}" if isinstance(dr, (int, float)) else str(dr)
            asp = (row.get("Applied_Special_Duty") or "")[:40]
            sr = (row.get("sanction_risk") or "").replace("\n", " ")[:100]
            v = row.get("vat_rate")
            vs = f"{float(v):g}" if isinstance(v, (int, float)) else str(v)
            print(f"{n}\t{h}\t{drs}\t{asp}\t{sr}\t{vs}", flush=True)
        print("-" * 120, flush=True)

    print(
        f"Готово: обработано {len(rows_out)} из {total} строк (лимит max-rows={args.max_rows}).\n"
        f"Отчёт: {out_path}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
