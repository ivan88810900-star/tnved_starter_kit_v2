"""ORM-модели слоя ведомственных документов."""
from __future__ import annotations

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
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
