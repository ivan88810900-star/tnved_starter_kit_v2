"""Иерархия ТН ВЭД: раздел → группа (глава) → товарная позиция (для локальной нормативной БД и расчётов)."""

from __future__ import annotations

from typing import List

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base


class Section(Base):
    """Раздел номенклатуры (римский номер и заголовок)."""

    __tablename__ = "tnved_sections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    roman_number: Mapped[str] = mapped_column(String(16), index=True)
    title: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")

    chapters: Mapped[List["Chapter"]] = relationship(
        back_populates="section",
        cascade="all, delete-orphan",
        order_by="Chapter.code",
    )


class Chapter(Base):
    """Группа внутри раздела: код главы (2 знака) или товарной группы (4 знака), например «01» или «0101»."""

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
    code: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")

    section: Mapped["Section"] = relationship(back_populates="chapters")
    commodities: Mapped[List["Commodity"]] = relationship(
        back_populates="chapter",
        cascade="all, delete-orphan",
        order_by="Commodity.code",
    )


class Commodity(Base):
    """Товарная позиция / подсубпозиция: код без пробелов, описание, единица, ставка ввозной пошлины (текст)."""

    __tablename__ = "tnved_commodities"
    __table_args__ = (
        UniqueConstraint("chapter_id", "code", name="uq_tnved_commodities_chapter_code"),
        Index("ix_tnved_commodities_code", "code"),
        # Нужен для внешнего ключа hs_duty_rules.commodity_code -> tnved_commodities.code
        Index("uq_tnved_commodities_code", "code", unique=True),
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
    supp_unit: Mapped[str] = mapped_column(String(16), default="")
    weight_coeff: Mapped[float] = mapped_column(Float, default=0.0)

    chapter: Mapped["Chapter"] = relationship(back_populates="commodities")
    duty_rule: Mapped["HsDutyRule | None"] = relationship(
        back_populates="commodity",
        cascade="all, delete-orphan",
        uselist=False,
    )
    non_tariff_measures: Mapped[List["NonTariffMeasure"]] = relationship(
        back_populates="commodity",
        cascade="all, delete-orphan",
        order_by="NonTariffMeasure.id",
    )


class HsDutyRule(Base):
    """Структурированное правило ввозной пошлины для кода ТН ВЭД."""

    __tablename__ = "hs_duty_rules"
    __table_args__ = (
        Index("ix_hs_duty_rules_commodity_code", "commodity_code"),
        UniqueConstraint("commodity_code", name="uq_hs_duty_rules_commodity_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    commodity_code: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("tnved_commodities.code", ondelete="CASCADE"),
        nullable=False,
    )
    # ad_valorem | specific | combined_max | combined_min
    type: Mapped[str] = mapped_column(String(32), nullable=False, default="ad_valorem")
    ad_valorem_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    specific_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    specific_currency: Mapped[str] = mapped_column(String(8), default="")
    specific_uom: Mapped[str] = mapped_column(String(16), default="")

    commodity: Mapped["Commodity"] = relationship(back_populates="duty_rule")


class NonTariffMeasure(Base):
    """Нетарифные меры по коду ТН ВЭД: запреты, лицензии, сертификация, контроль."""

    __tablename__ = "non_tariff_measures"
    __table_args__ = (
        Index("ix_non_tariff_measures_commodity_code", "commodity_code"),
        Index("ix_non_tariff_measures_type", "measure_type"),
        UniqueConstraint(
            "commodity_code",
            "measure_type",
            "regulatory_act",
            name="uq_non_tariff_measures_code_type_act",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    commodity_code: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("tnved_commodities.code", ondelete="CASCADE"),
        nullable=False,
    )
    # ban | license | certificate | vet_control | phyto_control | tr_ts
    measure_type: Mapped[str] = mapped_column(String(32), nullable=False, default="certificate")
    description: Mapped[str] = mapped_column(Text, default="")
    document_required: Mapped[str] = mapped_column(String(255), default="")
    regulatory_act: Mapped[str] = mapped_column(String(255), default="")
    quality: Mapped[str] = mapped_column(String(16), nullable=False, default="normal")

    commodity: Mapped["Commodity"] = relationship(back_populates="non_tariff_measures")


class TroisRegistry(Base):
    """
    Плоский реестр записей ТРОИС с alta.ru/rois (наименование ОИС, правообладатель, рег. номер).
    Отдельно от :class:`IntellectualProperty` (привязка к префиксу ТН ВЭД в каталоге).
    """

    __tablename__ = "trois_registry"
    __table_args__ = (
        Index("ix_trois_registry_trademark", "trademark"),
        Index("ix_trois_registry_brand", "brand"),
        UniqueConstraint("reg_number", name="uq_trois_registry_reg_number"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    brand: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    trademark: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    right_holder: Mapped[str] = mapped_column(String(512), default="")
    reg_number: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(128), default="")
    valid_until: Mapped[str] = mapped_column(String(128), default="")
    representatives: Mapped[str] = mapped_column(Text, default="")


class IntellectualProperty(Base):
    """Записи ТРОИС: бренд, префикс ТН ВЭД, номер регистрации и правообладатель."""

    __tablename__ = "intellectual_properties"
    __table_args__ = (
        Index("ix_intellectual_properties_hs_prefix", "hs_code_prefix"),
        Index("ix_intellectual_properties_brand", "brand_name"),
        UniqueConstraint(
            "brand_name",
            "hs_code_prefix",
            "reg_number",
            name="uq_intellectual_properties_brand_prefix_reg",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    brand_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Допустимы префиксы 4 или 6 цифр.
    hs_code_prefix: Mapped[str] = mapped_column(String(6), nullable=False)
    reg_number: Mapped[str] = mapped_column(String(128), default="")
    right_holder: Mapped[str] = mapped_column(String(255), default="")


class SpecialDuty(Base):
    """Специальные пошлины: антидемпинговые, защитные, компенсационные."""

    __tablename__ = "special_duties"
    __table_args__ = (
        Index("ix_special_duties_hs_prefix", "hs_code_prefix"),
        Index("ix_special_duties_origin_country", "origin_country"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Префикс ТН ВЭД (обычно 4/6/10 знаков), только цифры.
    hs_code_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    # ISO-2 код страны происхождения (например, CN, MY).
    origin_country: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    # Адвалорная ставка спецпошлины в процентах.
    rate_percent: Mapped[float] = mapped_column(Float, default=0.0)
    # Специфическая ставка (если применима).
    rate_specific: Mapped[float] = mapped_column(Float, default=0.0)
    # Валюта специфической ставки (например, EUR, USD, RUB).
    currency_code: Mapped[str] = mapped_column(String(8), default="")
    # Нормативный акт.
    regulatory_act: Mapped[str] = mapped_column(String(255), default="")
    # anti_dumping | special_safeguard | special_protective | countervailing
    measure_type: Mapped[str] = mapped_column(String(32), default="anti_dumping")
    manufacturer_exporter: Mapped[str] = mapped_column(String(512), default="")
    product_description: Mapped[str] = mapped_column(Text, default="")
    effective_from: Mapped[str] = mapped_column(String(20), default="")
    effective_to: Mapped[str] = mapped_column(String(20), default="")
    # Row-level official anti-dumping provenance (отдельно от hs_rates / import-duty).
    source_code: Mapped[str] = mapped_column(String(50), default="")
    source_revision: Mapped[str] = mapped_column(String(128), default="")
    source_url: Mapped[str] = mapped_column(Text, default="")
    synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Row-level official special-safeguard provenance (изолировано от anti-dumping source_*).
    safeguard_source_code: Mapped[str] = mapped_column(String(50), default="")
    safeguard_source_revision: Mapped[str] = mapped_column(String(128), default="")
    safeguard_source_url: Mapped[str] = mapped_column(Text, default="")
    safeguard_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Row-level official countervailing provenance (изолировано от AD/safeguard/duty/VAT/excise).
    countervailing_source_code: Mapped[str] = mapped_column(String(50), default="")
    countervailing_source_revision: Mapped[str] = mapped_column(String(128), default="")
    countervailing_source_url: Mapped[str] = mapped_column(Text, default="")
    countervailing_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class VatPreference(Base):
    """Льготные ставки НДС по префиксам ТН ВЭД (например, ПП РФ № 908, № 688)."""

    __tablename__ = "vat_preferences"
    __table_args__ = (
        Index("ix_vat_preferences_hs_prefix", "hs_code_prefix"),
        Index("ix_vat_preferences_vat_rate", "vat_rate"),
        UniqueConstraint(
            "hs_code_prefix",
            "vat_rate",
            "decree_info",
            name="uq_vat_preferences_prefix_rate_decree",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hs_code_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    vat_rate: Mapped[int] = mapped_column(Integer, nullable=False, default=22)
    decree_info: Mapped[str] = mapped_column(String(255), default="")
    comment: Mapped[str] = mapped_column(Text, default="")


class CountryTariffPreference(Base):
    """Тарифные преференции по стране происхождения (коэффициент к базовой ставке пошлины)."""

    __tablename__ = "country_tariff_preferences"
    __table_args__ = (
        Index("ix_ctp_country_code", "country_code"),
        UniqueConstraint("country_code", name="uq_ctp_country_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    preference_type: Mapped[str] = mapped_column(String(20), nullable=False)
    duty_coefficient: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    legal_ref: Mapped[str] = mapped_column(String(255), default="")
    effective_from: Mapped[str] = mapped_column(String(20), default="")


class RecyclingFee(Base):
    """Утилизационный сбор на транспортные средства (ПП РФ №870)."""

    __tablename__ = "recycling_fees"
    __table_args__ = (
        Index("ix_recycling_fees_hs_prefix", "hs_prefix"),
        UniqueConstraint("hs_prefix", "vehicle_type", "is_new", name="uq_recycling_fees"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hs_prefix: Mapped[str] = mapped_column(String(10), nullable=False)
    vehicle_type: Mapped[str] = mapped_column(String(50), nullable=False)
    is_new: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    base_rate: Mapped[float] = mapped_column(Float, nullable=False, default=20000.0)
    coefficient: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    engine_volume_from: Mapped[int | None] = mapped_column(Integer, nullable=True)
    engine_volume_to: Mapped[int | None] = mapped_column(Integer, nullable=True)
    description: Mapped[str] = mapped_column(String(255), default="")
    legal_ref: Mapped[str] = mapped_column(String(255), default="")


class ImportRestriction(Base):
    """Запреты и ограничения на ввоз: санкции, эмбарго, квоты, dual-use."""

    __tablename__ = "import_restrictions"
    __table_args__ = (
        Index("ix_import_restrictions_hs", "hs_prefix"),
        Index("ix_import_restrictions_type", "restriction_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hs_prefix: Mapped[str] = mapped_column(String(10), nullable=False)
    restriction_type: Mapped[str] = mapped_column(String(30), nullable=False)
    country_code: Mapped[str] = mapped_column(String(10), nullable=False, default="ALL")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    legal_ref: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    effective_from: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    effective_to: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="warning")
    source_url: Mapped[str] = mapped_column(String(512), nullable=False, default="")


class DeclarationDocument(Base):
    """Требуемые документы для таможенного декларирования по коду ТН ВЭД."""

    __tablename__ = "declaration_documents"
    __table_args__ = (
        Index("ix_declaration_documents_hs", "hs_prefix"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hs_prefix: Mapped[str] = mapped_column(String(10), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(50), nullable=False)
    doc_name: Mapped[str] = mapped_column(String(512), nullable=False)
    is_mandatory: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    condition: Mapped[str] = mapped_column(Text, nullable=False, default="")
    legal_ref: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    category: Mapped[str] = mapped_column(String(50), nullable=False, default="general")


class CustomsProcedure(Base):
    """Таможенные процедуры и режимы (ИМ40, ЭК10, ТТ80 и др.)."""

    __tablename__ = "customs_procedures"
    __table_args__ = (
        Index("ix_customs_procedures_code", "procedure_code"),
        UniqueConstraint("procedure_code", name="uq_customs_procedures_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    procedure_code: Mapped[str] = mapped_column(String(10), nullable=False)
    name_ru: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    direction: Mapped[str] = mapped_column(String(10), nullable=False, default="import")
    description: Mapped[str] = mapped_column(Text, default="")
    legal_ref: Mapped[str] = mapped_column(String(255), default="")
    duty_applies: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    vat_applies: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    excise_applies: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    customs_fee_applies: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    time_limit_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    documents_required: Mapped[str] = mapped_column(Text, default="")
    conditions: Mapped[str] = mapped_column(Text, default="")
    hs_restrictions: Mapped[str] = mapped_column(Text, default="")


class TamdocSyncCandidate(Base):
    """Staging-кандидаты из tamdoc до ручного подтверждения/апрува."""

    __tablename__ = "tamdoc_sync_candidates"
    __table_args__ = (
        Index("ix_tamdoc_candidates_doc_url", "doc_url"),
        Index("ix_tamdoc_candidates_status", "status"),
        Index("ix_tamdoc_candidates_hs_prefix", "hs_prefix"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    doc_url: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    doc_title: Mapped[str] = mapped_column(String(255), default="")
    doc_type: Mapped[str] = mapped_column(String(32), default="other")
    status: Mapped[str] = mapped_column(String(32), default="pending")
    hs_prefix: Mapped[str] = mapped_column(String(16), default="")
    country_codes: Mapped[str] = mapped_column(String(128), default="")
    vat_rates: Mapped[str] = mapped_column(String(32), default="")
    percent_rates: Mapped[str] = mapped_column(String(64), default="")
    measure_type_hint: Mapped[str] = mapped_column(String(32), default="other")
    excerpt: Mapped[str] = mapped_column(Text, default="")
    error_message: Mapped[str] = mapped_column(String(512), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )
