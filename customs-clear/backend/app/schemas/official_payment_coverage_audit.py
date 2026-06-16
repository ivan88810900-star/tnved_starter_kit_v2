"""Схемы read-only аудита покрытия официальных платёжных контуров."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

CoverageAuditStatus = Literal[
    "present",
    "partial",
    "missing",
    "stale",
    "manual_review_required",
    "parser_failed",
    "not_configured",
]

BackfillSituation = Literal[
    "run_apply",
    "acquire_official_source",
    "reapply_official_bundle",
    "refresh_official_source",
    "manual_review_required",
    "none",
]


class OfficialPaymentDomainAudit(BaseModel):
    domain: str
    domain_key: str
    expected_official_source: str | None = None
    configured_official_source: str | None = None
    local_bundle_present: bool = False
    local_bundle_path: str | None = None
    source_revision: str | None = None
    source_url: str | None = None
    row_count: int = 0
    official_row_count: int = 0
    legacy_row_count: int = 0
    parsed_rows: int = 0
    missing_source: bool = False
    parser_failed: bool = False
    manual_review_required: bool = False
    source_present_but_not_applied: bool = False
    stale_source_status: bool = False
    unsafe_revision: bool = False
    unsafe_url: bool = False
    partial_rows: bool = False
    domain_unsupported: bool = False
    coverage_status: CoverageAuditStatus
    known_gaps: list[str] = Field(default_factory=list)
    recommended_next_action: BackfillSituation
    backfill_situation: BackfillSituation
    backfill_notes: list[str] = Field(default_factory=list)
    countervailing_source_url: str | None = None
    countervailing_synced_at: str | None = None


class OfficialPaymentCoverageAuditResponse(BaseModel):
    status: str = "OK"
    generated_at: str
    db_mutated: bool = False
    domains: list[OfficialPaymentDomainAudit]
    summary: dict[str, Any] = Field(default_factory=dict)
    trade_remedies_aggregate: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
