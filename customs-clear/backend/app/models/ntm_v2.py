"""NTM v2: меры и правила применимости (параллельный контур, не смешивать с legacy ORM)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..datetime_util import utc_now_naive
from ..db import Base


class NtmMeasureV2(Base):
    """Атомарная нетарифная мера (v2)."""

    __tablename__ = "ntm_measures_v2"
    __table_args__ = (
        UniqueConstraint("import_key", name="uq_ntm_measures_v2_import_key"),
        Index("ix_ntm_measures_v2_permit_type", "permit_type"),
        Index("ix_ntm_measures_v2_measure_kind", "measure_kind"),
        Index("ix_ntm_measures_v2_tr_ts_act_code", "tr_ts_act_code"),
        Index("ix_ntm_measures_v2_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    measure_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    permit_type: Mapped[str] = mapped_column(String(8), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    short_description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tr_ts_act_code: Mapped[str] = mapped_column(String(32), nullable=False)
    regulatory_document_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    valid_from: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    valid_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    source_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    source_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    import_key: Mapped[str] = mapped_column(String(192), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive, onupdate=utc_now_naive)

    applicability_rules: Mapped[list["NtmApplicabilityRuleV2"]] = relationship(
        "NtmApplicabilityRuleV2",
        back_populates="measure",
        cascade="all, delete-orphan",
    )


class NtmApplicabilityRuleV2(Base):
    """Правило применимости меры (v2)."""

    __tablename__ = "ntm_applicability_rules_v2"
    __table_args__ = (
        UniqueConstraint("rule_import_key", name="uq_ntm_applicability_rules_v2_rule_import_key"),
        Index("ix_ntm_applicability_rules_v2_measure_id", "measure_id"),
        Index("ix_ntm_applicability_rules_v2_hs_code", "hs_code"),
        Index("ix_ntm_applicability_rules_v2_hs_scope_hs", "hs_scope_mode", "hs_code"),
        Index("ix_ntm_applicability_rules_v2_direction", "direction"),
        Index("ix_ntm_applicability_rules_v2_valid_from", "valid_from"),
        Index("ix_ntm_applicability_rules_v2_valid_to", "valid_to"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    measure_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("ntm_measures_v2.id", ondelete="CASCADE"),
        nullable=False,
    )
    direction: Mapped[str] = mapped_column(String(16), nullable=False, default="import")
    country_iso: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    hs_scope_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="prefix")
    hs_code: Mapped[str] = mapped_column(String(16), nullable=False)
    excluded_hs_json: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    description_match_json: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    applicability: Mapped[str] = mapped_column(String(32), nullable=False, default="definite")
    requires_manual_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    valid_from: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    valid_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    source_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    source_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    rule_import_key: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive, onupdate=utc_now_naive)

    measure: Mapped["NtmMeasureV2"] = relationship("NtmMeasureV2", back_populates="applicability_rules")
