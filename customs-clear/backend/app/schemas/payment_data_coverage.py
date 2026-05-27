"""Схемы отчёта диагностики покрытия ТН ВЭД и платёжных данных."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

PaymentCoverageStatus = Literal[
    "present",
    "partial",
    "missing",
    "stale",
    "parser_failed",
    "not_configured",
    "manual_review_required",
]


class CoverageDomainSummary(BaseModel):
    status: PaymentCoverageStatus
    count: int | None = None
    covered_codes: int | None = None
    total_codes: int | None = None
    manual_review_required: bool = False
    source_label: str | None = None
    authority_level: str | None = None
    last_successful_sync_at: str | None = None
    gaps: list[str] = Field(default_factory=list)
    missing_samples: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class TnvedTreeCoverage(BaseModel):
    status: PaymentCoverageStatus
    sections: int = 0
    chapters: int = 0
    headings: int = 0
    subheadings: int = 0
    full_codes: int = 0
    catalog_commodities: int = 0
    flat_entries: int = 0
    manual_review_required: bool = False
    source_label: str | None = None
    gaps: list[str] = Field(default_factory=list)
    missing_samples: list[str] = Field(default_factory=list)


class SmartPaymentsReadiness(BaseModel):
    status: PaymentCoverageStatus
    can_produce_final_total: bool = False
    can_produce_estimate: bool = False
    blocking_domains: list[str] = Field(default_factory=list)
    manual_review_domains: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class PaymentDataCoverageResponse(BaseModel):
    status: str = "OK"
    generated_at: str
    summary: dict[str, CoverageDomainSummary | TnvedTreeCoverage | SmartPaymentsReadiness]
    smart_payments: SmartPaymentsReadiness
    next_actions: list[str] = Field(default_factory=list)
