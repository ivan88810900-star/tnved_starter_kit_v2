"""ROP eco fee tables: official PP 1041 / PP 2414 rates."""

from __future__ import annotations

from sqlalchemy import Boolean, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class RopGoodsRate(Base):
    """Ставки РОП на товары (группы 1–16 ПП №2414)."""

    __tablename__ = "rop_goods_rates"
    __table_args__ = (
        UniqueConstraint("pp2414_group", "calendar_year", name="uq_rop_goods_group_year"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category_code: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    pp2414_group: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    category_name: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    hs_prefixes_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    base_rate_per_ton: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    ke_coefficient: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    rate_per_ton: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    recycling_norm: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    calendar_year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    legal_ref: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    needs_verification: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class RopPackagingRate(Base):
    """Ставки РОП на упаковку (группы 17–52 ПП №2414)."""

    __tablename__ = "rop_packaging_rates"
    __table_args__ = (
        UniqueConstraint("pp2414_group", "calendar_year", name="uq_rop_packaging_group_year"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category_code: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    pp2414_group: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    category_name: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    packaging_type: Mapped[str] = mapped_column(String(32), nullable=False, default="", index=True)
    base_rate_per_ton: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    ke_coefficient: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    rate_per_ton: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    recycling_norm: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    calendar_year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    legal_ref: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    needs_verification: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class RopPackagingDefault(Base):
    """Правила определения типа упаковки по префиксу ТН ВЭД."""

    __tablename__ = "rop_packaging_defaults"
    __table_args__ = (
        UniqueConstraint("hs_prefix", name="uq_rop_packaging_defaults_prefix"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hs_prefix: Mapped[str] = mapped_column(String(16), nullable=False, default="", index=True)
    packaging_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    pp2414_group: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_default_rule: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
