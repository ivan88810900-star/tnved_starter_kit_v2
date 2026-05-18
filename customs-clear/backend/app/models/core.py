from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, List, Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..datetime_util import utc_now_naive
from ..db import Base


def _new_doc_id() -> str:
    return str(uuid.uuid4())


def _new_calc_id() -> str:
    return str(uuid.uuid4())


class SourceStatus(Base):
    __tablename__ = "source_status"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    source_name: Mapped[str] = mapped_column(String(255))
    source_url: Mapped[str] = mapped_column(Text)
    revision: Mapped[str] = mapped_column(String(128), default="unknown")
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)
    is_stale: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str] = mapped_column(Text, default="")


class HsRate(Base):
    __tablename__ = "hs_rates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hs_code: Mapped[str] = mapped_column(String(10), index=True)
    hs_prefix: Mapped[str] = mapped_column(String(10), index=True)
    duty_rate: Mapped[str] = mapped_column(String(2048), nullable=False, default="0", server_default="0")
    vat_import_rate: Mapped[float] = mapped_column(Float, default=22.0)
    # vat_rule: none | reduced10 | zero | exempt
    vat_rule: Mapped[str] = mapped_column(String(20), default="none")
    vat_rule_basis: Mapped[str] = mapped_column(Text, default="")
    excise_type: Mapped[str] = mapped_column(String(20), default="none")  # none|percent|fixed
    excise_value: Mapped[float] = mapped_column(Float, default=0.0)
    excise_basis: Mapped[str] = mapped_column(Text, default="")
    has_antidumping: Mapped[bool] = mapped_column(Boolean, default=False)
    antidumping_type: Mapped[str] = mapped_column(String(20), default="none")  # none|percent|fixed
    antidumping_value: Mapped[float] = mapped_column(Float, default=0.0)
    antidumping_condition: Mapped[str] = mapped_column(Text, default="")
    antidumping_countries: Mapped[str] = mapped_column(Text, default="")
    valid_from: Mapped[str] = mapped_column(String(20), default="")
    valid_to: Mapped[str] = mapped_column(String(20), default="")
    source_url: Mapped[str] = mapped_column(Text, default="")
    source_revision: Mapped[str] = mapped_column(String(128), default="seed")


