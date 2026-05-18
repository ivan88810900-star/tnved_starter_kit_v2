"""Оркестрация: классификация → платежи → нетарифка → реестр → контекст для ИИ."""
from __future__ import annotations

import asyncio
import os
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from loguru import logger

from .claude_service import classify_hs_code
from .normative_store import get_tnved_context_for_hs
from .payment_engine_compat import compute_payments
from .non_tariff_service import check_position_non_tariff


def _digits_hs(s: str, max_len: int = 10) -> str:
    return re.sub(r"\D", "", (s or "").strip())[:max_len]


def pick_hs_from_classification(parsed: Dict[str, Any]) -> str:
    """Достаёт 10-значный код из разных форматов ответа LLM-классификатора."""
    if not parsed:
        return ""
    rec = parsed.get("recommended")
    if isinstance(rec, str):
        d = _digits_hs(rec)
        if len(d) >= 4:
            return d
    if isinstance(rec, dict):
        for k in ("hs_code", "code", "tnved", "тн_вед"):
            d = _digits_hs(str(rec.get(k) or ""))
            if len(d) >= 4:
                return d
    for r in parsed.get("results") or parsed.get("variants") or []:
        if not isinstance(r, dict):
            continue
        for k in ("hs_code", "code", "tnved"):
            d = _digits_hs(str(r.get(k) or ""))
            if len(d) >= 4:
                return d
    return ""


async def run_copilot_pipeline(
    *,
    description: str,
    hs_code: str = "",
    country: Optional[str] = None,
    customs_value: Optional[float] = None,
    freight: float = 0.0,
    insurance: Optional[float] = None,
    quantity: Optional[float] = None,
    permits: List[Dict[str, str]],
    run_ai_classification: bool = False,
    run_payment: bool = True,
    run_registry_verify: bool = False,
) -> Dict[str, Any]:
    """Выполняет цепочку шагов и возвращает структурированный результат для UI и LLM."""
    pipeline: List[Dict[str, Any]] = []
    classification: Optional[Dict[str, Any]] = None
    effective_hs = _digits_hs(hs_code)

    # 1) Классификация (если нет кода и включено)
    if not effective_hs and run_ai_classification and (description or "").strip():
        logger.info("Copilot: шаг classify_hs_code")
        classification = await classify_hs_code(description.strip())
        effective_hs = pick_hs_from_classification(classification)
        pipeline.append(
            {
                "step": "classification",
                "ok": bool(effective_hs),
                "detail": effective_hs or "код не извлечён из ответа ИИ",
            }
        )
    elif effective_hs:
        pipeline.append({"step": "classification", "skipped": True, "detail": "код задан вручную"})
    else:
        pipeline.append(
            {
                "step": "classification",
                "skipped": True,
                "detail": "нет описания для ИИ или выключена авто-классификация",
            }
        )

    permit_list = [{"type": p.get("type", ""), "number": (p.get("number") or "").strip()} for p in permits]
    permit_list = [p for p in permit_list if p["number"]]

    payment: Optional[Dict[str, Any]] = None
    non_tariff: Dict[str, Any] = {}

    # 2) Нетарифка (нужен код; иначе только предупреждение)
    if effective_hs:
        logger.info(f"Copilot: нетарифка {effective_hs}")
        non_tariff = await check_position_non_tariff(
            effective_hs,
            (description or "").strip() or "—",
            country,
            permit_list,
            skip_registry_verify=not run_registry_verify,
        )
        pipeline.append({"step": "non_tariff", "ok": True, "status": non_tariff.get("status")})
    else:
        pipeline.append({"step": "non_tariff", "skipped": True, "detail": "нет кода ТН ВЭД"})
        non_tariff = {
            "status": "UNKNOWN",
            "hs_code": "",
            "note": "Укажите код ТН ВЭД или включите авто-классификацию с ключом ИИ.",
        }

    # 3) Платежи
    if run_payment and effective_hs and customs_value is not None and customs_value > 0:
        logger.info("Copilot: расчёт платежей")
        pay_in: Dict[str, Any] = {
            "hs_code": effective_hs,
            "customs_value": float(customs_value),
            "freight": float(freight),
        }
        if insurance is not None:
            pay_in["insurance"] = insurance
        if quantity is not None:
            pay_in["quantity"] = quantity
        payment = compute_payments(pay_in)
        pipeline.append({"step": "payment", "ok": True, "total": payment.get("breakdown", {}).get("total_payable")})
    else:
        pipeline.append(
            {
                "step": "payment",
                "skipped": True,
                "detail": "нет кода или таможенной стоимости ≤ 0 или выключено",
            }
        )

    # 4) Реестр — внутри non_tariff.permits (или SKIPPED)
    if run_registry_verify and permit_list and effective_hs:
        pipeline.append(
            {
                "step": "registry",
                "ok": True,
                "count": len(non_tariff.get("permits") or []),
            }
        )
    elif run_registry_verify and not permit_list:
        pipeline.append({"step": "registry", "skipped": True, "detail": "нет номеров документов"})
    else:
        pipeline.append({"step": "registry", "skipped": True, "detail": "выключено — документы не проверялись в ФСА"})

    permits_verification = non_tariff.get("permits") if effective_hs else None

    tnved_context: Optional[Dict[str, Any]] = None
    if effective_hs:
        tnved_context = get_tnved_context_for_hs(effective_hs)

    bundle: Dict[str, Any] = {
        "effective_hs_code": effective_hs,
        "description": description,
        "country": country,
        "pipeline": pipeline,
        "classification": classification,
        "non_tariff": non_tariff,
        "payment": payment,
        "permits_input": permit_list,
        "permits_verification": permits_verification,
        "tnved_context": tnved_context,
    }
    return bundle


