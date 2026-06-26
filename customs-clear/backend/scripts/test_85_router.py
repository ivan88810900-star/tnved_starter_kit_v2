#!/usr/bin/env python3
"""
Быстрый smoke-тест пайплайна invoice_analyzer для 85-й группы ТН ВЭД.

Проверяет на одном товаре:
- подбор 10-значного кода ТН ВЭД через Gemini + RAG;
- блок электроники (частоты / ФСБ / РЧЦ);
- подтяжку нетарифных мер из customs.db;
- сверку по реестрам (ФСБ/РЭС + вложенный блок СГР).

Запуск (из customs-clear/backend):
  PYTHONPATH=. python3 scripts/test_85_router.py
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

from app.db import SessionLocal  # noqa: E402
from app.services.invoice_analyzer import InvoiceAnalyzer, enrich_with_customs_data  # noqa: E402


def _build_test_payload() -> dict[str, Any]:
    return {
        "name_ru": "Беспроводной маршрутизатор (роутер)",
        "brand": "Xiaomi",
        "model": "Mi Wi-Fi Router 4A",
        # Можно оставить пустым для чистого подбора ИИ; 8517 — как подсказка группы.
        "declared_hs_code": "8517",
        "usage": "Маршрутизация сетевого трафика, Wi-Fi связь",
        "material": "Пластик, электронные компоненты",
        "country_origin": "CN",
        "article": "Mi Wi-Fi Router 4A",
        "quantity": "1",
    }


def _to_pretty_dict(payload: dict[str, Any], hs_payload: dict[str, Any], enrichment: dict[str, Any]) -> dict[str, Any]:
    hs_code = str(hs_payload.get("suggested_hs_code") or hs_payload.get("hs_code") or "").strip()
    electronics = hs_payload.get("electronics_compliance")
    electronics = electronics if isinstance(electronics, dict) else {}
    registry = hs_payload.get("registry_check")
    registry = registry if isinstance(registry, dict) else {}
    sgr = registry.get("sgr")
    sgr = sgr if isinstance(sgr, dict) else {}
    non_tariff = enrichment.get("non_tariff") if isinstance(enrichment, dict) else []
    non_tariff = non_tariff if isinstance(non_tariff, list) else []

    return {
        "input_payload": payload,
        "tnved_result": {
            "hs_code_10": hs_code or "НЕ ОПРЕДЕЛЕН",
            "confidence_score": hs_payload.get("confidence_score"),
            "justification": hs_payload.get("justification") or "",
            "opi_reasoning_steps": hs_payload.get("opi_reasoning_steps") or hs_payload.get("reasoning_steps") or [],
            "missing_info": hs_payload.get("missing_info") or [],
            "supplier_question_en": hs_payload.get("supplier_question_en") or "",
        },
        "electronics_web_findings": {
            "frequencies": electronics.get("frequencies") or [],
            "has_wireless_tech": bool(electronics.get("has_wireless_tech")),
            "has_encryption": bool(electronics.get("has_encryption")),
            "fss_notification_required": bool(electronics.get("fss_notification_required")),
            "rf_license_required": bool(electronics.get("rf_license_required")),
            "compliance_justification": electronics.get("compliance_justification") or "",
        },
        "non_tariff_from_db": non_tariff,
        "registry_check_fss_reo": {
            "status": registry.get("status") or "—",
            "document_number": registry.get("document_number") or "—",
            "date_status": registry.get("date_status") or "—",
            "recommendation": registry.get("recommendation") or "—",
        },
        "registry_check_sgr": {
            "status": sgr.get("status") or "—",
            "document_number": sgr.get("document_number") or "—",
            "date_status": sgr.get("date_status") or "—",
            "recommendation": sgr.get("recommendation") or "—",
        },
    }


def main() -> int:
    payload = _build_test_payload()

    with SessionLocal() as db:
        analyzer = InvoiceAnalyzer(db_session=db)
        hs_payload = analyzer.suggest_hs_code_for_item(payload, db_session=db)
        hs_code = str(hs_payload.get("hs_code") or "").strip()
        enrichment = enrich_with_customs_data(hs_code, payload) if hs_code else enrich_with_customs_data("", payload)

    out = _to_pretty_dict(payload, hs_payload, enrichment)

    try:
        from rich.console import Console
        from rich.pretty import Pretty

        console = Console()
        console.rule("[bold cyan]TEST 85 ROUTER PIPELINE[/bold cyan]")
        console.print(Pretty(out, expand_all=False))
    except Exception:
        pprint.pprint(out, sort_dicts=False, width=120)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
