from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Finance(BaseModel):
    duty_rate: str
    vat_rate: float
    excise: float


class AnalysisItem(BaseModel):
    name: str
    hs_code: str
    hs_code_view: str | None = None
    finance: Finance
    non_tariff_docs: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    opi_steps: list[str] = Field(default_factory=list)
    # Для фронта: новый агрегированный контракт платежей/комплаенса.
    payment_profile: dict[str, Any] | None = None


class AnalyzeInvoiceResponse(BaseModel):
    status: str
    mode: str
    items_count: int
    items: list[AnalysisItem] = Field(default_factory=list)
    warning: str | None = None
    source: str | None = None
