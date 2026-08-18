"""Консервативный advisory-контур экспортного контроля РФ.

Коды ТН ВЭД в шести списках ПП РФ №1284–1288 и №1299 имеют справочный характер: окончательная
идентификация делается по наименованию и техническим параметрам. Поэтому
совпадение из этого модуля никогда не участвует в broker enforcement.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from .hs_matching import normalize_hs_code

EXPORT_CONTROL_SOURCE_KIND = "official_export_control"
EXPORT_CONTROL_SOURCE_LABEL = "Экспортный контроль РФ (ФСТЭК)"
PP_1299_URL = "https://publication.pravo.gov.ru/Document/View/0001202207220041"
FSTEC_IDENTIFICATION_URL = (
    "https://fstec.ru/dokumenty/vse-dokumenty/informatsionnye-i-analiticheskie-materialy/"
    "nezavisimaya-identifikatsionnaya-ekspertiza-v-sisteme-eksportnogo-kontrolya"
)
DEFAULT_DATASET_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "official_export_control_rules.seed.json"
)


@lru_cache(maxsize=1)
def load_export_control_dataset() -> dict[str, Any]:
    payload = json.loads(DEFAULT_DATASET_PATH.read_text(encoding="utf-8"))
    candidates = payload.get("hs_candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("official export-control dataset must contain hs_candidates")
    normalized = sorted(
        {normalize_hs_code(str(value)) for value in candidates if normalize_hs_code(str(value))},
        key=lambda value: (-len(value), value),
    )
    if any(len(value) < 4 or len(value) > 10 for value in normalized):
        raise ValueError("official export-control candidate length must be 4..10 digits")
    source_lists = payload.get("source_lists")
    if not isinstance(source_lists, list) or len(source_lists) != 6:
        raise ValueError("official export-control dataset must contain six source_lists")
    source_numbers = {int(row.get("number")) for row in source_lists if isinstance(row, dict) and row.get("number")}
    if source_numbers != {1284, 1285, 1286, 1287, 1288, 1299}:
        raise ValueError("official export-control dataset has unexpected source list numbers")
    source_union = {
        normalize_hs_code(str(value))
        for row in source_lists
        if isinstance(row, dict)
        for value in (row.get("hs_candidates") or [])
        if normalize_hs_code(str(value))
    }
    if set(normalized) != source_union:
        raise ValueError("official export-control union differs from source_lists")
    retired_metadata = payload.get("retired_exact_codes")
    if not isinstance(retired_metadata, dict) or retired_metadata.get("schema_version") != "1":
        raise ValueError("official export-control dataset must contain versioned retired_exact_codes")
    retired_rows = retired_metadata.get("codes")
    if not isinstance(retired_rows, list) or not retired_rows:
        raise ValueError("official export-control retired_exact_codes must contain codes")
    normalized_retired_rows: list[dict[str, Any]] = []
    retired_codes: set[str] = set()
    for row in retired_rows:
        if not isinstance(row, dict):
            raise ValueError("official export-control retired code row must be an object")
        retired_code = normalize_hs_code(str(row.get("hs_code") or ""))
        replacement_code = normalize_hs_code(str(row.get("replacement_code") or ""))
        if len(retired_code) != 10 or len(replacement_code) != 10:
            raise ValueError("official export-control retired/replacement codes must be 10 digits")
        if retired_code not in source_union or replacement_code not in source_union:
            raise ValueError("official export-control retired/replacement code is absent from raw source union")
        retired_codes.add(retired_code)
        normalized_retired_rows.append({
            **row,
            "hs_code": retired_code,
            "replacement_code": replacement_code,
        })
    if len(retired_codes) != len(normalized_retired_rows):
        raise ValueError("official export-control retired_exact_codes contains duplicates")
    return {
        **payload,
        "hs_candidates": normalized,
        "retired_exact_codes": {
            **retired_metadata,
            "codes": normalized_retired_rows,
        },
    }


@lru_cache(maxsize=1)
def _retired_exact_code_set() -> frozenset[str]:
    metadata = load_export_control_dataset()["retired_exact_codes"]
    return frozenset(str(row["hs_code"]) for row in metadata["codes"])


@lru_cache(maxsize=1)
def _source_prefix_index() -> tuple[tuple[dict[str, Any], tuple[str, ...]], ...]:
    rows: list[tuple[dict[str, Any], tuple[str, ...]]] = []
    for source in load_export_control_dataset().get("source_lists") or []:
        prefixes = tuple(sorted(
            {
                normalize_hs_code(str(value))
                for value in (source.get("hs_candidates") or [])
                if normalize_hs_code(str(value))
            },
            key=lambda value: (-len(value), value),
        ))
        rows.append(({
            "number": source.get("number"),
            "title": source.get("title"),
            "official_url": source.get("official_url"),
        }, prefixes))
    return tuple(rows)


def match_export_control_candidate(hs_code: str) -> str | None:
    """Возвращает наиболее точный справочный HS-кандидат шести списков."""
    code = normalize_hs_code(hs_code)
    if not code or code in _retired_exact_code_set():
        return None
    for prefix in load_export_control_dataset()["hs_candidates"]:
        if code.startswith(prefix):
            return prefix
    return None


def _matched_source_lists(hs_code: str) -> list[dict[str, Any]]:
    code = normalize_hs_code(hs_code)
    matched: list[dict[str, Any]] = []
    for source, prefixes in _source_prefix_index():
        if any(code.startswith(prefix) for prefix in prefixes):
            matched.append(dict(source))
    return matched


def evaluate_export_control_requirement(hs_code: str, description: str = "") -> dict[str, Any] | None:
    """Строит только ``needs_clarification``-строку для экспорта."""
    matched = match_export_control_candidate(hs_code)
    if not matched:
        return None
    payload = load_export_control_dataset()
    matched_sources = _matched_source_lists(hs_code)
    source_numbers = ", ".join(f"№{row['number']}" for row in matched_sources)
    return {
        "source": EXPORT_CONTROL_SOURCE_KIND,
        "source_kind": EXPORT_CONTROL_SOURCE_KIND,
        "source_label": EXPORT_CONTROL_SOURCE_LABEL,
        "source_url": str(
            (matched_sources[0].get("official_url") if matched_sources else None)
            or payload.get("source_url")
            or PP_1299_URL
        ),
        "family": "export_control_dual_use",
        "permit_type": str(payload.get("permit_type") or "ЛЗ/разрешение ФСТЭК"),
        "tr_ts": None,
        "applicability": "needs_clarification",
        "hs_prefix": matched,
        "direction": "export",
        "rule_name": f"Контрольные списки экспортного контроля РФ — ПП РФ {source_numbers}",
        "reason": (
            "Код встречается в справочных кодах одного или нескольких контрольных списков. "
            "Нужна идентификация по наименованию, назначению и техническим параметрам; "
            "при необходимости — идентификационная экспертиза."
        ),
        "note": (
            "Совпадение по коду не подтверждает контролируемость и не создаёт обязательный документ. "
            "Проверяется экспорт/передача технологии и технические характеристики товара."
        ),
        "identification_url": FSTEC_IDENTIFICATION_URL,
        "source_documents": matched_sources,
        "requires_manual_review": True,
        "used_for_missing_check": False,
    }


def export_control_dataset_summary() -> dict[str, Any]:
    payload = load_export_control_dataset()
    raw_candidate_count = len(payload["hs_candidates"])
    retired_exact_code_count = len(_retired_exact_code_set())
    return {
        "dataset_id": payload.get("dataset_id"),
        # candidate_count сохранён как alias сырого source-faithful union для
        # обратной совместимости отчётов; runtime исключает retired exact codes.
        "candidate_count": raw_candidate_count,
        "raw_candidate_count": raw_candidate_count,
        "effective_candidate_count": raw_candidate_count - retired_exact_code_count,
        "retired_exact_code_count": retired_exact_code_count,
        "retired_exact_codes": sorted(_retired_exact_code_set()),
        "retired_exact_codes_catalog_revision": payload["retired_exact_codes"].get("catalog_revision"),
        "source_list_count": len(payload.get("source_lists") or []),
        "source_list_candidate_counts": {
            str(row.get("number")): len(row.get("hs_candidates") or [])
            for row in (payload.get("source_lists") or [])
            if isinstance(row, dict)
        },
        "source_url": payload.get("source_url"),
        "extracted_at": payload.get("extracted_at"),
        "identification_scope": "hs_candidates_only",
        "technical_parameters_covered": False,
        "applicability": "needs_clarification",
        "enforcement_enabled": False,
    }
