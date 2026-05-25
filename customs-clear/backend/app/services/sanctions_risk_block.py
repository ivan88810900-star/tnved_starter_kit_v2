"""
Продуктовый блок санкций и рисков (MVP).

Переиспользует ``compliance_resolver._check_sanction_risks`` и диагностику
реестра нормативных источников. Не меняет broker / payment / normative enforcement.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

from ..db import SessionLocal
from ..models.core import (
    CountryRisk,
    EuSanctionsList,
    GeoSpecialDuty,
    OfacSdnList,
    SanctionImportRisk,
)
from ..schemas.sanctions_risk import (
    RiskBlockStatus,
    RiskSeverity,
    RiskSignalOut,
    SanctionsRiskBlockOut,
    SourceCoverageOut,
)
from .compliance_resolver import _check_sanction_risks
from .regulatory_source_registry import (
    AUTHORITY_LEVEL_LABELS,
    get_registry_entry,
    registry_entry_to_dict,
)

RiskSeverityRank = {
    "clear": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
    "unknown": 4,
    "manual_review_required": 5,
}

SOURCE_LABELS: dict[str, str] = {
    "sanction_import_risks": "Справочник санкционных рисков по ТН ВЭД",
    "country_risks": "Страновые риски / недружественные юрисдикции",
    "geo_special_duties": "Геополитические меры (эмбарго / повышенные ставки)",
    "ofac_sdn_list": "OFAC SDN (США)",
    "eu_sanctions_list": "Консолидированный список санкций ЕС",
    "country_specific_rules": "Страновые правила комплаенса",
}

SANCTIONS_REGISTRY_IDS: tuple[str, ...] = (
    "ofac_sdn_list",
    "eu_sanctions_list",
    "sanction_import_risks",
    "country_risks_geopolitics",
    "geo_special_duties_embargo",
)

HS_SCOPE_SOURCE_IDS: frozenset[str] = frozenset(
    {"sanction_import_risks", "eu_sanctions_list", "geo_special_duties_embargo"}
)
COUNTRY_SCOPE_SOURCE_IDS: frozenset[str] = frozenset({"country_risks_geopolitics", "geo_special_duties_embargo"})
ENTITY_SCOPE_SOURCE_IDS: frozenset[str] = frozenset({"ofac_sdn_list", "eu_sanctions_list"})

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE_PATH = _BACKEND_ROOT / "data/fixtures/sanctions_risk.sample.json"

_DISCLAIMER = (
    "Диагностическая проверка по локальным источникам платформы. "
    "Не заменяет полноценный санкционный скрининг и юридическую экспертизу."
)

_EMPTY_CLEAR_MESSAGE = (
    "По доступным локальным источникам явных санкционных сигналов не выявлено. "
    "Покрытие ограничено — при необходимости выполните расширенную проверку."
)

_COVERAGE_INCOMPLETE_MESSAGE = (
    "Источники санкционных данных не настроены или неполны для данной проверки. "
    "Результат не может быть интерпретирован как «без риска» — требуется ручная проверка."
)


def _norm_hs(raw: str) -> str:
    return re.sub(r"\D", "", str(raw or ""))[:10]


def source_label_for(source: str | None) -> str:
    key = (source or "").strip()
    if not key:
        return "Источник не указан"
    entry = get_registry_entry(key)
    if entry:
        return entry.title
    return SOURCE_LABELS.get(key, key)


def _count_table(probe: str, db) -> int:
    try:
        if probe == "ofac_sdn_list":
            return db.query(OfacSdnList).count()
        if probe == "eu_sanctions_list":
            return db.query(EuSanctionsList).count()
        if probe == "sanction_import_risks":
            return db.query(SanctionImportRisk).count()
        if probe == "country_risks":
            return db.query(CountryRisk).count()
        if probe == "geo_special_duties":
            return db.query(GeoSpecialDuty).count()
    except Exception:
        return 0
    return 0


def _coverage_status_for_entry(source_id: str, count: int, *, fixture_exists: bool) -> str:
    entry = get_registry_entry(source_id)
    if not entry:
        return "not_configured"
    if entry.local_paths and fixture_exists and count == 0:
        return "partial"
    if count < 0:
        return "not_applicable"
    if count == 0:
        if entry.local_paths and fixture_exists:
            return "partial"
        return "missing"
    if count < entry.min_document_count:
        return "partial"
    return "present"


def diagnose_sanctions_source_coverage(db=None) -> tuple[list[SourceCoverageOut], dict[str, str]]:
    """Диагностика покрытия санкционных источников (без полного gap-отчёта)."""
    own = db is None
    session = db or SessionLocal()
    fixture_exists = _FIXTURE_PATH.is_file()
    status_by_id: dict[str, str] = {}
    rows: list[SourceCoverageOut] = []
    try:
        for source_id in SANCTIONS_REGISTRY_IDS:
            entry = get_registry_entry(source_id)
            if not entry:
                continue
            probe = entry.db_probe or ""
            count = _count_table(probe, session) if probe else 0
            cov = _coverage_status_for_entry(source_id, count, fixture_exists=fixture_exists)
            status_by_id[source_id] = cov
            meta = registry_entry_to_dict(entry)
            rows.append(
                SourceCoverageOut(
                    source_id=source_id,
                    title=entry.title,
                    coverage_status=cov,
                    record_count=count if count >= 0 else None,
                    manual_review_required=entry.manual_review_default or cov in {"missing", "partial", "not_configured"},
                    authority_level=meta.get("authority_label"),
                )
            )
    finally:
        if own:
            session.close()
    return rows, status_by_id


def _scope_coverage_complete(
    *,
    status_by_id: dict[str, str],
    country: str | None,
    counterparty: str | None,
) -> bool:
    """Минимальное покрытие для допустимого «clear» по HS/стране."""
    hs_sources_ok = any(status_by_id.get(sid) == "present" for sid in HS_SCOPE_SOURCE_IDS)
    if not hs_sources_ok:
        return False
    if country and not any(status_by_id.get(sid) == "present" for sid in COUNTRY_SCOPE_SOURCE_IDS):
        return False
    if counterparty and not any(status_by_id.get(sid) == "present" for sid in ENTITY_SCOPE_SOURCE_IDS):
        return False
    return True


def _compliance_status_to_severity(status: str, *, source: str) -> RiskSeverity:
    st = (status or "").strip().upper()
    if st == "CRITICAL_RISK":
        return "high"
    if st == "WARNING":
        if source == "eu_sanctions_list":
            return "medium"
        return "medium"
    return "low"


def _source_to_category(source: str, doc: dict[str, Any]) -> str:
    src = (source or "").strip()
    if src == "sanction_import_risks":
        return "hs_sanctions"
    if src == "country_risks":
        return "country_restrictions"
    if src == "geo_special_duties":
        return "embargo"
    if src == "ofac_sdn_list":
        return "counterparty_ofac"
    if src == "eu_sanctions_list":
        if (doc.get("title") or "").lower().find("контрагент") >= 0:
            return "counterparty_eu"
        return "hs_sanctions"
    return "other"


def _doc_to_signal(doc: dict[str, Any]) -> RiskSignalOut:
    source = str(doc.get("source") or "").strip()
    entry = get_registry_entry(source)
    authority = AUTHORITY_LEVEL_LABELS.get(entry.authority_level, entry.authority_level) if entry else None
    legal_ref = str(doc.get("legal_ref") or "").strip() or None
    title = str(doc.get("title") or "").strip()
    detail = str(doc.get("detail") or "").strip()
    explanation = detail or title or "Выявлен санкционный сигнал."
    matched_entity = None
    if "контрагент" in title.lower() or "производитель" in title.lower():
        matched_entity = title.split(":", 1)[-1].strip() if ":" in title else None
    hs_prefix = None
    if legal_ref and "HS" in legal_ref.upper():
        m = re.search(r"HS\s+(\d{4,10})", legal_ref, re.I)
        if m:
            hs_prefix = m.group(1)
    return RiskSignalOut(
        category=_source_to_category(source, doc),
        severity=_compliance_status_to_severity(str(doc.get("compliance_status") or ""), source=source),
        source=source,
        source_label=source_label_for(source),
        authority_level=authority,
        matched_entity=matched_entity,
        matched_hs_prefix=hs_prefix,
        explanation=explanation,
        legal_ref=legal_ref,
    )


def _max_severity(severities: list[RiskSeverity]) -> RiskSeverity:
    if not severities:
        return "clear"
    return max(severities, key=lambda s: RiskSeverityRank.get(s, 99))


def _status_from_severity(severity: RiskSeverity) -> RiskBlockStatus:
    if severity == "high":
        return "CRITICAL"
    if severity in {"medium", "low"}:
        return "WARNING"
    if severity in {"unknown", "manual_review_required"}:
        return "MANUAL_REVIEW"
    return "OK"


def build_sanctions_risk_block(
    *,
    hs_code: str,
    description: str = "",
    country: str | None = None,
    destination_country: str | None = None,
    counterparty_name: str | None = None,
    db=None,
) -> SanctionsRiskBlockOut:
    """Собирает продуктовый блок санкций/рисков для позиции."""
    own = db is None
    session = db or SessionLocal()
    hs = _norm_hs(hs_code)
    counterparty = (counterparty_name or "").strip() or None
    item_data: dict[str, Any] = {}
    if counterparty:
        item_data["counterparty"] = counterparty
        item_data["manufacturer"] = counterparty

    warnings: list[str] = []
    try:
        coverage_rows, status_by_id = diagnose_sanctions_source_coverage(session)
        coverage_complete = _scope_coverage_complete(
            status_by_id=status_by_id,
            country=country,
            counterparty=counterparty,
        )

        missing_sources = [r for r in coverage_rows if r.coverage_status in {"missing", "not_configured"}]
        partial_sources = [r for r in coverage_rows if r.coverage_status == "partial"]
        if missing_sources:
            warnings.append(
                "Не настроены или пусты источники: "
                + ", ".join(r.title for r in missing_sources[:5])
                + ("…" if len(missing_sources) > 5 else "")
            )
        if partial_sources:
            warnings.append(
                "Частичное покрытие источников: "
                + ", ".join(r.title for r in partial_sources[:5])
            )

        sanction_docs, _blocking = _check_sanction_risks(hs, country, item_data or None, session)
        signals = [_doc_to_signal(d) for d in sanction_docs]

        if signals:
            overall = _max_severity([s.severity for s in signals])
            empty_message = None
        elif not coverage_complete:
            overall = "manual_review_required"
            empty_message = _COVERAGE_INCOMPLETE_MESSAGE
            warnings.append(_COVERAGE_INCOMPLETE_MESSAGE)
        else:
            overall = "clear"
            empty_message = _EMPTY_CLEAR_MESSAGE

        stale_like = [r for r in coverage_rows if r.manual_review_required and r.coverage_status != "present"]
        if stale_like and overall == "clear":
            overall = "low"
            warnings.append(
                "Часть санкционных источников помечена как требующая ручной верификации — "
                "результат «без сигналов» не означает полное юридическое покрытие."
            )

        block_status = _status_from_severity(overall)

        return SanctionsRiskBlockOut(
            status=block_status,
            overall_severity=overall,
            hs_code=hs,
            description=(description or "").strip(),
            country=(country or "").strip().upper() or None,
            destination_country=(destination_country or "").strip().upper() or None,
            counterparty_name=counterparty,
            signals=signals,
            warnings=warnings,
            source_coverage=coverage_rows,
            coverage_complete=coverage_complete,
            empty_message=empty_message,
            disclaimer=_DISCLAIMER,
        )
    finally:
        if own:
            session.close()


def load_sanctions_risk_fixture(db=None) -> int:
    """Загружает fixture в БД (идемпотентно для тестов)."""
    if not _FIXTURE_PATH.is_file():
        return 0
    payload = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    own = db is None
    session = db or SessionLocal()
    inserted = 0
    try:
        for row in payload.get("sanction_import_risks") or []:
            pref = _norm_hs(str(row.get("hs_code_prefix") or ""))[:10]
            if len(pref) < 4:
                continue
            exists = (
                session.query(SanctionImportRisk.id)
                .filter(
                    SanctionImportRisk.hs_code_prefix == pref,
                    SanctionImportRisk.jurisdiction == str(row.get("jurisdiction") or "EU"),
                )
                .first()
            )
            if exists:
                continue
            session.add(
                SanctionImportRisk(
                    hs_code_prefix=pref,
                    jurisdiction=str(row.get("jurisdiction") or "EU"),
                    risk_level=str(row.get("risk_level") or "risk"),
                    description=str(row.get("description") or ""),
                )
            )
            inserted += 1

        for row in payload.get("ofac_sdn_list") or []:
            name = str(row.get("name") or "").strip()
            if not name:
                continue
            exists = (
                session.query(OfacSdnList.id)
                .filter(
                    OfacSdnList.name == name,
                    OfacSdnList.type == str(row.get("type") or "entity"),
                )
                .first()
            )
            if exists:
                continue
            session.add(
                OfacSdnList(
                    name=name,
                    type=str(row.get("type") or "entity"),
                    origin_country=str(row.get("origin_country") or ""),
                    aliases=str(row.get("aliases") or ""),
                )
            )
            inserted += 1

        for row in payload.get("eu_sanctions_list") or []:
            hs = _norm_hs(str(row.get("hs_code") or ""))
            desc = str(row.get("description") or "")
            entity = str(row.get("entity_name") or "")
            exists = (
                session.query(EuSanctionsList.id)
                .filter(
                    EuSanctionsList.hs_code == hs,
                    EuSanctionsList.entity_name == entity,
                    EuSanctionsList.description == desc,
                )
                .first()
            )
            if exists:
                continue
            session.add(
                EuSanctionsList(
                    hs_code=hs,
                    entity_name=entity,
                    description=desc,
                )
            )
            inserted += 1

        for row in payload.get("country_risks") or []:
            iso = str(row.get("iso_code") or "").strip().upper()
            if not iso:
                continue
            if session.query(CountryRisk).filter(CountryRisk.iso_code == iso).first():
                continue
            session.add(
                CountryRisk(
                    iso_code=iso,
                    name_ru=str(row.get("name_ru") or ""),
                    is_unfriendly=bool(row.get("is_unfriendly")),
                    has_preference=bool(row.get("has_preference")),
                    required_cert=str(row.get("required_cert") or ""),
                )
            )
            inserted += 1

        for row in payload.get("geo_special_duties") or []:
            pref = _norm_hs(str(row.get("hs_code_prefix") or ""))[:10]
            country_iso = str(row.get("country_iso") or "").strip().upper()
            basis = str(row.get("document_basis") or "")
            exists = (
                session.query(GeoSpecialDuty.id)
                .filter(
                    GeoSpecialDuty.hs_code_prefix == pref,
                    GeoSpecialDuty.country_iso == country_iso,
                    GeoSpecialDuty.document_basis == basis,
                )
                .first()
            )
            if exists:
                continue
            session.add(
                GeoSpecialDuty(
                    hs_code_prefix=pref,
                    country_iso=country_iso,
                    duty_rate=str(row.get("duty_rate") or "0"),
                    document_basis=basis,
                    measure_type=str(row.get("measure_type") or "embargo"),
                    document_link=str(row.get("document_link") or ""),
                )
            )
            inserted += 1

        session.commit()
    finally:
        if own:
            session.close()
    return inserted
