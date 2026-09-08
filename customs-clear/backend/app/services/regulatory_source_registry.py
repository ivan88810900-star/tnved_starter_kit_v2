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

RefreshCadence = Literal["daily", "weekly", "monthly", "manual"]

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
    # Exact machine-readable/legal artifacts used by monitors or adapters.  The
    # landing page above remains the user-facing citation.
    monitor_urls: tuple[str, ...] = ()
    # Пути относительно customs-clear/backend/
    local_paths: tuple[str, ...] = ()
    # Ключ счётчика в regulatory_source_completeness._count_db_probe
    db_probe: str | None = None
    # Связь с source_status.source_code (если sync обновляет метаданные)
    source_status_code: str | None = None
    # Имя существующего скрипта в scripts/ (если источник имеет structured-sync)
    sync_script: str | None = None
    min_document_count: int = 1
    # Operational freshness contract.  ``max_age_hours`` is intentionally
    # explicit instead of being inferred at report time: a missed daily/weekly
    # run must make the source stale even when its last snapshot is still in DB.
    refresh_cadence: RefreshCadence = "manual"
    max_age_hours: int | None = None
    known_gaps: tuple[str, ...] = ()
    manual_review_default: bool = False


# Порядок фиксирован — отчёт сортирует по source_id для детерминизма.
REGULATORY_SOURCE_REGISTRY: tuple[RegulatorySourceEntry, ...] = (
    RegulatorySourceEntry(
        source_id="cbr_exchange_rates",
        title="Официальные курсы валют Банка России",
        authority_level="official_reference",
        official_url="https://www.cbr.ru/scripts/XML_daily.asp",
        description="Ежедневные официальные курсы валют для расчётов и инвойсов.",
        monitor_urls=("https://www.cbr.ru/scripts/XML_daily.asp",),
        db_probe="exchange_rates",
        source_status_code="CBRF",
        sync_script="update_rates.py",
        min_document_count=1,
        refresh_cadence="daily",
        max_age_hours=48,
    ),
    RegulatorySourceEntry(
        source_id="eec_ett_tnved",
        title="ТН ВЭД и ЕТТ ЕАЭС",
        authority_level="official_binding",
        official_url="https://eec.eaeunion.org/comission/department/catr/ett/",
        description="Официальный тариф ЕТТ / справочник кодов ЕАЭС.",
        db_probe="tnved_entries",
        source_status_code="EEC_ETT",
        sync_script=None,
        min_document_count=100,
        known_gaps=("Полный массив кодов может требовать отдельного bundle/PDF-парсера.",),
    ),
    RegulatorySourceEntry(
        source_id="eec_tr_ts_catalog",
        title="Перечень технических регламентов ТР ТС/ЕАЭС",
        authority_level="official_binding",
        official_url="https://eec.eaeunion.org/comission/department/deptexreg/tr/TR_general.php",
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
        source_id="eec_decision30_ntm_contours",
        title="Единый перечень товаров с запретами и разрешительным порядком",
        authority_level="official_binding",
        official_url="https://eec.eaeunion.org/comission/department/catr/nontariff/ep.new.php",
        description="Решение Коллегии ЕЭК №30; индекс всех действующих разделов Единого перечня.",
        local_paths=("app/services/official_ntm_contours.py",),
        sync_script="monitor_official_ntm_sources.py",
        known_gaps=("Advisory-only; код «из» требует проверки наименования и характеристик.",),
        manual_review_default=True,
    ),
    RegulatorySourceEntry(
        source_id="rf_pp_2425_conformity",
        title="Национальные перечни обязательной оценки соответствия РФ",
        authority_level="official_binding",
        official_url="https://publication.pravo.gov.ru/document/0001202112300200",
        description="Постановление Правительства РФ №2425; национальный контур, включая посуду.",
        local_paths=("app/services/official_ntm_contours.py",),
        sync_script="monitor_official_ntm_sources.py",
        known_gaps=("Применимость зависит от вида, материала, назначения и территории обращения.",),
        manual_review_default=True,
    ),
    RegulatorySourceEntry(
        source_id="eec_sgr_decision_299",
        title="Единый перечень санитарного контроля и СГР (Решение КТС №299)",
        authority_level="official_binding",
        official_url="https://eec.eaeunion.org/upload/medialibrary/f52/EdpertovarovEEU.pdf",
        description="Решение КТС №299: нормативный перечень и кодовые кандидаты раздела II.",
        monitor_urls=("https://eec.eaeunion.org/upload/medialibrary/f52/EdpertovarovEEU.pdf",),
        local_paths=("app/services/official_ntm_contours.py",),
        sync_script="monitor_official_ntm_sources.py",
        known_gaps=(
            "Большинство строк раздела II содержит «из»: код без назначения, состава и исключений не доказывает обязанность СГР.",
            "Изменение нормативного перечня требует проверки и не продвигается в правила автоматически.",
        ),
        manual_review_default=True,
    ),
    RegulatorySourceEntry(
        source_id="eec_sgr_registry",
        title="Единый реестр выданных свидетельств о государственной регистрации",
        authority_level="registry_evidence",
        official_url="https://nsi.eaeunion.org/portal/1995",
        description="Машиночитаемый реестр выданных СГР для проверки конкретного документа.",
        monitor_urls=("https://nsi.eaeunion.org/portal/1995",),
        local_paths=("data/official_sgr_rules.seed.json",),
        db_probe="sgr_certificates",
        source_status_code="SGR_REGISTRY",
        sync_script="sync_sgr_registry.py",
        min_document_count=1,
        refresh_cadence="daily",
        max_age_hours=48,
        known_gaps=(
            "Большинство строк раздела II содержит «из»: код без назначения, состава и исключений не доказывает обязанность СГР.",
            "Актуальность конкретного документа требует отдельной проверки реестра.",
            "Автосинхронизация реестра не изменяет нормативные code-only правила Решения №299.",
        ),
    ),
    RegulatorySourceEntry(
        source_id="eec_fss_notifications_registry",
        title="Единый реестр нотификаций о характеристиках шифровальных средств",
        authority_level="registry_evidence",
        official_url="https://nsi.eaeunion.org/portal/1994",
        description="Официальный реестр нотификаций ФСБ/ЕАЭС для проверки конкретного товара.",
        db_probe="fss_notifications",
        source_status_code="FSS_NOTIFICATIONS",
        sync_script="sync_state_registries.py",
        min_document_count=1,
        refresh_cadence="daily",
        max_age_hours=48,
        known_gaps=("Запись реестра подтверждает документ, но не заменяет проверку применимости меры по товару.",),
    ),
    RegulatorySourceEntry(
        source_id="eec_reo_vchu_registry",
        title="Единый реестр РЭС и ВЧУ",
        authority_level="registry_evidence",
        official_url="https://nsi.eaeunion.org/portal/1992",
        description="Официальный реестр радиоэлектронных средств и высокочастотных устройств.",
        db_probe="reo_registry",
        source_status_code="REO_VCHU",
        sync_script="sync_state_registries.py",
        min_document_count=1,
        refresh_cadence="daily",
        max_age_hours=48,
        known_gaps=("Совпадение модели является доказательством реестра, а не автоматическим выводом о разрешительном документе.",),
    ),
    RegulatorySourceEntry(
        source_id="eec_veterinary_decision_317",
        title="Единый перечень товаров под ветеринарным контролем (Решение КТС №317)",
        authority_level="official_binding",
        official_url="https://eec.eaeunion.org/upload/medialibrary/89f/Pr.1-Edinyy-perechen-tov.pdf",
        description="Текущий перечень подконтрольных товаров; код, наименование, назначение и примечания проверяются совместно.",
        local_paths=("app/services/official_ntm_contours.py",),
        sync_script="monitor_official_ntm_sources.py",
        known_gaps=(
            "Факт ветеринарного контроля не означает один универсальный вид ветеринарного документа.",
            "Условные строки требуют назначения товара, происхождения и параметров операции.",
        ),
        manual_review_default=True,
    ),
    RegulatorySourceEntry(
        source_id="eec_phytosanitary_decisions_318_157",
        title="Карантинный фитосанитарный перечень и требования (Решения КТС №318 / Совета ЕЭК №157)",
        authority_level="official_binding",
        official_url="https://eec.eaeunion.org/comission/department/depsanmer/regulation/karantinnye-fitosanitarnye-mery.php",
        description="Решение КТС №318 задаёт перечень и уровень риска; Решение Совета ЕЭК №157 — единые требования.",
        local_paths=("app/services/official_ntm_contours.py",),
        sync_script="monitor_official_ntm_sources.py",
        known_gaps=(
            "Фитосанитарный сертификат требуется для высокого риска; низкий риск нельзя автоматически превращать в ФСС.",
            "Строки «из» требуют вида товара, обработки и упаковки.",
        ),
        manual_review_default=True,
    ),
    RegulatorySourceEntry(
        source_id="rf_export_control_lists",
        title="Шесть списков экспортного контроля РФ",
        authority_level="official_binding",
        official_url="https://publication.pravo.gov.ru/Document/View/0001202207220041",
        description="ПП РФ №1284–1288 и №1299; справочные HS-кандидаты для обязательной идентификации по техническим параметрам.",
        local_paths=(
            "app/services/official_export_control.py",
            "data/official_export_control_rules.seed.json",
        ),
        sync_script="monitor_official_ntm_sources.py",
        known_gaps=(
            "Датасет содержит HS-кандидаты, а не полные позиции, технические параметры, исключения и CAS каждого списка.",
            "Advisory-only: код не заменяет идентификацию товара и технологии.",
            "Для каждого из шести списков применимость проверяется по наименованию, назначению и параметрам.",
            "Отсутствие кодового совпадения не исключает всеобъемлющий экспортный контроль.",
        ),
        manual_review_default=True,
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
        monitor_urls=(
            "https://fsa.gov.ru/opendata/7736638268-rss/meta.xml",
            "https://fsa.gov.ru/opendata/7736638268-rds/meta.xml",
        ),
        db_probe="fsa_certificates",
        source_status_code="FSA_REGISTRY",
        sync_script="opendata_sync.py",
        min_document_count=1,
        refresh_cadence="weekly",
        max_age_hours=216,
        known_gaps=("Локальный снимок обновляется из официальных открытых данных; юридический статус документа проверяется на дату операции.",),
    ),
    RegulatorySourceEntry(
        source_id="fts_trois_registry",
        title="ТРОИС ФТС России",
        authority_level="registry_evidence",
        official_url="https://customs.gov.ru/opendata/7730176610-trois",
        description="Официальные открытые данные Таможенного реестра объектов интеллектуальной собственности.",
        monitor_urls=("https://customs.gov.ru/7730176610-trois/meta.csv",),
        db_probe="trois_registry",
        source_status_code="FTS_TROIS",
        sync_script="opendata_sync.py",
        min_document_count=1,
        refresh_cadence="weekly",
        max_age_hours=216,
    ),
    RegulatorySourceEntry(
        source_id="fts_customs_document_masks",
        title="Справочники документов ФТС России",
        authority_level="official_reference",
        official_url="https://customs.gov.ru/opendata",
        description="Официальные открытые справочники и маски документов для декларации.",
        monitor_urls=(
            "https://customs.gov.ru/7730176610-mask44/meta.csv",
            "https://customs.gov.ru/opendata/list.csv",
        ),
        db_probe="customs_doc_masks",
        source_status_code="FTS_CUSTOMS_DOCS",
        sync_script="opendata_sync.py",
        min_document_count=1,
        refresh_cadence="weekly",
        max_age_hours=216,
    ),
    RegulatorySourceEntry(
        source_id="regulatory_documents_corpus",
        title="Корпус ведомственных документов (regulatory_documents)",
        authority_level="official_reference",
        official_url="https://customs.gov.ru/document",
        description="Скачанные приказы, письма, решения ведомств с привязкой к HS.",
        db_probe="regulatory_documents",
        sync_script=None,
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
        sync_script=None,
        min_document_count=0,
        known_gaps=("Все строки требуют ручной верификации перед enforcement.",),
        manual_review_default=True,
    ),
    RegulatorySourceEntry(
        source_id="legacy_ntm_tr_catalog",
        title="Legacy каталог ТР ТС (ALL_REGULATIONS)",
        authority_level="legacy_seed",
        official_url="https://eec.eaeunion.org/comission/department/deptexreg/tr/TR_general.php",
        description="Переходный импорт tr_ts_catalog → ntm_measures_v2 (legacy_tr_ts_catalog).",
        local_paths=("app/services/tr_ts_catalog.py",),
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
    RegulatorySourceEntry(
        source_id="ofac_sdn_list",
        title="OFAC SDN (США)",
        authority_level="official_reference",
        official_url="https://ofac.treasury.gov/specially-designated-nationals-list-sdn-list",
        description="Список SDN OFAC для проверки контрагентов (диагностический контур).",
        monitor_urls=("https://www.treasury.gov/ofac/downloads/sdn.xml",),
        db_probe="ofac_sdn_list",
        source_status_code="OFAC_SDN",
        sync_script="sync_ofac_sanctions.py",
        min_document_count=1,
        refresh_cadence="daily",
        max_age_hours=48,
        known_gaps=(
            "Scheduled-контур только валидирует официальный bulk-фид; применение в blocking-таблицу выполняется вручную.",
            "Fuzzy-match по наименованию — advisory, не юридическое заключение.",
        ),
        manual_review_default=True,
    ),
    RegulatorySourceEntry(
        source_id="eu_sanctions_list",
        title="Санкции ЕС (consolidated / dual-use)",
        authority_level="official_reference",
        official_url="https://finance.ec.europa.eu/eu-and-world/sanctions-reform/sanctions-against-russia_en",
        description="Консолидированный контур ограничений ЕС по HS и субъектам.",
        monitor_urls=(
            "https://webgate.ec.europa.eu/fsd/fsf/public/files/xmlFullSanctionsList_1_1/content",
            "https://finance.ec.europa.eu/document/download/e5a807d3-6ca0-4bfb-8c6c-2f56f55e0b2e_en?filename=faqs-sanctions-russia-correlation-table-goods-regulation-833_en.xlsx",
        ),
        local_paths=("data/fixtures/sanctions_risk.sample.json",),
        db_probe="eu_sanctions_list",
        source_status_code="EU_SANCTIONS",
        sync_script="sync_eu_sanctions.py",
        min_document_count=1,
        refresh_cadence="daily",
        max_age_hours=48,
        known_gaps=(
            "Scheduled-контур только валидирует официальный bulk-фид; применение в blocking-таблицу выполняется вручную.",
            "Entity/HS correlation остаётся диагностическим контуром и не заменяет правовую проверку операции.",
        ),
        manual_review_default=True,
    ),
    RegulatorySourceEntry(
        source_id="sanction_import_risks",
        title="Справочник санкционных рисков по ТН ВЭД",
        authority_level="legacy_seed",
        official_url="",
        description="Упрощённый слой HS × jurisdiction для диагностики рисков ввоза.",
        local_paths=("data/fixtures/sanctions_risk.sample.json",),
        db_probe="sanction_import_risks",
        sync_script="sync_sanction_risks.py",
        min_document_count=1,
        known_gaps=("Не claim полного санкционного покрытия; curated/seed слой.",),
        manual_review_default=True,
    ),
    RegulatorySourceEntry(
        source_id="country_risks_geopolitics",
        title="Страновые риски и преференции",
        authority_level="legacy_seed",
        official_url="",
        description="Справочник недружественных/преференциальных стран (seed_geopolitics).",
        local_paths=("data/fixtures/sanctions_risk.sample.json",),
        db_probe="country_risks",
        sync_script="seed_geopolitics.py",
        min_document_count=1,
        known_gaps=("Seed-данные; не официальный перечень МИД/ЦБ.",),
        manual_review_default=True,
    ),
    RegulatorySourceEntry(
        source_id="trade_remedies_official",
        title="Официальный контур антидемпинговых мер ЕЭК",
        authority_level="official_binding",
        official_url="https://eec.eaeunion.org/comission/department/deptexsec/trade_remedies/",
        description="Official anti-dumping measures contour (special_duties + EEC_ANTI_DUMPING).",
        local_paths=("data/raw_normative/eec_anti_dumping.json",),
        db_probe="special_duties_anti_dumping",
        source_status_code="EEC_ANTI_DUMPING",
        min_document_count=1,
        known_gaps=(
            "MVP: локальный canonical bundle; полный перечень мер — отдельный data curation.",
            "geo_special_duties и hs_rates antidumping_* не считаются official proof.",
        ),
        manual_review_default=True,
    ),
    RegulatorySourceEntry(
        source_id="trade_remedies_special_safeguard_official",
        title="Официальный контур специальных защитных мер ЕЭК",
        authority_level="official_binding",
        official_url="https://eec.eaeunion.org/comission/department/deptexsec/trade_remedies/",
        description=(
            "Official special-safeguard measures contour "
            "(special_duties + EEC_SPECIAL_SAFEGUARD)."
        ),
        local_paths=("data/raw_normative/eec_special_safeguard.json",),
        db_probe="special_duties_special_safeguard",
        source_status_code="EEC_SPECIAL_SAFEGUARD",
        min_document_count=1,
        known_gaps=(
            "MVP: локальный canonical bundle; полный перечень мер — отдельный data curation.",
            "Строки антидемпинговых и компенсационных мер не считаются proof этого контура.",
        ),
        manual_review_default=True,
    ),
    RegulatorySourceEntry(
        source_id="trade_remedies_countervailing_official",
        title="Официальный контур компенсационных мер ЕЭК",
        authority_level="official_binding",
        official_url="https://eec.eaeunion.org/comission/department/deptexsec/trade_remedies/",
        description=(
            "Official countervailing measures contour "
            "(special_duties + EEC_COUNTERVAILING)."
        ),
        local_paths=("data/raw_normative/eec_countervailing.json",),
        db_probe="special_duties_countervailing",
        source_status_code="EEC_COUNTERVAILING",
        min_document_count=1,
        known_gaps=(
            "MVP: локальный canonical bundle; полный перечень мер — отдельный data curation.",
            "Строки антидемпинговых и защитных мер не считаются proof этого контура.",
        ),
        manual_review_default=True,
    ),
    RegulatorySourceEntry(
        source_id="rf_excise_tax_code",
        title="Официальный контур ставок акцизов РФ",
        authority_level="official_binding",
        official_url="https://www.nalog.gov.ru/rn77/taxation/taxes/akciz/",
        description="НК РФ и официальные разъяснения ФНС по подакцизным товарам и ставкам.",
        local_paths=("data/raw_normative/eec_excise.json",),
        db_probe="hs_rates_excise_eec",
        source_status_code="EEC_EXCISE",
        known_gaps=("Изменение ставок требует review канонического bundle до применения.",),
        manual_review_default=True,
    ),
    RegulatorySourceEntry(
        source_id="eec_odata_vat_preferences",
        title="Открытые данные ЕАЭС по льготам НДС",
        authority_level="official_reference",
        official_url="https://opendata.eaeunion.org/",
        description="Машиночитаемые справочники льгот и решений ЕЭК по НДС.",
        db_probe="vat_preferences_eec_odata",
        source_status_code="EEC_ODATA",
        known_gaps=("Требуется проверка правового основания и срока действия каждой строки.",),
        manual_review_default=True,
    ),
    RegulatorySourceEntry(
        source_id="geo_special_duties_embargo",
        title="Геополитические меры (эмбарго / повышенные ставки)",
        authority_level="legacy_seed",
        official_url="",
        description="geo_special_duties: embargo и increased_duty по HS × страна.",
        local_paths=("data/fixtures/sanctions_risk.sample.json",),
        db_probe="geo_special_duties",
        sync_script="seed_geopolitics.py",
        min_document_count=1,
        known_gaps=("Демо/seed каркас ПП РФ №2140; не полный официальный перечень.",),
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
        "monitor_urls": list(entry.monitor_urls),
        "local_paths": list(entry.local_paths),
        "db_probe": entry.db_probe,
        "source_status_code": entry.source_status_code,
        "sync_script": entry.sync_script,
        "min_document_count": entry.min_document_count,
        "refresh_cadence": entry.refresh_cadence,
        "max_age_hours": entry.max_age_hours,
        "known_gaps": list(entry.known_gaps),
        "manual_review_default": entry.manual_review_default,
    }


def list_registry_entries() -> list[dict[str, Any]]:
    """Детерминированный список записей реестра (без runtime-диагностики)."""
    return [registry_entry_to_dict(e) for e in REGULATORY_SOURCE_REGISTRY]
