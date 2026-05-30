"""Схемы плана и dry-run отчёта ingestion официальных платёжных источников."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

IngestionProvenanceKind = Literal[
    "official",
    "seed",
    "fallback",
    "ambiguous",
    "missing",
    "commercial_mirror",
    "legacy_seed",
]

IngestionReadiness = Literal[
    "ready_to_ingest",
    "blocked",
    "manual_review_required",
    "missing_source",
    "not_applicable",
    "stub_only",
]

RowEstimateAction = Literal["insert", "update", "skip"]


class RowEstimate(BaseModel):
    action: RowEstimateAction
    count: int | None = None
    note: str | None = None


class PaymentSourceCandidate(BaseModel):
    source_code: str
    name: str
    domains: list[str] = Field(default_factory=list)
    provenance_kind: IngestionProvenanceKind
    authority_level: str | None = None
    official_url: str | None = None
    legal_basis: str | None = None
    local_paths_found: list[str] = Field(default_factory=list)
    source_status_revision: str | None = None
    source_status_stale: bool | None = None
    loader_status: str | None = None
    target_tables: list[str] = Field(default_factory=list)
    readiness: IngestionReadiness
    blockers: list[str] = Field(default_factory=list)
    manual_review_required: bool = False
    row_estimates: dict[str, RowEstimate] = Field(default_factory=dict)
    parser_result: dict[str, Any] = Field(default_factory=dict)


class PaymentDomainIngestionPlan(BaseModel):
    domain: str
    normalization_status: str | None = None
    coverage_status: str | None = None
    readiness: IngestionReadiness
    candidates: list[PaymentSourceCandidate] = Field(default_factory=list)
    affected_tables: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    manual_review_required: bool = False
    notes: list[str] = Field(default_factory=list)


class PaymentSourceIngestionPlanResponse(BaseModel):
    status: str = "OK"
    generated_at: str
    mode: Literal["plan", "dry_run"] = "plan"
    dry_run: bool = False
    db_mutated: bool = False
    overall_readiness: IngestionReadiness
    domains: dict[str, PaymentDomainIngestionPlan]
    registry_snapshot: list[dict[str, Any]] = Field(default_factory=list)
    normalization_link: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
