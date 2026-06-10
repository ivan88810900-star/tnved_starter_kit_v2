"""Реестр официальных и локальных источников платёжных данных (пошлина, НДС, акциз, торговые меры)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .regulatory_source_registry import AUTHORITY_LEVEL_LABELS, AuthorityLevel, SOURCE_OF_TRUTH_LEVELS

PaymentDomain = Literal[
    "import_duty",
    "vat",
    "excise",
    "anti_dumping",
    "special_protective",
    "countervailing",
]

LoaderStatus = Literal["stub", "partial", "ready", "not_available", "manual_review_required"]

PAYMENT_DOMAINS: tuple[str, ...] = (
    "import_duty",
    "vat",
    "excise",
    "anti_dumping",
    "special_protective",
    "countervailing",
)


@dataclass(frozen=True)
class PaymentSourceEntry:
    """Кандидат источника для ingestion pipeline — метаданные и целевые таблицы."""

    source_code: str
    name: str
    domains: tuple[str, ...]
    authority_level: AuthorityLevel
    official_url: str
    legal_basis: str
    # Пути относительно customs-clear/backend/
    local_canonical_paths: tuple[str, ...] = ()
    source_status_code: str | None = None
    effective_from: str | None = None
    effective_to: str | None = None
    loader_status: LoaderStatus = "stub"
    sync_script: str | None = None
    target_tables: tuple[str, ...] = ()
    registry_source_id: str | None = None
    known_gaps: tuple[str, ...] = ()
    manual_review_default: bool = False


# Детерминированный порядок — сортировка по source_code в отчётах.
PAYMENT_SOURCE_REGISTRY: tuple[PaymentSourceEntry, ...] = (
    PaymentSourceEntry(
        source_code="eec_ett_tariff",
        name="ЕТТ ЕАЭС — импортные пошлины",
        domains=("import_duty",),
        authority_level="official_binding",
        official_url="https://eec.eaeunion.org/comission/department/catr/ett/",
        legal_basis="Единый таможенный тариф ЕАЭС (ЕТТ)",
        local_canonical_paths=(
            "data/raw_normative/eec_ett_normative_bundle.json",
            "data/raw_normative/eec_ett_import_duty.json",
        ),
        source_status_code="EEC_ETT",
        loader_status="ready",
        sync_script="source_sync.py",
        target_tables=("hs_rates", "hs_duty_rules"),
        registry_source_id="eec_ett_tnved",
        known_gaps=(
            "Локальный canonical bundle кладётся в data/raw_normative/; без файла — missing_official_source.",
            "seed/fallback hs_rates не заменяются автоматически без явной revision.",
            "VAT bundle (eec_ett_vat.json) — отдельный контур eec_ett_vat / EEC_VAT.",
        ),
    ),
    PaymentSourceEntry(
        source_code="eec_ett_vat",
        name="ЕТТ ЕАЭС — НДС при ввозе",
        domains=("vat",),
        authority_level="official_binding",
        official_url="https://eec.eaeunion.org/comission/department/catr/ett/",
        legal_basis="Единый таможенный тариф ЕАЭС (ЕТТ) — ставки НДС",
        local_canonical_paths=("data/raw_normative/eec_ett_vat.json",),
        source_status_code="EEC_VAT",
        loader_status="ready",
        sync_script="source_sync.py",
        target_tables=("hs_rates",),
        registry_source_id="eec_ett_tnved",
        known_gaps=(
            "Обновляет только VAT-поля существующих hs_rates; не создаёт duty rows.",
            "Official VAT proof — SourceStatus EEC_VAT, не duty source_revision.",
        ),
    ),
    PaymentSourceEntry(
        source_code="eec_odata_vat_preferences",
        name="OData ЕАЭС — льготный НДС",
        domains=("vat",),
        authority_level="official_reference",
        official_url="https://opendata.eaeunion.org/",
        legal_basis="Решения ЕЭК по льготам НДС (OData NSI)",
        source_status_code="EEC_ODATA",
        loader_status="partial",
        sync_script="ett_odata_parser.py",
        target_tables=("vat_preferences", "hs_rates"),
        registry_source_id="eec_ett_tnved",
        known_gaps=("Требует настроенного OData sync; tamdoc — отдельный commercial contour.",),
        manual_review_default=True,
    ),
    PaymentSourceEntry(
        source_code="alta_tamdoc_vat_special",
        name="Alta tamdoc — фрагменты НДС и спецпошлин (staging)",
        domains=("vat", "anti_dumping", "special_protective"),
        authority_level="commercial_mirror",
        official_url="https://www.alta.ru/tamdoc/",
        legal_basis="Коммерческое зеркало; не source of truth",
        source_status_code="ALTA_TAMDOC",
        loader_status="partial",
        sync_script="sync_tamdoc_targeted.py",
        target_tables=("vat_preferences", "special_duties"),
        registry_source_id="alta_tamdoc_mirror",
        known_gaps=("Staging/approve workflow; blocked from official ingestion.",),
        manual_review_default=True,
    ),
    PaymentSourceEntry(
        source_code="excise_official_contour",
        name="Официальный контур акцизных ставок",
        domains=("excise",),
        authority_level="official_binding",
        official_url="",
        legal_basis="НК РФ / подзаконные акты по акцизам (контур не зарегистрирован)",
        loader_status="not_available",
        target_tables=("hs_rates",),
        known_gaps=(
            "Dedicated official excise source не настроен в реестре.",
            "hs_rates.excise_* из seed не считается official.",
        ),
        manual_review_default=True,
    ),
    PaymentSourceEntry(
        source_code="trade_remedies_official",
        name="Официальный контур торговых мер (антидемпинг / защита)",
        domains=("anti_dumping", "special_protective", "countervailing"),
        authority_level="official_binding",
        official_url="https://eec.eaeunion.org/",
        legal_basis="Решения ЕЭК / Комиссии по торговым мерам",
        loader_status="not_available",
        target_tables=("special_duties", "geo_special_duties", "hs_rates"),
        known_gaps=(
            "Нет зарегистрированного official contour для bulk-import торговых мер.",
            "geo_special_duties — legacy_seed.",
        ),
        manual_review_default=True,
    ),
    PaymentSourceEntry(
        source_code="geo_special_duties_seed",
        name="geo_special_duties (legacy seed)",
        domains=("anti_dumping", "special_protective"),
        authority_level="legacy_seed",
        official_url="",
        legal_basis="Демо/seed каркас (ПП РФ №2140 и др.)",
        local_canonical_paths=("data/fixtures/sanctions_risk.sample.json",),
        loader_status="manual_review_required",
        sync_script="seed_geopolitics.py",
        target_tables=("geo_special_duties",),
        registry_source_id="geo_special_duties_embargo",
        known_gaps=("Fixture/seed — blocked from official ingestion.",),
        manual_review_default=True,
    ),
    PaymentSourceEntry(
        source_code="normative_bundle_example",
        name="Пример normative bundle (не официальный)",
        domains=("import_duty", "vat"),
        authority_level="legacy_seed",
        official_url="",
        legal_basis="example bundle для разработки",
        local_canonical_paths=("data/normative_bundle.example.json",),
        loader_status="manual_review_required",
        target_tables=("hs_rates", "tnved_entries"),
        known_gaps=("revision=example; не использовать для production ingestion.",),
        manual_review_default=True,
    ),
    PaymentSourceEntry(
        source_code="tws_commercial_tariff",
        name="tws.by Excel (коммерческое зеркало тарифа)",
        domains=("import_duty", "vat"),
        authority_level="commercial_mirror",
        official_url="https://www.tws.by/tws/tnved/download",
        legal_basis="Коммерческая выгрузка; не ЕТТ source of truth",
        loader_status="partial",
        sync_script="sync_tws_data.py",
        target_tables=("hs_rates",),
        known_gaps=("Blocked from official ingestion; только diagnostic/commercial mirror.",),
        manual_review_default=True,
    ),
)


def get_payment_source_entry(source_code: str) -> PaymentSourceEntry | None:
    for entry in PAYMENT_SOURCE_REGISTRY:
        if entry.source_code == source_code:
            return entry
    return None


def list_payment_sources_for_domain(domain: str) -> list[PaymentSourceEntry]:
    return [e for e in PAYMENT_SOURCE_REGISTRY if domain in e.domains]


def payment_source_entry_to_dict(entry: PaymentSourceEntry) -> dict[str, Any]:
    return {
        "source_code": entry.source_code,
        "name": entry.name,
        "domains": list(entry.domains),
        "authority_level": entry.authority_level,
        "authority_label": AUTHORITY_LEVEL_LABELS.get(entry.authority_level, entry.authority_level),
        "is_official_contour": entry.authority_level in SOURCE_OF_TRUTH_LEVELS,
        "official_url": entry.official_url,
        "legal_basis": entry.legal_basis,
        "local_canonical_paths": list(entry.local_canonical_paths),
        "source_status_code": entry.source_status_code,
        "effective_from": entry.effective_from,
        "effective_to": entry.effective_to,
        "loader_status": entry.loader_status,
        "sync_script": entry.sync_script,
        "target_tables": list(entry.target_tables),
        "registry_source_id": entry.registry_source_id,
        "known_gaps": list(entry.known_gaps),
        "manual_review_default": entry.manual_review_default,
    }


def list_payment_registry_snapshot() -> list[dict[str, Any]]:
    return [payment_source_entry_to_dict(e) for e in PAYMENT_SOURCE_REGISTRY]
