"""
Парсер PDF-файлов ТН ВЭД ЕАЭС.

Формат файлов: ru.NN_YYYY[_дата].pdf — по одному файлу на каждую группу (NN = 01..97).
Каждый файл содержит:
  - текст раздела и примечания группы (первые страницы / верх первой таблично страницы)
  - таблицу товарных позиций с колонками:
        Код ТН ВЭД | Наименование позиции | Доп. ед. изм. | Ставка ввозной пошлины

Координаты столбцов (pt):
  x_code_max  = 185  — область кода (4 части: XXXX XX XXX X)
  x_unit_min  = 400  — единицы измерения
  x_duty_min  = 468  — ставка пошлины
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pdfplumber

log = logging.getLogger(__name__)

# ── Границы столбцов (pt) ────────────────────────────────────────────────────
# Реальные x-позиции частей кода (из анализа PDF): 99.3 / 128.5 / 144.7 / 167.5
X_CODE_PART1_MIN = 93   # первая 4-значная часть: x ≈ 99 (диапазон узкий, исключает ссылки в примечаниях на x≈107+)
X_CODE_PART1_MAX = 104
X_CODE_MAX  = 180    # правая граница всей области кода
X_DESC_MAX  = 405    # правая граница описания
X_UNIT_MIN  = 398    # начало единиц измерения
X_DUTY_MIN  = 465    # начало ставки пошлины

# Заголовок таблицы, который повторяется на каждой странице
_TABLE_HEADER_RE = re.compile(
    r"Ставка\s+ввозной\s+таможенной",
    re.I,
)

# Паттерн для распознавания 4-значной части кода в левой зоне
_CODE4_RE = re.compile(r"^\d{4}$")
# 2-значная вторая часть кода
_CODE2_RE = re.compile(r"^\d{2}$")
# 3-значная третья часть
_CODE3_RE = re.compile(r"^\d{3}$")
# 1-значная четвёртая часть
_CODE1_RE = re.compile(r"^\d$")


# ── Структуры данных ──────────────────────────────────────────────────────────

@dataclass
class TnvedRow:
    """Одна позиция ТН ВЭД, извлечённая из PDF."""
    code: str           # нормализованный 10-значный код (без пробелов)
    description: str    # полное наименование позиции
    unit: str = ""      # доп. единица измерения
    duty: str = ""      # ставка ввозной пошлины
    is_heading: bool = False  # True для заголовочных строк без ставки


@dataclass
class ChapterData:
    """Данные одной группы ТН ВЭД, извлечённые из PDF."""
    chapter_code: str
    chapter_title: str = ""
    section_roman: str = ""
    section_title: str = ""
    notes: str = ""
    rows: list[TnvedRow] = field(default_factory=list)


# ── Вспомогательные функции ───────────────────────────────────────────────────

def _digits_only(s: str) -> str:
    return re.sub(r"\D", "", s)


def _pad_code(digits: str) -> str:
    """Нормализует строку цифр к 10 символам (справа нулями или усекает)."""
    if not digits:
        return ""
    if len(digits) < 10:
        return digits.ljust(10, "0")
    return digits[:10]


def _is_table_header_row(words: list[dict]) -> bool:
    """Возвращает True, если строка — часть повторяющегося заголовка таблицы."""
    text = " ".join(w["text"] for w in words)
    return bool(_TABLE_HEADER_RE.search(text))


def _group_by_y(words: list[dict], tolerance: int = 4) -> dict[int, list[dict]]:
    """Группирует слова по строкам с допуском по y-координате."""
    rows: dict[int, list[dict]] = {}
    for w in words:
        y_key = int(round(w["top"] / tolerance)) * tolerance
        rows.setdefault(y_key, []).append(w)
    return rows


# ── Извлечение слов-кодов из строки ─────────────────────────────────────────

def _parse_code_from_row(code_words: list[dict]) -> tuple[str, bool]:
    """
    Из слов в области кода собирает строку цифр и флаг is_heading.
    Возвращает (digits, is_heading).
    - 4 части кода (DDDD DD DDD D) → 10 цифр → не заголовок
    - Меньше 4 частей → заголовок
    
    Используем X-позиционные диапазоны для каждой части, чтобы исключить
    ложные срабатывания на цифры из текста примечаний:
      Part1 (4 цифры): x ≈ 93-108
      Part2 (2 цифры): x ≈ 120-138
      Part3 (3 цифры): x ≈ 138-155
      Part4 (1 цифра): x ≈ 158-178
    """
    parts = []
    for w in sorted(code_words, key=lambda w: w["x0"]):
        x = w["x0"]
        d = _digits_only(w["text"])
        if not d:
            continue
        # Принимаем только слова в ожидаемых x-зонах для частей кода
        if 93 <= x <= 104:       # Part1: 4 цифры
            if len(d) == 4:
                parts.append(("p1", d))
        elif 120 <= x <= 138:    # Part2: 2 цифры
            if len(d) == 2:
                parts.append(("p2", d))
        elif 138 <= x <= 155:    # Part3: 3 цифры
            if len(d) == 3:
                parts.append(("p3", d))
        elif 158 <= x <= 178:    # Part4: 1 цифра
            if len(d) == 1:
                parts.append(("p4", d))

    if not parts:
        return "", True
    # Должна быть хотя бы Part1
    if parts[0][0] != "p1":
        return "", True

    code_digits = "".join(p[1] for p in parts)
    if len(code_digits) < 4:
        return "", True
    is_heading = len(code_digits) < 10
    return code_digits, is_heading


# ── Парсинг строк таблицы из страницы ────────────────────────────────────────

# y-диапазон, в котором находятся повторяющиеся заголовки страниц (первые ~160pt)
_HEADER_Y_MAX = 160


def _extract_table_words(page, y_start: float = 0.0) -> list[dict]:
    """
    Возвращает слова на странице ниже y_start, исключая повторяющиеся
    заголовки таблицы (шапку "Ставка ввозной таможенной пошлины ...").
    """
    words = page.extract_words(x_tolerance=4, y_tolerance=4)
    # Фильтруем по y_start и исключаем "шапку страницы" (первые ~160pt)
    result = []
    for w in words:
        if w["top"] < y_start:
            continue
        # Пропускаем шапку: строки правой части страницы в верхней зоне
        # которые относятся к заголовку таблицы (x > 300 и y < _HEADER_Y_MAX)
        if w["top"] < _HEADER_Y_MAX and w["x0"] > 300:
            continue
        result.append(w)
    return result


def _find_first_code_y(page) -> float:
    """
    Находит y-координату первой строки с реальным 4-значным кодом ТН ВЭД.
    Использует СТРОГИЙ диапазон x ≈ 93-108 (реальная колонка кода), 
    чтобы не ловить ссылки на коды из текста примечаний.
    Возвращает 0.0 если не найдено.
    """
    words = page.extract_words(x_tolerance=4, y_tolerance=4)
    by_y = _group_by_y(words, tolerance=6)
    for y_key in sorted(by_y.keys()):
        row_words = sorted(by_y[y_key], key=lambda w: w["x0"])
        # Ищем ТОЛЬКО слова в строгой зоне первой части кода
        strict_code = [
            w for w in row_words
            if X_CODE_PART1_MIN <= w["x0"] <= X_CODE_PART1_MAX
            and _CODE4_RE.match(w["text"])
        ]
        if strict_code:
            return float(y_key)
    return 0.0


# ── Сборка строк ТН ВЭД ──────────────────────────────────────────────────────

def _build_tnved_rows(all_page_words: list[tuple[list[dict], float]]) -> list[TnvedRow]:
    """
    Принимает список (words_on_page, y_start_offset) — слова таблицы со страниц.
    Группирует по строкам и собирает строки TnvedRow.
    """
    # Нормируем y чтобы строки шли по порядку страниц
    # (добавляем offset = page_num * 10000 к y_key)
    all_rows_raw: list[dict] = []

    for page_idx, (words, y_start) in enumerate(all_page_words):
        filtered = [w for w in words if w["top"] >= y_start]
        by_y = _group_by_y(filtered, tolerance=5)
        for y_key in sorted(by_y.keys()):
            row_words = sorted(by_y[y_key], key=lambda w: w["x0"])
            # Пропускаем строки-шапки таблицы
            row_text = " ".join(w["text"] for w in row_words)
            if _TABLE_HEADER_RE.search(row_text):
                continue

            code_area   = [w for w in row_words if w["x0"] < X_CODE_MAX]
            desc_area   = [w for w in row_words if X_CODE_MAX <= w["x0"] < X_DESC_MAX]
            unit_area   = [w for w in row_words if X_UNIT_MIN <= w["x0"] < X_DUTY_MIN]
            duty_area   = [w for w in row_words if w["x0"] >= X_DUTY_MIN]

            code_digits, is_heading = _parse_code_from_row(code_area)
            desc_text  = " ".join(w["text"] for w in desc_area).strip()
            unit_text  = " ".join(w["text"] for w in unit_area).strip()
            duty_text  = " ".join(w["text"] for w in duty_area).strip()

            all_rows_raw.append({
                "order": page_idx * 100000 + y_key,
                "code_digits": code_digits,
                "desc": desc_text,
                "unit": unit_text,
                "duty": duty_text,
                "is_heading": is_heading,
            })

    # Сортируем и склеиваем многострочные описания
    all_rows_raw.sort(key=lambda r: r["order"])
    return _assemble_rows(all_rows_raw)


def _fix_unit_duty(row: TnvedRow) -> None:
    """
    Исправляет случаи когда в поле unit попало число из комбинированной ставки.
    Формат: "л 15," или "кг 5," — число принадлежит ставке, не единице.
    Пример: unit="л 15," duty="но не менее 0,07 евро за 1 л"
          → unit="л" duty="15, но не менее 0,07 евро за 1 л"
    """
    _SIMPLE_UNITS = {
        "шт", "кг", "л", "–", "-", "г", "т", "пара", "м2", "м3", "м",
        "кв.м", "куб.м", "тыс.", "мл", "1000", "100",
    }
    parts = row.unit.strip().split()
    if len(parts) >= 2 and parts[0].lower() in _SIMPLE_UNITS:
        # Всё кроме первого слова — начало ставки
        row.unit = parts[0]
        extra = " ".join(parts[1:])
        row.duty = (extra + " " + row.duty).strip() if row.duty else extra


def _assemble_rows(raw: list[dict]) -> list[TnvedRow]:
    """Склеивает многострочные описания и создаёт TnvedRow."""
    result: list[TnvedRow] = []
    pending: Optional[TnvedRow] = None

    def flush():
        nonlocal pending
        if pending is not None:
            pending.description = re.sub(r"\s+", " ", pending.description).strip()
            pending.duty = re.sub(r"\s+", " ", pending.duty).strip()
            _fix_unit_duty(pending)
            result.append(pending)
            pending = None

    for r in raw:
        digits = r["code_digits"]
        has_code = len(digits) >= 4

        if has_code:
            flush()
            norm = _pad_code(digits)
            is_heading = r["is_heading"] or len(_digits_only(digits)) < 10
            pending = TnvedRow(
                code=norm,
                description=r["desc"],
                unit=r["unit"],
                duty=r["duty"],
                is_heading=is_heading,
            )
        else:
            # Продолжение текущей строки
            if pending is not None:
                if r["desc"]:
                    pending.description += " " + r["desc"]
                if not pending.is_heading:
                    # Для строк с ценами: unit и duty зоны continuation
                    # принадлежат продолжению ставки пошлины
                    continuation = (r["unit"] + " " + r["duty"]).strip()
                    if continuation:
                        if pending.duty:
                            pending.duty += " " + continuation
                        elif pending.unit:
                            # duty ещё не заполнен, но unit есть — значит continuation это duty
                            pending.duty = continuation
                        else:
                            # единицы ещё нет: first continuation = unit
                            pending.unit = r["unit"]
                            if r["duty"]:
                                pending.duty = r["duty"]

    flush()
    return result


# ── Извлечение примечаний ─────────────────────────────────────────────────────

def _extract_notes_text(page, y_end: float) -> str:
    """
    Извлекает текст из верхней части страницы (до y_end) без макета.
    """
    if y_end <= 10:
        return ""
    cropped = page.crop((0, 0, page.width, y_end))
    text = cropped.extract_text() or ""
    return text.strip()


def _parse_titles_and_notes(raw_notes_text: str, chapter_code: str) -> tuple[str, str, str, str]:
    """
    Из сырого текста примечаний извлекает:
      (section_roman, section_title, chapter_title, clean_notes)
    """
    lines = [l.strip() for l in raw_notes_text.split("\n")]
    lines = [l for l in lines if l]

    roman_number = ""
    section_title_parts: list[str] = []
    chapter_title_parts: list[str] = []
    notes_parts: list[str] = []

    # Паттерны
    roman_line_re = re.compile(r"^РАЗДЕЛ\s+([IVXLCDM]+)\s*$", re.I)
    section_inline_re = re.compile(r"^РАЗДЕЛ\s+([IVXLCDM]+)\s+(.+)$", re.I)
    group_line_re = re.compile(r"^ГРУППА\s+\d+\s*$", re.I)
    primechaniye_re = re.compile(r"^Примечани", re.I)
    dop_primechaniye_re = re.compile(r"^Дополнительн", re.I)

    STATE_PRE = 0
    STATE_SECTION = 1
    STATE_GROUP = 2
    STATE_NOTES = 3

    state = STATE_PRE

    for line in lines:
        # Пропускаем мусорные заголовки таблицы если просочились
        if _TABLE_HEADER_RE.search(line):
            continue

        m_roman = roman_line_re.match(line)
        m_sec_inline = section_inline_re.match(line)
        m_group = group_line_re.match(line)

        if m_roman and state == STATE_PRE:
            roman_number = m_roman.group(1)
            state = STATE_SECTION
            continue

        if m_sec_inline and state == STATE_PRE:
            roman_number = m_sec_inline.group(1)
            section_title_parts.append(m_sec_inline.group(2).strip())
            state = STATE_SECTION
            continue

        # Группа без раздела (например, группа 77 — резерв)
        if m_group and state == STATE_PRE:
            state = STATE_GROUP
            continue

        if state == STATE_SECTION:
            if m_group:
                state = STATE_GROUP
                continue
            # Многострочное название раздела (заглавные буквы)
            if re.match(r"^[А-ЯЁA-Z\s\(\)\/;,:\-\"\.]+$", line) and len(line) > 2:
                section_title_parts.append(line)
            continue

        if state == STATE_GROUP:
            if primechaniye_re.match(line) or dop_primechaniye_re.match(line):
                state = STATE_NOTES
                notes_parts.append(line)
                continue
            # Это название группы (обычно заглавными)
            if re.match(r"^[А-ЯЁA-Z\s\(\)\/;,:\-\"\.]+$", line) and len(line) > 2:
                chapter_title_parts.append(line)
            continue

        if state == STATE_NOTES:
            notes_parts.append(line)
            continue

        # state == STATE_PRE и ничего не распознали — может быть начало примечаний
        if primechaniye_re.match(line) or dop_primechaniye_re.match(line):
            state = STATE_NOTES
            notes_parts.append(line)
            continue

    section_title = re.sub(r"\s+", " ", " ".join(section_title_parts)).strip()
    chapter_title = re.sub(r"\s+", " ", " ".join(chapter_title_parts)).strip()
    notes_clean = "\n".join(notes_parts).strip()

    # Убираем мусорный повтор заголовка таблицы из примечаний (если просочился)
    notes_clean = re.sub(
        r"таможенной\s*\n\s*пошлины\s*\n\s*Доп\.\s*\n",
        "", notes_clean
    )
    notes_clean = re.sub(r"\s{3,}", "  ", notes_clean).strip()

    return roman_number, section_title, chapter_title, notes_clean


# ── Основная функция парсинга файла ─────────────────────────────────────────

def parse_pdf(path: Path) -> ChapterData:
    """
    Парсит один PDF-файл группы ТН ВЭД.
    Возвращает ChapterData с кодом группы, заголовками, примечаниями и строками.
    """
    fname = path.stem
    m = re.match(r"ru\.(\d+)", fname)
    chapter_code = m.group(1).zfill(2) if m else "00"

    log.info("Парсинг %s (группа %s)", path.name, chapter_code)

    # Аккумуляторы
    notes_text_parts: list[str] = []
    table_pages_words: list[tuple[list[dict], float]] = []
    notes_done = False

    with pdfplumber.open(path) as pdf:
        for page_num, page in enumerate(pdf.pages):
            words = page.extract_words(x_tolerance=4, y_tolerance=4)

            # y-координата первого кода ТН ВЭД на странице
            # Для страниц с таблицей это позволяет пропустить повторяющуюся шапку
            first_code_y = _find_first_code_y(page)

            # Небольшой отступ назад чтобы не отсечь сам код при рундировании
            Y_MARGIN = 12.0

            if not notes_done:
                if first_code_y > 10:
                    # На странице есть примечания (выше first_code_y) и таблица
                    notes_text = _extract_notes_text(page, first_code_y)
                    if notes_text.strip():
                        notes_text_parts.append(notes_text)
                    notes_done = True
                    y_start = max(0.0, first_code_y - Y_MARGIN)
                    table_pages_words.append((words, y_start))
                else:
                    # Вся страница — примечания (нет кодов)
                    text = page.extract_text() or ""
                    if text.strip():
                        notes_text_parts.append(text)
            else:
                # Страница целиком таблица, но шапка повторяется в верхней части
                # first_code_y указывает где именно начинаются данные
                y_start = max(0.0, first_code_y - Y_MARGIN) if first_code_y > 10 else 0.0
                table_pages_words.append((words, y_start))

    # Если коды нашли только со второй страницы, первые страницы — примечания
    if not notes_done:
        # Все страницы — примечания (маловероятно, но обработаем)
        pass

    # Собираем строки таблицы
    tnved_rows = _build_tnved_rows(table_pages_words)

    # Если примечаний нет, но есть первые страницы без кодов — добавляем их текст
    raw_notes = "\n".join(notes_text_parts)
    roman, section_title, chapter_title, notes_clean = _parse_titles_and_notes(
        raw_notes, chapter_code
    )

    # Фолбэк: если название группы не найдено — ищем в первых строках таблицы
    if not chapter_title:
        for row in tnved_rows[:10]:
            d = _digits_only(row.code)
            # 4-значный код начала группы без тире — потенциальное название
            if len(d) == 4 and d[:2] == chapter_code and not row.description.startswith("–"):
                chapter_title = row.description
                break

    return ChapterData(
        chapter_code=chapter_code,
        chapter_title=chapter_title,
        section_roman=roman,
        section_title=section_title,
        notes=notes_clean,
        rows=tnved_rows,
    )


# ── CLI для тестирования ──────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys, json

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if len(sys.argv) < 2:
        print("Использование: python tnved_pdf_parser.py <path_to_pdf> [--json]")
        sys.exit(1)

    path = Path(sys.argv[1])
    result = parse_pdf(path)

    if "--json" in sys.argv:
        data = {
            "chapter_code": result.chapter_code,
            "chapter_title": result.chapter_title,
            "section_roman": result.section_roman,
            "section_title": result.section_title,
            "notes_preview": result.notes[:300],
            "rows_count": len(result.rows),
            "rows_sample": [
                {
                    "code": r.code,
                    "description": r.description[:80],
                    "unit": r.unit,
                    "duty": r.duty,
                    "is_heading": r.is_heading,
                }
                for r in result.rows[:30]
            ],
        }
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(f"Группа:        {result.chapter_code} — {result.chapter_title}")
        print(f"Раздел:        {result.section_roman}  {result.section_title}")
        print(f"Примечания:    {len(result.notes)} символов")
        print(f"Строк ТН ВЭД: {len(result.rows)}")
        print()
        for row in result.rows[:30]:
            flag = "H" if row.is_heading else " "
            print(f"  [{flag}] {row.code}  |  {row.description[:55]:<55}  |  {row.unit:<8}  |  {row.duty}")
