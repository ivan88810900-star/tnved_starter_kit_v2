"""SemanticStructureExtractor — read-only извлечение смысловых групп из текста ТН ВЭД.

Идея: в официальном тексте ТН ВЭД групповые заголовки субпозиций — это строки
с ОДНИМ ведущим тире («– Лососевые (Salmonidae):»). В выгрузке tnved_commodities
такие заголовки не являются отдельными кодами: они «прилипают» в конец описания
pad-кода (XXXX000000) или в конец описания позиции «прочие».

Пример (heading 0302):
    0302000000  «Рыба свежая ... 0304: – лососевые, за исключением ...:»
    0302190000  «– – прочие – камбалообразные (Pleuronectidae, ...):»

Этап 2: строгий режим. Не каждый хвост после тире считается группой. Кандидат
отбраковывается, если он похож на технический параметр / числовой диапазон /
generic-подкатегорию («прочие», «для ...»). Каждой группе присваивается
confidence (high/medium/low); в дерево попадают только high и medium.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..tnved_tree.helpers import digits, strip_leading_dashes
from .models import SourceRecord

# Тире: en-dash, em-dash, hyphen-minus (hyphen строго последним — иначе диапазон в [..]).
_DASH_CLASS = "\u2013\u2014\u002d"
_LEADING_DASHES_RE = re.compile(rf"^[\s{_DASH_CLASS}]*")
# Разделитель внутри описания: «<пробел> тире <пробел>» — потенциальный новый заголовок.
_INLINE_GROUP_SEP_RE = re.compile(rf"\s[{_DASH_CLASS}]\s")
# Обрезка заголовка группы до базового наименования.
_TITLE_CUT_RE = re.compile(r"[,:;(]")

# Confidence-уровни.
HIGH = "high"
MEDIUM = "medium"
LOW = "low"

# Единицы измерения (как отдельные токены) — признак технического параметра.
_UNIT_TOKENS = (
    "тгц", "ггц", "мгц", "кгц", "гц",
    "нм", "мкм", "мм", "см", "дм", "км",
    "мг", "кг", "гр",
    "мбит", "гбит", "кбит",
    "квт", "вт", "мвт",
    "мл", "мм2", "м2", "м3",
)
_UNIT_RE = re.compile(
    r"\b\d+(?:[.,]\d+)?\s*(?:" + "|".join(_UNIT_TOKENS) + r")\b",
    re.IGNORECASE,
)
_BARE_UNIT_RE = re.compile(
    r"\b(?:тгц|ггц|мгц|кгц|гц|нм|мкм)\b",
    re.IGNORECASE,
)
_LETTER_RE = re.compile(r"[а-яёa-z]", re.IGNORECASE)
_TRAILING_NUMBER_RE = re.compile(r"\d[\d.,]*\s*$")
_LEADING_NUMBER_RE = re.compile(r"^\s*\d")

# Generic-подкатегории: это товарные уточнения, а не классификационные группы.
# Прим.: «из ...» НЕ отбраковываем — встречаются реальные группы вида
# «из пряжи различных цветов» (5208).
_GENERIC_PREFIXES: tuple[str, ...] = (
    "прочие",
    "прочий",
    "прочая",
    "прочее",
    "для ",
    "в том числе",
    "неразделанн",
    "разделанн",
)

_MIN_TITLE_LEN = 4


@dataclass
class ExtractedGroup:
    """Принятый групповой заголовок (классификационная группа)."""

    title: str
    raw: str
    source_code: str  # код, из описания которого извлечён заголовок
    after_code: str | None  # активируется после этого кода (None = до первого)
    confidence: str  # high | medium
    reason: str
    #: Глубина заголовка в официальном тексте. Разделяющее тире — уровень 1,
    #: оставшиеся ведущие тире в trailing raw увеличивают глубину.
    dash_depth: int = 1
    #: Консервативная подсказка родителя, вычисленная только по уже встреченному
    #: принятому заголовку в том же heading.
    parent_title_hint: str | None = None
    parent_source_code_hint: str | None = None
    hierarchy_hint: str | None = None  # dash_depth | title_prefix


@dataclass
class RejectedCandidate:
    """Отбракованный кандидат в групповой заголовок (confidence=low)."""

    title: str
    raw: str
    source_code: str
    reason: str


@dataclass
class ExtractionResult:
    """Результат read-only анализа heading."""

    heading: str
    pad_code: str | None
    commodity_codes: list[str]
    records_by_code: dict[str, SourceRecord]
    groups: list[ExtractedGroup] = field(default_factory=list)
    rejected: list[RejectedCandidate] = field(default_factory=list)


def _count_leading_dashes(s: str) -> int:
    m = _LEADING_DASHES_RE.match(s or "")
    if not m:
        return 0
    return sum(1 for ch in m.group(0) if ch in _DASH_CLASS)


def _clean_group_title(raw: str) -> str:
    """Базовое наименование группы: «камбалообразные (Pleuronectidae...)» → «камбалообразные»."""
    s = strip_leading_dashes(raw)
    m = _TITLE_CUT_RE.search(s)
    if m and m.start() > 0:
        s = s[: m.start()]
    return s.strip()


def _split_main_and_trailing(description: str) -> tuple[str, str | None]:
    """Делит описание на основное наименование и (необязательный) хвостовой заголовок группы.

    Возвращает (main, trailing_raw|None). Хвостовой заголовок — текст после первого
    внутреннего разделителя «<пробел>тире<пробел>», следующего за основным текстом.
    """
    s = (description or "").strip()
    if not s:
        return "", None
    lead_m = _LEADING_DASHES_RE.match(s)
    lead = lead_m.group(0) if lead_m else ""
    body = s[len(lead) :]
    sep = _INLINE_GROUP_SEP_RE.search(body)
    if not sep:
        return s, None
    main = (lead + body[: sep.start()]).strip()
    trailing = body[sep.end() :].strip()
    if not trailing:
        return s, None
    return main, trailing


def _rejection_reason(main: str, trailing_raw: str, title: str) -> str | None:
    """Возвращает причину отбраковки кандидата или None, если кандидат валиден."""
    t = title.strip()
    low = t.lower()
    if len(t) < _MIN_TITLE_LEN:
        return "too_short"
    if not _LETTER_RE.search(low):
        return "no_letters"
    if _LEADING_NUMBER_RE.match(t):
        return "starts_with_number"
    if _UNIT_RE.search(low) or _BARE_UNIT_RE.search(low):
        return "measurement_unit"
    # Числовой диапазон вида «2,2 – 10 ГГц» / «1270 – 1610 нм»: разрыв по тире.
    main_clean = strip_leading_dashes(main)
    if _TRAILING_NUMBER_RE.search(main_clean) and _LEADING_NUMBER_RE.match(trailing_raw.strip()):
        return "numeric_range"
    if low.startswith(_GENERIC_PREFIXES):
        return "generic_subcategory"
    return None


def _confidence_for(trailing_raw: str, reason: str | None) -> tuple[str, str]:
    """(confidence, reason_text) для кандидата."""
    if reason is not None:
        return LOW, reason
    if _count_leading_dashes(trailing_raw) > 0:
        return MEDIUM, "embedded_subheader"
    return HIGH, "canonical_merged_header"


def _normalise_title(value: str) -> str:
    return " ".join((value or "").casefold().split())


def _is_title_prefix_child(parent_title: str, child_title: str) -> bool:
    """Строгая lexical-подсказка: «тунец» → «тунец синий».

    Совпадение целого первого слова/словосочетания намеренно не пытается
    угадывать синонимы или грамматические формы.
    """

    parent = _normalise_title(parent_title)
    child = _normalise_title(child_title)
    return bool(parent and child != parent and child.startswith(f"{parent} "))


class SemanticStructureExtractor:
    """Извлекает смысловые группы heading из официальных описаний (read-only, strict)."""

    #: confidence-уровни, попадающие в дерево.
    ACCEPTED_CONFIDENCE: frozenset[str] = frozenset({HIGH, MEDIUM})

    def extract(self, heading: str, records: list[SourceRecord]) -> ExtractionResult:
        heading4 = digits(heading).zfill(4)[:4]
        pad_code = heading4 + "000000"

        records_by_code: dict[str, SourceRecord] = {}
        commodity_codes: list[str] = []
        pad_record: SourceRecord | None = None

        for rec in records:
            d = digits(rec.code)
            if len(d) <= 4:
                continue  # 4-значный заголовок позиции — не товар
            code10 = d.zfill(10)[:10]
            records_by_code[code10] = SourceRecord(
                code=code10,
                description=rec.description,
                import_duty=rec.import_duty,
            )
            if code10 == pad_code:
                pad_record = records_by_code[code10]
            else:
                commodity_codes.append(code10)

        commodity_codes.sort()

        groups: list[ExtractedGroup] = []
        rejected: list[RejectedCandidate] = []
        active_parent: ExtractedGroup | None = None

        def consider(source_code: str, description: str, after_code: str | None) -> None:
            nonlocal active_parent
            main, trailing = _split_main_and_trailing(description)
            if not trailing:
                return
            dash_depth = 1 + _count_leading_dashes(trailing)
            title = _clean_group_title(trailing)
            if not title:
                if dash_depth == 1:
                    active_parent = None
                rejected.append(
                    RejectedCandidate(
                        title=trailing.strip()[:60],
                        raw=trailing,
                        source_code=source_code,
                        reason="empty_title",
                    )
                )
                return
            reason = _rejection_reason(main, trailing, title)
            confidence, reason_text = _confidence_for(trailing, reason)
            if confidence in self.ACCEPTED_CONFIDENCE:
                parent_hint: ExtractedGroup | None = None
                hierarchy_hint: str | None = None
                if active_parent is not None and dash_depth > 1:
                    parent_hint = active_parent
                    hierarchy_hint = "dash_depth"
                elif (
                    active_parent is not None
                    and dash_depth == 1
                    and _is_title_prefix_child(active_parent.title, title)
                ):
                    parent_hint = active_parent
                    hierarchy_hint = "title_prefix"

                group = ExtractedGroup(
                    title=title,
                    raw=trailing,
                    source_code=source_code,
                    after_code=after_code,
                    confidence=confidence,
                    reason=reason_text,
                    dash_depth=dash_depth,
                    parent_title_hint=(
                        parent_hint.title if parent_hint is not None else None
                    ),
                    parent_source_code_hint=(
                        parent_hint.source_code if parent_hint is not None else None
                    ),
                    hierarchy_hint=hierarchy_hint,
                )
                groups.append(group)

                # Явный новый level-1 заголовок закрывает предыдущий сегмент.
                # Lexical child остаётся внутри действующего umbrella-parent.
                if dash_depth == 1 and parent_hint is None:
                    active_parent = group
            else:
                # Даже отбракованный level-1 заголовок является границей сегмента:
                # следующую подгруппу нельзя привязать к устаревшему родителю.
                if dash_depth == 1:
                    active_parent = None
                rejected.append(
                    RejectedCandidate(
                        title=title,
                        raw=trailing,
                        source_code=source_code,
                        reason=reason_text,
                    )
                )

        # 1. Первый групповой заголовок — из хвоста описания pad-кода.
        if pad_record is not None:
            consider(pad_code, pad_record.description, None)

        # 2. Заголовки, «прилипшие» к описаниям позиций.
        for code10 in commodity_codes:
            consider(code10, records_by_code[code10].description, code10)

        return ExtractionResult(
            heading=heading4,
            pad_code=pad_code if pad_record is not None else None,
            commodity_codes=commodity_codes,
            records_by_code=records_by_code,
            groups=groups,
            rejected=rejected,
        )

    def main_title(self, description: str) -> str:
        """Чистое наименование позиции без хвостового заголовка группы."""
        main, _ = _split_main_and_trailing(description)
        return strip_leading_dashes(main)
