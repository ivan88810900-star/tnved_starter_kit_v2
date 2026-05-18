"""Комбинированный расчёт: платежи + нетарифка."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..services.calculation_history_service import save_calculation_record
from ..services.non_tariff_service import check_position_non_tariff
from ..services.payment_engine_compat import compute_payments
from ..security import require_authenticated_user

router = APIRouter(dependencies=[Depends(require_authenticated_user)])


class PermitIn(BaseModel):
    type: str
    number: str


class ComplianceItemIn(BaseModel):
    hs_code: str
    description: str
    country: str | None = None
    permits: List[PermitIn] = []
    customs_value: float
    freight: float = 0.0
    insurance: float | None = None
    duty_rate: float | None = None
    vat_rate: float | None = None
    excise: float | None = None
    quantity: float | None = None


class ComplianceRequest(BaseModel):
    items: List[ComplianceItemIn]
    save_history: bool = Field(False, description="Сохранить сводку проверки в customs_calculation_history")
    document_id: str | None = Field(None, description="Связь с ingested_documents.id")
    user_ref: str = Field("", description="Пользователь / клиент для журнала")


@router.post("/check")
async def compliance_check(req: ComplianceRequest) -> JSONResponse:
    if not req.items:
        raise HTTPException(status_code=400, detail="Список позиций пуст")

    save_hist = req.save_history
    doc_link = req.document_id
    user_ref = req.user_ref or ""

    results: List[Dict[str, Any]] = []
    for item in req.items:
        payment = compute_payments(item.model_dump())
        non_tariff = await check_position_non_tariff(
            item.hs_code,
            item.description,
            item.country,
            [{"type": p.type, "number": p.number} for p in item.permits],
        )
        # Документы: требуемые и предоставленные разрешения
        documents = {
            "required": non_tariff.get("required_permit_types", []),
            "provided": [p.type for p in item.permits if p.number.strip()],
            "missing": non_tariff.get("missing_permit_types", []),
        }
        # Риски: отсутствующие документы, антидемпинг без страны, реестр ФСА
        risks: List[str] = []
        if documents["missing"]:
            risks.append(f"Отсутствуют разрешительные документы: {', '.join(documents['missing'])}")
        if payment.get("data_quality", {}).get("antidumping_status") == "manual_review":
            risks.append("Антидемпинговые меры требуют ручной проверки (страна не указана)")
        if non_tariff.get("data_freshness", {}).get("is_stale"):
            risks.append("Данные нормативных источников устарели")
        permits_rows = non_tariff.get("permits") or []
        for pr in permits_rows:
            if pr.get("status") == "NOT_FOUND" and (pr.get("number") or "").strip():
                risks.append(
                    f"Документ {pr.get('type')} №{pr.get('number')} не найден в открытом реестре"
                )
            hc = pr.get("hs_code_check") or {}
            if hc.get("hs_match") == "mismatch":
                risks.append(f"ТН ВЭД позиции и реестр: {hc.get('detail', 'расхождение')}")
            elif hc.get("hs_match") == "partial":
                risks.append(f"Частичное совпадение ТН ВЭД с реестром: {hc.get('detail', '')}")

        pv_summary = {
            "checked": len(permits_rows),
            "valid": sum(1 for p in permits_rows if p.get("status") == "VALID"),
            "not_found": sum(1 for p in permits_rows if p.get("status") == "NOT_FOUND"),
            "hs_mismatch": sum(
                1 for p in permits_rows if (p.get("hs_code_check") or {}).get("hs_match") == "mismatch"
            ),
        }
        results.append(
            {
                "hs_code": item.hs_code,
                "description": item.description,
                "country": item.country,
                "payment": payment,
                "non_tariff": non_tariff,
                "documents": documents,
                "permits_verification": {
                    "registry": "pub.fsa.gov.ru / fp.crc.ru",
                    "documents": permits_rows,
                    "summary": pv_summary,
                },
                "risks": risks,
            }
        )

    overall = "OK"
    if any(r["non_tariff"]["status"] == "ERROR" for r in results):
        overall = "ERROR"
    elif any(r["non_tariff"]["status"] == "WARNING" for r in results):
        overall = "WARNING"

    # Summary data quality from payment engine
    all_confidences = [r["payment"]["data_quality"]["confidence"] for r in results]
    any_stale = any(
        r["non_tariff"].get("data_freshness", {}).get("is_stale", False)
        for r in results
    )
    any_manual_review = any(
        r["payment"]["data_quality"].get("antidumping_status") == "manual_review"
        for r in results
    )

    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_confidence": all_confidences,
        "any_stale_source": any_stale,
        "any_manual_review": any_manual_review,
    }

    if save_hist:
        input_compact = {
            "items_count": len(req.items),
            "user_ref": user_ref,
            "items": [
                {
                    "hs_code": it.hs_code,
                    "description": (it.description or "")[:240],
                    "customs_value": it.customs_value,
                    "freight": it.freight,
                    "country": it.country,
                }
                for it in req.items
            ],
        }
        output_compact = {
            "status": overall,
            "meta": meta,
            "items_summary": [
                {
                    "hs_code": r["hs_code"],
                    "nt_status": r["non_tariff"]["status"],
                    "total_payable": r["payment"]["breakdown"]["total_payable"],
                    "risks_count": len(r["risks"]),
                }
                for r in results
            ],
        }
        save_calculation_record(
            input_payload=input_compact,
            output_payload=output_compact,
            document_id=doc_link,
            user_ref=user_ref,
            kind="compliance",
        )

    return JSONResponse({"status": overall, "items": results, "meta": meta})
