"""Principle-based noise classifier for non_tariff_measures.

Uses legacy catalog heuristics based on EEC regulatory scopes (Решение №317
ветконтроль, №318 фитоконтроль, №299 СГР, №30 лицензирование) to select
crawler rows for retention or noise review; this is not a legal applicability
resolver.

The TKS crawler bulk-assigned all measure types to nearly every HS code.
This classifier narrows those rows using the existing catalog heuristics.

For ``tr_ts``, the legacy positive catalog is incomplete and cannot establish
exclusion. Unknown TR scope is retained for review, never marked as proven noise
or treated as a mandatory document. Import and presentation must also preserve
``tr_ts_scope_requires_review``; ``False`` from this classifier is not proof of
legal applicability.

Почему доля noise высокая (issue #110, аудит #108)
--------------------------------------------------
Высокая доля noise по license (~93%) и sgr (~96%) — ожидаема и обоснована:
краулер присвоил эти меры почти всем 10-значным кодам, а официальный scope
(Решение Коллегии ЕЭК №30 разд. 2.10 — лицензирование; Решение ЕЭК №299 —
СГР) распространяется лишь на узкие группы. Исторические контрольные примеры
не подтверждают полноту нормативного покрытия или применимость всех мер.

``fsetc`` из старого краулера помечается noise безусловно: эти строки были
массово присвоены и не имеют доказуемой привязки. Официальный advisory-контур
ПП РФ №1284–1288 и №1299 реализован отдельно в ``official_export_control`` и не подключён к
broker enforcement, поскольку код в списке имеет справочный характер.

Периодический аудит: ``scripts/audit_ntm_noise.py``.
"""
from __future__ import annotations

from .ntm_layers import (
    LICENCE_DOMAINS,
    NF_DOMAINS,
    PHYTO_DOMAINS,
    SGR_DOMAINS,
    VET_DOMAINS,
)
from .tr_ts_catalog import ALL_REGULATIONS


def _build_prefix_set(domains: list[str]) -> set[str]:
    return set(domains)


_VET_PREFIXES = _build_prefix_set(VET_DOMAINS)
_PHYTO_PREFIXES = _build_prefix_set(PHYTO_DOMAINS)
_SGR_PREFIXES = _build_prefix_set(SGR_DOMAINS)
_NF_PREFIXES = _build_prefix_set(NF_DOMAINS)
_LICENCE_PREFIXES = _build_prefix_set(LICENCE_DOMAINS)

_TR_TS_PREFIXES: set[str] = {prefix for prefix, _code, _form in ALL_REGULATIONS}

_FOOD_CHAPTERS = {
    "01", "02", "03", "04", "05", "06", "07", "08", "09", "10",
    "11", "12", "13", "14", "15", "16", "17", "18", "19", "20",
    "21", "22", "23", "24",
}

_CERTIFICATE_CHAPTERS = (
    _FOOD_CHAPTERS
    | {
        "25", "27", "28", "29", "30", "31", "32", "33", "34", "35",
        "36", "37", "38", "39", "40", "41", "42", "43", "44", "45",
        "46", "47", "48", "49", "56", "57", "58", "59", "60",
        "61", "62", "63", "64", "65", "68", "69", "70", "71",
        "72", "73", "74", "75", "76", "78", "79", "80", "81", "82",
        "83", "84", "85", "86", "87", "88", "89", "90", "91", "92",
        "93", "94", "95", "96",
    }
)


def _code_matches_any_prefix(hs_code: str, prefixes: set[str]) -> bool:
    for plen in (10, 8, 6, 4):
        if hs_code[:plen] in prefixes:
            return True
    return False


def tr_ts_scope_requires_review(commodity_code: str, measure_type: str) -> bool:
    """Identify legacy TR rows whose scope the positive catalog cannot establish.

    This is a technical coverage check, not a new legal rule or an exclusion
    list. Existing catalog matches retain their prior handling. Caller-supplied
    documentary wording cannot resolve a missing code/product scope.
    """
    if (measure_type or "").strip().lower() != "tr_ts":
        return False
    code = (commodity_code or "").strip()
    return not (
        _code_matches_any_prefix(code, _TR_TS_PREFIXES)
        or code[:2] in _FOOD_CHAPTERS
    )


def tr_ts_review_metadata(commodity_code: str, measure_type: str) -> dict[str, object]:
    if not tr_ts_scope_requires_review(commodity_code, measure_type):
        return {}
    return {
        "applicability": "needs_clarification",
        "requires_manual_review": True,
        "used_for_missing_check": False,
        "applicability_reason": "legacy_tr_ts_scope_not_established",
    }


def is_measure_noise(commodity_code: str, measure_type: str) -> bool:
    """Return True if (commodity_code, measure_type) is noise.

    False means retained, including unresolved scope; it does not establish
    legal applicability or permit enforcement.
    """
    code = (commodity_code or "").strip()
    mtype = (measure_type or "").strip().lower()

    if len(code) < 4:
        return False

    ch2 = code[:2]
    ch4 = code[:4]

    if mtype == "sgr":
        return not _code_matches_any_prefix(code, _SGR_PREFIXES)

    if mtype == "vet_control":
        return not _code_matches_any_prefix(code, _VET_PREFIXES)

    if mtype == "phyto_control":
        return not _code_matches_any_prefix(code, _PHYTO_PREFIXES)

    if mtype == "license" or mtype == "licence":
        if _code_matches_any_prefix(code, _LICENCE_PREFIXES):
            return False
        # Medicines (chapter 30) always need license
        if ch2 == "30":
            return False
        return True

    if mtype == "certificate":
        if ch2 in _CERTIFICATE_CHAPTERS:
            return False
        return True

    if mtype == "tr_ts":
        # Missing positive coverage is not evidence of legal exclusion.
        # Unknown rows are separately guarded by tr_ts_scope_requires_review.
        return False

    if mtype == "marking":
        if ch2 in _FOOD_CHAPTERS:
            return False
        if _code_matches_any_prefix(code, _TR_TS_PREFIXES):
            return False
        return True

    if mtype == "fsetc":
        return True

    # Unknown measure types: keep (don't mark as noise)
    return False


def classify_measures(
    rows: list[tuple[int, str, str]],
) -> tuple[list[int], list[int]]:
    """Classify a batch of (id, commodity_code, measure_type) tuples.

    Returns (noise_ids, retained_ids). Retention includes unresolved TR rows
    requiring review and must never be interpreted as legal applicability.
    """
    noise_ids: list[int] = []
    legit_ids: list[int] = []
    for row_id, code, mtype in rows:
        if is_measure_noise(code, mtype):
            noise_ids.append(row_id)
        else:
            legit_ids.append(row_id)
    return noise_ids, legit_ids
