from __future__ import annotations

from pydantic import BaseModel, Field


class MoneyBreakdown(BaseModel):
    base_duty: float = Field(description="Ввозная пошлина (Import Duty), RUB.")
    vat: float | None = Field(description="НДС (VAT), RUB; null при недостоверной автоматической ставке.")
    excise: float = Field(description="Акциз, RUB.")
    anti_dumping: float | None = Field(description="Антидемпинговая составляющая, RUB; null при unresolved scope.")
    customs_fee: float = Field(description="Таможенный сбор, RUB.")
    total_payable: float | None = Field(description="Итого к уплате, RUB; null при обязательной ручной проверке.")


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
    destination_country: str | None = None
    breakdown: MoneyBreakdown
    documents: list[ComplianceDocumentItem] = Field(default_factory=list)
    blocking_issue: bool = False
    geo: dict | None = None
    data_quality: dict | None = None


class PaymentCompareScenarioItem(BaseModel):
    label: str
    delta_total_vs_first_rub: float | None = None
    profile: PaymentProfileResponse


class PaymentCompareResponse(BaseModel):
    status: str
    shared_economic: dict
    scenarios: list[PaymentCompareScenarioItem] = Field(default_factory=list)
