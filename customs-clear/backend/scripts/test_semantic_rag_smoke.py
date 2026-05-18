#!/usr/bin/env python3
"""
Короткий smoke-тест для семантического RAG + классификатора.

Печатает:
- блок === СЕМАНТИЧЕСКИЕ ПРЕЦЕДЕНТЫ (TOP-3) ===,
- сырой JSON-ответ suggest_hs_code (включая opi_reasoning_steps).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
from app.db import SessionLocal
from app.services.invoice_analyzer import (
    InvoiceAnalyzer,
    _get_rag_context,
    _product_blob_for_rag,
    _suggested_chapter_for_rag,
)
from app.services.rag_retriever import get_semantic_legal_context
from app.services.text_processor import normalize_product_description

load_dotenv(ROOT / ".env")
load_dotenv()


TEST_ITEMS: list[dict[str, Any]] = [
    {
        "name_ru": "Умные часы с функцией измерения пульса, Bluetooth, без SIM-карты, в индивидуальной упаковке",
        "name_cn": "",
        "material": "корпус полимер/металл, ремешок силикон",
        "usage": "носимое электронное устройство для уведомлений и мониторинга активности",
        "brand": "Generic",
        "model": "Smart Watch X",
        "declared_hs_code": "",
        "suggested_chapter": "85",
        "country_origin": "CN",
    },
    {
        "name_ru": "Станок токарный металлообрабатывающий с ЧПУ, поставляется в разобранном виде двумя партиями",
        "name_cn": "",
        "material": "сталь, чугун, электронные узлы управления",
        "usage": "токарная обработка металлических деталей на производстве",
        "brand": "IndustrialTech",
        "model": "CNC-Lathe-9000",
        "declared_hs_code": "",
        "suggested_chapter": "84",
        "country_origin": "CN",
    },
]


def _normalized_blob_for_rag(item_data: dict[str, Any]) -> str:
    raw = _product_blob_for_rag(item_data) or " ".join(
        x
        for x in (
            str(item_data.get("name_ru") or ""),
            str(item_data.get("name_cn") or ""),
            str(item_data.get("material") or ""),
            str(item_data.get("usage") or ""),
            str(item_data.get("brand") or ""),
        )
        if x
    ).strip()
    if not raw:
        return ""
    nd = normalize_product_description(raw)
    clean = (nd.get("clean_russian_name") or "").strip()
    kw = (nd.get("search_keywords") or "").strip()
    return (kw or clean or raw).strip()


def main() -> int:
    with SessionLocal() as db:
        analyzer = InvoiceAnalyzer(db_session=db)
        for idx, item in enumerate(TEST_ITEMS, start=1):
            print("\n" + "=" * 120)
            print(f"ТЕСТОВЫЙ ТОВАР #{idx}: {item.get('name_ru')}")
            print("=" * 120)

            ch_hint = _suggested_chapter_for_rag(item)
            blob = _normalized_blob_for_rag(item)
            rag_text = _get_rag_context(db, blob, ch_hint)
            semantic_top3 = get_semantic_legal_context(blob, db, top_k=3, hs_code_prefix=ch_hint)

            print("\n=== RAG INPUT (NORMALIZED) ===")
            print(blob or "—")

            print("\n=== СЕМАНТИЧЕСКИЕ ПРЕЦЕДЕНТЫ (TOP-3) ===")
            if semantic_top3:
                for line in semantic_top3[:3]:
                    print(f"- {line}")
            else:
                print("- (релевантные векторные прецеденты не найдены)")

            print("\n=== RAG CONTEXT PREVIEW (FIRST 1200 chars) ===")
            print((rag_text or "")[:1200] or "—")

            result = analyzer.suggest_hs_code_for_item(item, fast_mode=False)

            print("\n=== RAW AI RESPONSE JSON ===")
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

            print("\n=== opi_reasoning_steps ===")
            steps = result.get("opi_reasoning_steps") or []
            if isinstance(steps, list) and steps:
                for n, step in enumerate(steps, start=1):
                    print(f"{n}. {step}")
            else:
                print("(пусто)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
