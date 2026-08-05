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
import unicodedata
from dataclasses import dataclass, field

from ..tnved_tree.helpers import digits, strip_leading_dashes
from .bounded_slices import (
    PDO_2204_ANCHOR_CODE,
    PDO_2204_CODES,
    PDO_2204_DEPTH,
    PDO_2204_HEADING,
    PDO_2204_LEAF_COUNT,
    PDO_2204_OFFICIAL_HEADER,
    PDO_2204_PARENT_CODE,
    PDO_2204_REASON,
    PDO_2204_SCOPE_KIND,
    PDO_2204_STOP_CODE,
    PGI_2204_OFFICIAL_HEADER,
    PGI_2204_TITLE,
)
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

# One packed official description contains several dash-prefixed headers.  The
# regex is used only by the bounded 2204 guard below; the generic extractor
# intentionally keeps its established single-trailing-header policy.
_PACKED_HEADER_MARKER_RE = re.compile(
    rf"(?:^|\s)(?P<marks>[{_DASH_CLASS}](?:\s+[{_DASH_CLASS}])*)\s+"
)


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
    #: Optional fail-closed scope proven from one Canonical source snapshot.
    #: TASK-SEMANTIC-006 is the only producer; ordinary groups leave these None.
    verified_scope_kind: str | None = None
    verified_scope_start_exclusive: str | None = None
    verified_scope_end_inclusive: str | None = None
    verified_scope_parent_code: str | None = None
    verified_scope_leaf_count: int | None = None


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


@dataclass(frozen=True)
class _PackedHeader:
    """One dash-prefixed segment inside the exact bounded official chain."""

    title: str
    raw: str
    dash_depth: int


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


def _normalise_official_header(value: str) -> str:
    """NFC/case/whitespace normalization for exact official-header matching."""

    normalized = unicodedata.normalize("NFC", value or "").strip()
    normalized = normalized[:-1].rstrip() if normalized.endswith(":") else normalized
    return _normalise_title(normalized)


def _packed_headers(description: str) -> list[_PackedHeader]:
    """Split a packed official description into dash-depth segments.

    This helper is intentionally not part of the generic acceptance path.  It
    only supplies evidence to the fully bounded 2204 PDO rule.
    """

    source = unicodedata.normalize("NFC", description or "").strip()
    matches = list(_PACKED_HEADER_MARKER_RE.finditer(source))
    headers: list[_PackedHeader] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(source)
        title = " ".join(source[match.end() : end].strip().split())
        if not title:
            continue
        clean_title = title[:-1].rstrip() if title.endswith(":") else title
        headers.append(
            _PackedHeader(
                title=clean_title,
                raw=source[match.start() : end].strip(),
                dash_depth=sum(
                    1 for char in match.group("marks") if char in _DASH_CLASS
                ),
            )
        )
    return headers


