"""Синхронизация предварительных решений ФТС (FCS) — MVP на fixture / bounded import."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger

from ..db import SessionLocal
from ..models.core import ClassificationDecision, PreliminaryDecision
from .normative_store import (
    append_sync_log,
    upsert_classification_decision,
    upsert_preliminary_decision,
    upsert_source_status,
)

FCS_PRELIMINARY_SOURCE_CODE = "FCS_PRELIMINARY"
# Прежний URL "https://customs.gov.ru/document" отдавал 404 (проверено 2026-06,
# см. scripts/probe_fcs_sources.py). Раздел customs.gov.ru/folder/519 — это
# таможенная статистика, а НЕ реестр предрешений. Корень портала доступен;
# реальные предрешения публикуются за JS/анти-бот барьерами (TKS — клиентский
# JS, Alta — 403), поэтому live-ingest пока не подключён, источник истины —
# fixture с честной маркировкой (FCS-/fcs_official).
FCS_OFFICIAL_URL = "https://customs.gov.ru/"
FCS_OFFICIAL_DECISION_PREFIX = "FCS-"
FCS_PRELIMINARY_SOURCE_TAG = "fcs_official"

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FIXTURE_PATH = _BACKEND_ROOT / "data" / "fixtures" / "fcs_preliminary_decisions.sample.json"


@dataclass(frozen=True)
class FcsPreliminaryRecord:
    hs_code: str
    decision_number: str
    issue_date: str
    product_name: str
    description: str
    target_entity: str


def _normalize_hs(raw: str) -> str:
    return re.sub(r"\D", "", str(raw or ""))[:10]


def _normalize_decision_number(raw: str) -> str:
    dn = str(raw or "").strip()
    if not dn:
        return ""
    if not dn.upper().startswith(FCS_OFFICIAL_DECISION_PREFIX):
        dn = f"{FCS_OFFICIAL_DECISION_PREFIX}{dn.lstrip('-')}"
    return dn[:128]


def count_fcs_official_decisions() -> int:
    """Счётчик официального контура FCS (не Alta/IFCG зеркала)."""
    with SessionLocal() as db:
        cls_count = (
            db.query(ClassificationDecision)
            .filter(ClassificationDecision.decision_number.like(f"{FCS_OFFICIAL_DECISION_PREFIX}%"))
            .count()
        )
        pre_count = (
            db.query(PreliminaryDecision)
            .filter(PreliminaryDecision.source == FCS_PRELIMINARY_SOURCE_TAG)
            .count()
        )
        return cls_count + pre_count


def parse_fcs_preliminary_payload(data: dict[str, Any]) -> list[FcsPreliminaryRecord]:
    """
    Разбор JSON-payload fixture/импорта.

    Raises:
        ValueError: при невалидной структуре или пустом списке items.
    """
    if not isinstance(data, dict):
        raise ValueError("payload must be a JSON object")
    schema_version = str(data.get("schema_version") or "").strip()
    if schema_version != "1":
        raise ValueError(f"unsupported schema_version: {schema_version!r}")
    items = data.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("items must be a non-empty list")

    records: list[FcsPreliminaryRecord] = []
    seen_numbers: set[str] = set()
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"items[{idx}] must be an object")
        hs = _normalize_hs(item.get("hs_code"))
        if len(hs) < 4:
            raise ValueError(f"items[{idx}].hs_code must contain at least 4 digits")
        dn = _normalize_decision_number(str(item.get("decision_number") or ""))
        if not dn:
            raise ValueError(f"items[{idx}].decision_number is required")
        if dn in seen_numbers:
            raise ValueError(f"duplicate decision_number in payload: {dn}")
        seen_numbers.add(dn)
        records.append(
            FcsPreliminaryRecord(
                hs_code=hs,
                decision_number=dn,
                issue_date=str(item.get("issue_date") or "")[:32],
                product_name=str(item.get("product_name") or "").strip(),
                description=str(item.get("description") or "").strip(),
                target_entity=str(item.get("target_entity") or item.get("product_name") or "").strip()[:512],
            )
        )
    return records


def load_fcs_preliminary_fixture(path: Path | None = None) -> list[FcsPreliminaryRecord]:
    fixture_path = Path(path) if path else DEFAULT_FIXTURE_PATH
    if not fixture_path.is_file():
        raise FileNotFoundError(f"fixture not found: {fixture_path}")
    try:
        raw = json.loads(fixture_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in fixture: {exc}") from exc
    return parse_fcs_preliminary_payload(raw)


def import_fcs_preliminary_records(
    records: list[FcsPreliminaryRecord],
    *,
    dry_run: bool = False,
) -> int:
    """UPSERT записей в classification_decisions (+ зеркало в preliminary_decisions)."""
    if dry_run:
        return len(records)
    imported = 0
    for rec in records:
        upsert_classification_decision(
            {
                "hs_code": rec.hs_code,
                "decision_number": rec.decision_number,
                "issue_date": rec.issue_date,
                "product_name": rec.product_name,
                "description": rec.description,
                "target_entity": rec.target_entity,
            }
        )
        pre_desc = (
            f"ПКР ФТС: № {rec.decision_number}; дата: {rec.issue_date or '—'}; "
            f"товар: {rec.product_name}; описание: {rec.description}"
        ).strip()[:12000]
        upsert_preliminary_decision(
            {"hs_code": rec.hs_code, "description": pre_desc},
            source=FCS_PRELIMINARY_SOURCE_TAG,
        )
        imported += 1
    return imported


def _payload_revision(records: list[FcsPreliminaryRecord], *, fixture_path: Path | None) -> str:
    if fixture_path and fixture_path.is_file():
        digest = hashlib.sha256(fixture_path.read_bytes()).hexdigest()[:16]
        return f"fixture-{digest}"
    joined = "|".join(f"{r.decision_number}:{r.hs_code}" for r in records)
    return f"import-{hashlib.sha256(joined.encode('utf-8')).hexdigest()[:16]}"


def _record_sync_success(revision: str, rows_affected: int, note: str) -> None:
    upsert_source_status(
        source_code=FCS_PRELIMINARY_SOURCE_CODE,
        source_name="Предварительные решения ФТС по классификации",
        source_url=FCS_OFFICIAL_URL,
        revision=revision,
        is_stale=False,
        note=note,
    )
    append_sync_log(
        source_code=FCS_PRELIMINARY_SOURCE_CODE,
        status="OK",
        revision=revision,
        rows_affected=rows_affected,
        note=note,
    )


def _record_sync_failure(error: str) -> None:
    upsert_source_status(
        source_code=FCS_PRELIMINARY_SOURCE_CODE,
        source_name="Предварительные решения ФТС по классификации",
        source_url=FCS_OFFICIAL_URL,
        revision="unavailable",
        is_stale=True,
        note=f"Ошибка синхронизации: {error}",
    )
    append_sync_log(
        source_code=FCS_PRELIMINARY_SOURCE_CODE,
        status="ERROR",
        revision="unavailable",
        rows_affected=0,
        note=error,
    )


def sync_fcs_preliminary_decisions(
    *,
    fixture_path: Path | str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Импорт предварительных решений FCS из fixture.

    При ошибке парсинга/чтения возвращает status=ERROR и пишет sync_log (без silent success).
    """
    path = Path(fixture_path) if fixture_path else DEFAULT_FIXTURE_PATH
    try:
        records = load_fcs_preliminary_fixture(path)
        rows = import_fcs_preliminary_records(records, dry_run=dry_run)
        revision = _payload_revision(records, fixture_path=path)
        note = (
            f"MVP fixture import: {rows} записей из {path.name}"
            if not dry_run
            else f"dry-run: {rows} записей распознано в {path.name}"
        )
        if not dry_run:
            _record_sync_success(revision, rows, note)
        return {
            "status": "OK",
            "source": FCS_PRELIMINARY_SOURCE_CODE,
            "revision": revision,
            "rows_affected": rows,
            "document_count": count_fcs_official_decisions() if not dry_run else rows,
            "fixture_path": str(path),
            "dry_run": dry_run,
            "note": note,
        }
    except Exception as exc:
        logger.warning("FCS preliminary sync failed: {}", exc)
        if not dry_run:
            _record_sync_failure(str(exc))
        return {
            "status": "ERROR",
            "source": FCS_PRELIMINARY_SOURCE_CODE,
            "error": str(exc),
            "fixture_path": str(path),
            "dry_run": dry_run,
        }
