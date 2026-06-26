"""Справочник ТН ВЭД: разделы, группы, позиции и иерархическое дерево.

БД содержит только коды длиной 4 и 10 знаков.
Дерево строится как 4-знак → 6-знак (синтетический) → 10-знак.
Поле code — строго строка; 10-значные коды всегда хранятся без потери нулей.
"""

from __future__ import annotations

import json
import os
import time
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload, selectinload

from ..db import SessionLocal
from ..models.tnved import Chapter, Commodity, IntellectualProperty, NonTariffMeasure, Section, SpecialDuty, VatPreference
from ..schemas.tnved_catalog import TnvedCommodityDetailsResponse
from ..services.non_tariff_measures_lookup import get_measures_for_code
from ..services.normative_store import find_rate_for_hs
from ..services.tnved_code_card import find_preliminary_decisions_for_hs
from ..services.preview_cache_revision import (
    bump_preview_cache_revision,
    read_preview_cache_revision_marker,
)

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def _digits(raw: str) -> str:
    """Только цифры из строки."""
    return re.sub(r"\D", "", raw or "")


def _pad_code(raw: str) -> str:
    """
    Приводим код к каноническому виду:
    - 4-значный: 4 цифры с ведущими нулями
    - 10-значный: 10 цифр с ведущими нулями
    Если пришло что-то иное — оставляем как есть, не удаляем нули.
    """
    d = _digits(raw)
    if not d:
        return raw.strip()
    if len(d) <= 4:
        return d.zfill(4)
    return d.zfill(10)[:10]   # конечный код всегда ровно 10 символов


# Legacy TKS non_tariff_measures в карточке (certificate/license/marking) — отключено.
USE_LEGACY_NTM = False


def _fetch_nt_rows(db: Session, hs_code: str) -> list[NonTariffMeasure]:
    """Нетарифные меры: каскадный поиск по префиксам кода."""
    return get_measures_for_code(hs_code, db)


def _measure_label(mtype: str) -> str:
    t = (mtype or "").strip().lower()
    return {
        "ban": "Запрет",
        "license": "Лицензирование",
        "certificate": "Сертификация",
        "vet_control": "Ветконтроль",
        "phyto_control": "Фитоконтроль",
        "tr_ts": "Технический регламент",
        "marking": "Маркировка",
        "sgr": "СГР",
        "fsetc": "Экспортный контроль",
        "fsb": "ФСБ / шифрование",
    }.get(t, "Иные меры")


# Главы, для которых СГР может применяться (пищевая, косметика, детские и т.п.).
# Глава 84 (машины) и прочие — СГР из legacy-импорта TKS отфильтровываем.
_SGR_APPLICABLE_CHAPTERS: frozenset[str] = frozenset({
    "04", "15", "16", "17", "18", "19", "20", "21", "22", "23", "28", "30",
    "32", "33", "34", "39", "48", "57", "61", "62", "63", "64", "65", "87",
    "90", "94", "95",
})


def _chapter_code_from_hs(code: str) -> str:
    d = _digits(code)
    return d[:2].zfill(2) if len(d) >= 2 else ""


def _filter_nt_rows_for_chapter(rows: list[Any], hs_code: str) -> list[Any]:
    ch = _chapter_code_from_hs(hs_code)
    if ch in _SGR_APPLICABLE_CHAPTERS:
        return rows
    return [m for m in rows if (getattr(m, "measure_type", None) or "").strip().lower() != "sgr"]


