"""Versioned ETT candidates. No row in these tables authorizes active rates."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, ForeignKeyConstraint, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from ..datetime_util import utc_now_naive


class ETTSnapshot(Base):
    __tablename__ = "ett_snapshots"
    __table_args__ = (
        CheckConstraint("length(manifest_sha256) = 64", name="ck_ett_snapshot_digest"),
        CheckConstraint("coverage_from < coverage_to", name="ck_ett_snapshot_dates"),
        CheckConstraint("status = 'candidate'", name="ck_ett_snapshot_candidate_only"),
        CheckConstraint("storage_kind = 'local_development'", name="ck_ett_snapshot_local_only"),
    )
    manifest_sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    coverage_from: Mapped[date] = mapped_column(Date, nullable=False)
    coverage_to: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="candidate")
    storage_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="local_development")
    manifest_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    staged_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now_naive)


class ETTArtifact(Base):
    __tablename__ = "ett_artifacts"
    snapshot_sha256: Mapped[str] = mapped_column(String(64), ForeignKey("ett_snapshots.manifest_sha256"), primary_key=True)
    artifact_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class ETTCodeVersion(Base):
    __tablename__ = "ett_code_versions"
    __table_args__ = (CheckConstraint("length(code) = 10", name="ck_ett_code_length"),)
    snapshot_sha256: Mapped[str] = mapped_column(String(64), ForeignKey("ett_snapshots.manifest_sha256"), primary_key=True)
    code: Mapped[str] = mapped_column(String(10), primary_key=True)
    valid_from: Mapped[date] = mapped_column(Date, primary_key=True)
    valid_to: Mapped[date] = mapped_column(Date, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class ETTFootnote(Base):
    __tablename__ = "ett_footnotes"
    snapshot_sha256: Mapped[str] = mapped_column(String(64), ForeignKey("ett_snapshots.manifest_sha256"), primary_key=True)
    footnote_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class ETTRateRule(Base):
    __tablename__ = "ett_rate_rules"
    __table_args__ = (
        ForeignKeyConstraint(["snapshot_sha256", "code", "code_valid_from"], ["ett_code_versions.snapshot_sha256", "ett_code_versions.code", "ett_code_versions.valid_from"]),
        CheckConstraint("valid_from < valid_to", name="ck_ett_rule_dates"),
    )
    snapshot_sha256: Mapped[str] = mapped_column(String(64), ForeignKey("ett_snapshots.manifest_sha256"), primary_key=True)
    rule_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    code: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    code_valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date] = mapped_column(Date, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
