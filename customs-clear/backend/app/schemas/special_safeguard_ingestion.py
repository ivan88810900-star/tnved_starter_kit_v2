"""Схемы dry-run / apply ingestion официальных специальных защитных пошлин ЕЭК."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

SpecialSafeguardIngestionStatus = Literal[
    "OK",
    "blocked",
    "manual_review_required",
    "missing_official_source",
    "parser_failed",
]


class SpecialSafeguardRowCounts(BaseModel):
    insert: int = 0
    update: int = 0
    skip: int = 0
    blocked: int = 0
    total_in_source: int = 0


class SpecialSafeguardProvenance(BaseModel):
    source_code: str
    source_name: str
    legal_basis: str | None = None
    official_url: str | None = None
    revision: str | None = None
    checksum_sha256: str | None = None
    effective_from: str | None = None
    effective_to: str | None = None
    loaded_at: str | None = None
    local_path: str | None = None


class SpecialSafeguardIngestionResponse(BaseModel):
    status: SpecialSafeguardIngestionStatus
    mode: Literal["dry_run", "apply"] = "dry_run"
    dry_run: bool = True
    db_mutated: bool = False
    provenance: SpecialSafeguardProvenance | None = None
    row_counts: SpecialSafeguardRowCounts = Field(default_factory=SpecialSafeguardRowCounts)
    blockers: list[str] = Field(default_factory=list)
    parser_result: dict[str, Any] = Field(default_factory=dict)
    coverage_link: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
