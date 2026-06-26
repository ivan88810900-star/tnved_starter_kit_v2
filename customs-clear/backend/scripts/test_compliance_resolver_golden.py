#!/usr/bin/env python3
"""Golden-регрессия для системного compliance-resolver + enrich_with_customs_data."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.invoice_analyzer import enrich_with_customs_data


def _blob(enrichment: dict[str, Any]) -> str:
    chunks: list[str] = [str(enrichment.get("Required_Certificates") or "")]
    for m in enrichment.get("non_tariff") or []:
        if not isinstance(m, dict):
            continue
        chunks.append(str(m.get("document_required") or ""))
        chunks.append(str(m.get("description") or ""))
        chunks.append(str(m.get("regulatory_act") or ""))
    return " | ".join(chunks).lower()


def _must_have(blob: str, needles: list[str], case_name: str) -> None:
    for n in needles:
        if n.lower() not in blob:
            raise AssertionError(f"{case_name}: отсутствует обязательный маркер: {n}")


def _must_not_have(blob: str, needles: list[str], case_name: str) -> None:
    for n in needles:
        if n.lower() in blob:
            raise AssertionError(f"{case_name}: обнаружен запрещенный маркер: {n}")


def _run_case(case_name: str, hs: str, item: dict[str, Any], *, vat: float | None = None) -> dict[str, Any]:
    enr = enrich_with_customs_data(hs, item, vat_import_override=vat)
    print(f"[OK] {case_name}: hs={hs} vat={enr.get('vat_import_rate')} excise={enr.get('excise_value')}")
    return enr


def main() -> int:
    # 1) Смартфон 8517: DS + ФСБ + радио, без СГР.
    enr_8517 = _run_case(
        "smartphone_8517",
        "8517130000",
        {
            "name_ru": "Смартфон с Wi-Fi/Bluetooth/NFC, криптографические функции",
            "usage": "мобильная связь и передача данных",
        },
    )
    b8517 = _blob(enr_8517)
    _must_have(
        b8517,
        ["ДС ТР ТС 020/2011", "ДС ТР ЕАЭС 037/2016", "Нотификация ФСБ", "Радиочастотное разрешение/заключение"],
        "smartphone_8517",
    )
    _must_not_have(b8517, ["СГР"], "smartphone_8517")

    # 2) Напиток 2202: DS 021/022 + акциз 11 руб/л.
    enr_2202 = _run_case(
        "sweet_drink_2202",
        "2202990000",
        {
            "name_ru": "Газированный напиток с сахарозаменителем и сиропом",
            "usage": "безалкогольный напиток",
        },
    )
    b2202 = _blob(enr_2202)
    _must_have(b2202, ["ДС ТР ТС 021/2011", "ДС ТР ТС 022/2011", "акцизных таможенных постах"], "sweet_drink_2202")
    if float(enr_2202.get("excise_value") or 0) != 11.0:
        raise AssertionError("sweet_drink_2202: акциз должен быть 11 руб/л")

    # 3) Игрушки 9503: VAT 10 + CC 008 + маркировка.
    enr_9503 = _run_case(
        "toy_9503",
        "9503007000",
        {
            "name_ru": "Набор для детского творчества Юный химик",
            "usage": "детская игрушка",
        },
    )
    b9503 = _blob(enr_9503)
    _must_have(b9503, ["СС ТР ТС 008/2011", "Маркировка «Честный знак»"], "toy_9503")
    vat_9503 = float(enr_9503.get("vat_import_rate") or 0.0)
    if abs(vat_9503 - 10.0) > 1e-9:
        raise AssertionError(f"toy_9503: НДС должен быть 10%, получено {vat_9503}")

    # 4) БАД 2106: DS + СГР.
    enr_2106 = _run_case(
        "baad_2106",
        "2106909808",
        {
            "name_ru": "БАД в капсулах с экстрактом женьшеня",
            "usage": "биологически активная добавка",
        },
    )
    b2106 = _blob(enr_2106)
    _must_have(b2106, ["ДС ТР ТС 021/2011", "ДС ТР ТС 022/2011", "СГР"], "baad_2106")

    # 5) Быстрая проверка 8413: CC 010 (базовый профиль).
    enr_8413 = _run_case(
        "pump_8413",
        "8413707500",
        {
            "name_ru": "Насос центробежный с электродвигателем",
            "usage": "промышленный насос",
        },
    )
    b8413 = _blob(enr_8413)
    _must_have(b8413, ["СС ТР ТС 010/2011"], "pump_8413")

    print("ALL GOLDEN CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
