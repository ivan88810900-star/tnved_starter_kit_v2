from __future__ import annotations

from typing import Any

from ..db import SessionLocal
from ..schemas.payment_profile import (
    ComplianceDocumentItem,
    MoneyBreakdown,
    PaymentCompareResponse,
    PaymentCompareScenarioItem,
    PaymentProfileResponse,
)
from .compliance_resolver import build_compliance_document_items
from .payment_engine_compat import compare_payment_scenarios, compute_payments


def _map_raw_to_profile(
    *,
    hs_code: str,
    country: str | None,
    raw_result: dict[str, Any],
    item_data: dict[str, Any] | None = None,
) -> PaymentProfileResponse:
    breakdown = raw_result.get("breakdown") or {}
    with SessionLocal() as db:
        compliance_bundle = build_compliance_document_items(
            hs_code=hs_code,
            item_data=item_data,
            country=country,
            db=db,
        )
        document_rows = list(compliance_bundle.get("documents") or [])
        blocking_issue = bool(compliance_bundle.get("blocking_issue"))
        documents: list[ComplianceDocumentItem] = [
            ComplianceDocumentItem(
                doc_type=str(row.get("doc_type") or ""),
                legal_ref=str(row.get("legal_ref") or ""),
                title=str(row.get("title") or ""),
                detail=str(row.get("detail") or ""),
                source=str(row.get("source") or ""),
                priority=int(row.get("priority") or 100),
                registry_match=(str(row.get("registry_match")) if row.get("registry_match") else None),
                compliance_status=str(row.get("compliance_status") or "REQUIRED"),
            )
            for row in document_rows
        ]

    return PaymentProfileResponse(
        status=str(raw_result.get("status") or "OK"),
        hs_code=hs_code,
        country=country,
        breakdown=MoneyBreakdown(
            base_duty=float(breakdown.get("duty") or 0.0),
            vat=float(breakdown.get("vat") or 0.0),
            excise=float(breakdown.get("excise") or 0.0),
            anti_dumping=float(breakdown.get("antidumping") or 0.0),
            customs_fee=float(breakdown.get("customs_fee") or 0.0),
            total_payable=float(breakdown.get("total_payable") or 0.0),
        ),
        documents=documents,
        blocking_issue=blocking_issue,
        geo=raw_result.get("geo"),
        data_quality=raw_result.get("data_quality"),
    )


def build_full_payment_profile(
    *,
    payload: dict[str, Any],
    hs_code: str,
    country: str | None,
    item_data: dict[str, Any] | None = None,
) -> PaymentProfileResponse:
    """Единая сборка полного профиля мер: платежи + документы комплаенса."""
    raw = compute_payments(payload)
    return _map_raw_to_profile(
        hs_code=hs_code,
        country=country,
        raw_result=raw,
        item_data=item_data,
    )


def build_compare_payment_profiles(
    *,
    payload: dict[str, Any],
) -> PaymentCompareResponse:
    """
    Строгий контракт сравнения сценариев.
    На входе payload формата compare_payment_scenarios.
    """
    raw = compare_payment_scenarios(payload)
    scenarios_raw = list(raw.get("scenarios") or [])
    shared = raw.get("shared_economic") or {}

    scenarios: list[PaymentCompareScenarioItem] = []
    for row in scenarios_raw:
        hs_code = str(row.get("hs_code") or "").strip()
        scenario_country = str(row.get("country") or shared.get("country") or "").strip().upper() or None
        profile = build_full_payment_profile(
            payload={**shared, "hs_code": hs_code, "country": scenario_country},
            hs_code=hs_code,
            country=scenario_country,
        )
        scenarios.append(
            PaymentCompareScenarioItem(
                label=str(row.get("label") or hs_code),
                delta_total_vs_first_rub=(
                    float(row["delta_total_vs_first_rub"])
                    if row.get("delta_total_vs_first_rub") is not None
                    else None
                ),
                profile=profile,
            )
        )

    return PaymentCompareResponse(
        status=str(raw.get("status") or "OK"),
        shared_economic=shared,
        scenarios=scenarios,
    )
