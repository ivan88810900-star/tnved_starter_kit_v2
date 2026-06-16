"""Схемы аудита покрытия официальных платёжных/remedy доменов (issue #51)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

OfficialCoverageStatus = Literal[
    "missing",
    "partial",
    "present",
    "stale",
    "parser_failed",
    "not_configured",
    "manual_review_required",
    "incomplete",
]

BackfillRecommendation = Literal[
    "run_apply",
    "acquire_official_source",
    "reapply_official_bundle",
    "refresh_official_source",
    "manual_review_required",
    "none",
]

BackfillSituation = Literal[
    "missing_official_source",
    "official_source_present_not_applied",
    "applied_no_row_provenance",
    "stale_source_status",
    "unsafe_revision",
    "unsafe_url",
    "parser_failure",
    "partial_rows",
    "domain_unsupported",
    "completeness_not_verified",
    "ok",
]


class OfficialDomainCoverageAudit(BaseModel):
    """Machine-readable аудит одного официального домена."""

    domain: str
    domain_key: str
    expected_official_source: str
    configured_official_source: bool = False
    local_bundle_present: bool = False
    local_bundle_path: str | None = None
    source_revision: str | None = None
    source_url: str | None = None
    row_count: int = 0
    official_row_count: int = 0
    legacy_row_count: int = 0
    parsed_rows: int | None = None
    missing_source: bool = False
    parser_failed: bool = False
    manual_review_required: bool = True
    source_present_but_not_applied: bool = False
    stale_source_status: bool = False
    unsafe_revision: bool = False
    unsafe_url: bool = False
    partial_rows: bool = False
    domain_unsupported: bool = False
    coverage_status: OfficialCoverageStatus = "missing"
    known_gaps: list[str] = Field(default_factory=list)
    recommended_next_action: BackfillRecommendation = "manual_review_required"
    backfill_situation: BackfillSituation = "missing_official_source"
    backfill_notes: list[str] = Field(default_factory=list)


class OfficialPaymentCoverageAuditResponse(BaseModel):
    status: str = "OK"
    generated_at: str
    db_mutated: bool = False
    domains: list[OfficialDomainCoverageAudit] = Field(default_factory=list)
    summary: dict[str, OfficialDomainCoverageAudit] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
