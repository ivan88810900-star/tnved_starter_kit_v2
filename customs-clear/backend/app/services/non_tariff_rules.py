"""Правила нетарифных мер по ТР ТС и диапазонам ТН ВЭД.

Основной источник — БД (таблица non_tariff_rules), заполняемая через seed_data().
Fallback: in-memory список для случаев, когда БД недоступна или пуста.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List

from ..db import SessionLocal
from ..models.tnved import NonTariffMeasure
from .hs_matching import get_hs_prefixes, match_hs_prefix, normalize_hs_code

NEGATIVE_MARKERS = [
    "не требуется",
    "не требуют",
    "не требует",
    "не подлеж",
    "лицензирование: нет",
    "разреш: нет",
    "не относится",
    "отсутствует",
    "нет ",
    "прочие",
    "базовая",
    "оптовая",
    "розничная",
    "общий порядок",
    "без ограничений",
    "не предусмотрен",
]

PERMIT_PATTERNS: dict[str, list[str]] = {
    "ЛЗ": [
        "лицензия минпромторга",
        "лицензия фсб",
        "лицензия мвд",
        "лицензия росалкоголь",
        "лицензия минздрав",
        "разовая лицензия",
        "генеральная лицензия",
        "импортная лицензия",
        "экспортная лицензия",
        "лицензия на импорт",
        "лицензия на ввоз",
        "лицензия росатом",
        "лицензия ростехнадзор",
    ],
    "РУ": [
        "регистрационное удостоверение",
        "регудостоверение",
        "ру росздравнадзор",
        "ру минздрав",
        "регистрация лекарственного",
        "государственная регистрация лекарственного",
    ],
    "СГР": [
        "свидетельство о государственной регистрации",
        "свидетельство о госрегистрации",
        "сгр роспотребнадзор",
        "свидетельство госрегистрации",
    ],
    "СС": [
        "сертификат соответствия",
        "обязательная сертификация",
        "сертификат тр тс",
        "сертификат еаэс",
        "обязательной сертификации",
        "подлежит сертификации",
        "сс по тр тс",
        "сертификат соответствия тс",
        "сертификации тр тс",
    ],
    # Не использовать отдельное «сс» — ложные срабатывания в произвольном тексте мер (marking и т.д.).
    "ДС": [
        "декларация о соответствии",
        "декларирование соответствия",
        "декларация тр тс",
        "декларация еаэс",
        "декларации соответствия",
        "декларация соответствия",
        "подлежит декларированию",
        "дс по тр тс",
        "дс тр тс",
        "обязательное декларирование",
    ],
    "КВ": [
        "квота на импорт",
        "квота на ввоз",
        "тарифная квота",
        "импортная квота",
    ],
    "ВС": [
        "ветеринарный сертификат",
        "ветсертификат",
        "ветеринарное свидетельство",
    ],
    "ФСС": [
        "фитосанитарный сертификат",
        "фитосертификат",
        "карантинный сертификат",
    ],
    "НФ": [
        "нотификация фсб",
        "нотификация шифровальных",
    ],
}

DIRECT_MAP_WITH_DEFAULT: dict[str, tuple[str | None, bool]] = {
    "license": ("ЛЗ", False),
    "licence": ("ЛЗ", False),
    "certificate": ("СС", True),
    "declaration": ("ДС", True),
    "vet_control": ("ВС", True),
    "phyto_control": ("ФСС", True),
    "sgr": ("СГР", True),
    "marking": (None, False),
    "tr_ts": (None, False),
    "fsetc": (None, False),
    "fsb": ("НФ", True),
    "ban": (None, False),
    "other": (None, False),
}

# Устаревшие перечни SS_DOMAINS / DS_DOMAINS заменены на ``tr_ts_catalog.get_tr_ts_requirements``.
# SS_DOMAINS: dict[str, str] = { ... }
# DS_DOMAINS: dict[str, str] = { ... }

SENSITIVE_OVERRIDES = {
    "30": "РУ",
    "2203": "ЛЗ",
    "2204": "ЛЗ",
    "2205": "ЛЗ",
    "2206": "ЛЗ",
    "2207": "ЛЗ",
    "2208": "ЛЗ",
    "24": "ЛЗ",
    "9301": "ЛЗ",
    "9302": "ЛЗ",
    "9303": "ЛЗ",
    "9304": "ЛЗ",
    "9305": "ЛЗ",
    "9306": "ЛЗ",
    "9307": "ЛЗ",
    "3601": "ЛЗ",
    "3602": "ЛЗ",
    "3603": "ЛЗ",
    "3604": "ЛЗ",
}

# In-memory fallback used only when DB is unavailable
_FALLBACK_RULES: List[Dict[str, Any]] = [
    {
        "name": "Бытовая электроника",
        "hs_prefixes": ["8509", "8516", "8517", "8471", "8472"],
        "tr_ts": ["004/2011", "020/2011", "037/2016"],
        "required_permits": ["СС", "ДС"],
    },
    {
        "name": "Косметика и парфюмерия",
        "hs_prefixes": ["3304", "3305", "3307"],
        "tr_ts": ["009/2011", "021/2011"],
        "required_permits": ["ДС"],
    },
    {
        "name": "Одежда 1-й слой",
        "hs_prefixes": ["6101", "6102", "6201", "6202", "6109", "6209"],
        "tr_ts": ["017/2011"],
        "required_permits": ["СС"],
    },
    {
        "name": "Одежда 2–3 слой",
        "hs_prefixes": ["6103", "6104", "6203", "6204", "6110", "6210"],
        "tr_ts": ["017/2011"],
        "required_permits": ["ДС"],
    },
    {
        "name": "Ткани хлопковые",
        "hs_prefixes": ["5208", "5209", "5210", "5211", "5212"],
        "tr_ts": ["017/2011"],
        "required_permits": ["ДС"],
    },
    {
        "name": "Детские товары",
        "hs_prefixes": ["9503", "9403", "6307", "9619", "6209"],
        "tr_ts": ["007/2011"],
        "required_permits": ["СС"],
    },
    {
        "name": "Посуда керамическая",
        "hs_prefixes": ["6911", "6912", "6913"],
        "tr_ts": ["021/2011"],
        "required_permits": ["ДС"],
    },
    {
        "name": "Игрушки",
        "hs_prefixes": ["9503"],
        "tr_ts": ["008/2011"],
        "required_permits": ["СС"],
    },
    {
        "name": "Лекарственные средства",
        "hs_prefixes": ["3004"],
        "tr_ts": ["061/2012"],
        "required_permits": ["РУ"],
    },
]


def find_rules_for_code(hs_code: str) -> List[Dict[str, Any]]:
    """Find applicable non-tariff rules for an HS code.

    Tries the database first; falls back to the in-memory list if the DB
    returns nothing and the in-memory list has a match.
    """
    hs_code = normalize_hs_code(hs_code)
    if not hs_code:
        return []

    # 1. Try DB
    try:
        from .normative_store import find_non_tariff_rules_for_hs
        db_rules = find_non_tariff_rules_for_hs(hs_code)
        if db_rules:
            return db_rules
    except Exception:
        pass

    # 2. Fallback: in-memory
    res: List[Dict[str, Any]] = []
    seen: set[int] = set()
    for rule in _FALLBACK_RULES:
        for pref in rule.get("hs_prefixes", []):
            if match_hs_prefix(hs_code, pref) and id(rule) not in seen:
                # Normalise to the same format as DB rules return
                res.append({
                    "name": rule["name"],
                    "hs_prefix": pref,
                    "tr_ts": rule.get("tr_ts", []),
                    "required_permits": rule.get("required_permits", []),
                    "tr_ts_edition": "",
                    "exception_note": "",
                    "priority": 0,
                    "source_url": "",
                    "source_revision": "fallback-memory",
                })
                seen.add(id(rule))
                break
    return res


def _extract_tr_ts_code(*parts: str) -> str | None:
    import re

    text = " ".join(p for p in parts if p)
    match = re.search(r"(?:ТР\s*(?:ТС|ЕАЭС)?\s*)?(\d{3}/\d{4})", text, flags=re.IGNORECASE)
    if match:
        return match.group(1)
    return None


def get_default_cert_form(hs_code: str) -> str | None:
    """
    DEPRECATED: используй ``get_tr_ts_requirements`` из ``tr_ts_catalog``.
    Возвращает форму первого основного регламента из каталога
    для обратной совместимости (СС имеет приоритет над ДС).
    """
    from .tr_ts_catalog import get_tr_ts_requirements

    requirements = get_tr_ts_requirements(hs_code)
    if not requirements:
        return None
    forms = {r["permit_type"] for r in requirements if r.get("permit_type") in ("СС", "ДС")}
    if "СС" in forms:
        return "СС"
    if "ДС" in forms:
        return "ДС"
    return None


def _measure_to_permit_type(measure_type: str, text: str, hs_code: str = "") -> str | None:
    """
    Определяет тип permit на основе measure_type и текста.
    Использует точные паттерны и проверку на негативные маркеры.
    """
    full_text = f"{measure_type} {text}".lower()

    for neg in NEGATIVE_MARKERS:
        if neg in full_text:
            return None

    mtype_lower = (measure_type or "").lower().strip()
    # 1) Точные паттерны имеют приоритет
    for permit_type, patterns in PERMIT_PATTERNS.items():
        for pattern in patterns:
            if pattern in full_text:
                return permit_type

    # 2) Для certificate/declaration - используем доменную классификацию по HS
    if mtype_lower in ("certificate", "declaration"):
        domain_form = get_default_cert_form(hs_code)
        if domain_form:
            return domain_form
        if mtype_lower == "certificate":
            return "СС"
        return "ДС"

    # 3) Прочие measure_type - direct map
    if mtype_lower in DIRECT_MAP_WITH_DEFAULT:
        permit, has_default = DIRECT_MAP_WITH_DEFAULT[mtype_lower]
        if has_default:
            return permit

    return None


def get_sensitive_override(hs_code: str) -> str | None:
    """Возвращает обязательный permit_type для чувствительных кодов."""
    code = normalize_hs_code(hs_code)
    if not code:
        return None
    for length in (4, 2):
        if len(code) < length:
            continue
        prefix = code[:length]
        if prefix in SENSITIVE_OVERRIDES:
            return SENSITIVE_OVERRIDES[prefix]
    return None


def find_measures_for_code(hs_code: str, direction: str = "import") -> list[dict]:
    """
    Читает нетарифные меры из non_tariff_measures по коду.
    Каскадный поиск по всем префиксам (см. ``get_measures_for_code``).
    """
    from .non_tariff_measures_lookup import get_measures_for_code

    code = normalize_hs_code(hs_code)
    if not code:
        return []
    direction_norm = (direction or "import").strip().lower()

    _len_to_level: dict[int, str] = {
        10: "exact",
        8: "8_digit",
        6: "6_digit",
        4: "4_digit",
        2: "chapter",
    }

    def _source_level_for_code(commodity_code: str) -> tuple[str, int]:
        cc = normalize_hs_code(commodity_code)
        pref_len = len(cc) if cc else 0
        for threshold in (10, 8, 6, 4, 2):
            if pref_len >= threshold:
                return _len_to_level[threshold], threshold
        return "chapter", 2

    with SessionLocal() as db:
        direction_exists = hasattr(NonTariffMeasure, "direction")
        level_order = {
            "exact": 0,
            "8_digit": 1,
            "6_digit": 2,
            "4_digit": 3,
            "chapter": 4,
        }
        results: list[dict] = []
        for row in get_measures_for_code(code, db, direction=direction_norm):
            desc = (row.description or "").strip()
            legal_ref = (row.regulatory_act or "").strip()
            doc = (row.document_required or "").strip()
            mtype = (row.measure_type or "").strip()
            source_level, pref_len = _source_level_for_code(row.commodity_code or "")
            permit_type = _measure_to_permit_type(
                mtype,
                f"{doc} {desc} {legal_ref}",
                hs_code=code,
            )
            tr_ts_code = _extract_tr_ts_code(desc, legal_ref, doc)
            results.append(
                {
                    "commodity_code": row.commodity_code,
                    "measure_type": mtype,
                    "description": desc,
                    "document_required": doc,
                    "legal_ref": legal_ref,
                    "permit_type": permit_type,
                    "tr_ts_code": tr_ts_code,
                    "match_prefix_len": pref_len,
                    "source_level": source_level,
                    "direction": direction_norm if direction_exists else None,
                }
            )

        results.sort(
            key=lambda m: (
                level_order.get(str(m.get("source_level") or ""), 99),
                -int(m.get("match_prefix_len") or 0),
                str(m.get("commodity_code") or ""),
            )
        )
        return results


def _measure_result_fingerprint(m: dict[str, Any]) -> tuple[Any, ...]:
    """Ключ для сравнения записей мер между режимами (без ORM id в публичном dict)."""
    return (
        m.get("commodity_code"),
        m.get("measure_type"),
        m.get("legal_ref"),
        m.get("permit_type"),
        m.get("tr_ts_code"),
        m.get("match_prefix_len"),
        m.get("source_level"),
    )


def _find_measures_cumulative_all_levels(hs_code: str, direction: str = "import") -> list[dict[str, Any]]:
    """
    Диагностика: те же SQL-фильтры, что у ``find_measures_for_code``, но обход **всех**
    префиксов без остановки на первом непустом уровне; дедуп по ``row.id`` и по
    ``compact_key`` **глобально** по всем уровням.

    Не использовать в production-ответах API — только сравнение и отчёты.
    """
    code = normalize_hs_code(hs_code)
    if not code:
        return []
    direction_norm = (direction or "import").strip().lower()

    _len_to_level: dict[int, str] = {
        10: "exact",
        8: "8_digit",
        6: "6_digit",
        4: "4_digit",
        2: "chapter",
    }
    prefixes: list[tuple[str, str, int]] = []
    for pref in get_hs_prefixes(code, levels=(10, 8, 6, 4, 2)):
        ln = len(pref)
        prefixes.append((pref, _len_to_level[ln], ln))
    if not prefixes:
        return []

    with SessionLocal() as db:
        results: list[dict[str, Any]] = []
        seen_ids: set[int] = set()
        global_compact_seen: set[tuple[str, str, str | None, str | None]] = set()
        direction_exists = hasattr(NonTariffMeasure, "direction")
        level_order = {
            "exact": 0,
            "8_digit": 1,
            "6_digit": 2,
            "4_digit": 3,
            "chapter": 4,
        }

        for pref, source_level, pref_len in prefixes:
            query = db.query(NonTariffMeasure).filter(
                NonTariffMeasure.commodity_code.like(f"{pref}%"),
            )
            if hasattr(NonTariffMeasure, "quality"):
                query = query.filter(
                    (NonTariffMeasure.quality.is_(None)) | (NonTariffMeasure.quality != "noise")
                )
            if direction_exists:
                query = query.filter(NonTariffMeasure.direction == direction_norm)
            rows = query.order_by(NonTariffMeasure.commodity_code.asc()).all()
            if not rows:
                continue
            for row in rows:
                if row.id in seen_ids:
                    continue
                desc = (row.description or "").strip()
                legal_ref = (row.regulatory_act or "").strip()
                doc = (row.document_required or "").strip()
                mtype = (row.measure_type or "").strip()
                permit_type = _measure_to_permit_type(
                    mtype,
                    f"{doc} {desc} {legal_ref}",
                    hs_code=code,
                )
                tr_ts_code = _extract_tr_ts_code(desc, legal_ref, doc)
                compact_key = (mtype.lower(), legal_ref.lower(), permit_type, tr_ts_code)
                if compact_key in global_compact_seen:
                    continue
                global_compact_seen.add(compact_key)
                seen_ids.add(row.id)
                results.append(
                    {
                        "commodity_code": row.commodity_code,
                        "measure_type": mtype,
                        "description": desc,
                        "document_required": doc,
                        "legal_ref": legal_ref,
                        "permit_type": permit_type,
                        "tr_ts_code": tr_ts_code,
                        "match_prefix_len": pref_len,
                        "source_level": source_level,
                        "direction": direction_norm if direction_exists else None,
                    }
                )

        results.sort(
            key=lambda m: (
                level_order.get(str(m.get("source_level") or ""), 99),
                -int(m.get("match_prefix_len") or 0),
                str(m.get("commodity_code") or ""),
            )
        )
        return results


def diagnose_measures_prefix_strategies(hs_code: str, direction: str = "import") -> dict[str, Any]:
    """
    Сравнение production (первый непустой уровень) и накопительного режима без изменения API.

    Возвращает оба списка, счётчики, записи только в cumulative, группы семантических дублей
    в cumulative (одинаковый compact_key, разные commodity_code).
    """
    current = find_measures_for_code(hs_code, direction)
    cumulative = _find_measures_cumulative_all_levels(hs_code, direction)
    fp_cur = {_measure_result_fingerprint(m) for m in current}
    fp_cum = {_measure_result_fingerprint(m) for m in cumulative}
    only_cumulative = [m for m in cumulative if _measure_result_fingerprint(m) not in fp_cur]

    by_semantic: dict[tuple[str, str, str | None, str | None], list[str | None]] = defaultdict(list)
    for m in cumulative:
        k = (
            str(m.get("measure_type") or "").lower(),
            str(m.get("legal_ref") or "").lower(),
            m.get("permit_type"),
            m.get("tr_ts_code"),
        )
        by_semantic[k].append(m.get("commodity_code"))

    duplicate_commodities = {str(k): v for k, v in by_semantic.items() if len(v) > 1}

    return {
        "hs_normalized": normalize_hs_code(hs_code),
        "direction": (direction or "import").strip().lower(),
        "counts": {"current": len(current), "cumulative": len(cumulative)},
        "only_in_cumulative": only_cumulative,
        "only_in_current": [m for m in current if _measure_result_fingerprint(m) not in fp_cum],
        "cumulative_semantic_duplicate_commodities": duplicate_commodities,
        "recommended_future_sort": (
            "После накопительного режима: сохранить sort key "
            "(-match_prefix_len, level_order[source_level], commodity_code) "
            "как в find_measures_for_code; при необходимости добавить в ключ -specificity(pref)."
        ),
        "current": current,
        "cumulative": cumulative,
    }