def _bounded_2204_pdo_group(
    *,
    heading: str,
    commodity_codes: list[str],
    records_by_code: dict[str, SourceRecord],
    accepted_groups: list[ExtractedGroup],
) -> ExtractedGroup | None:
    """Return the exact 220421 PDO slice or fail closed to the flat model.

    The official anchor packs several headers into 2204210900.  We accept only
    its final, exact depth-6 PDO header and only while the first same-depth PGI
    boundary remains 2204217800.  The open interval after the anchor through
    that boundary must still be 33 contiguous Canonical sibling leaves under
    2204210000.  Any source/topology drift simply leaves the existing safe
    extraction unchanged.
    """

    if heading != PDO_2204_HEADING:
        return None
    try:
        anchor_index = commodity_codes.index(PDO_2204_ANCHOR_CODE)
        stop_index = commodity_codes.index(PDO_2204_STOP_CODE)
        anchor = records_by_code[PDO_2204_ANCHOR_CODE]
        parent = records_by_code[PDO_2204_PARENT_CODE]
    except (KeyError, ValueError):
        return None
    if not anchor_index < stop_index:
        return None
    if (
        anchor.is_leaf is not True
        or anchor.parent_code != PDO_2204_PARENT_CODE
        or parent.is_leaf is not False
    ):
        return None

    anchor_headers = _packed_headers(anchor.description)
    anchor_same_depth = [
        (index, header)
        for index, header in enumerate(anchor_headers)
        if header.dash_depth == PDO_2204_DEPTH
    ]
    if (
        len(anchor_same_depth) != 1
        or anchor_same_depth[0][0] == 0
        or anchor_same_depth[0][0] != len(anchor_headers) - 1
        or _normalise_official_header(anchor_same_depth[0][1].title)
        != _normalise_official_header(PDO_2204_OFFICIAL_HEADER)
    ):
        return None
    pdo_header = anchor_same_depth[0][1]

    # An unknown same- or higher-level header would legally close the PDO span
    # even when the conservative generic extractor rejects its first fragment.
    # Therefore every intervening packed record must contain only deeper headers.
    if any(
        header.dash_depth <= PDO_2204_DEPTH
        for code in commodity_codes[anchor_index + 1 : stop_index]
        for header in _packed_headers(records_by_code[code].description)
    ):
        return None

    stop_headers = _packed_headers(records_by_code[PDO_2204_STOP_CODE].description)
    stop_same_depth = [
        (index, header)
        for index, header in enumerate(stop_headers)
        if header.dash_depth == PDO_2204_DEPTH
    ]
    if (
        len(stop_same_depth) != 1
        or stop_same_depth[0][0] == 0
        or stop_same_depth[0][0] != len(stop_headers) - 1
        or _normalise_official_header(stop_same_depth[0][1].title)
        != _normalise_official_header(PGI_2204_OFFICIAL_HEADER)
    ):
        return None

    # The ordinary strict extractor must also have accepted the PGI boundary;
    # otherwise adding the PDO group could leave it open beyond the proven span.
    if not any(
        group.source_code == PDO_2204_STOP_CODE
        and group.after_code == PDO_2204_STOP_CODE
        and group.dash_depth == pdo_header.dash_depth
        and _normalise_title(group.title)
        == _normalise_title(PGI_2204_TITLE)
        for group in accepted_groups
    ):
        return None
    if any(
        group.after_code is not None
        and PDO_2204_ANCHOR_CODE < group.after_code < PDO_2204_STOP_CODE
        for group in accepted_groups
    ):
        return None

    slice_codes = commodity_codes[anchor_index + 1 : stop_index + 1]
    interval_codes = [
        code
        for code in commodity_codes
        if PDO_2204_ANCHOR_CODE < code <= PDO_2204_STOP_CODE
    ]
    if (
        tuple(slice_codes) != PDO_2204_CODES
        or slice_codes != interval_codes
        or any(
            records_by_code[code].is_leaf is not True
            or records_by_code[code].parent_code != PDO_2204_PARENT_CODE
            for code in slice_codes
        )
    ):
        return None

    return ExtractedGroup(
        title=_clean_group_title(pdo_header.title),
        raw=pdo_header.raw,
        source_code=PDO_2204_ANCHOR_CODE,
        after_code=PDO_2204_ANCHOR_CODE,
        confidence=HIGH,
        reason=PDO_2204_REASON,
        dash_depth=pdo_header.dash_depth,
        verified_scope_kind=PDO_2204_SCOPE_KIND,
        verified_scope_start_exclusive=PDO_2204_ANCHOR_CODE,
        verified_scope_end_inclusive=PDO_2204_STOP_CODE,
        verified_scope_parent_code=PDO_2204_PARENT_CODE,
        verified_scope_leaf_count=PDO_2204_LEAF_COUNT,
    )


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
                is_leaf=rec.is_leaf,
                parent_code=rec.parent_code,
            )
            if code10 == pad_code:
                pad_record = records_by_code[code10]
                if pad_record.is_leaf:
                    commodity_codes.append(code10)
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
        if pad_record is not None and not pad_record.is_leaf:
            consider(pad_code, pad_record.description, None)

        # 2. Заголовки, «прилипшие» к описаниям позиций.
        for code10 in commodity_codes:
            if code10 == pad_code:
                # Exact terminal L4 — товар, а не источник semantic-группы.
                continue
            consider(code10, records_by_code[code10].description, code10)

        bounded_pdo = _bounded_2204_pdo_group(
            heading=heading4,
            commodity_codes=commodity_codes,
            records_by_code=records_by_code,
            accepted_groups=groups,
        )
        if bounded_pdo is not None:
            insert_at = next(
                (
                    index
                    for index, group in enumerate(groups)
                    if group.after_code is not None
                    and group.after_code > PDO_2204_ANCHOR_CODE
                ),
                len(groups),
            )
            groups.insert(insert_at, bounded_pdo)

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
