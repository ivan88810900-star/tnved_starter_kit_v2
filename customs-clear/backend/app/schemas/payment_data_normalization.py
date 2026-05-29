"""Схемы отчёта нормализации платёжных источников (readiness / data-trust)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

PaymentNormalizationStatus = Literal[
    "present",
    "partial",
    "missing",
    "stale",
    "manual_review_required",
    "not_applicable",
    "not_configured",
]


class NormalizedSourceRef(BaseModel):
    """Локальная таблица или fixture — наличие и объём без claim полноты."""

    id: str
    label: str
    present: bool
    record_count: int | None = None
    mapped_hs_codes: int | None = None
    authority_level: str | None = None
    notes: list[str] = Field(default_factory=list)


class PaymentDomainNormalization(BaseModel):
    domain: str
    coverage_status: PaymentNormalizationStatus
    authority_level: str | None = None
    sources: list[NormalizedSourceRef] = Field(default_factory=list)
    record_count: int | None = None
    mapped_hs_codes: int | None = None
    total_catalog_codes: int | None = None
    missing_samples: list[str] = Field(default_factory=list)
    known_gaps: list[str] = Field(default_factory=list)
    manual_review_required: bool = False
    normalized_snapshot: dict[str, Any] = Field(default_factory=dict)


class PaymentDataNormalizationResponse(BaseModel):
    status: str = "OK"
    generated_at: str
    overall_readiness: PaymentNormalizationStatus
    domains: dict[str, PaymentDomainNormalization]
    notes: list[str] = Field(default_factory=list)
