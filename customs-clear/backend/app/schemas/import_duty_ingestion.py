"""Схемы dry-run / apply ingestion официальных import-duty ставок ЕТТ ЕАЭС."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ImportDutyIngestionStatus = Literal[
    "OK",
    "blocked",
    "manual_review_required",
    "missing_official_source",
    "parser_failed",
]


class ImportDutyRowCounts(BaseModel):
    insert: int = 0
    update: int = 0
    skip: int = 0
    blocked: int = 0
    total_in_source: int = 0


class ImportDutyProvenance(BaseModel):
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


class ImportDutyIngestionResponse(BaseModel):
    status: ImportDutyIngestionStatus
    mode: Literal["dry_run", "apply"] = "dry_run"
    dry_run: bool = True
    db_mutated: bool = False
    provenance: ImportDutyProvenance | None = None
    row_counts: ImportDutyRowCounts = Field(default_factory=ImportDutyRowCounts)
    blockers: list[str] = Field(default_factory=list)
    parser_result: dict[str, Any] = Field(default_factory=dict)
    coverage_link: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
