from __future__ import annotations

from pydantic import BaseModel, Field


class MoneyBreakdown(BaseModel):
    base_duty: float = Field(description="Ввозная пошлина (Import Duty), RUB.")
    vat: float = Field(description="НДС (VAT), RUB.")
    excise: float = Field(description="Акциз, RUB.")
    anti_dumping: float = Field(description="Антидемпинговая составляющая, RUB.")
    customs_fee: float = Field(description="Таможенный сбор, RUB.")
    total_payable: float = Field(description="Расчётный итог, RUB; предварительный при amounts_provisional=true.")


class ComplianceDocumentItem(BaseModel):
    doc_type: str
    legal_ref: str
    title: str
    detail: str
    source: str
    priority: int = 100
    registry_match: str | None = None
    compliance_status: str = "REQUIRED"


class PaymentProfileResponse(BaseModel):
    status: str
    hs_code: str
    country: str | None = None
    breakdown: MoneyBreakdown
    documents: list[ComplianceDocumentItem] = Field(default_factory=list)
    blocking_issue: bool = False
    geo: dict | None = None
    data_quality: dict | None = None
    amounts_provisional: bool | None = None
    tariff_preference: dict | None = None
    payment_review_reason: str | None = None
    payment_review_reasons: list[str] = Field(default_factory=list)


class PaymentCompareScenarioItem(BaseModel):
    label: str
    delta_total_vs_first_rub: float | None = None
    profile: PaymentProfileResponse


class PaymentCompareResponse(BaseModel):
    status: str
    shared_economic: dict
    scenarios: list[PaymentCompareScenarioItem] = Field(default_factory=list)
    amounts_provisional: bool | None = None
    comparison_complete: bool | None = None
