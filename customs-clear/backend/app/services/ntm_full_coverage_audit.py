"""Каталожный аудит полного NTM-блока без изменения БД и enforcement."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from .. import db
from ..models.tnved import Chapter, Commodity, Section
from .ntm_catalog_baseline import (
    active_ett_fingerprint,
    catalog_fingerprint,
    compare_source_baseline,
    load_catalog_baseline,
    pdf_source_manifest,
)
from .ntm_layers import LICENCE_DOMAINS, NF_DOMAINS, PHYTO_DOMAINS, SGR_DOMAINS, VET_DOMAINS
from .official_ntm_contours import (
    DECISION_317_VET_GENERAL_RANGES,
    DECISION_318_PHYTO_HIGH_RISK_RANGES,
    DECISION_318_PHYTO_LOW_RISK_RANGES,
    DECISION_299_SGR_RANGES,
    DECISION_30_SECTIONS,
    DECISION_30_SECTION_216_RANGES,
    DECISION_30_SECTION_219_RANGES,
    OFFICIAL_NTM_FAMILIES,
    _DECISION_317_VET_CONDITIONAL_RULES,
    _DECISION_30_SPECIAL_RULES,
    _TABLEWARE_RULES,
    _TECHNICAL_CHARACTERISTIC_RULES,
    evaluate_official_ntm_contours,
)
from .official_export_control import export_control_dataset_summary, load_export_control_dataset
from .tr_ts_catalog import ALL_REGULATIONS, TR_TS_FULL_NAMES, get_full_ntm_requirements


# Эти регламенты намеренно не получают широкую товарную привязку: 047/048 и
# 053 не включены в broker enforcement до подтверждения вступления/переходных
# положений и точного перечня, 049 регулирует магистральный трубопровод как объект.
_ALLOWED_TECHNICAL_WITHOUT_HS_FILTER = {"047/2018", "048/2019", "049/2020", "053/2026"}
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ETT_CATALOG_PATH = _BACKEND_ROOT / "data" / "raw_normative" / "eec_ett_normative_bundle.json"
CODE_CATALOG_MINIMUM = 10_000
REFERENCE_TNVED_SECTIONS = 21
REFERENCE_TNVED_CHAPTERS = 96
REFERENCE_TNVED_COMMODITIES = 17_809
# В закреплённом reference-корпусе из 96 PDF ровно 35 десятизначных строк
# не имеют наименования и не входят в pinned active ETT rate snapshot.
# Это не утверждает причину их отсутствия или юридический статус. Все 13 290 кодов
# pinned active ETT snapshot обязаны присутствовать и иметь описание.
REFERENCE_TNVED_DESCRIPTIONS = 17_774
REFERENCE_ACTIVE_ETT_CODES = 13_290
FULL_COMMODITY_CATALOG_MINIMUM = REFERENCE_TNVED_COMMODITIES

CATALOG_REFERENCE_MINIMUMS = {
    "tnved_sections": REFERENCE_TNVED_SECTIONS,
    "tnved_chapters": REFERENCE_TNVED_CHAPTERS,
    "tnved_commodities": REFERENCE_TNVED_COMMODITIES,
    "commodity_descriptions": REFERENCE_TNVED_DESCRIPTIONS,
}

_FULL_CATALOG_SOURCES = {
    "tnved_commodities",
    "explicit_sqlite_tnved_commodities",
}
_CODE_CATALOG_SOURCES = _FULL_CATALOG_SOURCES | {"official_ett_rate_codes"}


def _family_for_permit(permit_type: str) -> str | None:
    if permit_type in {"ДС", "СС"}:
        return "technical_conformity"
    return {
        "СГР": "sanitary_registration",
        "ВС": "veterinary_control",
        "ФСС": "phytosanitary_control",
        "НФ": "cryptography",
        "ЛЗ": "licensing",
        "ЛЗ ФСТЭК": "export_control_dual_use",
        "ЛЗ/разрешение ФСТЭК": "export_control_dual_use",
    }.get(permit_type)


def _signals_for_position(hs_code: str, description: str) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    for row in get_full_ntm_requirements(hs_code, description):
        permit_type = str(row.get("permit_type") or "")
        family = _family_for_permit(permit_type)
        if not family:
            continue
        signals.append({
            "family": family,
            "permit_type": permit_type,
            "tr_ts": row.get("tr_ts"),
            "source": "catalog_coverage_audit",
            "source_label": "Каталог требований",
        })
    return signals


def _synthetic_positions() -> list[tuple[str, str]]:
    prefixes: set[str] = {prefix for prefix, _, _ in ALL_REGULATIONS}
    for values in (VET_DOMAINS, PHYTO_DOMAINS, SGR_DOMAINS, NF_DOMAINS, LICENCE_DOMAINS):
        prefixes.update(values)
    prefixes.update(DECISION_30_SECTION_216_RANGES)
    prefixes.update(DECISION_30_SECTION_219_RANGES)
    prefixes.update(DECISION_299_SGR_RANGES)
    prefixes.update(DECISION_317_VET_GENERAL_RANGES)
    prefixes.update(DECISION_318_PHYTO_HIGH_RISK_RANGES)
    prefixes.update(DECISION_318_PHYTO_LOW_RISK_RANGES)
    prefixes.update(load_export_control_dataset()["hs_candidates"])
    for rule in _DECISION_30_SPECIAL_RULES:
        prefixes.update(rule["prefixes"])
    for rule in _TABLEWARE_RULES:
        prefixes.update(rule["prefixes"])
    for rule in _TECHNICAL_CHARACTERISTIC_RULES:
        prefixes.update(rule["prefixes"])
    for rule in _DECISION_317_VET_CONDITIONAL_RULES:
        prefixes.update(rule["prefixes"])
    rows = []
    for prefix in sorted(prefixes):
        code = (prefix + "0" * 10)[:10]
        rows.append((code, "контрольная товарная позиция"))
    return rows


def _load_official_ett_positions(
    path: Path = DEFAULT_ETT_CATALOG_PATH,
    *,
    limit: int | None = None,
) -> tuple[list[tuple[str, str]], dict[str, Any]]:
    """Читает code-only срез из ETT; он не заменяет каталог с описаниями."""
    if not path.is_file():
        return [], {"catalog_error": f"official ETT bundle not found: {path.name}"}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [], {"catalog_error": f"cannot read official ETT bundle: {exc}"}
    rates = payload.get("rates")
    if not isinstance(rates, list):
        return [], {"catalog_error": "official ETT bundle has no rates array"}
    raw_codes = [
        str(row.get("hs_code") or "").strip()
        for row in rates
        if isinstance(row, dict)
    ]
    valid_codes = [code for code in raw_codes if code.isdigit() and len(code) == 10]
    codes = sorted(set(valid_codes))
    total_unique_codes = len(codes)
    if limit is not None:
        codes = codes[:limit]
    return [(code, "") for code in codes], {
        "catalog_revision": payload.get("revision"),
        "catalog_effective_from": payload.get("effective_from"),
        "catalog_official_url": payload.get("official_ett_url") or payload.get("source_url"),
        "catalog_raw_rows": len(rates),
        "catalog_rows": len(rates),
        "catalog_unique_codes": total_unique_codes,
        "catalog_duplicate_rows": len(valid_codes) - total_unique_codes,
        "catalog_invalid_code_rows": len(rates) - len(valid_codes),
        "catalog_sections": 0,
        "catalog_chapters": 0,
        "description_rows": 0,
        "description_coverage_pct": 0.0,
        "positions_loaded": len(codes),
    }


def _deduplicate_catalog_rows(
    raw_rows: Iterable[tuple[Any, Any]],
) -> tuple[list[tuple[str, str]], dict[str, int]]:
    """Нормализует DB-строки, сохраняя самое информативное описание кода."""
    materialized = [
        (str(code or "").strip(), str(description or "").strip())
        for code, description in raw_rows
    ]
    by_code: dict[str, str] = {}
    invalid_code_rows = 0
    for code, description in materialized:
        if not code.isdigit() or len(code) not in {4, 10}:
            invalid_code_rows += 1
            continue
        if code not in by_code or len(description) > len(by_code[code]):
            by_code[code] = description
    rows = sorted(by_code.items())
    return rows, {
        "catalog_rows": len(materialized),
        "catalog_unique_codes": len(rows),
        "catalog_duplicate_rows": len(materialized) - invalid_code_rows - len(rows),
        "catalog_invalid_code_rows": invalid_code_rows,
        "description_rows": sum(bool(description) for _, description in rows),
    }


def _active_ett_coverage_metadata(
    rows: Iterable[tuple[str, str]],
    *,
    active_codes: frozenset[str],
    revision: str | None,
) -> dict[str, Any]:
    """Проверяет присутствие и описания всех действующих code-only ETT строк."""
    by_code = {str(code): str(description or "").strip() for code, description in rows}
    present = active_codes & by_code.keys()
    described = {code for code in present if by_code[code]}
    return {
        "active_ett_reference_available": bool(active_codes),
        "active_ett_reference_revision": revision,
        "active_ett_reference_codes": len(active_codes),
        "active_ett_codes_present": len(present),
        "active_ett_codes_described": len(described),
        "active_ett_codes_missing": len(active_codes - present),
        "active_ett_codes_without_description": len(present - described),
    }


def _catalog_baseline_metadata(
    metadata: dict[str, Any],
    *,
    catalog_path: Path,
    active_codes: frozenset[str],
) -> dict[str, Any]:
    """Сверяет DB fingerprint с закреплёнными PDF/ETT/catalog manifests."""
    blank_codes = sorted(str(code) for code in metadata.get("blank_description_codes") or [])
    blank_active = sorted(set(blank_codes) & active_codes)
    common = {
        "blank_description_codes": blank_codes,
        "blank_codes_in_active_ett_snapshot": blank_active,
        "blank_codes_not_in_active_ett_snapshot": sorted(set(blank_codes) - active_codes),
        "overall_description_coverage_pct": (
            round(
                100.0
                * int(metadata.get("description_rows") or 0)
                / int(metadata.get("catalog_unique_codes") or 0),
                4,
            )
            if int(metadata.get("catalog_unique_codes") or 0)
            else 0.0
        ),
        "active_description_coverage_pct": (
            round(
                100.0
                * int(metadata.get("active_ett_codes_described") or 0)
                / int(metadata.get("active_ett_reference_codes") or 0),
                4,
            )
            if int(metadata.get("active_ett_reference_codes") or 0)
            else 0.0
        ),
    }
    try:
        baseline = load_catalog_baseline()
        current_pdf = pdf_source_manifest()
        current_ett = active_ett_fingerprint(catalog_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            **common,
            "catalog_baseline_available": False,
            "catalog_baseline_error": str(exc),
            "pdf_source_manifest_match": False,
            "active_ett_snapshot_match": False,
            "catalog_parser_match": False,
            "catalog_baseline_section_set_match": False,
            "catalog_baseline_chapter_set_match": False,
            "catalog_baseline_code_set_match": False,
            "catalog_baseline_code_description_match": False,
        }

    expected_catalog = baseline["catalog"]
    source_comparison = compare_source_baseline(
        baseline,
        pdf_source=current_pdf,
        active_ett=current_ett,
    )
    return {
        **common,
        **source_comparison,
        "catalog_baseline_available": True,
        "catalog_baseline_dataset_id": baseline.get("dataset_id"),
        "catalog_baseline_qualification": baseline.get("qualification"),
        "catalog_baseline_section_set_match": (
            metadata.get("catalog_section_codes") == expected_catalog.get("section_codes")
        ),
        "catalog_baseline_chapter_set_match": (
            metadata.get("catalog_chapter_codes") == expected_catalog.get("chapter_codes")
        ),
        "catalog_baseline_code_set_match": (
            metadata.get("catalog_code_set_sha256") == expected_catalog.get("code_set_sha256")
        ),
        "catalog_baseline_code_description_match": (
            metadata.get("catalog_code_description_sha256")
            == expected_catalog.get("code_description_sha256")
        ),
        "catalog_baseline_pdf_manifest_sha256": baseline["pdf_source"].get("manifest_sha256"),
        "catalog_baseline_code_set_sha256": expected_catalog.get("code_set_sha256"),
        "catalog_baseline_code_description_sha256": expected_catalog.get(
            "code_description_sha256"
        ),
    }


def _load_sqlite_catalog_positions(
    path: Path,
    *,
    limit: int | None = None,
    active_codes: frozenset[str] = frozenset(),
    active_revision: str | None = None,
) -> tuple[list[tuple[str, str]], dict[str, Any]]:
    """Read-only загрузка каталога из явного SQLite-файла без app migrations."""
    if not path.is_file():
        return [], {"catalog_error": f"SQLite catalog not found: {path.name}"}
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
        connection.execute("PRAGMA query_only=ON")
        section_codes = sorted(
            str(row[0] or "").strip()
            for row in connection.execute("SELECT roman_number FROM tnved_sections")
        )
        chapter_codes = sorted(
            str(row[0] or "").strip()
            for row in connection.execute("SELECT code FROM tnved_chapters")
        )
        raw_rows = list(
            connection.execute(
                "SELECT code, description FROM tnved_commodities ORDER BY code"
            )
        )
    except sqlite3.Error as exc:
        return [], {"catalog_error": f"cannot read SQLite catalog: {exc}"}
    finally:
        if connection is not None:
            connection.close()
    rows, metadata = _deduplicate_catalog_rows(raw_rows)
    fingerprint = catalog_fingerprint(rows)
    active_metadata = _active_ett_coverage_metadata(
        rows,
        active_codes=active_codes,
        revision=active_revision,
    )
    if limit is not None:
        rows = rows[:limit]
    described = int(metadata["description_rows"])
    return rows, {
        **metadata,
        "catalog_section_codes": section_codes,
        "catalog_chapter_codes": chapter_codes,
        "blank_description_codes": fingerprint["blank_description_codes"],
        "catalog_code_set_sha256": fingerprint["code_set_sha256"],
        "catalog_code_description_sha256": fingerprint["code_description_sha256"],
        **active_metadata,
        "catalog_sections": len(section_codes),
        "catalog_chapters": len(chapter_codes),
        "description_coverage_pct": (
            round(100.0 * described / int(metadata["catalog_unique_codes"]), 4)
            if metadata["catalog_unique_codes"]
            else 0.0
        ),
        "catalog_database_size_bytes": path.stat().st_size,
        "positions_loaded": len(rows),
    }


def _load_application_catalog_positions(
    *,
    limit: int | None = None,
    active_codes: frozenset[str] = frozenset(),
    active_revision: str | None = None,
) -> tuple[list[tuple[str, str]], dict[str, Any]]:
    """Читает агрегаты и позиции из настроенной application DB."""
    with db.SessionLocal() as session:
        raw_rows = list(
            session.execute(
                select(Commodity.code, Commodity.description).order_by(Commodity.code)
            )
        )
        section_codes = sorted(
            str(value or "").strip()
            for value in session.scalars(select(Section.roman_number))
        )
        chapter_codes = sorted(
            str(value or "").strip()
            for value in session.scalars(select(Chapter.code))
        )
    rows, metadata = _deduplicate_catalog_rows(raw_rows)
    fingerprint = catalog_fingerprint(rows)
    active_metadata = _active_ett_coverage_metadata(
        rows,
        active_codes=active_codes,
        revision=active_revision,
    )
    if limit is not None:
        rows = rows[:limit]
    described = int(metadata["description_rows"])
    unique_codes = int(metadata["catalog_unique_codes"])
    return rows, {
        **metadata,
        "catalog_section_codes": section_codes,
        "catalog_chapter_codes": chapter_codes,
        "blank_description_codes": fingerprint["blank_description_codes"],
        "catalog_code_set_sha256": fingerprint["code_set_sha256"],
        "catalog_code_description_sha256": fingerprint["code_description_sha256"],
        **active_metadata,
        "catalog_sections": len(section_codes),
        "catalog_chapters": len(chapter_codes),
        "description_coverage_pct": (
            round(100.0 * described / unique_codes, 4) if unique_codes else 0.0
        ),
        "positions_loaded": len(rows),
    }


def load_catalog_positions(
    limit: int | None = None,
    *,
    catalog_path: Path = DEFAULT_ETT_CATALOG_PATH,
    database_path: Path | None = None,
) -> tuple[list[tuple[str, str]], str, dict[str, Any]]:
    """Читает DB-каталог либо отдельный code-only ETT fallback без synthetic-подмены."""
    ett_all_rows, ett_metadata = _load_official_ett_positions(catalog_path)
    active_codes = frozenset(code for code, _ in ett_all_rows)
    active_revision = (
        str(ett_metadata.get("catalog_revision"))
        if ett_metadata.get("catalog_revision")
        else None
    )
    if database_path is not None:
        explicit_rows, metadata = _load_sqlite_catalog_positions(
            database_path,
            limit=limit,
            active_codes=active_codes,
            active_revision=active_revision,
        )
        metadata.update(_catalog_baseline_metadata(
            metadata,
            catalog_path=catalog_path,
            active_codes=active_codes,
        ))
        return explicit_rows, "explicit_sqlite_tnved_commodities", metadata

    application_catalog_error: str | None = None
    try:
        rows, db_metadata = _load_application_catalog_positions(
            limit=limit,
            active_codes=active_codes,
            active_revision=active_revision,
        )
    except SQLAlchemyError as exc:
        # A fresh CI checkout intentionally has no application SQLite file.
        # Keep the audit read-only and fall back to the pinned code-only ETT
        # scope; full-catalog mode still fails closed below.
        rows = []
        db_metadata = {
            "catalog_rows": 0,
            "catalog_unique_codes": 0,
            "catalog_duplicate_rows": 0,
            "catalog_invalid_code_rows": 0,
            "description_rows": 0,
            "catalog_sections": 0,
            "catalog_chapters": 0,
            "positions_loaded": 0,
        }
        application_catalog_error = f"cannot read application catalog: {exc}"
    if int(db_metadata.get("catalog_unique_codes") or 0) >= CODE_CATALOG_MINIMUM:
        db_metadata.update(_catalog_baseline_metadata(
            db_metadata,
            catalog_path=catalog_path,
            active_codes=active_codes,
        ))
        return rows, "tnved_commodities", db_metadata

    ett_rows = ett_all_rows[:limit] if limit is not None else ett_all_rows
    metadata = {
        **ett_metadata,
        **_active_ett_coverage_metadata(
            ett_all_rows,
            active_codes=active_codes,
            revision=active_revision,
        ),
        "positions_loaded": len(ett_rows),
    }
    metadata.update(_catalog_baseline_metadata(
        metadata,
        catalog_path=catalog_path,
        active_codes=active_codes,
    ))
    if ett_rows:
        metadata["lightweight_db_rows_ignored"] = int(
            db_metadata.get("catalog_unique_codes") or 0
        )
        if application_catalog_error:
            metadata["application_catalog_error"] = application_catalog_error
        return ett_rows, "official_ett_rate_codes", metadata

    return rows, "tnved_commodities", {
        **db_metadata,
        **metadata,
        **(
            {"application_catalog_error": application_catalog_error}
            if application_catalog_error
            else {}
        ),
    }


def _catalog_scope(
    *,
    source: str,
    positions_loaded: int,
    metadata: dict[str, Any],
    limit: int | None,
) -> dict[str, Any]:
    """Возвращает доказуемый scope; неполный прогон не повышается до full."""
    actual = {
        "catalog_rows": int(metadata.get("catalog_rows") or 0),
        "tnved_sections": int(metadata.get("catalog_sections") or 0),
        "tnved_chapters": int(metadata.get("catalog_chapters") or 0),
        "tnved_commodities": int(metadata.get("catalog_unique_codes") or 0),
        "commodity_descriptions": int(metadata.get("description_rows") or 0),
        "positions_loaded": positions_loaded,
        "duplicate_rows": int(metadata.get("catalog_duplicate_rows") or 0),
        "invalid_code_rows": int(metadata.get("catalog_invalid_code_rows") or 0),
        "blank_description_rows": max(
            0,
            int(metadata.get("catalog_unique_codes") or 0)
            - int(metadata.get("description_rows") or 0),
        ),
        "active_ett_reference_codes": int(metadata.get("active_ett_reference_codes") or 0),
        "active_ett_codes_present": int(metadata.get("active_ett_codes_present") or 0),
        "active_ett_codes_described": int(metadata.get("active_ett_codes_described") or 0),
        "active_ett_codes_missing": int(metadata.get("active_ett_codes_missing") or 0),
        "active_ett_codes_without_description": int(
            metadata.get("active_ett_codes_without_description") or 0
        ),
    }
    full_gate_failures: list[str] = []
    if source not in _FULL_CATALOG_SOURCES:
        full_gate_failures.append("source_has_no_commodity_descriptions")
    if limit is not None:
        full_gate_failures.append("limited_run")
    exact_reference_counts = {
        "tnved_sections": REFERENCE_TNVED_SECTIONS,
        "tnved_chapters": REFERENCE_TNVED_CHAPTERS,
        "tnved_commodities": REFERENCE_TNVED_COMMODITIES,
    }
    for field, expected in exact_reference_counts.items():
        if actual[field] != expected:
            full_gate_failures.append(f"{field}_not_equal_{expected}")
    if actual["commodity_descriptions"] < REFERENCE_TNVED_DESCRIPTIONS:
        full_gate_failures.append(
            f"commodity_descriptions_below_{REFERENCE_TNVED_DESCRIPTIONS}"
        )
    if actual["catalog_rows"] != REFERENCE_TNVED_COMMODITIES:
        full_gate_failures.append(f"catalog_rows_not_equal_{REFERENCE_TNVED_COMMODITIES}")
    if positions_loaded != REFERENCE_TNVED_COMMODITIES:
        full_gate_failures.append(f"positions_loaded_not_equal_{REFERENCE_TNVED_COMMODITIES}")
    if actual["duplicate_rows"]:
        full_gate_failures.append("duplicate_catalog_codes")
    if actual["invalid_code_rows"]:
        full_gate_failures.append("invalid_catalog_codes")
    if not metadata.get("active_ett_reference_available"):
        full_gate_failures.append("active_ett_reference_unavailable")
    elif actual["active_ett_reference_codes"] < REFERENCE_ACTIVE_ETT_CODES:
        full_gate_failures.append(
            f"active_ett_reference_codes_below_{REFERENCE_ACTIVE_ETT_CODES}"
        )
    else:
        if actual["active_ett_codes_present"] < actual["active_ett_reference_codes"]:
            full_gate_failures.append("active_ett_codes_missing_from_catalog")
        if actual["active_ett_codes_described"] < actual["active_ett_reference_codes"]:
            full_gate_failures.append("active_ett_codes_without_description")
    if metadata.get("blank_codes_in_active_ett_snapshot"):
        full_gate_failures.append("blank_codes_overlap_active_ett_snapshot")
    baseline_gates = {
        "catalog_baseline_available": "catalog_baseline_unavailable",
        "pdf_source_manifest_match": "pdf_source_manifest_mismatch",
        "active_ett_snapshot_match": "active_ett_snapshot_mismatch",
        "catalog_parser_match": "catalog_parser_mismatch",
        "catalog_baseline_section_set_match": "catalog_section_set_mismatch",
        "catalog_baseline_chapter_set_match": "catalog_chapter_set_mismatch",
        "catalog_baseline_code_set_match": "catalog_code_set_mismatch",
        "catalog_baseline_code_description_match": "catalog_code_description_mismatch",
    }
    for field, failure in baseline_gates.items():
        if metadata.get(field) is not True:
            full_gate_failures.append(failure)

    code_catalog_complete = bool(
        source in _CODE_CATALOG_SOURCES
        and limit is None
        and actual["tnved_commodities"] >= CODE_CATALOG_MINIMUM
        and positions_loaded >= CODE_CATALOG_MINIMUM
    )
    full_catalog_complete = not full_gate_failures
    if full_catalog_complete:
        kind = "full_commodity_catalog"
    elif limit is not None:
        kind = "limited_catalog_sample"
    elif source == "official_ett_rate_codes":
        kind = "code_only_catalog"
    elif source in _FULL_CATALOG_SOURCES and positions_loaded:
        kind = "partial_commodity_catalog"
    else:
        kind = "catalog_unavailable"

    return {
        "kind": kind,
        "limited": limit is not None,
        "description_aware": actual["commodity_descriptions"] > 0,
        "active_ett_description_complete": bool(
            metadata.get("active_ett_reference_available")
            and actual["active_ett_reference_codes"] >= REFERENCE_ACTIVE_ETT_CODES
            and actual["active_ett_codes_present"] == actual["active_ett_reference_codes"]
            and actual["active_ett_codes_described"] == actual["active_ett_reference_codes"]
        ),
        "overall_description_coverage_pct": float(
            metadata.get("overall_description_coverage_pct") or 0.0
        ),
        "active_description_coverage_pct": float(
            metadata.get("active_description_coverage_pct") or 0.0
        ),
        "code_catalog_verified": code_catalog_complete,
        "full_catalog_verified": full_catalog_complete,
        "full_catalog_gate_failures": full_gate_failures,
        "reference_minimums": dict(CATALOG_REFERENCE_MINIMUMS),
        "actual_counts": actual,
    }


def audit_ntm_full_coverage(positions: Iterable[tuple[str, str]]) -> dict[str, Any]:
    expected_families = {row["family"] for row in OFFICIAL_NTM_FAMILIES}
    invalid_matrix: list[str] = []
    enforcement_leaks: list[str] = []
    evaluated = 0
    status_counts: dict[str, int] = {}
    requirement_family_counts: dict[str, int] = {}
    requirement_permit_counts: dict[str, int] = {}
    observed_sections: set[str] = set()
    requirements_evaluated = 0
    for hs_code, description in positions:
        signals = _signals_for_position(hs_code, description)
        result = evaluate_official_ntm_contours(
            hs_code,
            description,
            family_signals=signals,
        )
        evaluated += 1
        families = {str(row.get("family")) for row in result["measure_families"]}
        if families != expected_families or len(result["measure_families"]) != len(expected_families):
            invalid_matrix.append(hs_code)
        if any(row.get("used_for_missing_check") is not False for row in result["requirements"]):
            enforcement_leaks.append(hs_code)
        for row in result["requirements"]:
            requirements_evaluated += 1
            family = str(row.get("family") or "unknown")
            requirement_family_counts[family] = requirement_family_counts.get(family, 0) + 1
            permit_type = str(row.get("permit_type") or "unknown")
            requirement_permit_counts[permit_type] = requirement_permit_counts.get(permit_type, 0) + 1
            if row.get("section"):
                observed_sections.add(str(row["section"]))
        for row in result["measure_families"]:
            status = str(row.get("status") or "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1

    indexed_sections = {row["section"] for row in DECISION_30_SECTIONS}
    rule_sections = {str(row["section"]) for row in _DECISION_30_SPECIAL_RULES} | {"2.16", "2.19"}
    regulations_with_hs_rules = {tr_ts for _, tr_ts, _ in ALL_REGULATIONS}
    advisory_regulations_with_hs_filters = {
        str(rule["tr_ts"]) for rule in _TECHNICAL_CHARACTERISTIC_RULES
    }
    regulations_with_primary_filter = regulations_with_hs_rules | advisory_regulations_with_hs_filters
    regulations_without_filter = set(TR_TS_FULL_NAMES) - regulations_with_primary_filter
    unexpected_regulation_gaps = regulations_without_filter - _ALLOWED_TECHNICAL_WITHOUT_HS_FILTER
    export_summary = export_control_dataset_summary()
    return {
        "positions_evaluated": evaluated,
        "families_per_position": len(expected_families),
        "invalid_matrix_count": len(invalid_matrix),
        "invalid_matrix_examples": invalid_matrix[:20],
        # Legacy names are retained for evidence compatibility; this check is
        # scoped only to rows emitted by the official advisory contour.
        "enforcement_leak_count": len(enforcement_leaks),
        "enforcement_leak_examples": enforcement_leaks[:20],
        "official_contour_enforcement_leak_count": len(enforcement_leaks),
        "official_contour_enforcement_leak_examples": enforcement_leaks[:20],
        "decision_30_sections_indexed": len(indexed_sections),
        "decision_30_sections_with_primary_filter": len(rule_sections),
        "decision_30_sections_without_primary_filter": sorted(indexed_sections - rule_sections),
        "decision_30_sections_observed": sorted(observed_sections & indexed_sections),
        "decision_30_sections_not_observed": sorted(indexed_sections - observed_sections),
        "decision_299_sgr_ranges": len(DECISION_299_SGR_RANGES),
        # Legacy field remains the source-faithful raw union; effective runtime
        # scope excludes versioned retired exact codes.
        "export_control_hs_candidates": export_summary["raw_candidate_count"],
        "export_control_hs_candidates_raw": export_summary["raw_candidate_count"],
        "export_control_hs_candidates_effective": export_summary["effective_candidate_count"],
        "export_control_retired_exact_codes": export_summary["retired_exact_code_count"],
        "export_control_identification_scope": export_summary["identification_scope"],
        "export_control_technical_parameters_covered": export_summary[
            "technical_parameters_covered"
        ],
        "technical_regulations_registered": len(TR_TS_FULL_NAMES),
        "technical_regulations_with_broker_hs_rules": len(regulations_with_hs_rules),
        "technical_regulations_with_primary_filter": len(regulations_with_primary_filter),
        "technical_regulations_without_hs_filter": sorted(regulations_without_filter),
        "technical_regulations_unexpected_gaps": sorted(unexpected_regulation_gaps),
        "status_counts": status_counts,
        "requirements_evaluated": requirements_evaluated,
        "requirement_family_counts": dict(sorted(requirement_family_counts.items())),
        "requirement_permit_counts": dict(sorted(requirement_permit_counts.items())),
        "ok": (
            evaluated > 0
            and not invalid_matrix
            and not enforcement_leaks
            and indexed_sections == rule_sections
            and not unexpected_regulation_gaps
        ),
    }


def build_ntm_full_coverage_report(
    limit: int | None = None,
    *,
    catalog_path: Path = DEFAULT_ETT_CATALOG_PATH,
    database_path: Path | None = None,
    require_code_catalog: bool = False,
    require_full_catalog: bool = True,
) -> dict[str, Any]:
    if limit is not None and limit <= 0:
        raise ValueError("limit must be positive")
    positions, source, metadata = load_catalog_positions(
        limit,
        catalog_path=catalog_path,
        database_path=database_path,
    )
    report = audit_ntm_full_coverage(positions)
    structural_ok = bool(report.get("ok"))
    report["position_source"] = source
    report.update(metadata)
    scope = _catalog_scope(
        source=source,
        positions_loaded=len(positions),
        metadata=metadata,
        limit=limit,
    )
    report["audit_scope"] = scope["kind"]
    report["scope"] = scope
    report["catalog_reference_minimums"] = scope["reference_minimums"]
    report["catalog_actual_counts"] = scope["actual_counts"]
    report["code_catalog_complete"] = scope["code_catalog_verified"]
    report["catalog_complete"] = scope["full_catalog_verified"]
    report["full_catalog_required"] = require_full_catalog
    report["code_catalog_required"] = require_code_catalog
    report["limited_run"] = limit is not None
    report["audit_claim"] = (
        "official_advisory_structure_and_pinned_catalog_coverage"
    )
    report["legal_applicability_proven_for_every_position"] = False

    probes = audit_ntm_full_coverage(_synthetic_positions())
    report["rule_probe_positions_evaluated"] = probes["positions_evaluated"]
    probe_family_gaps = sorted(
        {row["family"] for row in OFFICIAL_NTM_FAMILIES}
        - set(probes["requirement_family_counts"])
    )
    report["rule_probe_family_candidate_counts"] = probes["requirement_family_counts"]
    report["rule_probe_family_gaps"] = probe_family_gaps
    report["rule_probe_decision_30_sections_observed"] = probes["decision_30_sections_observed"]
    report["rule_probe_decision_30_sections_not_observed"] = probes["decision_30_sections_not_observed"]
    report["rule_probe_ok"] = bool(
        probes["ok"]
        and not probe_family_gaps
        and not probes["decision_30_sections_not_observed"]
    )
    report["total_position_evaluations"] = report["positions_evaluated"] + probes["positions_evaluated"]
    report["structural_ok"] = bool(structural_ok and report["rule_probe_ok"])
    report["ok"] = bool(
        report["structural_ok"]
        and (report["code_catalog_complete"] or not require_code_catalog)
        and (report["catalog_complete"] or not require_full_catalog)
    )

    catalog_errors: list[str] = []
    if report.get("catalog_error"):
        catalog_errors.append(str(report["catalog_error"]))
    if require_code_catalog and not report["code_catalog_complete"]:
        catalog_errors.append(
            "code catalog required: "
            f"loaded {len(positions)}, minimum {CODE_CATALOG_MINIMUM}"
        )
    if require_full_catalog and not report["catalog_complete"]:
        catalog_errors.append(
            "full commodity catalog required: "
            + ", ".join(scope["full_catalog_gate_failures"])
        )
    if catalog_errors:
        report["catalog_error"] = "; ".join(dict.fromkeys(catalog_errors))
    return report
