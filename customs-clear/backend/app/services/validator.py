from __future__ import annotations

from typing import Any, Dict, List

# Короткие заголовки для UI (вместо внутренних кодов вроде packages_match)
CHECK_TITLES_RU: Dict[str, str] = {
    "upload_mode": "Режим проверки",
    "packages_match": "Количество мест / строк",
    "weight_gross_total": "Общий вес брутто",
    "weight_net_total": "Общий вес нетто",
    "lines_count_match": "Число товарных позиций",
    "qty_per_line": "Количество по строкам",
    "qty_per_line_overall": "Количество по строкам",
    "invoice_lines": "Товарные строки в инвойсе",
    "invoice_weight_totals": "Вес по инвойсу",
    "descriptions_semantic": "Описания товаров",
}


def _percent_diff(a: float, b: float) -> float:
    if a == 0 and b == 0:
        return 0.0
    base = (a + b) / 2 or 1.0
    return abs(a - b) / base * 100.0


def _build_check(name: str, status: str, detail: str) -> Dict[str, Any]:
    return {
        "check": name,
        "title": CHECK_TITLES_RU.get(name, name.replace("_", " ")),
        "status": status,
        "detail": detail,
    }


def _verdict_ru(status: str, errors: int, warnings: int, *, comparison_mode: str) -> Dict[str, str]:
    """Краткий вывод простым языком для блока над таблицей проверок."""
    mode_note = (
        "Загружен только инвойс — сравнение с упаковочным листом не делалось."
        if comparison_mode == "invoice_only"
        else "Сравниваются инвойс и упаковочный лист."
    )
    if status == "OK":
        return {
            "headline": "Критичных расхождений не найдено",
            "detail": f"{mode_note} По доступным данным расхождений нет. Уточняйте итог на стороне таможни.",
        }
    if status == "WARNING":
        return {
            "headline": "Есть предупреждения",
            "detail": f"{mode_note} Проверьте жёлтые пункты ниже: часто это нехватка данных (например PDF без таблицы) или допуск по весу.",
        }
    return {
        "headline": "Обнаружены расхождения",
        "detail": f"{mode_note} Красные пункты — несовпадения между документами или отсутствие данных. Исправьте документы или уточните у поставщика.",
    }


def validate_invoice_only(invoice: Dict[str, Any]) -> Dict[str, Any]:
    """Проверка при загрузке только инвойса (без упаковочного листа)."""
    checks: List[Dict[str, Any]] = []
    checks.append(
        _build_check(
            "upload_mode",
            "OK",
            "Загружен только инвойс. Сверка весов и количеств с упаковочным листом не выполнялась — при необходимости добавьте второй файл.",
        )
    )
    items = invoice.get("items") or []
    raw = (invoice.get("raw_text") or "").strip()
    n = len(items)
    if n == 0:
        if len(raw) > 50:
            checks.append(
                _build_check(
                    "invoice_lines",
                    "WARNING",
                    "Из файла снят текст, но таблица товаров не распознана. Так бывает с PDF: попробуйте Excel (.xlsx) или экспорт таблицы из счёта.",
                )
            )
        else:
            checks.append(
                _build_check(
                    "invoice_lines",
                    "WARNING",
                    "Товарные строки не найдены. Проверьте формат файла (лучше Excel с колонками «описание», «количество»).",
                )
            )
    else:
        checks.append(
            _build_check(
                "invoice_lines",
                "OK",
                f"Распознано позиций в инвойсе: {n}. Проверьте, что колонки и суммы соответствуют оригиналу.",
            )
        )
    inv_summary = invoice.get("summary") or {}
    gw = float(inv_summary.get("gross_weight_total") or 0)
    nw = float(inv_summary.get("net_weight_total") or 0)
    if gw > 0 or nw > 0:
        checks.append(
            _build_check(
                "invoice_weight_totals",
                "OK",
                f"По строкам инвойса: брутто {gw} кг, нетто {nw} кг (сумма по распознанным колонкам веса).",
            )
        )
    errors = sum(1 for c in checks if c["status"] == "ERROR")
    warnings = sum(1 for c in checks if c["status"] == "WARNING")
    passed = sum(1 for c in checks if c["status"] == "OK")
    st = "ERROR" if errors else ("WARNING" if warnings else "OK")
    verdict = _verdict_ru(st, errors, warnings, comparison_mode="invoice_only")
    return {
        "status": st,
        "comparison_mode": "invoice_only",
        "verdict": verdict,
        "invoice_number": invoice.get("invoice_number"),
        "extracted_at": invoice.get("extracted_at"),
        "items": items,
        "checks": checks,
        "summary": {"errors": errors, "warnings": warnings, "passed": passed},
    }