def _merge_tr_ts_measures(hs_code: str, measures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Дополняет меры из каталога ТР ТС (ДС/СС), если в БД нет явного подтверждения."""
    from ..services.ntm_engine_v2 import get_tr_ts_requirements_for_pipeline

    existing_refs = {
        (m.get("regulatory_act") or "").strip().lower()
        for m in measures
        if (m.get("regulatory_act") or "").strip()
    }
    out = list(measures)
    for req in get_tr_ts_requirements_for_pipeline(hs_code, ""):
        pt = (req.get("permit_type") or "").strip()
        tr = (req.get("tr_ts") or "").strip()
        if not pt or not tr:
            continue
        act = f"ТР ТС {tr}"
        if act.lower() in existing_refs or any(tr in ref for ref in existing_refs):
            continue
        doc = "Декларация соответствия" if pt == "ДС" else "Сертификат соответствия" if pt == "СС" else pt
        out.append(
            {
                "id": -(abs(hash((hs_code, tr, pt))) % 1_000_000),
                "commodity_code": hs_code,
                "measure_type": "tr_ts",
                "description": (req.get("description") or req.get("tr_ts_full_name") or act).strip(),
                "document_required": doc,
                "regulatory_act": act,
            }
        )
        existing_refs.add(act.lower())
    return out


def _collapse_preview_badges(badges: set[str]) -> set[str]:
    """Все реальные типы документов на badge (СС и ДС не схлопываем)."""
    return badges


_PERMIT_BADGE_TYPES: frozenset[str] = frozenset({
    "ДС", "СС", "СГР", "РУ", "ЛЗ",
    "ВС",
    "ФСС",
    "НФ",
    "Фито", "Вет", "Серт", "Марк", "ФСТЭК", "Рад",
})

_MEASURE_TYPE_TO_BADGE: dict[str, str] = {
    "sgr": "СГР",
    "phyto_control": "Фито",
    "vet_control": "Вет",
    "certificate": "Серт",
    "license": "ЛЗ",
    "marking": "Марк",
    "fsetc": "ФСТЭК",
    "radiation_control": "Рад",
    "вс": "ВС",
    "фсс": "ФСС",
    "нф": "НФ",
    "ВС": "ВС",
    "ФСС": "ФСС",
    "НФ": "НФ",
}

_MEASURE_DESCRIPTIONS: dict[str, str] = {
    "phyto_control": "Фитосанитарный сертификат страны экспорта",
    "vet_control": "Ветеринарный сертификат",
    "certificate": "Карантинный сертификат / разрешение на ввоз",
    "license": "Лицензия на ввоз",
    "marking": "Маркировка (ЧЗ / ЕГАИС / Меркурий)",
    "fsetc": "Нотификация ФСТЭК",
    "radiation_control": "Радиационный контроль",
    "sgr": "Свидетельство государственной регистрации",
}


def _measure_type_label(measure_type: str) -> str:
    t = (measure_type or "").strip().lower()
    return _MEASURE_DESCRIPTIONS.get(t) or _measure_label(t)


def _serialize_nt_measure_row(m: NonTariffMeasure) -> dict[str, Any]:
    mtype = (m.measure_type or "").strip().lower()
    return {
        "id": m.id,
        "commodity_code": m.commodity_code,
        "measure_type": m.measure_type,
        "description": m.description or "",
        "document_required": m.document_required or "",
        "regulatory_act": m.regulatory_act or "",
        "type_label": _measure_type_label(mtype),
        "permit_type": "",
    }


_NTM_V2_PERMIT_TYPE_LABELS: dict[str, str] = {
    "СС": "Сертификат соответствия",
    "ДС": "Декларация о соответствии",
    "СГР": "Свидетельство государственной регистрации",
    "ВС": "Ветеринарный сертификат",
    "ФСС": "Фитосанитарный сертификат страны экспорта",
    "НФ": "Нотификация ФСТЭК",
    "ЛЗ": "Лицензия на ввоз",
    "РУ": "Разрешение на ввоз",
}


def _measure_type_for_v2_permit(permit_type: str, tr_ts: str | None) -> str:
    pt = (permit_type or "").strip()
    if pt in ("СС", "ДС") or tr_ts:
        return "tr_ts"
    return {
        "ВС": "vet_control",
        "ФСС": "phyto_control",
        "НФ": "fsetc",
        "СГР": "sgr",
        "ЛЗ": "license",
        "РУ": "license",
    }.get(pt, "other")


def _parse_short_desc(raw: Any) -> dict[str, Any]:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(str(raw))
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}


def _convert_ntm_v2_to_display(hs_code: str, requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Конвертирует строки ``get_full_ntm_requirements`` в формат вкладки «Нетарифка»."""
    from ..services.tr_ts_catalog import TR_TS_FULL_NAMES

    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for req in requirements:
        permit_type = (req.get("permit_type") or "").strip()
        tr_ts = (req.get("tr_ts") or "").strip()
        key = (permit_type, tr_ts)
        if key in seen:
            continue
        seen.add(key)

        short = _parse_short_desc(req.get("short_description") or "")
        label = (
            str(short.get("label") or "").strip()
            or str(short.get("consumer") or "").strip()
            or _NTM_V2_PERMIT_TYPE_LABELS.get(permit_type, "")
            or (req.get("description") or "").strip()
            or (req.get("tr_ts_full_name") or "").strip()
        )
        legal_ref = str(short.get("legal_ref") or "").strip() or (req.get("legal_ref") or "").strip()
        document_name = label or _NTM_V2_PERMIT_TYPE_LABELS.get(permit_type, permit_type)

        if tr_ts:
            full_name = TR_TS_FULL_NAMES.get(tr_ts, "") or (req.get("tr_ts_full_name") or "").strip()
            regulatory_act = f"ТР ТС {tr_ts}" + (f" — {full_name}" if full_name else "")
            type_label = _NTM_V2_PERMIT_TYPE_LABELS.get(permit_type, permit_type)
            document_required = type_label
            description = (req.get("description") or full_name or type_label).strip()
        else:
            regulatory_act = legal_ref or (req.get("regulatory_act") or "").strip()
            type_label = document_name
            document_required = (
                f"{document_name} — {legal_ref}"
                if legal_ref and legal_ref not in document_name
                else (document_name or legal_ref)
            )
            description = (req.get("description") or document_name).strip()

        result.append(
            {
                "id": abs(hash((hs_code, permit_type, tr_ts))) % 1_000_000,
                "commodity_code": hs_code,
                "measure_type": _measure_type_for_v2_permit(permit_type, tr_ts or None),
                "type_label": type_label,
                "permit_type": permit_type,
                "document_required": document_required,
                "regulatory_act": regulatory_act,
                "description": description,
                "tr_ts_full_name": TR_TS_FULL_NAMES.get(tr_ts, "") if tr_ts else label,
            }
        )
    return result


def _non_tariff_measures_for_code(hs_code: str, description: str = "") -> list[dict[str, Any]]:
    from ..services.tr_ts_catalog import get_full_ntm_requirements

    return _convert_ntm_v2_to_display(hs_code, get_full_ntm_requirements(hs_code, description))


def _permit_badges_for_hs(hs_code: str, measure_types: list[str]) -> list[str]:
    """Badge для карточки: legacy TKS (опционально) + get_full_ntm_requirements (ТР ТС + слои v2)."""
    from ..services.tr_ts_catalog import get_full_ntm_requirements

    badges: set[str] = set()
    if USE_LEGACY_NTM:
        for mt in measure_types:
            t = (mt or "").strip().lower()
            badge = _MEASURE_TYPE_TO_BADGE.get(t)
            if badge:
                badges.add(badge)

    for req in get_full_ntm_requirements(hs_code, ""):
        pt = (req.get("permit_type") or "").strip()
        if pt and pt in _PERMIT_BADGE_TYPES:
            badges.add(pt)

    badges = _collapse_preview_badges(badges)

    priority = {
        "ДС": 0, "СС": 1, "СГР": 2,
        "Фито": 3, "Вет": 4, "ФСС": 5, "ВС": 6,
        "Серт": 7, "ЛЗ": 8, "Марк": 9, "ФСТЭК": 10, "НФ": 11, "Рад": 12,
        "РУ": 13,
    }
    return sorted(badges, key=lambda b: (priority.get(b, 99), b))


def _measures_for_api(hs_code: str, measure_types: list[str] | None = None) -> list[dict[str, str]]:
    """Упрощённые меры для фронта: type + document + description."""
    from ..services.tr_ts_catalog import get_full_ntm_requirements

    badges = _permit_badges_for_hs(hs_code, measure_types or [])
    by_type: dict[str, dict[str, Any]] = {}

    if USE_LEGACY_NTM:
        for mt in measure_types or []:
            t = (mt or "").strip().lower()
            badge = _MEASURE_TYPE_TO_BADGE.get(t)
            if badge and badge not in by_type:
                label = _MEASURE_DESCRIPTIONS.get(t, badge)
                by_type[badge] = {
                    "type": badge,
                    "document": label,
                    "description": label,
                }

    for req in get_full_ntm_requirements(hs_code, ""):
        pt = (req.get("permit_type") or "").strip()
        if pt in badges and pt not in by_type:
            tr = (req.get("tr_ts") or "").strip()
            by_type[pt] = {
                "type": pt,
                "document": f"ТР ТС {tr}" if tr else pt,
                "description": (req.get("description") or req.get("tr_ts_full_name") or "").strip(),
            }
    out: list[dict[str, str]] = []
    for pt in badges:
        if pt in by_type:
            out.append(by_type[pt])
        else:
            out.append({"type": pt, "document": pt, "description": ""})
    return out


def _resolve_duty_for_display(row: Commodity, hs_code: str) -> str:
    duty = _format_duty(row.import_duty or "")
    if duty:
        return duty
    hs_rate, _ = find_rate_for_hs(hs_code)
    if hs_rate and hs_rate.duty_rate is not None:
        duty = _format_duty(str(hs_rate.duty_rate).strip())
        if duty:
            return duty
    return ""


_NT_FALLBACK_NOISE = "Извлечено в fallback-режиме без LLM"


def _is_non_tariff_ui_noise(text: str) -> bool:
    """Текст меры, который не показываем в справке (fallback-парсер, «мусорные» числа)."""
    t = (text or "").strip()
    if not t:
        return True
    if _NT_FALLBACK_NOISE in t:
        return True
    if re.fullmatch(r"\d+", t):
        return True
    return False


def _format_nt_measure_line(m: NonTariffMeasure) -> str | None:
    """Одна строка справки по мере: тип + осмысленные поля."""
    mtype = (m.measure_type or "").strip().lower()
    label = _measure_label(mtype)
    doc = (m.document_required or "").strip()
    act = (m.regulatory_act or "").strip()
    desc = (m.description or "").strip()
    parts: list[str] = []
    if not _is_non_tariff_ui_noise(doc):
        parts.append(doc)
    if not _is_non_tariff_ui_noise(act):
        parts.append(act)
    if not _is_non_tariff_ui_noise(desc):
        parts.append(desc)
    if not parts:
        return None
    return f"[{label}] " + " — ".join(parts)


def _nt_reference_lines(rows: list[NonTariffMeasure], types: set[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for m in rows:
        if (m.measure_type or "").strip().lower() not in types:
            continue
        line = _format_nt_measure_line(m)
        if not line or line in seen:
            continue
        seen.add(line)
        out.append(line)
    return out


def _nt_section_items_or_placeholder(items: list[str]) -> list[str]:
    return items if items else ["Специфические требования не найдены."]


def _trois_prefix_candidates(code: str) -> list[str]:
    d = _digits(code)
    if len(d) >= 10:
        return [d[:6], d[:4]]
    if len(d) == 6:
        return [d[:6], d[:4]]
    if len(d) == 4:
        return [d[:4]]
    if len(d) > 4:
        return [d[:6], d[:4]]
    return []


def _get_trois_matches(db: Session, code: str) -> list[IntellectualProperty]:
    prefixes = [p for p in _trois_prefix_candidates(code) if len(p) in (4, 6)]
    if not prefixes:
        return []
    rows = (
        db.query(IntellectualProperty)
        .filter(IntellectualProperty.hs_code_prefix.in_(prefixes))
        .order_by(IntellectualProperty.hs_code_prefix.desc(), IntellectualProperty.brand_name.asc())
        .all()
    )
    return rows


def _get_special_duty_rows(db: Session, code: str) -> list[SpecialDuty]:
    d = _digits(code)
    if not d:
        return []
    prefixes: list[str] = []
    if len(d) >= 10:
        prefixes.append(d[:10])
    if len(d) >= 8:
        prefixes.append(d[:8])
    if len(d) >= 6:
        prefixes.append(d[:6])
    if len(d) >= 4:
        prefixes.append(d[:4])
    prefixes = list(dict.fromkeys(prefixes))
    if not prefixes:
        return []
    return (
        db.query(SpecialDuty)
        .filter(SpecialDuty.hs_code_prefix.in_(prefixes))
        .order_by(SpecialDuty.hs_code_prefix.desc(), SpecialDuty.origin_country.asc())
        .all()
    )


def _get_vat_preferences_rows(db: Session, code: str) -> list[VatPreference]:
    d = _digits(code)
    if not d:
        return []
    prefixes: list[str] = []
    for ln in (10, 8, 6, 4, 2):
        if len(d) >= ln:
            prefixes.append(d[:ln])
    prefixes = list(dict.fromkeys(prefixes))
    rows = db.query(VatPreference).filter(VatPreference.hs_code_prefix.in_(prefixes)).all()
    by_prefix = {p: i for i, p in enumerate(prefixes)}
    rows.sort(key=lambda r: by_prefix.get(r.hs_code_prefix, 99))
    return rows


# Сноски к таблице тарифа в PDF: «63С)», «563С)», «1363С)» — не показываем пользователю.
_DUTY_FOOTNOTE_RE = re.compile(r"\d+[СC]\)")  # кириллическая С или латинская C


def _strip_duty_footnotes(s: str) -> str:
    """Убирает ссылки на сноски в колонке ставки (цифры + С + закрывающая скобка)."""
    if not s:
        return ""
    t = _DUTY_FOOTNOTE_RE.sub("", s)
    return re.sub(r"\s+", " ", t).strip()


def _format_duty(raw: str) -> str:
    """Нормализация ставки пошлины: '5' → '5%', '5 %' → '5%', '5 eur/kg' → без изменений."""
    t = _strip_duty_footnotes((raw or "").strip())
    if not t or t in ("-", "—"):
        return ""
    low = t.lower()
    # «Пошлина: 5% | НДС: 20%» — берём только часть пошлины; мусор без цифр отсекаем.
    if "пошлина:" in low and "ндс:" in low:
        if not re.search(r"\d", t):
            return ""
        duty_part = re.split(r"\|", t, maxsplit=1)[0]
        duty_part = re.sub(r"^.*?пошлина:\s*", "", duty_part, flags=re.I).strip()
        if not duty_part or not re.search(r"\d", duty_part):
            return ""
        t = duty_part
        low = t.lower()
    if low in {"пошлина:", "ндс:", "пошлина", "ндс"}:
        return ""
    # уже содержит % или спецсимволы
    if "%" in t or "eur" in t.lower() or "€" in t.lower() or any(c.isalpha() for c in t):
        return re.sub(r"\s+", " ", t).replace(" %", "%")
    # чистое число → добавляем %
    clean = t.replace(",", ".").replace(" ", "")
    try:
        num = float(clean)
        if num == int(num):
            return f"{int(num)}%"
        return f"{num}%".replace(".", ",")
    except ValueError:
        return t


# Паттерн ведущих дефисов/тире в описаниях ТН ВЭД
_LEADING_DASHES_RE = re.compile(r"^[\s\u2013\u2014\-]+")   # en-dash, em-dash, hyphen
_TRAILING_NOISE_RE = re.compile(r"[\s\u2013\u2014\-,]+$")


def _strip_leading_dashes(s: str) -> str:
    """Убирает ведущие «–»/«—»/«-» и завершающие запятые/тире из строки."""
    t = _LEADING_DASHES_RE.sub("", s.strip())
    return _TRAILING_NOISE_RE.sub("", t).strip()


_PAD_SUBHEADING_RE = re.compile(r"^(.+?)\s[\u2013\u2014\-]\s(.+)$")


def _split_position_pad_name(raw: str) -> tuple[str, str]:
    """Разбивает описание XXXX000000 на заголовок позиции и подзаголовок субпозиции."""
    s = (raw or "").strip()
    m = _PAD_SUBHEADING_RE.match(s)
    if m:
        title = m.group(1).strip()
        sub = _strip_leading_dashes(m.group(2).strip())
        return title, sub
    return _strip_leading_dashes(s), ""


def _count_leading_dashes(s: str) -> int:
    """Считает количество ведущих тире «–» (с пробелами между ними)."""
    m = re.match(r"^([\s\u2013\u2014\-]+)", s)
    if not m:
        return 0
    return len(re.findall(r"[\u2013\u2014\-]", m.group(1)))


# Префиксы, с которых начинаются «мусорные» производные имена для 6-значных узлов.
# Они описывают подкатегорию товара, а не само наименование позиции.
_GENERIC_PREFIXES: tuple[str, ...] = (
    "прочие", "другие", "иные",
    "для ", "животные для", "растения для",
    "из ", "в том числе",
    "обработанные", "необработанные",
    "шт ",
)


def _is_meaningful_name(s: str) -> bool:
    """Возвращает True, если строка — осмысленное наименование позиции,
    а не техническая подкатегория ('прочие', 'для научно...', и т.п.)."""
    if not s or len(s) < 4:
        return False
    low = s.lower().strip()
    for prefix in _GENERIC_PREFIXES:
        if low.startswith(prefix):
            return False
    # Обрезанный текст (оканчивается дефисом или незаконченным словом)
    if s.rstrip().endswith("-"):
        return False
    return True


def _best_name_for_group(leaves: list[dict]) -> str:
    """
    Выбирает наилучшее наименование для синтетического 6-значного узла.
    Сначала пытаемся выбрать «осмысленное» имя (не generic-подкатегория),
    иначе берём лучшее доступное непустое имя, чтобы узел не оставался пустым.
    """
    if not leaves:
        return ""
    by_dashes = sorted(leaves, key=lambda n: _count_leading_dashes(n.get("name", "") or ""))
    cleaned: list[str] = []
    for node in by_dashes:
        raw = (node.get("name") or "").strip()
        stripped = _strip_leading_dashes(raw)
        if not stripped:
            continue
        candidate = stripped[:1].upper() + stripped[1:] if stripped else ""
        if candidate:
            cleaned.append(candidate)

    if not cleaned:
        return ""

    meaningful = [name for name in cleaned if _is_meaningful_name(name)]
    if meaningful:
        return meaningful[0]
    return cleaned[0]


# ---------------------------------------------------------------------------
# Вспомогательные эндпоинты (секции/главы/позиции)
# ---------------------------------------------------------------------------

@router.get("/search")
def search_commodities(
    q: str = Query("", description="Поиск по коду или наименованию"),
    db: Session = Depends(get_db),
) -> JSONResponse:
    from ..services.normative_store import _expand_query_terms, get_search_suggestions, is_leaf_hs_code
    from ..services.tnved_fts import search_commodities_fts

    query = (q or "").strip()
    if len(query) < 2:
        return JSONResponse({"status": "OK", "results": []})

    # Основной путь — релевантный FTS5-поиск по всей номенклатуре (bm25 ранжирование).
    fts_rows = search_commodities_fts(query, limit=50)
    if fts_rows is not None:
        results = [
            {
                "code": _pad_code(r["code"] or ""),
                "name": _strip_leading_dashes((r.get("description") or "").strip()),
                "is_leaf": is_leaf_hs_code(_pad_code(r["code"] or "")),
            }
            for r in fts_rows
            if not _is_obsolete_reserved_description(r.get("description"))
        ]
    else:
        # Fallback (FTS5 недоступен в сборке SQLite): LIKE по расширенным терминам.
        terms = _expand_query_terms(query)
        digit_prefix = _digits(query)
        filters = [func.lower(Commodity.description).like(f"%{t}%") for t in terms]
        if digit_prefix:
            filters.append(Commodity.code.like(f"{digit_prefix}%"))
        rows = (
            _exclude_obsolete_reserved(
                db.query(Commodity.code, Commodity.description)
            )
            .filter(or_(*filters))
            .order_by(Commodity.code.asc())
            .limit(50)
            .all()
        )
        results = [
            {
                "code": _pad_code(code or ""),
                "name": _strip_leading_dashes((name or "").strip()),
                "is_leaf": is_leaf_hs_code(_pad_code(code or "")),
            }
            for code, name in rows
        ]

    resp: dict[str, Any] = {"status": "OK", "results": results}
    if not results:
        resp["suggestions"] = get_search_suggestions()
    return JSONResponse(resp)


@router.get("/sections")
def list_sections(db: Session = Depends(get_db)) -> JSONResponse:
    rows = db.query(Section).order_by(Section.id.asc()).all()
    count_rows = (
        db.query(
            Chapter.section_id.label("section_id"),
            func.count(func.distinct(Chapter.id)).label("chapters_count"),
            func.count(func.distinct(Commodity.id)).label("commodities_count"),
            func.count(NonTariffMeasure.id).label("non_tariff_measures_count"),
        )
        .outerjoin(Commodity, Commodity.chapter_id == Chapter.id)
        .outerjoin(NonTariffMeasure, NonTariffMeasure.commodity_code == Commodity.code)
        .group_by(Chapter.section_id)
        .all()
    )
    by_section_id = {
        int(row.section_id): {
            "chapters_count": int(row.chapters_count or 0),
            "commodities_count": int(row.commodities_count or 0),
            "non_tariff_measures_count": int(row.non_tariff_measures_count or 0),
        }
        for row in count_rows
    }
    sections: list[dict[str, Any]] = []
    for s in rows:
        counts = by_section_id.get(s.id, {})
        sections.append({
            "id": s.id,
            "roman_number": s.roman_number,
            "title": s.title or "",
            "notes": s.notes or "",
            "chapters_count": int(counts.get("chapters_count", 0)),
            "commodities_count": int(counts.get("commodities_count", 0)),
            "non_tariff_measures_count": int(counts.get("non_tariff_measures_count", 0)),
        })
    return JSONResponse({"status": "OK", "sections": sections})


@router.get("/sections/{section_id}/chapters")
def list_chapters(section_id: int, db: Session = Depends(get_db)) -> JSONResponse:
    sec = db.query(Section).filter(Section.id == section_id).first()
    if not sec:
        raise HTTPException(status_code=404, detail="Раздел не найден")
    chs = db.query(Chapter).filter(Chapter.section_id == section_id).order_by(Chapter.code.asc()).all()
    chapters = [{"id": c.id, "section_id": c.section_id, "code": c.code, "title": c.title or "", "notes": c.notes or ""} for c in chs]
    return JSONResponse({"status": "OK", "chapters": chapters})


@router.get("/chapters/{chapter_id}/commodities")
def list_commodities(
    chapter_id: int,
    db: Session = Depends(get_db),
    limit: int = Query(8000, ge=1, le=50_000),
) -> JSONResponse:
    ch = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    if not ch:
        raise HTTPException(status_code=404, detail="Группа не найдена")
    items = (
        db.query(Commodity)
        .filter(Commodity.chapter_id == chapter_id)
        .order_by(Commodity.code.asc())
        .limit(limit)
        .all()
    )
    commodities = [{
        "id": c.id,
        "chapter_id": c.chapter_id,
        "code": str(c.code),
        "description": c.description or "",
        "unit": c.unit or "",
        "import_duty": _format_duty(c.import_duty),
    } for c in items]
    return JSONResponse({"status": "OK", "chapter_id": chapter_id, "commodities": commodities, "total": len(commodities)})


# ---------------------------------------------------------------------------
# Построение иерархического дерева 4 → 10
# ---------------------------------------------------------------------------

_OBSOLETE_RESERVED_DESC_PREFIX = "Товарная позиция"


def _is_obsolete_reserved_description(description: str | None) -> bool:
    """Упразднённые резервные позиции без реального содержания (35 записей в БД)."""
    return (description or "").strip().startswith(_OBSOLETE_RESERVED_DESC_PREFIX)


def _exclude_obsolete_reserved(q):
    return q.filter(~Commodity.description.like(f"{_OBSOLETE_RESERVED_DESC_PREFIX}%"))


def _collect_chapter_notes(db: Session) -> dict[str, str]:
    """
    Собирает объединённые примечания (раздел + группа) для каждого кода главы.
    Ключ — 4-значный код группы (zfill(4)).
    """
    chs = db.query(Chapter).options(joinedload(Chapter.section)).all()
    result: dict[str, str] = {}
    for ch in chs:
        d = _digits(ch.code or "")
        if not d:
            continue
        key = d.zfill(4)
        parts: list[str] = []
        sec = ch.section
        if sec and (sec.notes or "").strip():
            parts.append(f"Раздел {sec.roman_number}:\n{sec.notes.strip()}")
        if (ch.notes or "").strip():
            parts.append(f"Группа {ch.code}:\n{ch.notes.strip()}")
        result[key] = "\n\n".join(parts)
    return result


def _node_level(code10: str) -> int:
    """Структурный уровень 10-значного кода ТН ВЭД: 4 / 6 / 8 / 9 / 10.

    Коды в БД хранятся 10-значными с паддингом нулями. Нулевой «хвост» означает,
    что это промежуточный (бескодовый) уровень иерархии, а не самостоятельный
    декларируемый код. Уровни считаются по границам субпозиций (4→6→8) и по
    национальным разрядам (9→10):

      9401200000 → 6  (субпозиция 9401 20, бескодовая если есть 9401 20 000 1/9)
      9401200001 → 10 (декларируемый национальный код)
      8703211090 → 9  (национальная группа, родитель 8703 21 109 1/9)
      9401000000 → 4  (паддинг товарной позиции = сама позиция 9401)
    """
    if code10[9] != "0":
        return 10
    if code10[8] != "0":
        return 9
    if code10[6:8] != "00":
        return 8
    if code10[4:6] != "00":
        return 6
    return 4


def _is_direct_position_subheading(code10: str) -> bool:
    """Субпозиция уровня XXXX30 / XXXX90 — прямой потомок 4-значной позиции, не XXXX00."""
    if _node_level(code10) != 6:
        return False
    return code10[4] != "0" and code10[5] == "0"


def _make_node(
    code: str,
    name: str,
    import_duty: str,
    notes: str,
    *,
    is_leaf: bool,
    is_codeless: bool,
    is_group: bool,
) -> dict[str, Any]:
    return {
        "code": code,
        "name": name,
        "import_duty": import_duty,
        "notes": notes,
        # Классификация узла для фронтенда:
        #   is_leaf     — терминальный 10-значный декларируемый код (кликабельный)
        #   is_codeless — промежуточная бескодовая субпозиция (только текст)
        #   is_group    — раздел/группа/позиция (раскрываемый заголовок)
        "is_leaf": is_leaf,
        "is_codeless": is_codeless,
        "is_group": is_group,
        "display_code": _digits(code),
        "children": [],
    }


def _collect_leaf_names(node: dict[str, Any], acc: list[dict[str, Any]]) -> None:
    for ch in node["children"]:
        if not ch["children"]:
            acc.append(ch)
        else:
            _collect_leaf_names(ch, acc)


def _needs_pad_subheading_group(pad_sub: str, level6_codes: list[str]) -> bool:
    """Codeless-узел pad-sub нужен только если есть «прямые» XXXX30/90 и другие level-6 (0101)."""
    if not pad_sub or not level6_codes:
        return False
    direct = sum(1 for c in level6_codes if _is_direct_position_subheading(c))
    return 0 < direct < len(level6_codes)


def _build_tree(rows: list[Commodity], chapter_notes: dict[str, str]) -> list[dict[str, Any]]:
    """
    Плоский список tnved_commodities (10-значные коды с паддингом) → дерево
    позиция(4) → субпозиция(6) → подсубпозиция(8) → национальный код(10).

    Бескодовые субпозиции (промежуточные узлы с детьми) помечаются
    is_codeless=True и НЕ являются кликабельными кодами. Терминальные коды —
    is_leaf=True. Иерархия восстанавливается из структуры самих кодов
    (см. _node_level), не из форматирования описаний.
    """
    parents: dict[str, dict[str, Any]] = {}      # 4-digit key → heading node
    ten_by_code: dict[str, dict[str, str]] = {}  # 10-digit code → raw fields

    for r in rows:
        raw_code = (r.code or "").strip()
        d = _digits(raw_code)
        if not d:
            continue

        if len(d) <= 4:
            key4 = d.zfill(4)
            if key4 not in parents:
                parents[key4] = _make_node(
                    key4, (r.description or "").strip(), "", chapter_notes.get(key4, ""),
                    is_leaf=False, is_codeless=False, is_group=True,
                )
            elif not parents[key4]["name"]:
                parents[key4]["name"] = (r.description or "").strip()
        else:
            code10 = d.zfill(10)[:10]
            ten_by_code[code10] = {
                "code": code10,
                "raw_name": (r.description or "").strip(),
                "name": _strip_leading_dashes((r.description or "").strip()),
                "import_duty": _format_duty(r.import_duty),
            }

    # Создаём отсутствующие 4-значные родители для 10-значных кодов
    for code10 in ten_by_code:
        p4 = code10[:4]
        if p4 not in parents:
            parents[p4] = _make_node(
                p4, "", "", chapter_notes.get(p4, ""),
                is_leaf=False, is_codeless=False, is_group=True,
            )

    # Группируем 10-значные коды по товарной позиции (первые 4 знака)
    by_heading: dict[str, list[str]] = {}
    for code10 in ten_by_code:
        by_heading.setdefault(code10[:4], []).append(code10)

    for p4, codes in by_heading.items():
        heading = parents[p4]
        codes.sort()

        # XXXX000000 — паддинг товарной позиции. Отдельный codeless-узел только
        # если есть уникальный подзаголовок («лошади:», «свежие:»). Иначе pad
        # дублирует heading — пропускаем, дети идут напрямую под позицию.
        pad_code = p4 + "000000"
        deeper = [c for c in codes if c != pad_code]
        pad_sub = ""
        if pad_code in ten_by_code:
            raw_pad = ten_by_code[pad_code].get("raw_name") or ""
            title, sub = _split_position_pad_name(raw_pad)
            if title and (not heading["name"] or not _is_meaningful_name(heading["name"])):
                heading["name"] = title
            pad_sub = sub
            if not pad_sub and (not heading["name"] or not _is_meaningful_name(heading["name"])):
                heading["name"] = title or ten_by_code[pad_code]["name"]
            codes = deeper
        elif pad_code in ten_by_code and not deeper:
            cand = ten_by_code[pad_code]["name"]
            if cand and (not heading["name"] or not _is_meaningful_name(heading["name"])):
                heading["name"] = cand

        level6_codes = [c for c in codes if _node_level(c) == 6]
        direct_l6 = {c for c in level6_codes if _is_direct_position_subheading(c)}
        use_subheading_group = _needs_pad_subheading_group(pad_sub, level6_codes)

        subheading_group: dict[str, Any] | None = None
        if use_subheading_group:
            pad_raw = ten_by_code.get(pad_code, {})
            subheading_group = _make_node(
                pad_code,
                pad_sub,
                pad_raw.get("import_duty", ""),
                heading["notes"],
                is_leaf=False,
                is_codeless=True,
                is_group=True,
            )
            heading["children"].append(subheading_group)

        stack: list[tuple[int, dict[str, Any]]] = []
        for code10 in codes:
            lvl = _node_level(code10)
            raw = ten_by_code[code10]
            node = _make_node(
                code10, raw["name"], raw["import_duty"], heading["notes"],
                is_leaf=True, is_codeless=False, is_group=False,
            )
            if use_subheading_group and lvl == 6 and code10 not in direct_l6:
                while stack:
                    stack.pop()
                parent_node = subheading_group
            else:
                while stack and stack[-1][0] >= lvl:
                    stack.pop()
                parent_node = stack[-1][1] if stack else heading
            parent_node["children"].append(node)
            stack.append((lvl, node))

    # Классификация: 10-значный узел с детьми — бескодовая субпозиция
    def _classify(node: dict[str, Any]) -> None:
        for ch in node["children"]:
            _classify(ch)
        if len(node["display_code"]) == 10:
            from ..services.normative_store import is_leaf_hs_code

            if node["children"]:
                node["is_leaf"] = False
                node["is_codeless"] = True
                node["is_group"] = True
            else:
                leaf = is_leaf_hs_code(node["code"])
                node["is_leaf"] = leaf
                node["is_codeless"] = not leaf
                node["is_group"] = not leaf

    def _sort(node: dict[str, Any]) -> None:
        node["children"].sort(key=lambda x: x["code"])
        for ch in node["children"]:
            _sort(ch)

    for p in parents.values():
        _classify(p)
        _sort(p)
        # Заполняем пустое имя позиции лучшим именем из дочерних листьев
        if not p["name"]:
            leaves: list[dict[str, Any]] = []
            _collect_leaf_names(p, leaves)
            p["name"] = _best_name_for_group(leaves)

    return sorted(parents.values(), key=lambda x: x["code"])


# ---------------------------------------------------------------------------
# Оборачиваем дерево 4→6→10 в структуру Раздел → Группа → …
# ---------------------------------------------------------------------------

_ROMAN_RANK: dict[str, int] = {r: i for i, r in enumerate([
    "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X",
    "XI", "XII", "XIII", "XIV", "XV", "XVI", "XVII", "XVIII", "XIX", "XX",
    "XXI", "XXII",
])}


def _wrap_in_sections(
    flat_tree: list[dict[str, Any]],
    db: Session,
) -> list[dict[str, Any]]:
    """
    Принимает плоский список 4-значных узлов и возвращает полную иерархию:
    Раздел (roman) → Группа (2 знака) → 4-знак → 6-знак → 10-знак.
    """
    # Быстрый доступ: первые 2 цифры → список 4-значных узлов
    by_ch: dict[str, list] = {}
    for node in flat_tree:
        by_ch.setdefault(node["code"][:2], []).append(node)

    sections = (
        db.query(Section)
        .options(selectinload(Section.chapters))
        .all()
    )
    # Сортируем по порядку римских цифр, не по id
    sections.sort(key=lambda s: _ROMAN_RANK.get(s.roman_number or "", 99))

    result: list[dict[str, Any]] = []
    for sec in sections:
        ch_nodes: list[dict[str, Any]] = []

        for ch in sorted(sec.chapters, key=lambda c: c.code):
            ch_digits = _digits(ch.code or "")
            if not ch_digits:
                continue
            ch_prefix = ch_digits[:2].zfill(2)
            headings = sorted(by_ch.get(ch_prefix, []), key=lambda x: x["code"])
            if not headings:
                continue
            ch_node = _make_node(
                ch_prefix, (ch.title or "").strip(), "", (ch.notes or "").strip(),
                is_leaf=False, is_codeless=False, is_group=True,
            )
            ch_node["children"] = headings
            ch_nodes.append(ch_node)

        if not ch_nodes:
            continue

        sec_node = _make_node(
            sec.roman_number or f"S{sec.id}", (sec.title or "").strip(), "", (sec.notes or "").strip(),
            is_leaf=False, is_codeless=False, is_group=True,
        )
        sec_node["display_code"] = ""  # раздел кодируется римской цифрой
        sec_node["children"] = ch_nodes
        result.append(sec_node)

    return result


_ROMAN_SECTION_RE = re.compile(r"^[IVXLCDM]+$", re.IGNORECASE)


def _is_roman_section(code: str) -> bool:
    return bool(_ROMAN_SECTION_RE.match((code or "").strip()))


def _tree_prefix_for_code(d: str) -> str:
    """Минимальный префикс для пересборки поддерева с прямыми потомками узла."""
    if not d:
        return ""
    if len(d) <= 2:
        return d
    return d[:4]


def _find_node_in_tree(nodes: list[dict[str, Any]], code: str) -> dict[str, Any] | None:
    target = (code or "").strip()
    target_digits = _digits(code)
    target_roman = target.upper() if _is_roman_section(target) else ""
    for node in nodes:
        node_code = (node.get("code") or "").strip()
        if target_roman and node_code.upper() == target_roman:
            return node
        if target_digits and _digits(node_code) == target_digits:
            return node
        if node_code == target:
            return node
        found = _find_node_in_tree(node.get("children") or [], code)
        if found:
            return found
    return None


def _infer_api_level(code: str, node: dict[str, Any]) -> str:
    if _is_roman_section(code):
        return "section"
    d = _digits(code)
    if len(d) <= 2:
        return "chapter"
    if len(d) <= 4:
        return "heading"
    if node.get("is_leaf"):
        return "leaf"
    if len(d) <= 6:
        return "subheading"
    if node.get("is_codeless") or node.get("is_group"):
        return "subheading"
    return "leaf"


def _resolve_rates_for_code(db: Session, code: str, import_duty: str) -> tuple[str, float | None]:
    d = _digits(code)
    hs_code = d.zfill(10)[:10] if len(d) >= 6 else d.zfill(4)[:4]
    hs_rate, _ = find_rate_for_hs(hs_code) if len(d) >= 4 else (None, 0)
    duty = _format_duty(import_duty)
    if not duty and hs_rate:
        duty = _format_duty(str(hs_rate.duty_rate or "").strip())
    vat_rate: float | None = None
    if hs_rate and hs_rate.vat_import_rate is not None:
        vat_rate = float(hs_rate.vat_import_rate)
    elif len(d) >= 4:
        vat_rate = 22.0
    return duty, vat_rate


def _permit_flags_for_hs(hs_code: str) -> tuple[bool, bool]:
    from ..services.tr_ts_catalog import get_tr_ts_requirements

    has_ds = False
    has_ss = False
    for req in get_tr_ts_requirements(hs_code):
        pt = (req.get("permit_type") or "").strip()
        if pt == "ДС":
            has_ds = True
        elif pt == "СС":
            has_ss = True
    return has_ds, has_ss


def _serialize_tree_node(db: Session, node: dict[str, Any]) -> dict[str, Any]:
    code = node.get("code") or ""
    children = node.get("children") or []
    duty, vat_rate = _resolve_rates_for_code(db, code, node.get("import_duty") or "")
    is_leaf = bool(node.get("is_leaf"))
    has_ds = False
    has_ss = False
    if is_leaf and not node.get("is_codeless"):
        has_ds, has_ss = _permit_flags_for_hs(code)
    measures: list[dict[str, str]] = []
    if is_leaf and not node.get("is_codeless"):
        measures = _measures_for_api(code)
    return {
        "code": code,
        "display_code": _digits(code) if not _is_roman_section(code) else code.upper(),
        "name": node.get("name") or "",
        "level": _infer_api_level(code, node),
        "is_leaf": is_leaf,
        "is_codeless": bool(node.get("is_codeless")),
        "is_group": bool(node.get("is_group")),
        "has_children": len(children) > 0,
        "import_duty": duty,
        "duty_rate": duty,
        "vat_rate": vat_rate,
        "children_count": len(children),
        "has_ds": has_ds,
        "has_ss": has_ss,
        "measures": measures,
    }


def _build_wrapped_tree(db: Session, prefix: str) -> list[dict[str, Any]]:
    p = _digits(prefix)
    q = _exclude_obsolete_reserved(db.query(Commodity).order_by(Commodity.code.asc()))
    if p:
        q = q.filter(Commodity.code.like(f"{p}%"))
    rows = q.limit(2_000_000).all()
    chapter_notes = _collect_chapter_notes(db)
    flat = _build_tree(rows, chapter_notes)
    return _wrap_in_sections(flat, db)


def _resolve_tree_node(db: Session, code: str) -> dict[str, Any] | None:
    code = (code or "").strip()
    if not code:
        return None
    if _is_roman_section(code):
        tree = _build_wrapped_tree(db, "")
        return _find_node_in_tree(tree, code.upper())
    d = _digits(code)
    if not d:
        return None
    prefix = _tree_prefix_for_code(d)
    tree = _build_wrapped_tree(db, prefix)
    return _find_node_in_tree(tree, code)


def list_tnved_children(db: Session, code: str, depth: str = "direct") -> dict[str, Any]:
    code = (code or "").strip()
    depth_norm = (depth or "direct").lower()
    if depth_norm not in {"direct", "all"}:
        raise HTTPException(status_code=400, detail="depth must be 'direct' or 'all'")

    if not code:
        sections = db.query(Section).order_by(Section.id.asc()).all()
        sections.sort(key=lambda s: _ROMAN_RANK.get(s.roman_number or "", 99))
        items = [
            {
                "code": sec.roman_number,
                "display_code": sec.roman_number,
                "name": (sec.title or "").strip(),
                "level": "section",
                "is_leaf": False,
                "is_codeless": False,
                "is_group": True,
                "has_children": True,
                "import_duty": "",
                "duty_rate": "",
                "vat_rate": None,
                "children_count": len(sec.chapters or []),
                "section_id": sec.id,
            }
            for sec in sections
        ]
        return {"status": "OK", "code": "", "depth": depth_norm, "items": items}

    if _is_roman_section(code):
        sec = (
            db.query(Section)
            .options(selectinload(Section.chapters))
            .filter(Section.roman_number == code.upper())
            .first()
        )
        if not sec:
            raise HTTPException(status_code=404, detail="Раздел не найден")
        items = [
            {
                "code": ch.code,
                "display_code": ch.code,
                "name": (ch.title or "").strip(),
                "level": "chapter",
                "is_leaf": False,
                "is_codeless": False,
                "is_group": True,
                "has_children": True,
                "import_duty": "",
                "duty_rate": "",
                "vat_rate": None,
                "children_count": 0,
                "section_id": sec.id,
                "chapter_id": ch.id,
            }
            for ch in sorted(sec.chapters or [], key=lambda c: c.code)
        ]
        return {"status": "OK", "code": code.upper(), "depth": depth_norm, "items": items}

    d = _digits(code)
    if len(d) == 2:
        node = _resolve_tree_node(db, d)
        if not node:
            raise HTTPException(status_code=404, detail="Группа не найдена")
        items = [_serialize_tree_node(db, ch) for ch in node.get("children") or []]
        return {"status": "OK", "code": d, "depth": depth_norm, "items": items}

    node = _resolve_tree_node(db, code)
    if not node:
        raise HTTPException(status_code=404, detail="Узел не найден")

    children = node.get("children") or []
    if depth_norm == "all":

        def _flatten(nodes: list[dict[str, Any]], acc: list[dict[str, Any]]) -> None:
            for ch in nodes:
                acc.append(_serialize_tree_node(db, ch))
                _flatten(ch.get("children") or [], acc)

        flat_items: list[dict[str, Any]] = []
        _flatten(children, flat_items)
        items = flat_items
    else:
        items = [_serialize_tree_node(db, ch) for ch in children]

    return {"status": "OK", "code": code, "depth": depth_norm, "items": items}


def get_tnved_node(db: Session, code: str) -> dict[str, Any]:
    code = (code or "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="code required")
    if _is_roman_section(code):
        raise HTTPException(status_code=400, detail="Используйте /children/{section} для разделов")
    node = _resolve_tree_node(db, code)
    if not node:
        raise HTTPException(status_code=404, detail="Узел не найден")
    payload = _serialize_tree_node(db, node)
    payload["children"] = [_serialize_tree_node(db, ch) for ch in node.get("children") or []]
    return {"status": "OK", "node": payload}


# ---------------------------------------------------------------------------
# Основной эндпоинт дерева
# ---------------------------------------------------------------------------

@router.get("/hierarchy-tree")
def hierarchy_tree(
    prefix: str = Query("", max_length=10, description="Префикс кода (цифры)"),
    limit: int = Query(2_000_000, ge=1, le=2_500_000),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """
    Возвращает вложенное дерево JSON:
    Раздел → Группа → 4-знак → 6-знак → 10-знак.
    Каждый узел: code, name, import_duty, notes, children.
    """
    p = _digits(prefix)
    q = _exclude_obsolete_reserved(
        db.query(Commodity)
        .order_by(Commodity.code.asc())
    )
    if p:
        q = q.filter(Commodity.code.like(f"{p}%"))
    rows = q.limit(limit).all()

    chapter_notes = _collect_chapter_notes(db)
    flat = _build_tree(rows, chapter_notes)
    tree = _wrap_in_sections(flat, db)

    return JSONResponse({
        "status": "OK",
        "prefix": p,
        "count_rows": len(rows),
        "tree": tree,
    })


@router.get("/children")
def tnved_children_root(
    depth: str = Query("direct", description="direct — только прямые потомки; all — все потомки"),
    db: Session = Depends(get_db),
) -> JSONResponse:
    return JSONResponse(list_tnved_children(db, "", depth))


@router.get("/children/{code}")
def tnved_children(
    code: str,
    depth: str = Query("direct", description="direct — только прямые потомки; all — все потомки"),
    db: Session = Depends(get_db),
) -> JSONResponse:
    if code.lower() in {"root", "_"}:
        code = ""
    return JSONResponse(list_tnved_children(db, code, depth))


@router.get("/node/{code}")
def tnved_node(code: str, db: Session = Depends(get_db)) -> JSONResponse:
    return JSONResponse(get_tnved_node(db, code))


# ---------------------------------------------------------------------------
# Hover preview по коду
# ---------------------------------------------------------------------------

_PREVIEW_CACHE_TTL_SEC = int(os.getenv("TNVED_PREVIEW_CACHE_TTL_SEC", "900") or "900")
_PREVIEW_REVISION_TTL_SEC = float(os.getenv("TNVED_PREVIEW_REVISION_TTL_SEC", "45") or "45")
_PREVIEW_CACHE: dict[str, tuple[float, str, dict[str, Any]]] = {}
_PREVIEW_REVISION_TS: float = 0.0
_PREVIEW_REVISION_VAL: str = ""


def _compute_catalog_revision_token() -> str:
    """Короткий отпечаток данных каталога: при импорте/изменении объёмов кэш preview инвалидируется."""
    bump = (os.getenv("TNVED_PREVIEW_CACHE_REVISION") or "").strip()
    marker = read_preview_cache_revision_marker()
    try:
        with SessionLocal() as db:
            nc = db.query(func.count()).select_from(Commodity).scalar() or 0
            nn = db.query(func.count()).select_from(NonTariffMeasure).scalar() or 0
            ni = db.query(func.count()).select_from(IntellectualProperty).scalar() or 0
            nsd = db.query(func.count()).select_from(SpecialDuty).scalar() or 0
            mxc = db.query(func.max(Commodity.id)).scalar() or 0
        core = f"c={nc}|nt={nn}|ip={ni}|sd={nsd}|mxc={mxc}|mrk={marker or '-'}"
    except Exception:
        core = f"err|mrk={marker or '-'}"
    return f"{bump}|{core}" if bump else core


def _get_preview_cache_revision() -> str:
    global _PREVIEW_REVISION_TS, _PREVIEW_REVISION_VAL
    now = time.time()
    if _PREVIEW_REVISION_VAL and (now - _PREVIEW_REVISION_TS) < _PREVIEW_REVISION_TTL_SEC:
        return _PREVIEW_REVISION_VAL
    _PREVIEW_REVISION_VAL = _compute_catalog_revision_token()
    _PREVIEW_REVISION_TS = now
    return _PREVIEW_REVISION_VAL


def _get_preview_from_cache(code: str) -> dict[str, Any] | None:
    key = _digits(code)
    if not key:
        return None
    row = _PREVIEW_CACHE.get(key)
    if not row:
        return None
    ts, rev, payload = row
    if rev != _get_preview_cache_revision():
        _PREVIEW_CACHE.pop(key, None)
        return None
    if (time.time() - ts) > _PREVIEW_CACHE_TTL_SEC:
        _PREVIEW_CACHE.pop(key, None)
        return None
    return payload


def _put_preview_to_cache(code: str, payload: dict[str, Any]) -> None:
    key = _digits(code)
    if not key:
        return
    _PREVIEW_CACHE[key] = (time.time(), _get_preview_cache_revision(), payload)
    if len(_PREVIEW_CACHE) > 6000:
        oldest = sorted(_PREVIEW_CACHE.items(), key=lambda x: x[1][0])[:1000]
        for k, _ in oldest:
            _PREVIEW_CACHE.pop(k, None)


def clear_preview_cache() -> None:
    global _PREVIEW_REVISION_TS, _PREVIEW_REVISION_VAL
    _PREVIEW_CACHE.clear()
    _PREVIEW_REVISION_TS = 0.0
    _PREVIEW_REVISION_VAL = ""
    bump_preview_cache_revision("api_clear")


def _build_preview_payload(code: str) -> dict[str, Any]:
    norm = _digits(code)
    if len(norm) not in (4, 6, 10):
        return {"status": "ERROR", "detail": "Ожидается код ТН ВЭД из 4, 6 или 10 цифр"}

    code_key = norm.zfill(10)[:10] if len(norm) >= 6 else norm.zfill(4)
    with SessionLocal() as db:
        row = (
            db.query(Commodity)
            .options(selectinload(Commodity.non_tariff_measures))
            .filter(Commodity.code == code_key)
            .order_by(Commodity.id.asc())
            .first()
        )
        if not row and len(norm) in (6, 10):
            # fallback по префиксу для 6/10-кода
            pref = norm[:6] if len(norm) >= 6 else norm[:4]
            row = (
                db.query(Commodity)
                .options(selectinload(Commodity.non_tariff_measures))
                .filter(Commodity.code.like(f"{pref}%"))
                .order_by(Commodity.code.asc())
                .first()
            )
        if not row and len(norm) == 4:
            # В БД могут отсутствовать отдельные 4-значные строки:
            # берём первую 10-значную позицию по префиксу.
            row = (
                db.query(Commodity)
                .options(selectinload(Commodity.non_tariff_measures))
                .filter(Commodity.code.like(f"{norm}%"))
                .order_by(Commodity.code.asc())
                .first()
            )
        if not row and code_key != norm:
            row = (
                db.query(Commodity)
                .options(selectinload(Commodity.non_tariff_measures))
                .filter(Commodity.code == norm)
                .order_by(Commodity.id.asc())
                .first()
            )
        if not row and len(norm) == 10:
            out_code = norm.zfill(10)
            measure_badges = _permit_badges_for_hs(out_code, [])
            name_row = (
                db.query(Commodity)
                .filter(Commodity.code.like(f"{norm[:6]}%"))
                .order_by(Commodity.code.asc())
                .first()
            )
            from ..services.payment_engine import get_effective_vat_rate
            from ..services.rate_display import format_duty_rule_label, format_excise_display, resolve_excise_for_hs

            duty = format_duty_rule_label(out_code, "")
            raw_vat = get_effective_vat_rate(out_code)
            vat_rates = [int(raw_vat) if raw_vat == int(raw_vat) else raw_vat]
            excise_type, excise_value, excise_basis = resolve_excise_for_hs(out_code)
            excise = format_excise_display(excise_type, excise_value, excise_basis)
            return {
                "status": "OK",
                "code": out_code,
                "name": _strip_leading_dashes((name_row.description or "").strip()) if name_row else "",
                "payments": {
                    "duty": duty,
                    "vat_rates": vat_rates,
                    "excise": excise,
                },
                "non_tariff": {
                    "has_ban": False,
                    "measure_types": [],
                    "measure_badges": measure_badges,
                    "empty_message": "✅ Меры нетарифного регулирования не применяются" if not measure_badges else "",
                },
                "features": [],
                "special_duties": {
                    "has_measures": False,
                    "countries": [],
                    "warning": "",
                    "disclaimer": (
                        "Данные по мерам защиты рынка могут быть неполными. "
                        "Для точной проверки используйте: https://remedies.eaeunion.org/dimd/ru"
                    ),
                },
                "trois": {
                    "has_protected_brands": False,
                    "brands": [],
                    "items": [],
                    "warning": "",
                },
            }
        if not row:
            return {"status": "NOT_FOUND", "code": _pad_code(code)}

        out_code = _pad_code(row.code or "")
        if USE_LEGACY_NTM:
            nt_rows = _fetch_nt_rows(db, out_code)
            nt_rows = _filter_nt_rows_for_chapter(nt_rows, out_code)
        else:
            nt_rows = []
        measure_types = sorted({(m.measure_type or "").strip().lower() for m in nt_rows if (m.measure_type or "").strip()})
        measure_badges = _permit_badges_for_hs(out_code, measure_types)
        has_ban = "ban" in measure_types

        # Упрощенная витрина платежей для hover.
        from ..services.payment_engine import get_effective_vat_rate
        from ..services.rate_display import format_duty_rule_label, format_excise_display, resolve_excise_for_hs

        duty = format_duty_rule_label(out_code, row.import_duty or "")
        raw_vat = get_effective_vat_rate(out_code)
        vat_rates = [int(raw_vat) if raw_vat == int(raw_vat) else raw_vat]
        excise_type, excise_value, excise_basis = resolve_excise_for_hs(out_code)
        excise = format_excise_display(excise_type, excise_value, excise_basis)

        features: list[str] = []
        source_text = " ".join(
            f"{m.description or ''} {m.document_required or ''} {m.regulatory_act or ''}".lower()
            for m in nt_rows
        )
        if "честный знак" in source_text or "маркиров" in source_text:
            features.append("Требуется маркировка Честный знак.")
        if ("определенных пост" in source_text) or ("специализированных пост" in source_text) or ("только на пост" in source_text):
            features.append("Оформление возможно только на определенных таможенных постах.")

        trois_rows = _get_trois_matches(db, out_code)
        trois_brands = sorted({(r.brand_name or "").strip() for r in trois_rows if (r.brand_name or "").strip()})
        special_rows = _get_special_duty_rows(db, out_code)
        special_countries = sorted({(r.origin_country or "").strip().upper() for r in special_rows if (r.origin_country or "").strip()})

        return {
            "status": "OK",
            "code": out_code,
            "name": _strip_leading_dashes((row.description or "").strip()),
            "payments": {
                "duty": duty,
                "vat_rates": vat_rates,
                "excise": excise,
            },
            "non_tariff": {
                "has_ban": has_ban,
                "measure_types": measure_types,
                "measure_badges": measure_badges,
                "empty_message": "✅ Меры нетарифного регулирования не применяются" if not measure_badges else "",
            },
            "features": features,
            "special_duties": {
                "has_measures": len(special_rows) > 0,
                "countries": special_countries,
                "warning": (
                    "⚠️ Внимание: для данного кода действуют антидемпинговые меры "
                    f"(например, для стран: {', '.join(special_countries)}). "
                    "Данные по мерам защиты рынка могут быть неполными — "
                    "для точной проверки используйте remedies.eaeunion.org."
                    if special_countries
                    else ""
                ),
                "disclaimer": (
                    "Данные по мерам защиты рынка могут быть неполными. "
                    "Для точной проверки используйте: https://remedies.eaeunion.org/dimd/ru"
                ),
            },
            "trois": {
                "has_protected_brands": len(trois_brands) > 0,
                "brands": trois_brands,
                "items": [
                    {
                        "id": r.id,
                        "brand_name": r.brand_name or "",
                        "hs_code_prefix": r.hs_code_prefix or "",
                        "reg_number": r.reg_number or "",
                        "right_holder": r.right_holder or "",
                    }
                    for r in trois_rows
                ],
                "warning": (
                    "⚠️ Внимание! Данный код содержит бренды под защитой ТРОИС. "
                    f"Проверьте наличие вашего бренда в списке: {', '.join(trois_brands)}."
                    if trois_brands
                    else ""
                ),
            },
        }


@router.get("/preview/{code}")
def preview_by_code(code: str) -> JSONResponse:
    data = _get_preview_from_cache(code)
    if data is None:
        data = _build_preview_payload(code)
        _put_preview_to_cache(code, data)
    if data.get("status") == "ERROR":
        raise HTTPException(status_code=400, detail=data.get("detail", "Некорректный код"))
    if data.get("status") == "NOT_FOUND":
        raise HTTPException(status_code=404, detail="Позиция не найдена")
    return JSONResponse(data)


@router.get("/reference/{code}")
def reference_by_code(
    code: str,
    country: str = Query("", description="Страна происхождения ISO-2 (необязательно)"),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Развернутая справка по коду ТН ВЭД в стиле «Справка о товаре (импорт)»."""
    norm = _digits(code)
    if len(norm) not in (4, 10):
        raise HTTPException(status_code=400, detail="Ожидается код ТН ВЭД из 4 или 10 цифр")
    code_key = norm.zfill(4) if len(norm) == 4 else norm.zfill(10)
    row = (
        db.query(Commodity)
        .options(joinedload(Commodity.chapter).joinedload(Chapter.section), selectinload(Commodity.non_tariff_measures))
        .filter(Commodity.code == code_key)
        .order_by(Commodity.id.asc())
        .first()
    )
    if not row and code_key != norm:
        row = (
            db.query(Commodity)
            .options(joinedload(Commodity.chapter).joinedload(Chapter.section), selectinload(Commodity.non_tariff_measures))
            .filter(Commodity.code == norm)
            .order_by(Commodity.id.asc())
            .first()
        )
    if not row:
        raise HTTPException(status_code=404, detail="Позиция не найдена")

    out_code = _pad_code(row.code or "")
    ch = row.chapter
    sec = ch.section if ch else None
    section_title = (sec.title or "").strip() if sec else ""
    chapter_title = (ch.title or "").strip() if ch else ""
    product_name = (
        f"Раздел {sec.roman_number} {section_title}\n" if sec else ""
    ) + (
        f"Группа {ch.code} {chapter_title}\n" if ch else ""
    ) + _strip_leading_dashes((row.description or "").strip())

    # Данные ставок/налогов
    hs_rate, _mlen = find_rate_for_hs(out_code)
    duty_from_hs = _format_duty(str(hs_rate.duty_rate).strip()) if hs_rate else ""
    duty_value = _resolve_duty_for_display(row, out_code) or duty_from_hs or "Не указана"
    excise_text = "Не облагается"
    if hs_rate and (hs_rate.excise_type or "none") != "none":
        if (hs_rate.excise_type or "").lower() == "percent":
            excise_text = f"Применяется ставка {float(hs_rate.excise_value):.2f}% от стоимости."
        elif (hs_rate.excise_type or "").lower() == "fixed":
            excise_text = f"Применяется фиксированная ставка {float(hs_rate.excise_value):.2f} руб./ед."
        if (hs_rate.excise_basis or "").strip():
            excise_text += f"\n{hs_rate.excise_basis}"

    vat_rows = _get_vat_preferences_rows(db, out_code)
    vat_lines: list[str] = ["При импорте взимается НДС", "Основная ставка - 22 %"]
    for vr in vat_rows:
        vat_lines.append(
            f"{(vr.comment or 'Льготная категория').strip()} - {int(vr.vat_rate)} %"
        )
        if (vr.decree_info or "").strip():
            vat_lines.append(f"См. {vr.decree_info.strip()}")

    special_rows = _get_special_duty_rows(db, out_code)
    ctry = (country or "").strip().upper()
    if ctry:
        special_rows = [r for r in special_rows if (r.origin_country or "").strip().upper() == ctry]
    special_lines: list[str] = []
    if not special_rows:
        special_lines.append("Дополнительных пошлин нет.")
    else:
        for s in special_rows:
            parts: list[str] = [f"Страна {s.origin_country}:"]
            if float(s.rate_percent or 0) > 0:
                parts.append(f"{float(s.rate_percent):.2f}%")
            if float(s.rate_specific or 0) > 0:
                parts.append(f"{float(s.rate_specific):.4g} {s.currency_code}/ед.")
            if (s.regulatory_act or "").strip():
                parts.append(s.regulatory_act.strip())
            special_lines.append(" ".join(parts))

    nt_rows = _fetch_nt_rows(db, out_code) if USE_LEGACY_NTM else []
    bans_license_items = _nt_section_items_or_placeholder(_nt_reference_lines(nt_rows, {"ban", "license"}))
    permits_nt_items = _nt_section_items_or_placeholder(_nt_reference_lines(nt_rows, {"certificate", "tr_ts"}))
    other_nt_items = _nt_section_items_or_placeholder(
        _nt_reference_lines(nt_rows, {"vet_control", "phyto_control", "other"})
    )

    trois_rows = _get_trois_matches(db, out_code)
    ipr_lines: list[str] = (
        ["Код товара попадает в Реестр объектов интеллектуальной собственности."]
        if trois_rows
        else ["Совпадений по Реестру объектов интеллектуальной собственности не найдено."]
    )
    if trois_rows:
        brands = sorted({(x.brand_name or "").strip() for x in trois_rows if (x.brand_name or "").strip()})
        if brands:
            ipr_lines.append("Бренды: " + ", ".join(brands))

    country_label = ctry if ctry else "Не выбрана (Базовая став.)"
    supp_unit_value = (row.supp_unit or "").strip() or "Нет"
    fields = [
        {"label": "Страна", "value": country_label},
        {"label": "Код страны", "value": ctry},
        {"label": "Код товара", "value": out_code},
        {"label": "Наименование товара", "value": product_name.strip()},
        {"label": "Доп. единицы измерения", "value": supp_unit_value},
    ]
    sections = [
        {
            "title": "Пошлина",
            "items": [
                f"Для данного товара при импорте из этой страны используется ставка, установленная Единым таможенным тарифом ЕАЭС: {duty_value}",
                "См. Единый таможенный тариф ЕАЭС",
                "Перечень товаров, при ввозе которых предоставляются тарифные преференции (Решение Совета ЕЭК № 99 от 05.10.2021)",
            ],
            "sources": [
                {"title": "Единый таможенный тариф ЕАЭС", "url": "https://eec.eaeunion.org/comission/department/catr/ett/"},
                {"title": "Преференции ЕАЭС (Решение Совета ЕЭК № 99)", "url": "https://eec.eaeunion.org/"},
            ],
        },
        {
            "title": "Акциз",
            "items": [
                excise_text,
                "См.: Налоговые ставки подакцизных товаров (статья 193 Налогового кодекса)",
                "Подакцизные товары (статья 181 Налогового кодекса)",
            ],
            "sources": [
                {"title": "НК РФ, статья 193", "url": "http://sudact.ru/law/nk-rf-chast2/razdel-viii/glava-22/statia-193/"},
                {"title": "НК РФ, статья 181", "url": "http://sudact.ru/law/nk-rf-chast2/razdel-viii/glava-22/statia-181/"},
            ],
        },
        {
            "title": "Особые виды пошлин",
            "items": special_lines,
            "sources": [
                {"title": "Меры торговой защиты ЕАЭС", "url": "https://eec.eaeunion.org/comission/department/catr/trade-protect/"},
            ],
        },
        {
            "title": "НДС",
            "items": vat_lines
            + [
                "См. Налоговый кодекс (часть 2). Глава 21",
                "Постановление Правительства РФ № 908 от 31.12.2004",
                "Постановление Правительства РФ № 688 (медицинская продукция)",
            ],
            "sources": [
                {"title": "НК РФ, глава 21", "url": "http://sudact.ru/law/nk-rf-chast2/razdel-viii/glava-21/"},
            ],
        },
        {
            "title": "Таможенные сборы",
            "items": [
                "Таможенные сборы взимаются в зависимости от таможенной стоимости.",
                "См. Постановление Правительства РФ № 1637 от 28.11.2024.",
            ],
            "sources": [
                {"title": "ПП РФ № 1637", "url": "http://publication.pravo.gov.ru/"},
            ],
        },
        {
            "title": "Запреты и лицензии",
            "items": bans_license_items,
            "sources": [],
        },
        {
            "title": "Разрешительные документы",
            "items": permits_nt_items,
            "sources": [],
        },
        {
            "title": "Прочие особенности",
            "items": other_nt_items,
            "sources": [],
        },
        {
            "title": "Двойное применение",
            "items": ["Нет данных по базе (требуется отдельная проверка по перечням экспортного контроля)."],
            "sources": [{"title": "ФСТЭК России", "url": "https://fstec.ru/"}],
        },
        {
            "title": "Особенности классификации",
            "items": ["Используйте примечания к разделу/группе и практику ФТС по спорным позициям."],
            "sources": [{"title": "Предварительные решения ФТС", "url": "https://customs.gov.ru/"}],
        },
        {"title": "Предварительные решения по классификации товаров", "items": ["Нет данных по базе."], "sources": []},
        {"title": "Арбитражная практика", "items": ["Нет данных по базе."], "sources": []},
        {
            "title": "Интеллектуальная собственность",
            "items": ipr_lines,
            "sources": [{"title": "Реестр объектов ИС (ТРОИС)", "url": "https://customs.gov.ru/"}],
        },
    ]
    return JSONResponse(
        {
            "status": "OK",
            "title": "Справка о товаре (импорт)",
            "fields": fields,
            "sections": sections,
        }
    )


# ---------------------------------------------------------------------------
# Карточка позиции по коду
# ---------------------------------------------------------------------------

@router.get("/{code}/preliminary-decisions")
def preliminary_decisions_by_code(code: str, db: Session = Depends(get_db)) -> JSONResponse:
    """Предварительные решения по коду ТН ВЭД (отдельный лёгкий эндпоинт)."""
    norm = _digits(code)
    if len(norm) not in (4, 10):
        raise HTTPException(status_code=400, detail="Ожидается код ТН ВЭД из 4 или 10 цифр")
    block = find_preliminary_decisions_for_hs(db, norm.zfill(10) if len(norm) == 10 else norm.zfill(4))
    return JSONResponse({"status": "OK", "code": _pad_code(code), "preliminary_decisions": block})


@router.get("/{code}", response_model=TnvedCommodityDetailsResponse)
def get_commodity_by_code(code: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """
    Карточка ТН ВЭД по коду (4 или 10 цифр).
    Возвращает: code, name, import_duty, notes, chapter, section.
    """
    norm = _digits(code)
    if len(norm) not in (4, 10):
        raise HTTPException(status_code=400, detail="Ожидается код ТН ВЭД из 4 или 10 цифр")

    code_key = norm.zfill(4) if len(norm) == 4 else norm.zfill(10)

    row = (
        db.query(Commodity)
        .options(
            joinedload(Commodity.chapter).joinedload(Chapter.section),
            selectinload(Commodity.non_tariff_measures),
        )
        .filter(Commodity.code == code_key)
        .order_by(Commodity.id.asc())
        .first()
    )
    # fallback без zfill
    if not row and code_key != norm:
        row = (
            db.query(Commodity)
            .options(
                joinedload(Commodity.chapter).joinedload(Chapter.section),
                selectinload(Commodity.non_tariff_measures),
            )
            .filter(Commodity.code == norm)
            .order_by(Commodity.id.asc())
            .first()
        )
    if not row and len(norm) == 10:
        out_code = norm.zfill(10)
        name_row = (
            db.query(Commodity)
            .filter(Commodity.code.like(f"{norm[:6]}%"))
            .order_by(Commodity.code.asc())
            .first()
        )
        measures = _measures_for_api(out_code)
        return {
            "status": "OK",
            "code": out_code,
            "name": _strip_leading_dashes((name_row.description or "").strip()) if name_row else "",
            "description": (name_row.description or "").strip() if name_row else "",
            "unit": "",
            "supp_unit": "",
            "weight_coeff": 0.0,
            "import_duty": _resolve_duty_for_display(name_row, out_code) if name_row else "",
            "notes": "",
            "notes_combined": "",
            "non_tariff_measures": [],
            "measures": measures,
            "intellectual_properties": [],
            "preliminary_decisions": find_preliminary_decisions_for_hs(db, out_code),
            "chapter": None,
            "section": None,
        }
    if not row:
        raise HTTPException(status_code=404, detail="Позиция не найдена")

    ch = row.chapter
    sec = ch.section if ch else None
    if not ch or not sec:
        raise HTTPException(status_code=500, detail="Нарушена связь раздел–группа")

    notes_parts: list[str] = []
    if (sec.notes or "").strip():
        notes_parts.append(f"Раздел {sec.roman_number}:\n{sec.notes.strip()}")
    if (ch.notes or "").strip():
        notes_parts.append(f"Группа {ch.code}:\n{ch.notes.strip()}")
    notes_text = "\n\n".join(notes_parts)

    out_code = _pad_code(row.code or "")
    description = (row.description or "").strip()
    if USE_LEGACY_NTM:
        nt_rows = _filter_nt_rows_for_chapter(_fetch_nt_rows(db, out_code), out_code)
        non_tariff_measures = [_serialize_nt_measure_row(m) for m in nt_rows]
        non_tariff_measures = _merge_tr_ts_measures(out_code, non_tariff_measures)
        measure_types = sorted({(m.measure_type or "").strip().lower() for m in nt_rows if (m.measure_type or "").strip()})
    else:
        non_tariff_measures = _non_tariff_measures_for_code(out_code, description)
        measure_types = sorted(
            {(m.get("measure_type") or "").strip().lower() for m in non_tariff_measures if (m.get("measure_type") or "").strip()}
        )
    trois_rows = _get_trois_matches(db, out_code)
    intellectual_properties = [
        {
            "id": r.id,
            "brand_name": r.brand_name or "",
            "hs_code_prefix": r.hs_code_prefix or "",
            "reg_number": r.reg_number or "",
            "right_holder": r.right_holder or "",
        }
        for r in trois_rows
    ]
    preliminary_decisions = find_preliminary_decisions_for_hs(db, out_code)

    return {
        "status": "OK",
        "code": out_code,
        "name": _strip_leading_dashes((row.description or "").strip()),
        "description": row.description or "",
        "unit": row.unit or "",
        "supp_unit": row.supp_unit or "",
        "weight_coeff": float(row.weight_coeff or 0.0),
        "import_duty": _resolve_duty_for_display(row, out_code),
        "notes": notes_text,
        "notes_combined": notes_text,
        "non_tariff_measures": non_tariff_measures,
        "measures": _measures_for_api(out_code, measure_types),
        "intellectual_properties": intellectual_properties,
        "preliminary_decisions": preliminary_decisions,
        "chapter": {"id": ch.id, "code": ch.code, "title": ch.title or "", "notes": ch.notes or ""},
        "section": {"id": sec.id, "roman_number": sec.roman_number, "title": sec.title or "", "notes": sec.notes or ""},
    }
