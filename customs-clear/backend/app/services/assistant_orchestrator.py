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
    """Сжатый evidence JSON для сводки (без raw и без потери provenance)."""
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
            "status": pay.get("status"),
            "amounts_provisional": pay.get("amounts_provisional"),
            "tariff_preference": pay.get("tariff_preference"),
            "payment_review_reason": pay.get("payment_review_reason"),
            "payment_review_reasons": pay.get("payment_review_reasons") or [],
            "duty": b.get("duty"),
            "duty_rate": b.get("duty_rate"),
            "vat": b.get("vat"),
            "excise": b.get("excise"),
            "antidumping": b.get("antidumping"),
            "antidumping_status": b.get("antidumping_status"),
            "total_payable": b.get("total_payable"),
            "vat_rate": b.get("vat_rate"),
            "data_quality": pay.get("data_quality") if isinstance(pay.get("data_quality"), dict) else {},
            "legal_basis": pay.get("legal_basis") if isinstance(pay.get("legal_basis"), dict) else {},
            "sources": [
                {
                    "name": x.get("name"),
                    "revision": x.get("revision"),
                    "data_info": x.get("data_info"),
                    "url": x.get("url"),
                }
                for x in (pay.get("sources") or [])[:8]
                if isinstance(x, dict)
            ],
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
            "official_ett_url": tv.get("official_ett_url"),
            "source_revision": tv.get("source_revision"),
        }

    normative = nt.get("normative_block") if isinstance(nt.get("normative_block"), dict) else {}
    if normative:
        def _normative_rows(key: str, *, limit: int = 12) -> list[dict[str, Any]]:
            return [
                {
                    "permit_type": row.get("permit_type"),
                    "tr_ts": row.get("tr_ts"),
                    "source": row.get("source"),
                    "source_label": row.get("source_label"),
                    "applicability": row.get("applicability"),
                    "reason": str(row.get("reason") or row.get("note") or "")[:320],
                }
                for row in (normative.get(key) or [])[:limit]
                if isinstance(row, dict)
            ]

        slim["normative_requirements"] = {
            "status": normative.get("status"),
            "required_documents": _normative_rows("required_documents"),
            "missing_documents": _normative_rows("missing_documents"),
            "advisory_requirements": _normative_rows("advisory_requirements"),
            "empty_message": normative.get("empty_message"),
        }

    risk = nt.get("risk_block") if isinstance(nt.get("risk_block"), dict) else {}
    if risk:
        slim["risk_summary"] = {
            "status": risk.get("status"),
            "overall_severity": risk.get("overall_severity"),
            "coverage_complete": bool(risk.get("coverage_complete")),
            "signals": [
                {
                    "category": row.get("category"),
                    "severity": row.get("severity"),
                    "source": row.get("source"),
                    "source_label": row.get("source_label"),
                    "source_url": row.get("source_url"),
                    "match_method": row.get("match_method"),
                    "explanation": str(row.get("explanation") or "")[:420],
                }
                for row in (risk.get("signals") or [])[:10]
                if isinstance(row, dict)
            ],
            "source_coverage": [
                {
                    "source_id": row.get("source_id"),
                    "title": row.get("title"),
                    "coverage_status": row.get("coverage_status"),
                    "manual_review_required": bool(row.get("manual_review_required")),
                    "source_url": row.get("source_url"),
                }
                for row in (risk.get("source_coverage") or [])[:10]
                if isinstance(row, dict)
            ],
            "screening_scope": list(risk.get("screening_scope") or [])[:6],
            "canonical_anchor": risk.get("canonical_anchor"),
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
