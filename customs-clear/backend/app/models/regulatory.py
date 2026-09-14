"""ORM-модели слоя ведомственных документов."""
from __future__ import annotations

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import relationship

from ..db import Base


class RegulatoryDocument(Base):
    __tablename__ = "regulatory_documents"

    id = Column(String(64), primary_key=True)
    agency = Column(String(64), nullable=False, index=True)
    doc_type = Column(String(64), nullable=False, index=True)
    doc_number = Column(String(256))
    doc_date = Column(Date)
    title = Column(Text, nullable=False)
    summary = Column(Text)
    body = Column(Text)
    source_url = Column(String(2048), nullable=False, unique=True)
    source_html_path = Column(String(1024))
    source_pdf_path = Column(String(1024))
    language = Column(String(16), default="ru")
    status = Column(String(32), default="active", index=True)
    supersedes_doc_id = Column(String(64))
    effective_from = Column(Date)
    effective_to = Column(Date)
    topic_tags = Column(JSON)
    ai_extracted = Column(JSON)
    quality = Column(String(32), default="normal")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    mappings = relationship(
        "RegulatoryDocHsMapping",
        back_populates="document",
        cascade="all, delete-orphan",
    )


class RegulatoryDocHsMapping(Base):
    __tablename__ = "regulatory_doc_hs_mapping"

    id = Column(Integer, primary_key=True, autoincrement=True)
    doc_id = Column(String(64), ForeignKey("regulatory_documents.id", ondelete="CASCADE"), nullable=False)
    hs_prefix = Column(String(16), nullable=False, index=True)
    scope = Column(String(32), default="import")
    relevance = Column(String(32), default="direct")
    confidence = Column(Float, default=1.0)
    source = Column(String(32), default="ai")
    note = Column(Text)
    approved = Column(Boolean, default=False)
    approved_by = Column(String(128))
    approved_at = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now())

    document = relationship("RegulatoryDocument", back_populates="mappings")


class RegulatorySyncLog(Base):
    __tablename__ = "regulatory_sync_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agency = Column(String(64), nullable=False)
    source_url = Column(String(2048))
    started_at = Column(DateTime, server_default=func.now())
    finished_at = Column(DateTime)
    status = Column(String(64))
    docs_added = Column(Integer, default=0)
    docs_updated = Column(Integer, default=0)
    docs_skipped = Column(Integer, default=0)
    error_message = Column(Text)


class RegulatorySourceReview(Base):
    """Durable monthly review item for a curated regulatory source.

    A source has at most one pending item. Evidence is immutable: a changed
    pending row becomes ``superseded`` and points to a strictly newer checked-in
    generation/digest; resolved rows retain their resolution and may receive the
    same explicit supersession annotation.
    """

    __tablename__ = "regulatory_source_reviews"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'resolved', 'superseded')",
            name="ck_regulatory_source_reviews_status",
        ),
        CheckConstraint(
            "occurrence_count >= 1",
            name="ck_regulatory_source_reviews_occurrence_count",
        ),
        CheckConstraint(
            "length(evidence_sha256) = 64",
            name="ck_regulatory_source_reviews_evidence_sha256",
        ),
        CheckConstraint(
            "evidence_generation >= 1",
            name="ck_regulatory_source_reviews_evidence_generation",
        ),
        CheckConstraint(
            "(status = 'pending' AND resolved_at IS NULL "
            "AND resolved_by = '' AND asserted_by = '' AND resolution_ref = '' "
            "AND superseded_at IS NULL AND superseded_by_evidence_sha256 = '' "
            "AND superseded_by_generation IS NULL) "
            "OR (status = 'resolved' AND resolved_at IS NOT NULL "
            "AND length(trim(resolved_by)) > 0 "
            "AND length(trim(asserted_by)) > 0 "
            "AND length(trim(resolution_ref)) > 0 "
            "AND ((superseded_at IS NULL AND superseded_by_evidence_sha256 = '' "
            "AND superseded_by_generation IS NULL) "
            "OR (superseded_at IS NOT NULL "
            "AND length(superseded_by_evidence_sha256) = 64 "
            "AND superseded_by_evidence_sha256 <> evidence_sha256 "
            "AND superseded_by_generation IS NOT NULL "
            "AND superseded_by_generation > evidence_generation))) "
            "OR (status = 'superseded' AND resolved_at IS NULL "
            "AND resolved_by = '' AND asserted_by = '' AND resolution_ref = '' "
            "AND superseded_at IS NOT NULL "
            "AND length(superseded_by_evidence_sha256) = 64 "
            "AND superseded_by_evidence_sha256 <> evidence_sha256 "
            "AND superseded_by_generation IS NOT NULL "
            "AND superseded_by_generation > evidence_generation)",
            name="ck_regulatory_source_reviews_resolution_state",
        ),
        Index(
            "uq_regulatory_source_reviews_one_pending_source",
            "source_id",
            unique=True,
            sqlite_where=text("status = 'pending'"),
            postgresql_where=text("status = 'pending'"),
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_id = Column(String(128), nullable=False, index=True)
    due_period = Column(String(7), nullable=False, index=True)
    strategy = Column(String(32), nullable=False, default="local_reconcile")
    cadence = Column(String(16), nullable=False, default="monthly")
    status = Column(String(16), nullable=False, default="pending", index=True)
    reason = Column(Text, nullable=False, default="")
    evidence_sha256 = Column(String(64), nullable=False)
    evidence_generation = Column(Integer, nullable=False)
    evidence_scope = Column(String(64), nullable=False)
    evidence_manifest = Column(JSON, nullable=False)
    first_raised_at = Column(DateTime, nullable=False, server_default=func.now())
    last_raised_at = Column(DateTime, nullable=False, server_default=func.now())
    occurrence_count = Column(Integer, nullable=False, default=1)
    resolved_at = Column(DateTime)
    resolved_by = Column(String(128), nullable=False, default="")
    asserted_by = Column(String(128), nullable=False, default="")
    resolution_ref = Column(String(2048), nullable=False, default="")
    superseded_at = Column(DateTime)
    superseded_by_evidence_sha256 = Column(String(64), nullable=False, default="")
    superseded_by_generation = Column(Integer)