def bundle_for_llm(bundle: Dict[str, Any]) -> Dict[str, Any]:
    """Сжатый JSON для промпта (без огромных raw)."""
    pay = bundle.get("payment") or {}
    b = pay.get("breakdown") if isinstance(pay, dict) else {}
    nt = bundle.get("non_tariff") or {}
    slim = {
        "effective_hs_code": bundle.get("effective_hs_code"),
        "description": bundle.get("description"),
        "country": bundle.get("country"),
        "non_tariff_status": nt.get("status"),
        "tr_ts": nt.get("tr_ts"),
        "required_permit_types": nt.get("required_permit_types"),
        "missing_permit_types": nt.get("missing_permit_types"),
        "permits_registry_summary": None,
    }
    if isinstance(b, dict) and b:
        slim["payment_summary"] = {
            "duty": b.get("duty"),
            "vat": b.get("vat"),
            "excise": b.get("excise"),
            "antidumping": b.get("antidumping"),
            "total_payable": b.get("total_payable"),
            "vat_rate": b.get("vat_rate"),
        }
    pv = bundle.get("permits_verification")
    if isinstance(pv, list):
        slim["permits_registry_summary"] = [
            {
                "type": x.get("type"),
                "number": x.get("number"),
                "status": x.get("status"),
                "hs_match": (x.get("hs_code_check") or {}).get("hs_match"),
            }
            for x in pv[:20]
        ]
    tv = bundle.get("tnved_context")
    if isinstance(tv, dict) and tv:
        note_titles = [str(n.get("title") or "") for n in (tv.get("notes") or [])[:6] if isinstance(n, dict)]
        slim["tnved_from_db"] = {
            "title": (tv.get("title") or "")[:500],
            "description_excerpt": (str(tv.get("description") or ""))[:400],
            "breadcrumb_hs": [b.get("hs_code") for b in (tv.get("breadcrumb") or []) if isinstance(b, dict)],
            "note_titles": [t for t in note_titles if t],
        }
    return slim


async def run_copilot_batch(
    items: Sequence[Dict[str, Any]],
    *,
    run_ai_classification: bool = False,
    run_payment: bool = True,
    run_registry_verify: bool = False,
) -> Dict[str, Any]:
    """Несколько позиций: конвейер на каждую (параллельно с лимитом) + общий контекст для ИИ."""
    concurrency = int(os.getenv("COPILOT_BATCH_CONCURRENCY", "4"))
    concurrency = max(1, min(concurrency, 16))
    sem = asyncio.Semaphore(concurrency)

    async def one(idx: int, it: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        permits = it.get("permits") or []
        if isinstance(permits, list):
            plist = [{"type": str(p.get("type", "")), "number": str(p.get("number", ""))} for p in permits]
        else:
            plist = []
        async with sem:
            b = await run_copilot_pipeline(
                description=str(it.get("description") or ""),
                hs_code=str(it.get("hs_code") or ""),
                country=it.get("country"),
                customs_value=it.get("customs_value"),
                freight=float(it.get("freight") or 0),
                insurance=it.get("insurance"),
                quantity=it.get("quantity"),
                permits=plist,
                run_ai_classification=run_ai_classification,
                run_payment=run_payment,
                run_registry_verify=run_registry_verify,
            )
        return idx, b

    pairs = await asyncio.gather(*[one(i, dict(it)) for i, it in enumerate(items)])
    pairs.sort(key=lambda x: x[0])
    bundles = [b for _, b in pairs]
    merged = {
        "positions": [bundle_for_llm(x) for x in bundles],
        "positions_count": len(bundles),
    }
    return {"bundles": bundles, "merged_context_for_ai": merged}
