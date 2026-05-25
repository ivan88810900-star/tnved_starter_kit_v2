"""Реестр нормативных источников: уровни полномочий и метаданные для монитора полноты."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

AuthorityLevel = Literal[
    "official_binding",
    "official_reference",
    "registry_evidence",
    "advisory_letter",
    "commercial_mirror",
    "legacy_seed",
    "ai_extracted",
]

AUTHORITY_LEVEL_LABELS: dict[str, str] = {
    "official_binding": "Официальный обязательный контур (source of truth)",
    "official_reference": "Официальный справочный контур",
    "registry_evidence": "Реестровое доказательство (проверка разрешений)",
    "advisory_letter": "Разъяснительное / информационное письмо",
    "commercial_mirror": "Коммерческое зеркало (не source of truth)",
    "legacy_seed": "Переходный seed / legacy",
    "ai_extracted": "Извлечено ИИ (требует ручной верификации)",
}

SOURCE_OF_TRUTH_LEVELS: frozenset[str] = frozenset(
    {"official_binding", "official_reference", "registry_evidence"}
)


@dataclass(frozen=True)
class RegulatorySourceEntry:
    """Одна запись реестра — стабильный идентификатор и параметры диагностики."""

    source_id: str
    title: str
    authority_level: AuthorityLevel
    official_url: str
    description: str
    # Пути относительно customs-clear/backend/
    local_paths: tuple[str, ...] = ()
    # Ключ счётчика в regulatory_source_completeness._count_db_probe
    db_probe: str | None = None
    # Связь с source_status.source_code (если sync обновляет метаданные)
    source_status_code: str | None = None
    # Имя скрипта в scripts/ для будущих sync-задач
    sync_script: str | None = None
    min_document_count: int = 1
    known_gaps: tuple[str, ...] = ()
    manual_review_default: bool = False


# Порядок фиксирован — отчёт сортирует по source_id для детерминизма.
REGULATORY_SOURCE_REGISTRY: tuple[RegulatorySourceEntry, ...] = (
    RegulatorySourceEntry(
        source_id="eec_ett_tnved",
        title="ТН ВЭД и ЕТТ ЕАЭС",
        authority_level="official_binding",
        official_url="https://eec.eaeunion.org/comission/department/catr/ett/",
        description="Официальный тариф ЕТТ / справочник кодов ЕАЭС.",
        db_probe="tnved_entries",
        source_status_code="EEC_ETT",
        sync_script="source_sync.py",
        min_document_count=100,
        known_gaps=("Полный массив кодов может требовать отдельного bundle/PDF-парсера.",),
    ),
    RegulatorySourceEntry(
        source_id="eec_tr_ts_catalog",
        title="Перечень технических регламентов ТР ТС/ЕАЭС",
        authority_level="official_binding",
        official_url="https://eec.eaeunion.org/comission/department/nts/",
        description="Справочник актов ТР ТС для привязки нетарифных мер.",
        db_probe="tr_ts_acts",
        sync_script="import_tr_ts_catalog_to_ntm_v2.py",
        min_document_count=10,
        known_gaps=("Карточки ТР могут быть seed; полный текст актов — отдельный контур regulatory_documents.",),
    ),
    RegulatorySourceEntry(
        source_id="eec_classification_decisions",
        title="Решения ЕЭК по классификации товаров",
        authority_level="official_binding",
        official_url="https://docs.eaeunion.org/docs/",
        description="Официальные решения Коллегии/Совета ЕЭК по ТН ВЭД.",
        db_probe="customs_case_law_eec",
        sync_script="historical_crawler.py",
        min_document_count=1,
        known_gaps=("Массовая загрузка решений ЕЭК в БД не входит в этот MVP-срез.",),
    ),
    RegulatorySourceEntry(
        source_id="fts_preliminary_classification",
        title="Предварительные решения ФТС по классификации",
        authority_level="official_binding",
        official_url="https://customs.gov.ru/document",
        description="ПКР и решения о классификации ФТС России.",
        local_paths=("data/fixtures/fcs_preliminary_decisions.sample.json",),
        db_probe="classification_decisions_official_fts",
        source_status_code="FCS_PRELIMINARY",
        sync_script="sync_fcs_predecisions.py",
        min_document_count=1,
        known_gaps=(
            "MVP: детерминированный импорт из fixture; полный официальный фид ФТС — scheduled sync.",
            "Коммерческие зеркала (TKS/Alta) не закрывают official gap.",
        ),
        manual_review_default=True,
    ),
    RegulatorySourceEntry(
        source_id="pravo_gov_publication",
        title="Официальный интернет-портал правовой информации",
        authority_level="official_binding",
        official_url="http://publication.pravo.gov.ru",
        description="Публикация федеральных НПА (законы, постановления, приказы).",
        db_probe="regulatory_documents_pravo",
        sync_script="sync_law_full.py",
        min_document_count=1,
        known_gaps=("Массовая синхронизация НПА не входит в этот PR.",),
    ),
    RegulatorySourceEntry(
        source_id="eec_sgr_decision_299",
        title="Единый реестр СГР (Решение ЕЭК №299)",
        authority_level="official_binding",
        official_url="https://portal.eaeunion.org/",
        description="Официальный реестр свидетельств о государственной регистрации ЕАЭС.",
        local_paths=("data/official_sgr_rules.seed.json",),
        db_probe="sgr_certificates",
        source_status_code="SGR_REGISTRY",
        sync_script="sync_sgr_registry.py",
        min_document_count=1,
        known_gaps=(
            "Curated official_sgr_rules.seed — не полный реестр; OData NSI требует SGR_ODATA_LIST_TITLE.",
        ),
    ),
    RegulatorySourceEntry(
        source_id="official_sgr_ntm_v2_curated",
        title="Curated official SGR rules (NTM v2)",
        authority_level="official_reference",
        official_url="https://eec.eaeunion.org/",
        description="Курируемый контур official_sgr_registry для advisory/enforcement-политики NTM v2.",
        local_paths=("data/official_sgr_rules.seed.json",),
        db_probe="ntm_v2_official_sgr_rules",
        sync_script="import_official_sgr_rules_to_ntm_v2.py",
        min_document_count=1,
        known_gaps=("Enforcement по умолчанию выключен; расширение seed — отдельные задачи.",),
        manual_review_default=True,
    ),
    RegulatorySourceEntry(
        source_id="fsa_registry_evidence",
        title="Реестр деклараций/сертификатов (Росаккредитация)",
        authority_level="registry_evidence",
        official_url="https://pub.fsa.gov.ru/",
        description="Проверка разрешительных документов в permits/compliance (не нормативная истина по мерам).",
        db_probe="permits_fsa_usage",
        sync_script=None,
        min_document_count=0,
        known_gaps=("Нет локального bulk-снимка; используется онлайн-проверка.",),
    ),
    RegulatorySourceEntry(
        source_id="regulatory_documents_corpus",
        title="Корпус ведомственных документов (regulatory_documents)",
        authority_level="official_reference",
        official_url="https://customs.gov.ru/document",
        description="Скачанные приказы, письма, решения ведомств с привязкой к HS.",
        db_probe="regulatory_documents",
        sync_script="regulatory_fetcher.py",
        min_document_count=1,
        known_gaps=("Парсеры по agency — частичное покрытие; AI-mapping требует approve.",),
        manual_review_default=True,
    ),
    RegulatorySourceEntry(
        source_id="ifcg_preliminary_mirror",
        title="IFCG.ru — предварительные решения и примеры",
        authority_level="commercial_mirror",
        official_url="https://ifcg.ru/kb/tnved/",
        description="Зеркало предварительных решений и declaration_examples.",
        db_probe="preliminary_decisions_ifcg",
        sync_script="sync_ifcg_examples.py",
        min_document_count=0,
        known_gaps=("Не официальный источник; только advisory/UI.",),
        manual_review_default=True,
    ),
    RegulatorySourceEntry(
        source_id="tks_predecisions_mirror",
        title="TKS.ru — зеркало ПКР",
        authority_level="commercial_mirror",
        official_url="https://www.tks.ru/db/tnved/predecision/",
        description="Коммерческий парсер предрешений → classification_decisions.",
        db_probe="preliminary_decisions_fts_alta",
        sync_script="sync_tks_predecisions.py",
        min_document_count=0,
        known_gaps=("Дублирует fts_preliminary_classification через зеркало.",),
        manual_review_default=True,
    ),
    RegulatorySourceEntry(
        source_id="alta_tamdoc_mirror",
        title="Alta.ru tamdoc — нормативные фрагменты",
        authority_level="commercial_mirror",
        official_url="https://www.alta.ru/tamdoc/",
        description="Парсинг tamdoc для НДС-льгот и нетарифных вставок.",
        source_status_code="ALTA_TAMDOC",
        sync_script="sync_tamdoc.py",
        min_document_count=0,
        known_gaps=("Staging/approve workflow; не source of truth.",),
        manual_review_default=True,
    ),
    RegulatorySourceEntry(
        source_id="regulatory_ai_extracts",
        title="LLM-извлечения из актов",
        authority_level="ai_extracted",
        official_url="",
        description="Правила из sync_engine / bulk_normative_ai.",
        db_probe="regulatory_ai_extracts",
        sync_script="sync_engine.py",
        min_document_count=0,
        known_gaps=("Все строки требуют ручной верификации перед enforcement.",),
        manual_review_default=True,
    ),
    RegulatorySourceEntry(
        source_id="legacy_ntm_tr_catalog",
        title="Legacy каталог ТР ТС (ALL_REGULATIONS)",
        authority_level="legacy_seed",
        official_url="https://eec.eaeunion.org/comission/department/nts/",
        description="Переходный импорт tr_ts_catalog → ntm_measures_v2 (legacy_tr_ts_catalog).",
        db_probe="ntm_v2_legacy_tr_catalog",
        sync_script="import_tr_ts_catalog_to_ntm_v2.py",
        min_document_count=0,
        known_gaps=("Не смешивать с official_sgr_registry без merge-policy.",),
        manual_review_default=True,
    ),
    RegulatorySourceEntry(
        source_id="non_tariff_measures_tks",
        title="Нетарифные меры TKS",
        authority_level="commercial_mirror",
        official_url="https://www.tks.ru/",
        description="Синхронизация non_tariff_measures с TKS.ru.",
        db_probe="non_tariff_measures",
        sync_script="sync_tks_nontariff.py",
        min_document_count=100,
        known_gaps=("Качество noise-разметки; не официальный контур.",),
        manual_review_default=True,
    ),
)


def get_registry_entry(source_id: str) -> RegulatorySourceEntry | None:
    for entry in REGULATORY_SOURCE_REGISTRY:
        if entry.source_id == source_id:
            return entry
    return None


def registry_entry_to_dict(entry: RegulatorySourceEntry) -> dict[str, Any]:
    return {
        "source_id": entry.source_id,
        "title": entry.title,
        "authority_level": entry.authority_level,
        "authority_label": AUTHORITY_LEVEL_LABELS.get(entry.authority_level, entry.authority_level),
        "is_source_of_truth": entry.authority_level in SOURCE_OF_TRUTH_LEVELS,
        "official_url": entry.official_url,
        "description": entry.description,
        "local_paths": list(entry.local_paths),
        "db_probe": entry.db_probe,
        "source_status_code": entry.source_status_code,
        "sync_script": entry.sync_script,
        "min_document_count": entry.min_document_count,
        "known_gaps": list(entry.known_gaps),
        "manual_review_default": entry.manual_review_default,
    }


def list_registry_entries() -> list[dict[str, Any]]:
    """Детерминированный список записей реестра (без runtime-диагностики)."""
    return [registry_entry_to_dict(e) for e in REGULATORY_SOURCE_REGISTRY]
