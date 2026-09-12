"""Схемы продуктового блока санкций и рисков (MVP)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .tnved_catalog import CanonicalAnchorOut

RiskSeverity = Literal[
    "clear",
    "low",
    "medium",
    "high",
    "unknown",
    "manual_review_required",
]

RiskBlockStatus = Literal["OK", "WARNING", "CRITICAL", "MANUAL_REVIEW"]
RiskScopeStatus = Literal["checked", "not_checked"]
MovementDirection = Literal["import", "export", "transit"]


class RiskCheckRequest(BaseModel):
    hs_code: str
    description: str = ""
    country: str | None = None
    destination_country: str | None = None
    counterparty_name: str | None = None
    movement_direction: MovementDirection = "import"


class RiskSignalOut(BaseModel):
    category: str
    severity: RiskSeverity
    source: str
    source_label: str
    source_url: str | None = None
    authority_level: str | None = None
    matched_entity: str | None = None
    matched_hs_prefix: str | None = None
    matched_country: str | None = None
    match_method: str | None = None
    explanation: str
    legal_ref: str | None = None


class SourceCoverageOut(BaseModel):
    source_id: str
    title: str
    coverage_status: str
    record_count: int | None = None
    manual_review_required: bool = False
    authority_level: str | None = None
    source_url: str | None = None
    known_gaps: list[str] = Field(default_factory=list)


class RiskCheckScopeOut(BaseModel):
    code: Literal["hs_code", "country", "counterparty"]
    label: str
    status: RiskScopeStatus
    value: str | None = None
    explanation: str = ""


class SanctionsRiskBlockOut(BaseModel):
    status: RiskBlockStatus = "OK"
    overall_severity: RiskSeverity = "unknown"
    hs_code: str = ""
    description: str = ""
    country: str | None = None
    destination_country: str | None = None
    counterparty_name: str | None = None
    movement_direction: MovementDirection = "import"
    signals: list[RiskSignalOut] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    source_coverage: list[SourceCoverageOut] = Field(default_factory=list)
    screening_scope: list[RiskCheckScopeOut] = Field(default_factory=list)
    coverage_complete: bool = False
    empty_message: str | None = None
    canonical_anchor: CanonicalAnchorOut | None = Field(
        default=None,
        description="Устойчивая ссылка на Canonical TN VED node для AI/RAG grounding.",
    )
    disclaimer: str = (
        "Диагностическая проверка по локальным источникам платформы. "
        "Не заменяет полноценный санкционный скрининг и юридическую экспертизу."
    )


class RiskCheckBatchRequest(BaseModel):
    items: list[RiskCheckRequest] = Field(default_factory=list)


class RiskCheckBatchResponse(BaseModel):
    status: RiskBlockStatus
    items: list[SanctionsRiskBlockOut] = Field(default_factory=list)
