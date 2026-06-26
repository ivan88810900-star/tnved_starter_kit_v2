"""Иерархия официального Таможенного тарифа ЕАЭС: раздел → группа → товарная позиция."""

from __future__ import annotations

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base


class Section(Base):
    """Раздел (римский номер, заголовок, примечания)."""

    __tablename__ = "tnved_sections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    roman_number: Mapped[str] = mapped_column(String(16), index=True)
    title: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")

    chapters: Mapped[list["Chapter"]] = relationship(
        back_populates="section",
        cascade="all, delete-orphan",
        order_by="Chapter.code",
    )


class Chapter(Base):
    """Группа (двухзначный код внутри раздела)."""

    __tablename__ = "tnved_chapters"
    __table_args__ = (
        UniqueConstraint("section_id", "code", name="uq_tnved_chapters_section_code"),
        Index("ix_tnved_chapters_code", "code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    section_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("tnved_sections.id", ondelete="CASCADE"),
        index=True,
    )
    code: Mapped[str] = mapped_column(String(2), nullable=False)
    title: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")

    section: Mapped["Section"] = relationship(back_populates="chapters")
    commodities: Mapped[list["Commodity"]] = relationship(
        back_populates="chapter",
        cascade="all, delete-orphan",
        order_by="Commodity.code",
    )


class Commodity(Base):
    """Товарная позиция (4 знака) или подсубпозиция (10 знаков)."""

    __tablename__ = "tnved_commodities"
    __table_args__ = (
        UniqueConstraint("chapter_id", "code", name="uq_tnved_commodities_chapter_code"),
        Index("ix_tnved_commodities_code", "code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chapter_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("tnved_chapters.id", ondelete="CASCADE"),
        index=True,
    )
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    unit: Mapped[str] = mapped_column(String(64), default="")
    import_duty: Mapped[str] = mapped_column(Text, default="")

    chapter: Mapped["Chapter"] = relationship(back_populates="commodities")