def validate_invoice_vs_packing(invoice: Dict[str, Any], packing: Dict[str, Any]) -> Dict[str, Any]:
    """Реализация правил из раздела 4.3 ТЗ.

    Ожидаемый формат минимальных данных:
    - invoice["summary"], packing["summary"] с полями:
      - gross_weight_total
      - net_weight_total
      - lines_count
    - invoice["items"], packing["items"] — массивы позиций.
    В случае отсутствия части данных проверки помечаются WARNING с пояснением.
    """
    checks: List[Dict[str, Any]] = []

    inv_summary = invoice.get("summary") or {}
    pack_summary = packing.get("summary") or {}

    # Количество мест (packages) — в MVP берём из lines_count как приближение
    inv_packages = inv_summary.get("packages") or inv_summary.get("lines_count")
    pack_packages = pack_summary.get("packages") or pack_summary.get("lines_count")
    if inv_packages is not None and pack_packages is not None:
        if inv_packages == pack_packages:
            checks.append(_build_check("packages_match", "OK", f"{inv_packages} == {pack_packages}"))
        else:
            checks.append(
                _build_check(
                    "packages_match",
                    "ERROR",
                    f"Инвойс: {inv_packages}, упаковочный: {pack_packages}",
                )
            )
    else:
        checks.append(
            _build_check(
                "packages_match",
                "WARNING",
                "Не удалось определить количество мест в одном из документов",
            )
        )

    # Общий вес брутто
    inv_gross = float(inv_summary.get("gross_weight_total") or 0)
    pack_gross = float(pack_summary.get("gross_weight_total") or 0)
    gross_diff_kg = abs(inv_gross - pack_gross)
    gross_diff_pct = _percent_diff(inv_gross, pack_gross)
    if inv_gross == 0 and pack_gross == 0:
        checks.append(
            _build_check(
                "weight_gross_total",
                "WARNING",
                "Нет данных по общему весу брутто",
            )
        )
    else:
        if gross_diff_kg <= 0.5 or gross_diff_pct <= 0.1:
            checks.append(
                _build_check(
                    "weight_gross_total",
                    "OK",
                    f"{inv_gross} кг vs {pack_gross} кг (Δ={gross_diff_kg:.3f} кг, {gross_diff_pct:.4f}%)",
                )
            )
        else:
            checks.append(
                _build_check(
                    "weight_gross_total",
                    "WARNING",
                    f"Разница брутто превышает допуск: {inv_gross} кг vs {pack_gross} кг (Δ={gross_diff_kg:.3f} кг, {gross_diff_pct:.4f}%)",
                )
            )

    # Общий вес нетто
    inv_net = float(inv_summary.get("net_weight_total") or 0)
    pack_net = float(pack_summary.get("net_weight_total") or 0)
    net_diff_kg = abs(inv_net - pack_net)
    net_diff_pct = _percent_diff(inv_net, pack_net)
    if inv_net == 0 and pack_net == 0:
        checks.append(
            _build_check(
                "weight_net_total",
                "WARNING",
                "Нет данных по общему весу нетто",
            )
        )
    else:
        if net_diff_kg <= 0.5 or net_diff_pct <= 0.1:
            checks.append(
                _build_check(
                    "weight_net_total",
                    "OK",
                    f"{inv_net} кг vs {pack_net} кг (Δ={net_diff_kg:.3f} кг, {net_diff_pct:.4f}%)",
                )
            )
        else:
            checks.append(
                _build_check(
                    "weight_net_total",
                    "WARNING",
                    f"Разница нетто превышает допуск: {inv_net} кг vs {pack_net} кг (Δ={net_diff_kg:.3f} кг, {net_diff_pct:.4f}%)",
                )
            )

    # Количество позиций
    inv_lines = int(inv_summary.get("lines_count") or len(invoice.get("items") or []))
    pack_lines = int(pack_summary.get("lines_count") or len(packing.get("items") or []))
    if inv_lines == pack_lines:
        checks.append(_build_check("lines_count_match", "OK", f"{inv_lines} == {pack_lines}"))
    else:
        checks.append(
            _build_check(
                "lines_count_match",
                "ERROR",
                f"Инвойс: {inv_lines} позиций, упаковочный: {pack_lines} позиций",
            )
        )

    # Количество по каждой позиции — в MVP сравниваем по индексу
    inv_items = invoice.get("items") or []
    pack_items = packing.get("items") or []
    per_line_status = "OK"
    for i, inv_item in enumerate(inv_items):
        if i >= len(pack_items):
            checks.append(
                _build_check(
                    "qty_per_line",
                    "ERROR",
                    f"Строка {i + 1}: нет соответствующей позиции в упаковочном листе",
                )
            )
            per_line_status = "ERROR"
            continue
        pack_item = pack_items[i]
        inv_qty = float(inv_item.get("quantity") or 0)
        pack_qty = float(pack_item.get("quantity") or 0)
        if inv_qty == pack_qty:
            continue
        per_line_status = "ERROR"
        checks.append(
            _build_check(
                "qty_per_line",
                "ERROR",
                f"Строка {i + 1}: Инвойс {inv_qty}, упаковочный {pack_qty}",
            )
        )
    if per_line_status == "OK":
        checks.append(_build_check("qty_per_line_overall", "OK", "Количество по всем строкам совпадает"))

    # Описания товаров: для MVP только технический флаг — реальный смысловой анализ сделает Claude
    if inv_items and pack_items:
        checks.append(
            _build_check(
                "descriptions_semantic",
                "WARNING",
                "Тексты описаний товаров автоматически не сравниваются — просмотрите вручную, что номенклатура в инвойсе и упаковке относится к одному товару.",
            )
        )

    # Сводный статус
    errors = sum(1 for c in checks if c["status"] == "ERROR")
    warnings = sum(1 for c in checks if c["status"] == "WARNING")
    passed = sum(1 for c in checks if c["status"] == "OK")

    if errors > 0:
        status = "ERROR"
    elif warnings > 0:
        status = "WARNING"
    else:
        status = "OK"

    verdict = _verdict_ru(status, errors, warnings, comparison_mode="invoice_and_packing")
    result: Dict[str, Any] = {
        "status": status,
        "comparison_mode": "invoice_and_packing",
        "verdict": verdict,
        "invoice_number": invoice.get("invoice_number"),
        "extracted_at": invoice.get("extracted_at"),
        "items": invoice.get("items") or [],
        "checks": checks,
        "summary": {"errors": errors, "warnings": warnings, "passed": passed},
    }
    return result

