"""Полный интеллектуальный разбор коммерческих документов для ВЭД.

Цепочка: валидация → черновик ДТ (ИИ, ТН ВЭД, графа 31, разрешения по правилам) →
конвейер copilot по каждой строке (нетарифка, платежи, ФСА) → общая ИИ-сводка (риски, шаги).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from loguru import logger

from .assistant_orchestrator import run_copilot_batch
from .claude_service import analyze_copilot_bundle
from .declaration_draft_service import build_declaration_draft
from .decision_history import similar_decisions_context
from .permit_extractor import extract_permits_from_text
from .permits_service import check_permits
from .rag_service import rag_context_for_copilot


def _permit_rows_from_extracted(extracted: List[Dict[str, str]]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for x in extracted or []:
        t = str(x.get("type") or "").strip()
        n = str(x.get("number") or "").strip()
        if t and n:
            out.append({"type": t, "number": n})
    return out


def _line_total_prices(declaration_lines: List[Dict[str, Any]], inv_items: List[Dict[str, Any]]) -> List[float]:
    """Стоимость строки из инвойса по номеру строки черновика (0 если нет)."""
    out: List[float] = []
    for dl in declaration_lines:
        line_no = int(dl.get("line") or 0) or 0
        idx = line_no - 1
        v = 0.0
        if 0 <= idx < len(inv_items):
            try:
                v = float(inv_items[idx].get("total_price") or 0)
            except (TypeError, ValueError):
                v = 0.0
        out.append(v)
    return out


def _customs_values_per_line(
    declaration_lines: List[Dict[str, Any]],
    inv_items: List[Dict[str, Any]],
    fallback_total_rub: float,
) -> tuple[List[float], Optional[str]]:
    """Таможенная стоимость по строкам: из файла или распределение fallback_total_rub."""
    n = len(declaration_lines)
    from_file = _line_total_prices(declaration_lines, inv_items)
    if n == 0:
        return [], None
    total_file = sum(from_file)
    if total_file > 0:
        return from_file, None
    fb = max(0.0, float(fallback_total_rub or 0.0))
    if fb <= 0:
        return [0.0] * n, None
    qtys: List[float] = []
    for dl in declaration_lines:
        try:
            qtys.append(max(0.0, float(dl.get("quantity") or 0)))
        except (TypeError, ValueError):
            qtys.append(0.0)
    sum_q = sum(qtys)
    if sum_q > 0:
        allocated = [fb * (qtys[i] / sum_q) for i in range(n)]
        return allocated, (
            f"Таможенная стоимость не найдена в файле; сумма {fb:,.0f} ₽ распределена пропорционально количеству."
        )
    share = fb / n
    return [share] * n, (
        f"Таможенная стоимость не найдена в файле; сумма {fb:,.0f} ₽ распределена поровну между {n} строками."
    )


def _freight_by_customs_weights(customs_values: List[float], freight_total: float) -> Dict[int, float]:
    """Фрахт по строкам пропорционально таможенной стоимости строки."""
    n = len(customs_values)
    if n <= 0 or freight_total <= 0:
        return {}
    total_cv = sum(customs_values)
    if total_cv > 0:
        return {i: freight_total * (customs_values[i] / total_cv) for i in range(n)}
    share = freight_total / n
    return {i: share for i in range(n)}


async def run_ved_intel_pipeline(
    *,
    invoice_data: Dict[str, Any],
    packing_data: Optional[Dict[str, Any]],
    has_packing: bool,
    validation_snapshot: Dict[str, Any],
    country: str,
    hs_code_hint: str,
    use_ai_declaration: bool,
    extract_permits: bool,
    verify_fsa: bool,
    skip_registry: bool,
    run_payment: bool,
    freight_total_rub: float,
    fallback_customs_total_rub: float = 0.0,
    prefer_client_id: Optional[str],
) -> Dict[str, Any]:
    """После extract+validate. Возвращает блоки для ответа API (без persist)."""
    text_parts: List[str] = []
    for key in ("invoice", "packing"):
        block = (invoice_data if key == "invoice" else (packing_data or {})) or {}
        raw = block.get("raw_text") or ""
        if raw:
            text_parts.append(str(raw))
    combined = "\n".join(text_parts)

    extracted: List[Dict[str, str]] = []
    permits_check: List[Any] = []
    permits_note: Optional[str] = None
    if extract_permits:
        extracted = extract_permits_from_text(combined)
        if verify_fsa and extracted and not skip_registry:
            try:
                permits_check = await check_permits(extracted, (hs_code_hint or "").strip(), enrich=True)
            except Exception as e:
                logger.warning(f"ved_intel FSA: {e}")
                permits_check = []
        elif verify_fsa and not extracted:
            permits_note = "Номера СС/ДС/СГР в тексте не обнаружены"

    permit_rows = _permit_rows_from_extracted(extracted)

    draft: Dict[str, Any] = {}
    if use_ai_declaration:
        try:
            draft = await build_declaration_draft(
                invoice_data,
                packing_data if has_packing else None,
                use_llm=True,
                prefer_client_id=(prefer_client_id or "").strip() or None,
            )
        except Exception as e:
            logger.exception("ved_intel declaration draft")
            draft = {"status": "ERROR", "error": str(e), "declaration_lines": []}
    else:
        draft = {"status": "SKIPPED", "declaration_lines": [], "summary": {}}

    lines = list(draft.get("declaration_lines") or [])
    if not lines:
        ai_fallback = await analyze_copilot_bundle(
            {
                "positions": [],
                "positions_count": 0,
                "note": "Не удалось получить строки черновика ДТ. Проверьте формат файла и настройку ИИ на сервере (GEMINI_API_KEY / ANTHROPIC_API_KEY).",
            },
        )
        return {
            "ved_intel_status": "incomplete",
            "declaration_draft": draft,
            "extracted_permits": extracted,
            "permits_registry_check": permits_check,
            "permits_registry_note": permits_note,
            "copilot_batch": None,
            "ai_analyst": ai_fallback,
            "validation": validation_snapshot,
        }

    inv_items = list(invoice_data.get("items") or [])
    lines50 = lines[:50]
    customs_vals, alloc_note = _customs_values_per_line(
        lines50,
        inv_items,
        fallback_customs_total_rub,
    )
    freight_map = _freight_by_customs_weights(
        customs_vals,
        max(0.0, float(freight_total_rub or 0)),
    )

    run_registry = verify_fsa and not skip_registry and bool(permit_rows)
    batch_items: List[Dict[str, Any]] = []
    for i, dl in enumerate(lines50):
        desc = str(dl.get("commercial_description") or "").strip()
        hs = str(dl.get("hs_code") or "").strip()
        cv_raw = customs_vals[i] if i < len(customs_vals) else 0.0
        cv: Optional[float] = float(cv_raw) if cv_raw and cv_raw > 0 else None
        fr = float(freight_map.get(i, 0.0))
        batch_items.append(
            {
                "description": desc or "—",
                "hs_code": hs,
                "country": country,
                "customs_value": cv,
                "freight": fr,
                "insurance": None,
                "quantity": dl.get("quantity"),
                "permits": list(permit_rows),
            }
        )

    try:
        out = await run_copilot_batch(
            batch_items,
            run_ai_classification=False,
            run_payment=run_payment,
            run_registry_verify=run_registry,
        )
    except Exception as e:
        logger.exception("ved_intel copilot batch")
        merged = {"positions": [], "positions_count": 0, "error": str(e)}
        ai = await analyze_copilot_bundle(merged)
        return {
            "ved_intel_status": "error",
            "declaration_draft": draft,
            "extracted_permits": extracted,
            "permits_registry_check": permits_check,
            "permits_registry_note": permits_note,
            "copilot_batch": None,
            "ai_analyst": ai,
            "validation": validation_snapshot,
        }

    merged = dict(out["merged_context_for_ai"])
    desc_join = " | ".join(str(x.get("commercial_description") or "") for x in lines)[:1200]
    try:
        rag = await rag_context_for_copilot(desc_join)
        sim = similar_decisions_context(desc_join, prefer_client_id=prefer_client_id)
        merged = {**merged, **rag, **sim}
    except Exception as e:
        logger.warning(f"ved_intel RAG/similar: {e}")

    ai = await analyze_copilot_bundle(merged)

    out_payload: Dict[str, Any] = {
        "ved_intel_status": "OK",
        "declaration_draft": draft,
        "extracted_permits": extracted,
        "permits_registry_check": permits_check,
        "permits_registry_note": permits_note,
        "copilot_batch": {
            "bundles": out["bundles"],
            "merged_context_for_ai": merged,
        },
        "ai_analyst": ai,
        "validation": validation_snapshot,
        "disclaimer_ved_intel": (
            "Интеллектуальный разбор носит справочный характер. Коды ТН ВЭД, платежи и нетарифные меры "
            "требуют проверки специалистом и актуальными правовыми источниками. Документы на китайском "
            "обрабатываются через извлечение текста и ИИ — возможны неточности наименований."
        ),
    }
    if alloc_note:
        out_payload["customs_value_allocation_note"] = alloc_note
    return out_payload
