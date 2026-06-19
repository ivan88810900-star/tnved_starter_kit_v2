"""Справочник ТН ВЭД: разделы, группы, позиции и иерархическое дерево.

БД содержит только коды длиной 4 и 10 знаков.
Дерево строится как 4-знак → 6-знак (синтетический) → 10-знак.
Поле code — строго строка; 10-значные коды всегда хранятся без потери нулей.
"""

from __future__ import annotations

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


def _non_tariff_code_candidates(code10: str) -> list[str]:
    """
    Кандидаты для fallback мер:
      10-значный -> 6-значный уровень -> 4-значный уровень.
    В БД храним как 10-значные коды с нулями справа.
    """
    d = _digits(code10).zfill(10)[:10]
    return [
        d,
        d[:6] + "0000",
        d[:4] + "000000",
    ]


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
    from ..services.normative_store import _expand_query_terms, get_search_suggestions
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
            }
            for r in fts_rows
        ]
    else:
        # Fallback (FTS5 недоступен в сборке SQLite): LIKE по расширенным терминам.
        terms = _expand_query_terms(query)
        digit_prefix = _digits(query)
        filters = [func.lower(Commodity.description).like(f"%{t}%") for t in terms]
        if digit_prefix:
            filters.append(Commodity.code.like(f"{digit_prefix}%"))
        rows = (
            db.query(Commodity.code, Commodity.description)
            .filter(or_(*filters))
            .order_by(Commodity.code.asc())
            .limit(50)
            .all()
        )
        results = [
            {
                "code": _pad_code(code or ""),
                "name": _strip_leading_dashes((name or "").strip()),
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

        # XXXX000000 — это сама товарная позиция (паддинг). Если под позицией
        # есть более глубокие коды, сворачиваем её имя в заголовок и НЕ создаём
        # для неё отдельный (фиктивный) узел-лист. Если это единственный код —
        # оставляем его как реальный декларируемый лист.
        pad_code = p4 + "000000"
        deeper = [c for c in codes if c != pad_code]
        if pad_code in ten_by_code and deeper:
            cand = ten_by_code[pad_code]["name"]
            if cand and (not heading["name"] or not _is_meaningful_name(heading["name"])):
                heading["name"] = cand
            codes = deeper

        # Восстанавливаем вложенность по структурному уровню кода через стек
        stack: list[tuple[int, dict[str, Any]]] = []
        for code10 in codes:
            lvl = _node_level(code10)
            raw = ten_by_code[code10]
            node = _make_node(
                code10, raw["name"], raw["import_duty"], heading["notes"],
                is_leaf=True, is_codeless=False, is_group=False,
            )
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
            if node["children"]:
                node["is_leaf"] = False
                node["is_codeless"] = True
            else:
                node["is_leaf"] = True
                node["is_codeless"] = False

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
    q = (
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
        if not row:
            return {"status": "NOT_FOUND", "code": _pad_code(code)}

        out_code = _pad_code(row.code or "")
        nt_candidates = _non_tariff_code_candidates(out_code)
        nt_rows = list(row.non_tariff_measures or [])
        if not nt_rows:
            fallback_candidates = nt_candidates[1:]
            nt_rows = (
                db.query(NonTariffMeasure)
                .filter(NonTariffMeasure.commodity_code.in_(fallback_candidates))
                .order_by(NonTariffMeasure.id.asc())
                .all()
            )

        measure_types = sorted({(m.measure_type or "").strip().lower() for m in nt_rows if (m.measure_type or "").strip()})
        measure_badges = [_measure_label(mt) for mt in measure_types]
        has_ban = "ban" in measure_types

        # Упрощенная витрина платежей для hover.
        duty = _format_duty(row.import_duty)
        # Фактическая ставка НДС из hs_rates (с префиксным fallback), без хардкода.
        rate_row, _vat_mlen = find_rate_for_hs(out_code)
        if rate_row and rate_row.vat_import_rate:
            raw_vat = float(rate_row.vat_import_rate)
            vat_rates = [int(raw_vat) if raw_vat.is_integer() else raw_vat]
        else:
            vat_rates = [22]  # стандартная ставка по умолчанию (с 01.01.2026)
        excise = ""

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
                "empty_message": "✅ Меры нетарифного регулирования не применяются" if not measure_types else "",
            },
            "features": features,
            "special_duties": {
                "has_measures": len(special_rows) > 0,
                "countries": special_countries,
                "warning": (
                    "⚠️ Внимание: для данного кода действуют антидемпинговые меры "
                    f"(например, для стран: {', '.join(special_countries)})."
                    if special_countries
                    else ""
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
    duty_value = _format_duty(row.import_duty) or duty_from_hs or "Не указана"
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

    nt_rows = list(row.non_tariff_measures or [])
    if not nt_rows:
        fallback_candidates = _non_tariff_code_candidates(out_code)[1:]
        nt_rows = (
            db.query(NonTariffMeasure)
            .filter(NonTariffMeasure.commodity_code.in_(fallback_candidates))
            .order_by(NonTariffMeasure.id.asc())
            .all()
        )
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
    nt_candidates = _non_tariff_code_candidates(out_code)
    nt_rows = list(row.non_tariff_measures or [])
    # Fallback по уровню агрегации: сначала 6 знаков, затем 4.
    if not nt_rows:
        fallback_candidates = nt_candidates[1:]
        nt_rows = (
            db.query(NonTariffMeasure)
            .filter(NonTariffMeasure.commodity_code.in_(fallback_candidates))
            .order_by(NonTariffMeasure.id.asc())
            .all()
        )
        order_map = {c: i for i, c in enumerate(fallback_candidates)}
        nt_rows.sort(key=lambda m: (order_map.get(m.commodity_code, 99), m.id))
    non_tariff_measures = [
        {
            "id": m.id,
            "commodity_code": m.commodity_code,
            "measure_type": m.measure_type,
            "description": m.description or "",
            "document_required": m.document_required or "",
            "regulatory_act": m.regulatory_act or "",
        }
        for m in nt_rows
    ]
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
        "import_duty": _format_duty(row.import_duty),
        "notes": notes_text,
        "notes_combined": notes_text,
        "non_tariff_measures": non_tariff_measures,
        "intellectual_properties": intellectual_properties,
        "preliminary_decisions": preliminary_decisions,
        "chapter": {"id": ch.id, "code": ch.code, "title": ch.title or "", "notes": ch.notes or ""},
        "section": {"id": sec.id, "roman_number": sec.roman_number, "title": sec.title or "", "notes": sec.notes or ""},
    }