class ExchangeRate(Base):
    """Актуальные курсы валют ЦБ РФ для пересчета в рубли."""

    __tablename__ = "exchange_rates"
    __table_args__ = (
        Index("ix_exchange_rates_currency_code", "currency_code", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    currency_code: Mapped[str] = mapped_column(String(8), nullable=False)
    rate: Mapped[float] = mapped_column(Float, default=0.0)  # RUB per 1 unit
    nominal: Mapped[float] = mapped_column(Float, default=1.0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive, index=True)


class NonTariffRule(Base):
    """Нетарифные требования по диапазонам ТН ВЭД (ТР ТС, разрешительные документы)."""
    __tablename__ = "non_tariff_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255))
    hs_prefix: Mapped[str] = mapped_column(String(10), index=True)
    # comma-separated lists
    tr_ts: Mapped[str] = mapped_column(Text, default="")
    required_permits: Mapped[str] = mapped_column(Text, default="")
    # редакция ТР ТС / решение ЕЭК (текст для справки)
    tr_ts_edition: Mapped[str] = mapped_column(String(512), default="")
    # исключения, оговорки (не освобождает от проверки документов)
    exception_note: Mapped[str] = mapped_column(Text, default="")
    # больше = выше в списке применённых правил
    priority: Mapped[int] = mapped_column(Integer, default=0)
    valid_from: Mapped[str] = mapped_column(String(20), default="")
    valid_to: Mapped[str] = mapped_column(String(20), default="")
    source_url: Mapped[str] = mapped_column(Text, default="")
    source_revision: Mapped[str] = mapped_column(String(128), default="seed")


class SyncLog(Base):
    """Журнал синхронизаций нормативных источников."""
    __tablename__ = "sync_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_code: Mapped[str] = mapped_column(String(50), index=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)
    status: Mapped[str] = mapped_column(String(20), default="OK")
    revision: Mapped[str] = mapped_column(String(128), default="")
    rows_affected: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str] = mapped_column(Text, default="")


class RegulatorySyncState(Base):
    """Одна строка состояния фоновой синхронизации нормативки (последний прогон)."""

    __tablename__ = "regulatory_sync_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # всегда 1
    last_completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_trigger: Mapped[str] = mapped_column(String(32), default="")  # scheduled | manual
    last_error: Mapped[str] = mapped_column(Text, default="")
    rows_upserted: Mapped[int] = mapped_column(Integer, default=0)


class RegulatoryAiExtract(Base):
    """Правила, извлечённые LLM из текста актов (UPSERT по паре документ + код + тип меры)."""

    __tablename__ = "regulatory_ai_extracts"
    __table_args__ = (
        UniqueConstraint(
            "hs_code_norm",
            "document_name",
            "measure_type",
            name="uq_regulatory_ai_extracts_natural",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hs_code_norm: Mapped[str] = mapped_column(String(12), index=True)
    measure_type: Mapped[str] = mapped_column(String(32), index=True)
    document_name: Mapped[str] = mapped_column(String(512), default="")
    source_excerpt: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive, onupdate=utc_now_naive)


class RegulatorySyncEvent(Base):
    """Строки журнала для админки (Sync Center)."""

    __tablename__ = "regulatory_sync_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive, index=True)
    level: Mapped[str] = mapped_column(String(16), default="info", index=True)
    message: Mapped[str] = mapped_column(Text, default="")


class BulkImportJob(Base):
    """Фоновая задача массового ИИ-импорта нормативных документов (прогресс для админки)."""

    __tablename__ = "bulk_import_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    total_files: Mapped[int] = mapped_column(Integer, default=0)
    processed_files: Mapped[int] = mapped_column(Integer, default=0)
    measures_applied: Mapped[int] = mapped_column(Integer, default=0)
    current_file: Mapped[str] = mapped_column(String(512), default="")
    error_message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive, onupdate=utc_now_naive)


class BulkImportFileCheckpoint(Base):
    """Чекпоинт обработанного файла (по SHA-256), чтобы не гонять LLM повторно."""

    __tablename__ = "bulk_import_file_checkpoints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    relative_path: Mapped[str] = mapped_column(String(512), default="")
    status: Mapped[str] = mapped_column(String(16), default="ok", index=True)  # ok | error
    measures_applied: Mapped[int] = mapped_column(Integer, default=0)
    error_note: Mapped[str] = mapped_column(Text, default="")
    job_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class HistoricalCrawlCheckpoint(Base):
    """Чекпоинт исторического краулера по URL (идемпотентность при длительных прогонах)."""

    __tablename__ = "historical_crawl_checkpoints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    url_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    canonical_url: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="ok", index=True)  # ok | error | skipped
    measures_applied: Mapped[int] = mapped_column(Integer, default=0)
    error_note: Mapped[str] = mapped_column(Text, default="")
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class TnvedEntry(Base):
    """Позиция ТН ВЭД ЕАЭС: код, иерархия, наименование и поясняющий текст (из выгрузок / пакета)."""

    __tablename__ = "tnved_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hs_code: Mapped[str] = mapped_column(String(12), unique=True, index=True)
    parent_hs: Mapped[str] = mapped_column(String(12), default="", index=True)
    level: Mapped[int] = mapped_column(Integer, default=10)
    title: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    chapter: Mapped[str] = mapped_column(String(4), default="", index=True)
    source_url: Mapped[str] = mapped_column(Text, default="")
    source_revision: Mapped[str] = mapped_column(String(128), default="seed")

    embedding_row: Mapped[Optional["TnvedEntryEmbedding"]] = relationship(
        back_populates="tnved_entry",
        uselist=False,
        cascade="all, delete-orphan",
    )


class TrTsAct(Base):
    """Справочник техрегламентов ТР ТС (код вида 004/2011, краткое и полное наименование)."""

    __tablename__ = "tr_ts_acts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    act_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    short_name: Mapped[str] = mapped_column(String(512), default="")
    full_title: Mapped[str] = mapped_column(Text, default="")
    edition_note: Mapped[str] = mapped_column(Text, default="")
    source_url: Mapped[str] = mapped_column(Text, default="")
    source_revision: Mapped[str] = mapped_column(String(128), default="seed")


class NormativeNote(Base):
    """Примечания к ТН ВЭД, ЕТТ, нетарифному регулированию (позиция / префикс / глава / глобально)."""

    __tablename__ = "normative_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # hs_code | prefix | chapter | global
    scope_type: Mapped[str] = mapped_column(String(16), index=True)
    scope_value: Mapped[str] = mapped_column(String(12), default="", index=True)
    # tnved | ett | non_tariff | general
    category: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(512), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    source_url: Mapped[str] = mapped_column(Text, default="")
    source_revision: Mapped[str] = mapped_column(String(128), default="seed")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class CountryRisk(Base):
    """Справочник страновых рисков / преференций (ISO-2 — первичный ключ)."""

    __tablename__ = "country_risks"

    iso_code: Mapped[str] = mapped_column(String(2), primary_key=True)
    name_ru: Mapped[str] = mapped_column(String(255), default="")
    is_unfriendly: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    has_preference: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    required_cert: Mapped[str] = mapped_column(String(128), default="")


class GeoSpecialDuty(Base):
    """
    Заградительные / повышенные ставки по префиксу ТН ВЭД и стране (каркас ПП РФ №2140 и аналоги).

    Таблица `special_duties` уже занята моделью антидемпинга (tnved.SpecialDuty), поэтому отдельное имя таблицы.
    country_iso: ISO2 или ALL_UNFRIENDLY (для любой страны из country_risks с is_unfriendly).

    measure_type: embargo | increased_duty | anti_dumping | preference
    """

    __tablename__ = "geo_special_duties"
    __table_args__ = (
        UniqueConstraint(
            "hs_code_prefix",
            "document_basis",
            "country_iso",
            name="uq_geo_special_duties_prefix_basis_country",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hs_code_prefix: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    country_iso: Mapped[str] = mapped_column(String(20), nullable=False, default="", index=True)
    duty_rate: Mapped[str] = mapped_column(String(512), nullable=False, default="0", server_default="0")
    document_basis: Mapped[str] = mapped_column(String(512), default="")
    measure_type: Mapped[str] = mapped_column(String(32), default="increased_duty", nullable=False)
    document_link: Mapped[str] = mapped_column(Text, default="")


class SanctionImportRisk(Base):
    """Упрощённый справочник рисков ввоза (префикс ТН ВЭД × юрисдикция санкционных списков)."""

    __tablename__ = "sanction_import_risks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hs_code_prefix: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    jurisdiction: Mapped[str] = mapped_column(String(8), default="EU", index=True)  # EU | US | UK
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False, default="risk")  # safe | risk | forbidden
    description: Mapped[str] = mapped_column(Text, default="")


class OfacSdnList(Base):
    """Список SDN (OFAC, США): лица и компании под санкциями."""

    __tablename__ = "ofac_sdn_list"
    __table_args__ = (
        UniqueConstraint("name", "type", "origin_country", name="uq_ofac_sdn_name_type_country"),
        Index("ix_ofac_sdn_name", "name"),
        Index("ix_ofac_sdn_origin_country", "origin_country"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    # individual | entity | vessel | aircraft | other
    type: Mapped[str] = mapped_column(String(64), default="other", index=True)
    origin_country: Mapped[str] = mapped_column(String(8), default="", index=True)
    # JSON-строка/CSV алиасов (как пришло из источника).
    aliases: Mapped[str] = mapped_column(Text, default="")


class EuSanctionsList(Base):
    """Консолидированный список ЕС: товары/лица/организации под ограничениями."""

    __tablename__ = "eu_sanctions_list"
    __table_args__ = (
        UniqueConstraint("hs_code", "entity_name", "description", name="uq_eu_sanctions_natural"),
        Index("ix_eu_sanctions_hs_code", "hs_code"),
        Index("ix_eu_sanctions_entity_name", "entity_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hs_code: Mapped[str] = mapped_column(String(10), default="", index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    entity_name: Mapped[str] = mapped_column(String(1024), default="", index=True)


class CountrySpecificRule(Base):
    """Страновые комплаенс-правила для ввоза/вывоза (локальные требования контроля)."""

    __tablename__ = "country_specific_rules"
    __table_args__ = (
        UniqueConstraint("country_code", "rule_type", "description", name="uq_country_specific_rules_natural"),
        Index("ix_country_specific_rules_country_code", "country_code"),
        Index("ix_country_specific_rules_rule_type", "rule_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    country_code: Mapped[str] = mapped_column(String(8), nullable=False, default="", index=True)
    # docs_control | embargo | enhanced_due_diligence | licensing | other
    rule_type: Mapped[str] = mapped_column(String(64), nullable=False, default="other", index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")


class ClassificationDecision(Base):
    """Предварительные / классификационные решения (ФТС), в т.ч. с tks.ru/db/tnved/predecision/."""

    __tablename__ = "classification_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hs_code: Mapped[str] = mapped_column(String(10), default="", index=True)
    product_name: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    # Очищенное наименование главного классифицируемого товара (ИИ / правила), без «шума» длинного описания
    target_entity: Mapped[str] = mapped_column(String(512), default="")
    decision_number: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    issue_date: Mapped[str] = mapped_column(String(32), default="")


class CustomsCaseLaw(Base):
    """
    Судебная и квазисудебная практика по классификации:
    - судебные акты;
    - разъяснения/решения ЕЭК;
    - пояснения к ТН ВЭД.
    """

    __tablename__ = "customs_case_law"
    __table_args__ = (
        Index("ix_customs_case_law_hs_prefix", "hs_code_prefix"),
        Index("ix_customs_case_law_source_type", "source_type"),
        Index("ix_customs_case_law_recommended_hs", "recommended_hs_code"),
        UniqueConstraint("source_type", "case_number", name="uq_customs_case_law_source_case"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # court | eec | explanatory_note | admin_guidance
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, default="court")
    case_number: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    title: Mapped[str] = mapped_column(String(512), default="")
    hs_code_prefix: Mapped[str] = mapped_column(String(10), default="", index=True)
    recommended_hs_code: Mapped[str] = mapped_column(String(10), default="", index=True)
    keywords: Mapped[str] = mapped_column(Text, default="")
    product_scope: Mapped[str] = mapped_column(Text, default="")
    legal_basis: Mapped[str] = mapped_column(Text, default="")
    opi_applied: Mapped[str] = mapped_column(String(32), default="")
    reasoning_summary: Mapped[str] = mapped_column(Text, default="")
    decision_summary: Mapped[str] = mapped_column(Text, default="")
    source_url: Mapped[str] = mapped_column(Text, default="")
    source_date: Mapped[str] = mapped_column(String(32), default="")
    # Подготовка под семантический поиск (при наличии эмбеддингов).
    embedding_model: Mapped[str] = mapped_column(String(128), default="")
    embedding: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive, onupdate=utc_now_naive)


class PrecedentEmbedding(Base):
    """Универсальный векторный индекс прецедентов из classification/preliminary/declaration таблиц."""

    __tablename__ = "precedent_embeddings"
    __table_args__ = (
        UniqueConstraint("source_table", "source_id", name="uq_precedent_embeddings_source"),
        Index("ix_precedent_embeddings_hs_code", "hs_code"),
        Index("ix_precedent_embeddings_source_table", "source_table"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_table: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    source_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    hs_code: Mapped[str] = mapped_column(String(10), default="", index=True)
    title: Mapped[str] = mapped_column(String(512), default="")
    text_content: Mapped[str] = mapped_column(Text, default="")
    embedding_model: Mapped[str] = mapped_column(String(128), default="")
    embedding_dim: Mapped[int] = mapped_column(Integer, default=0)
    embedding: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive, onupdate=utc_now_naive)


class DeclarationExample(Base):
    """Примеры декларирования (обезличенные формулировки графы 31), в т.ч. с ifcg.ru/kb/tnved/."""

    __tablename__ = "declaration_examples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hs_code: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="ifcg")


class PreliminaryDecision(Base):
    """Предварительные / иные решения по классификации (IFCG и др.), текст + код из блока страницы."""

    __tablename__ = "preliminary_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hs_code: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="ifcg")


class EcoFeeRate(Base):
    """Тарифы экологического сбора (РОП / утилизация): префикс ТН ВЭД, тип материала, год действия."""

    __tablename__ = "eco_fee_rates"
    __table_args__ = (
        UniqueConstraint(
            "hs_code_prefix",
            "material_type",
            "valid_from_year",
            name="uq_eco_fee_rates_prefix_material_year",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hs_code_prefix: Mapped[str] = mapped_column(String(16), nullable=False, default="", index=True)
    material_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    rate_rub_per_kg: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    normative_percent: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    valid_from_year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)


# --- Загрузка документов, строки инвойса, RAG-эмбеддинги ТН ВЭД, история расчётов ---


class IngestedDocument(Base):
    """Загруженный ТСД: инвойс, спецификация, скан (модуль ingestion)."""

    __tablename__ = "ingested_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_doc_id)
    original_filename: Mapped[str] = mapped_column(String(512), default="")
    mime_type: Mapped[str] = mapped_column(String(128), default="application/octet-stream")
    storage_uri: Mapped[str] = mapped_column(Text, default="")  # путь на диске или s3://…
    file_sha256: Mapped[str] = mapped_column(String(64), default="", index=True)
    detected_lang: Mapped[str] = mapped_column(String(16), default="")  # zh, en, ru, mixed

    # uploaded | ocr_done | llm_structured | failed
    status: Mapped[str] = mapped_column(String(32), default="uploaded", index=True)
    error_message: Mapped[str] = mapped_column(Text, default="")

    raw_text: Mapped[str] = mapped_column(Text, default="")
    structured_payload: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    # Тематика для RAG (law.tks.ru / sync_law_full); дублирует structured_payload["category"] при синке.
    category: Mapped[str] = mapped_column(String(512), default="")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive, onupdate=utc_now_naive)

    lines: Mapped[List["ParsedInvoiceLine"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="ParsedInvoiceLine.line_no",
    )


class ParsedInvoiceLine(Base):
    """Товарная строка после OCR/LLM-структурирования."""

    __tablename__ = "parsed_invoice_lines"
    __table_args__ = (Index("ix_pil_document_line", "document_id", "line_no"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("ingested_documents.id", ondelete="CASCADE"),
        index=True,
    )
    line_no: Mapped[int] = mapped_column(Integer, default=1)

    description_original: Mapped[str] = mapped_column(Text, default="")
    description_ru: Mapped[str] = mapped_column(Text, default="")

    quantity: Mapped[float] = mapped_column(Float, default=0.0)
    unit: Mapped[str] = mapped_column(String(32), default="")
    unit_price: Mapped[float] = mapped_column(Float, default=0.0)
    line_total: Mapped[float] = mapped_column(Float, default=0.0)

    weight_net_kg: Mapped[float] = mapped_column(Float, default=0.0)
    weight_gross_kg: Mapped[float] = mapped_column(Float, default=0.0)
    packages_count: Mapped[float] = mapped_column(Float, default=0.0)

    attributes: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)

    suggested_hs_code: Mapped[str] = mapped_column(String(12), default="", index=True)
    hs_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    hs_rag_snippet_ids: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)

    document: Mapped["IngestedDocument"] = relationship(back_populates="lines")


class TnvedEntryEmbedding(Base):
    """Вектор для семантического поиска по ТН ВЭД (PostgreSQL: см. pgvector; SQLite: JSON-текст)."""

    __tablename__ = "tnved_entry_embeddings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tnved_entry_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("tnved_entries.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    embedding_model: Mapped[str] = mapped_column(String(128), default="text-embedding-3-small")
    embedding_dim: Mapped[int] = mapped_column(Integer, default=1536)
    # Список float как JSON; при миграции на pgvector можно заменить тип столбца на vector(dim)
    embedding: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)

    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive, onupdate=utc_now_naive)

    tnved_entry: Mapped["TnvedEntry"] = relationship(back_populates="embedding_row")


class PermitsVerifyJob(Base):
    """Фоновая массовая проверка разрешений (ФСА); переживает перезапуск API."""

    __tablename__ = "permits_verify_jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    """Логин из JWT (`sub`); NULL — задания до введения поля (не показываются обычным пользователям)."""
    created_by_username: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    # queued | running | done | error
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive, index=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    summary: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    items: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    # Вход async-запроса (для отладки / возможного повторного запуска вручную)
    request_payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class VedIntelJob(Base):
    """Фоновый полный ВЭД-разбор документа; результат в `result` после status=done."""

    __tablename__ = "ved_intel_jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    # queued | running | done | error
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive, index=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    result: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    request_payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class CustomsCalculationHistory(Base):
    """Сохранённый расчёт таможенных платежей (модуль billing)."""

    __tablename__ = "customs_calculation_history"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_calc_id)
    document_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("ingested_documents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    user_ref: Mapped[str] = mapped_column(String(128), default="", index=True)

    input_payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    output_payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive, index=True)


class FssNotification(Base):
    """Реестр нотификаций ФСБ (импорт из открытых источников / выгрузок)."""

    __tablename__ = "fss_notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    number: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, default="", index=True)
    brand: Mapped[str] = mapped_column(String(512), default="", index=True)
    status: Mapped[str] = mapped_column(String(64), default="", index=True)
    expiry_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_updated: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive, onupdate=utc_now_naive)


class ReoRegistryEntry(Base):
    """Реестр РЭС / ВЧУ (Роскомнадзор) — строка разрешительного документа."""

    __tablename__ = "reo_registry"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    number: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    model_name: Mapped[str] = mapped_column(String(512), default="", index=True)
    brand: Mapped[str] = mapped_column(String(512), default="", index=True)
    characteristics: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(64), default="")
    expiry_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class SgrCertificate(Base):
    """Единый реестр свидетельств о государственной регистрации (СГР) — локальная копия для сверки."""

    __tablename__ = "sgr_certificates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sgr_number: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    product_name: Mapped[str] = mapped_column(Text, default="")
    manufacturer: Mapped[str] = mapped_column(String(512), default="", index=True)
    brand: Mapped[str] = mapped_column(String(512), default="", index=True)
    recipient: Mapped[str] = mapped_column(String(512), default="")
    status: Mapped[str] = mapped_column(String(128), default="", index=True)
    issue_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
