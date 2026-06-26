"""Principle-based noise classifier for non_tariff_measures.

Uses official EEC regulatory scopes (Решение №317 ветконтроль, №318
фитоконтроль, №299 СГР, №30 лицензирование) to decide whether a
(commodity_code, measure_type) pair is legitimate or noise.

The TKS crawler bulk-assigned all measure types to nearly every HS code.
This classifier reverses that by keeping only measures whose HS chapter
falls within the official regulatory scope.

Почему доля noise высокая (issue #110, аудит #108)
--------------------------------------------------
Высокая доля noise по license (~93%) и sgr (~96%) — ожидаема и обоснована:
краулер присвоил эти меры почти всем 10-значным кодам, а официальный scope
(Решение Коллегии ЕЭК №30 разд. 2.10 — лицензирование; Решение ЕЭК №299 —
СГР) распространяется лишь на узкие группы. Классификатор не теряет валидные
меры: точность подтверждается контрольными кодами
(``tests/test_ntm_noise_classifier.py::test_control_code_noise``, 12/12) и
полной брокерской регрессией (``tests/test_ntm_pipeline.py``, 71/71).

``fsetc`` (экспортный контроль ФСТЭК) помечается noise безусловно: для него нет
официального HS-scope, а брокерский слой ориентирован на импортные требования;
меры были массово присвоены краулером. Уточнение потребует курируемого перечня
товаров двойного назначения (отдельная задача).

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


def is_measure_noise(commodity_code: str, measure_type: str) -> bool:
    """Return True if (commodity_code, measure_type) is noise.

    A measure is noise when the HS code falls outside the official
    regulatory scope for that measure type.
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
        if _code_matches_any_prefix(code, _TR_TS_PREFIXES):
            return False
        # TR TS 021/022 cover all food chapters
        if ch2 in _FOOD_CHAPTERS:
            return False
        return True

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

    Returns (noise_ids, legitimate_ids).
    """
    noise_ids: list[int] = []
    legit_ids: list[int] = []
    for row_id, code, mtype in rows:
        if is_measure_noise(code, mtype):
            noise_ids.append(row_id)
        else:
            legit_ids.append(row_id)
    return noise_ids, legit_ids
