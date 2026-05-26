"""Схемы продуктового блока санкций и рисков (MVP)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

RiskSeverity = Literal[
    "clear",
    "low",
    "medium",
    "high",
    "unknown",
    "manual_review_required",
]

RiskBlockStatus = Literal["OK", "WARNING", "CRITICAL", "MANUAL_REVIEW"]


class RiskCheckRequest(BaseModel):
    hs_code: str
    description: str = ""
    country: str | None = None
    destination_country: str | None = None
    counterparty_name: str | None = None


class RiskSignalOut(BaseModel):
    category: str
    severity: RiskSeverity
    source: str
    source_label: str
    authority_level: str | None = None
    matched_entity: str | None = None
    matched_hs_prefix: str | None = None
    explanation: str
    legal_ref: str | None = None


class SourceCoverageOut(BaseModel):
    source_id: str
    title: str
    coverage_status: str
    record_count: int | None = None
    manual_review_required: bool = False
    authority_level: str | None = None


class SanctionsRiskBlockOut(BaseModel):
    status: RiskBlockStatus = "OK"
    overall_severity: RiskSeverity = "unknown"
    hs_code: str = ""
    description: str = ""
    country: str | None = None
    destination_country: str | None = None
    counterparty_name: str | None = None
    signals: list[RiskSignalOut] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    source_coverage: list[SourceCoverageOut] = Field(default_factory=list)
    coverage_complete: bool = False
    empty_message: str | None = None
    disclaimer: str = (
        "Диагностическая проверка по локальным источникам платформы. "
        "Не заменяет полноценный санкционный скрининг и юридическую экспертизу."
    )


class RiskCheckBatchRequest(BaseModel):
    items: list[RiskCheckRequest] = Field(default_factory=list)


class RiskCheckBatchResponse(BaseModel):
    status: RiskBlockStatus
    items: list[SanctionsRiskBlockOut] = Field(default_factory=list)
