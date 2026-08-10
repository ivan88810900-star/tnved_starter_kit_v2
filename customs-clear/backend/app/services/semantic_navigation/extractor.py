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
    Bounded0304GroupSpec,
    CHEESE_0406_AFTER_CODE,
    CHEESE_0406_AFTER_DESCRIPTION,
    CHEESE_0406_ANCHOR_CODE,
    CHEESE_0406_ANCHOR_DESCRIPTION,
    CHEESE_0406_GROUPS,
    CHEESE_0406_HEADING,
    CHEESE_0406_MIDDLE_ANCHOR_CODE,
    CHEESE_0406_MIDDLE_DESCRIPTION,
    CHEESE_0406_PAD_CODE,
    CHEESE_0406_PARENT_CODE,
    CHEESE_0406_REASON,
    CHEESE_0406_SCOPE_KIND,
    CHEESE_0406_STOP_CODE,
    CHEESE_0406_STOP_DESCRIPTION,
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
    STATE_0304_PAD_CODE,
    STATE_0304_REAL_SIGNATURE,
    STATE_0304_GROUPS,
    STATE_0304_HEADING,
    STATE_0304_REASON,
    STATE_0304_SCOPE_KIND,
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
# regex is used only by the bounded 2204/0304/0406 guards below; the generic
# extractor intentionally keeps its established single-trailing-header policy.
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
    #: Bounded TASK-SEMANTIC-006/007/008 rules are the only producers; ordinary
    #: groups leave these fields ``None``.
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
    exact_title: str
    has_terminal_colon: bool
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
    only supplies evidence to the fully bounded 2204/0304/0406 rules.
    """

    # Keep source spelling byte-for-byte apart from outer whitespace.  The
    # 2204 comparison applies its own NFC policy; the exact 0304 rule must be
    # able to detect even Unicode-normalization drift in a legal label.
    source = (description or "").strip()
    matches = list(_PACKED_HEADER_MARKER_RE.finditer(source))
    headers: list[_PackedHeader] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(source)
        exact_segment = source[match.end() : end].strip()
        if not exact_segment:
            continue
        has_terminal_colon = exact_segment.endswith(":")
        exact_title = (
            exact_segment[:-1].rstrip()
            if has_terminal_colon
            else exact_segment
        )
        title = " ".join(exact_segment.split())
        clean_title = title[:-1].rstrip() if title.endswith(":") else title
        headers.append(
            _PackedHeader(
                title=clean_title,
                exact_title=exact_title,
                has_terminal_colon=has_terminal_colon,
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


def _apply_bounded_0304_state(
    *,
    heading: str,
    commodity_codes: list[str],
    records_by_code: dict[str, SourceRecord],
    accepted_groups: list[ExtractedGroup],
    rejected_candidates: list[RejectedCandidate],
) -> tuple[list[ExtractedGroup], list[RejectedCandidate]]:
    """Upgrade all five exact official 0304 states or change nothing.

    The ordinary parser deliberately truncates titles at commas and rejects
    generic ``прочее`` labels.  In this one audited heading the complete source
    state proves five mutually exclusive level-1 headers.  A/C/D therefore
    replace their existing generic accepts, while B/E replace matching generic
    rejections.  Any source, boundary, order, parent or leaf drift keeps the
    established generic result unchanged.
    """

    if heading != STATE_0304_HEADING:
        return accepted_groups, rejected_candidates

    pad_record = records_by_code.get(STATE_0304_PAD_CODE)
    actual_real_signature = tuple(
        (
            code,
            str(records_by_code[code].parent_code or ""),
            records_by_code[code].is_leaf,
        )
        for code in commodity_codes
        if code in records_by_code
    )
    if (
        pad_record is None
        or pad_record.code != STATE_0304_PAD_CODE
        or pad_record.is_leaf is not False
        or pad_record.parent_code is not None
        or tuple(commodity_codes)
        != tuple(code for code, _, _ in STATE_0304_REAL_SIGNATURE)
        or actual_real_signature != STATE_0304_REAL_SIGNATURE
        or set(records_by_code)
        != {
            STATE_0304_PAD_CODE,
            *(code for code, _, _ in STATE_0304_REAL_SIGNATURE),
        }
    ):
        return accepted_groups, rejected_candidates

    position = {code: index for index, code in enumerate(commodity_codes)}
    expected_boundaries = [spec.anchor_code for spec in STATE_0304_GROUPS]
    boundary_headers: dict[str, _PackedHeader] = {}
    observed_boundaries: list[str] = []

    # A hidden same-level marker legally closes a product state even when the
    # generic parser rejects its title.  Require the complete depth-1 boundary
    # sequence, and require each known marker to be the final packed header.
    for code in commodity_codes:
        record = records_by_code.get(code)
        if record is None:
            return accepted_groups, rejected_candidates
        headers = _packed_headers(record.description)
        for header_index, header in enumerate(headers):
            if header.dash_depth != 1:
                continue
            observed_boundaries.append(code)
            if header_index != len(headers) - 1 or code in boundary_headers:
                return accepted_groups, rejected_candidates
            boundary_headers[code] = header
    if observed_boundaries != expected_boundaries:
        return accepted_groups, rejected_candidates

    generic_accepts: dict[str, tuple[int, ExtractedGroup]] = {}
    upgraded: list[
        tuple[Bounded0304GroupSpec, _PackedHeader, ExtractedGroup | None]
    ] = []

    for spec in STATE_0304_GROUPS:
        header = boundary_headers.get(spec.anchor_code)
        anchor = records_by_code.get(spec.anchor_code)
        anchor_signature = next(
            (
                signature
                for prior in STATE_0304_GROUPS
                for signature in prior.signature
                if signature[0] == spec.anchor_code
            ),
            None,
        )
        expected_anchor_parent = (
            anchor_signature[1]
            if anchor_signature is not None
            else STATE_0304_HEADING
        )
        if (
            header is None
            or anchor is None
            or anchor.is_leaf is not True
            or anchor.parent_code != expected_anchor_parent
            or not header.has_terminal_colon
            or header.exact_title != spec.title
        ):
            return accepted_groups, rejected_candidates

        actual_signature = tuple(
            (
                code,
                str(records_by_code[code].parent_code or ""),
                records_by_code[code].is_leaf,
            )
            for code in commodity_codes
            if code.startswith(spec.code_prefix)
        )
        if actual_signature != spec.signature:
            return accepted_groups, rejected_candidates

        matching_accepts = [
            (index, group)
            for index, group in enumerate(accepted_groups)
            if group.source_code == spec.anchor_code
            and group.after_code == spec.anchor_code
            and group.dash_depth == 1
        ]
        matching_rejections = [
            candidate
            for candidate in rejected_candidates
            if candidate.source_code == spec.anchor_code
            and candidate.reason == "generic_subcategory"
        ]
        existing: ExtractedGroup | None = None
        if spec.generic_disposition == "accepted":
            if len(matching_accepts) != 1 or matching_rejections:
                return accepted_groups, rejected_candidates
            generic_accepts[spec.key] = matching_accepts[0]
            existing = matching_accepts[0][1]
        else:
            if matching_accepts or len(matching_rejections) != 1:
                return accepted_groups, rejected_candidates
        upgraded.append((spec, header, existing))

    # Validation above is complete; only now mutate copies of generic output.
    groups = list(accepted_groups)
    rejected = list(rejected_candidates)
    additions: list[ExtractedGroup] = []
    for spec, header, existing in upgraded:
        bounded = ExtractedGroup(
            title=spec.title,
            raw=header.raw,
            source_code=spec.anchor_code,
            after_code=spec.anchor_code,
            confidence=HIGH,
            reason=STATE_0304_REASON,
            dash_depth=1,
            verified_scope_kind=STATE_0304_SCOPE_KIND,
            verified_scope_start_exclusive=spec.anchor_code,
            verified_scope_end_inclusive=spec.last_code,
            verified_scope_leaf_count=spec.leaf_count,
        )
        if existing is not None:
            index, old_parent = generic_accepts[spec.key]
            groups[index] = bounded
            for child in groups:
                if (
                    child.parent_source_code_hint == spec.anchor_code
                    and _normalise_title(child.parent_title_hint or "")
                    == _normalise_title(old_parent.title)
                ):
                    child.parent_title_hint = bounded.title
        else:
            additions.append(bounded)

    # Preserve activation order without changing ordering among ordinary groups.
    for bounded in additions:
        anchor_index = position[bounded.after_code or ""]
        insert_at = next(
            (
                index
                for index, group in enumerate(groups)
                if group.after_code is not None
                and position.get(group.after_code, len(position)) > anchor_index
            ),
            len(groups),
        )
        groups.insert(insert_at, bounded)
    return groups, rejected


def _apply_bounded_0406_moisture(
    *,
    heading: str,
    commodity_codes: list[str],
    records_by_code: dict[str, SourceRecord],
    accepted_groups: list[ExtractedGroup],
    rejected_candidates: list[RejectedCandidate],
) -> tuple[list[ExtractedGroup], list[RejectedCandidate]]:
    """Add the exact official 0406 moisture chain or change nothing.

    This is deliberately not a generic percentage/range parser.  The source
    strings, packed-header depths, ordered Canonical sibling tuples and generic
    extractor evidence must all match the audited Gate-2 projection.  A single
    mismatch leaves the complete, safe pre-task route untouched.
    """

    if heading != CHEESE_0406_HEADING:
        return accepted_groups, rejected_candidates

    try:
        pad = records_by_code[CHEESE_0406_PAD_CODE]
        parent = records_by_code[CHEESE_0406_PARENT_CODE]
        anchor = records_by_code[CHEESE_0406_ANCHOR_CODE]
        middle = records_by_code[CHEESE_0406_MIDDLE_ANCHOR_CODE]
        stop = records_by_code[CHEESE_0406_STOP_CODE]
        after = records_by_code[CHEESE_0406_AFTER_CODE]
    except KeyError:
        return accepted_groups, rejected_candidates

    if not (
        pad.is_leaf is False
        and pad.parent_code is None
        and parent.is_leaf is False
        and parent.parent_code == CHEESE_0406_HEADING
        and anchor.description == CHEESE_0406_ANCHOR_DESCRIPTION
        and middle.description == CHEESE_0406_MIDDLE_DESCRIPTION
        and stop.description == CHEESE_0406_STOP_DESCRIPTION
        and after.description == CHEESE_0406_AFTER_DESCRIPTION
    ):
        return accepted_groups, rejected_candidates

    anchor_headers = _packed_headers(anchor.description)
    middle_headers = _packed_headers(middle.description)
    stop_headers = _packed_headers(stop.description)
    after_headers = _packed_headers(after.description)
    expected_anchor_headers = (
        (4, "сыры из овечьего молока или молока буйволиц в контейнерах, "
         "содержащих рассол, или в бурдюках из овечьей или козьей шкуры", False),
        (4, "прочие", True),
        (5, CHEESE_0406_GROUPS[0].title, True),
        (6, CHEESE_0406_GROUPS[1].title, True),
    )
    expected_middle_headers = (
        (7, "прочие", False),
        (6, CHEESE_0406_GROUPS[2].title, True),
    )

    def header_signature(
        headers: list[_PackedHeader],
    ) -> tuple[tuple[int, str, bool], ...]:
        return tuple(
            (header.dash_depth, header.exact_title, header.has_terminal_colon)
            for header in headers
        )

    if (
        header_signature(anchor_headers) != expected_anchor_headers
        or header_signature(middle_headers) != expected_middle_headers
        or header_signature(stop_headers)
        != ((6, "более 72 мас.%", False),)
        or header_signature(after_headers) != ((5, "прочие", True),)
    ):
        return accepted_groups, rejected_candidates

    positions = {code: index for index, code in enumerate(commodity_codes)}
    if not all(
        code in positions
        for code in (
            CHEESE_0406_ANCHOR_CODE,
            CHEESE_0406_MIDDLE_ANCHOR_CODE,
            CHEESE_0406_STOP_CODE,
            CHEESE_0406_AFTER_CODE,
        )
    ):
        return accepted_groups, rejected_candidates
    if not (
        positions[CHEESE_0406_ANCHOR_CODE]
        < positions[CHEESE_0406_MIDDLE_ANCHOR_CODE]
        < positions[CHEESE_0406_STOP_CODE]
        < positions[CHEESE_0406_AFTER_CODE]
    ):
        return accepted_groups, rejected_candidates

    # Any unknown top-or-shallower packed boundary inside the verified span
    # legally closes the question, even if generic extraction rejects it.
    if any(
        header.dash_depth <= 5
        for code in commodity_codes[
            positions[CHEESE_0406_ANCHOR_CODE] + 1 :
            positions[CHEESE_0406_AFTER_CODE]
        ]
        if code != CHEESE_0406_AFTER_CODE
        for header in _packed_headers(records_by_code[code].description)
    ):
        return accepted_groups, rejected_candidates

    for spec in CHEESE_0406_GROUPS:
        actual = tuple(
            (
                code,
                str(records_by_code[code].parent_code or ""),
                records_by_code[code].is_leaf,
            )
            for code in commodity_codes
            if spec.anchor_code < code <= spec.stop_code
            and code in records_by_code
        )
        if actual != spec.signature:
            return accepted_groups, rejected_candidates

    anchor_rejections = [
        candidate
        for candidate in rejected_candidates
        if candidate.source_code == CHEESE_0406_ANCHOR_CODE
        and candidate.reason == "generic_subcategory"
    ]
    middle_accepts = [
        (index, group)
        for index, group in enumerate(accepted_groups)
        if group.source_code == CHEESE_0406_MIDDLE_ANCHOR_CODE
        and group.after_code == CHEESE_0406_MIDDLE_ANCHOR_CODE
        and group.dash_depth == 6
    ]
    if len(anchor_rejections) != 1 or len(middle_accepts) != 1:
        return accepted_groups, rejected_candidates

    def exact_group(spec_index: int, raw: str) -> ExtractedGroup:
        spec = CHEESE_0406_GROUPS[spec_index]
        return ExtractedGroup(
            title=spec.title,
            raw=raw,
            source_code=spec.anchor_code,
            after_code=spec.anchor_code,
            confidence=HIGH,
            reason=CHEESE_0406_REASON,
            dash_depth=spec.dash_depth,
            parent_title_hint=(
                CHEESE_0406_GROUPS[0].title if spec.key != "top" else None
            ),
            parent_source_code_hint=(
                CHEESE_0406_ANCHOR_CODE if spec.key != "top" else None
            ),
            hierarchy_hint="dash_depth" if spec.key != "top" else None,
            verified_scope_kind=CHEESE_0406_SCOPE_KIND,
            verified_scope_start_exclusive=spec.anchor_code,
            verified_scope_end_inclusive=spec.stop_code,
            verified_scope_parent_code=CHEESE_0406_PARENT_CODE,
            verified_scope_leaf_count=spec.leaf_count,
        )

    top = exact_group(0, anchor_headers[2].raw)
    low = exact_group(1, anchor_headers[3].raw)
    bounded_middle = exact_group(2, middle_headers[1].raw)
    groups = list(accepted_groups)
    middle_index, _ = middle_accepts[0]
    groups[middle_index] = bounded_middle
    insert_at = next(
        (
            index
            for index, group in enumerate(groups)
            if group.after_code is not None
            and group.after_code > CHEESE_0406_ANCHOR_CODE
        ),
        len(groups),
    )
    groups[insert_at:insert_at] = [top, low]
    return groups, list(rejected_candidates)


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

        groups, rejected = _apply_bounded_0304_state(
            heading=heading4,
            commodity_codes=commodity_codes,
            records_by_code=records_by_code,
            accepted_groups=groups,
            rejected_candidates=rejected,
        )

        groups, rejected = _apply_bounded_0406_moisture(
            heading=heading4,
            commodity_codes=commodity_codes,
            records_by_code=records_by_code,
            accepted_groups=groups,
            rejected_candidates=rejected,
        )

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
