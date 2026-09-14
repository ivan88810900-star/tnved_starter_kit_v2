"""Enumerate acts explicitly named in retained EEC index bytes.

This inventory describes the index declaration, not the universe of applicable
law. Dates are adoption dates quoted by that declaration. No effective date,
document URL, captured act body or legal-completeness assertion is inferred.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Literal

from app.services.ett_index import ETTIndexError, ETTIndexReference, parse_index

MAX_NAMED_AMENDMENTS = 2048
_GAP = r"[\s\u200b\u200c\u200d\ufeff]"
_SEPARATOR = re.compile(rf"{_GAP}*(?:,{_GAP}*)*")
_OPENING = re.compile(rf"\({_GAP}*в{_GAP}+ред\.{_GAP}*", re.I)
_AUTHORITY = re.compile(
    rf"решений{_GAP}+(Коллегии|Совета){_GAP}+Евразийской{_GAP}+"
    rf"экономической{_GAP}+комиссии(?!\w)", re.I,
)
_ACT = re.compile(
    rf"от{_GAP}+([0-9]{{2}})\.([0-9]{{2}})\.([0-9]{{4}})"
    rf"{_GAP}+№{_GAP}*([1-9][0-9]{{0,5}})(?!\w)"
    rf"(?:{_GAP}+с{_GAP}+разъяснением)?", re.I,
)
_MONTHS = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4,
    "мая": 5, "июня": 6, "июля": 7, "августа": 8,
    "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
}
_FOUNDING = re.compile(
    rf"(?P<authority>Решением{_GAP}+Совета)"
    rf"(?:{_GAP}+Евразийской{_GAP}+экономической{_GAP}+комиссии)?"
    rf"{_GAP}+от{_GAP}+(?P<day>[0-9]{{1,2}}){_GAP}+"
    rf"(?P<month>{'|'.join(_MONTHS)}){_GAP}+(?P<year>[0-9]{{4}})"
    rf"{_GAP}+г\.{_GAP}*№{_GAP}*(?P<number>[1-9][0-9]{{0,5}})(?=$|{_GAP})", re.I,
)


class ETTAmendmentInventoryError(ValueError):
    """An observed declaration cannot be enumerated without ambiguity."""


@dataclass(frozen=True)
class ETTDeclarationQuote:
    start: int
    end: int
    raw_text: str
    raw_text_sha256: str


@dataclass(frozen=True)
class ETTNamedAct:
    issuing_body: Literal["collegium", "council"]
    adoption_date: date
    number: str
    evidence: ETTDeclarationQuote
    authority_evidence: ETTDeclarationQuote
    direct_references: tuple[ETTIndexReference, ...] = ()


@dataclass(frozen=True)
class ETTAmendmentInventory:
    source_url: str
    source_sha256: str
    size_bytes: int
    declaration_text: str
    declaration_sha256: str
    founding_act: ETTNamedAct
    amendments: tuple[ETTNamedAct, ...]
    named_count: int
    linked_count: int
    missing_link_count: int
    legal_inventory_complete: bool = field(default=False, init=False)
    act_bodies_verified: bool = field(default=False, init=False)
    effective_dates_resolved: bool = field(default=False, init=False)


def _quote(text: str, start: int, end: int) -> ETTDeclarationQuote:
    raw = text[start:end]
    return ETTDeclarationQuote(start, end, raw, hashlib.sha256(raw.encode()).hexdigest())


def _date(year: str, month: str | int, day: str) -> date:
    try:
        return date(int(year), int(month), int(day))
    except ValueError as exc:
        raise ETTAmendmentInventoryError("declaration contains an invalid adoption date") from exc


def _identity(act: ETTNamedAct) -> tuple[str, date, str]:
    return act.issuing_body, act.adoption_date, act.number


def _normalized(text: str) -> str:
    return " ".join(re.sub(r"[\u200b\u200c\u200d\ufeff]", "", text).split())


def parse_amendment_inventory(raw: bytes) -> ETTAmendmentInventory:
    """Parse the complete supported declaration grammar from original index HTML.

    Exact quotes use character offsets into ``declaration_text`` (the retained
    visible-text projection from ``parse_index``), not byte offsets in HTML.
    Both the original HTML and that projection are separately hashed. Each direct
    link is assigned only by its unique observed label; target contents still
    require an independent identity check. Unknown residue is never discarded.
    """
    try:
        index = parse_index(raw)
    except ETTIndexError as exc:
        raise ETTAmendmentInventoryError("source is not a valid retained ETT index") from exc
    text = index.declaration_text
    openings = list(_OPENING.finditer(text))
    if len(openings) != 1:
        raise ETTAmendmentInventoryError("revision opening is missing or ambiguous")
    opening = openings[0]
    end = text.find(")", opening.end())
    if end < 0:
        raise ETTAmendmentInventoryError("revision declaration has no closing delimiter")
    prefix, suffix = text[:opening.start()], text[end + 1:]
    founding_matches = list(_FOUNDING.finditer(prefix))
    if len(founding_matches) != 1:
        raise ETTAmendmentInventoryError("founding act identity is missing or ambiguous")
    match = founding_matches[0]
    # Outside the single revision expression only the founding act may name an
    # authority/date declaration. Introductory titles and interpretation headings
    # are retained in the projection but never parsed as additional acts.
    leftover = prefix[:match.start()] + prefix[match.end():] + suffix
    if re.search(r"Решени[еяйм]|\bот\s+[0-9]{1,2}[.\s]", leftover, re.I):
        raise ETTAmendmentInventoryError("act declaration exists outside its supported scope")
    founding = ETTNamedAct(
        issuing_body="council",
        adoption_date=_date(match['year'], _MONTHS[match['month'].lower()], match['day']),
        number=match['number'], evidence=_quote(text, match.start(), match.end()),
        authority_evidence=_quote(text, match.start('authority'), match.end('authority')),
    )
    authorities = list(_AUTHORITY.finditer(text, opening.end(), end))
    if len(authorities) != 2 or [m.group(1).lower() for m in authorities] != ["коллегии", "совета"]:
        raise ETTAmendmentInventoryError("revision issuing-body blocks are missing or ambiguous")
    if not _SEPARATOR.fullmatch(text[opening.end():authorities[0].start()]):
        raise ETTAmendmentInventoryError("unrecognized text before the issuing-body blocks")
    amendments: list[ETTNamedAct] = []
    identities = {_identity(founding)}
    for position, authority in enumerate(authorities):
        stop = authorities[position + 1].start() if position + 1 < len(authorities) else end
        cursor = authority.end()
        matches = list(_ACT.finditer(text, cursor, stop))
        if not matches:
            raise ETTAmendmentInventoryError("issuing-body block names no amendments")
        for match in matches:
            if not _SEPARATOR.fullmatch(text[cursor:match.start()]):
                raise ETTAmendmentInventoryError("unrecognized text in amendment declaration")
            record = ETTNamedAct(
                issuing_body="collegium" if position == 0 else "council",
                adoption_date=_date(match.group(3), match.group(2), match.group(1)),
                number=match.group(4), evidence=_quote(text, match.start(), match.end()),
                authority_evidence=_quote(text, authority.start(), authority.end()),
            )
            if _identity(record) in identities:
                raise ETTAmendmentInventoryError("duplicate act identity in declaration")
            identities.add(_identity(record))
            amendments.append(record)
            if len(amendments) > MAX_NAMED_AMENDMENTS:
                raise ETTAmendmentInventoryError("named amendment count exceeds its bound")
            cursor = match.end()
        if not _SEPARATOR.fullmatch(text[cursor:stop]):
            raise ETTAmendmentInventoryError("unrecognized trailing amendment declaration")
    by_label: dict[tuple[date, str], list[int]] = {}
    for position, act in enumerate(amendments):
        by_label.setdefault((act.adoption_date, act.number), []).append(position)
    assigned_urls: dict[str, tuple[str, date, str]] = {}
    for reference in index.amendment_links:
        # A link alone has no inherited issuing body. Matching its date/number
        # to two bodies is ambiguous, even when both are legitimate declarations.
        label = _ACT.fullmatch(_normalized(reference.text))
        if label is None:
            raise ETTAmendmentInventoryError("amendment link has no supported observed act label")
        candidates = by_label.get((_date(label.group(3), label.group(2), label.group(1)), label.group(4)), [])
        if len(candidates) != 1:
            raise ETTAmendmentInventoryError("amendment link identity is missing or ambiguous")
        position = candidates[0]
        act = amendments[position]
        if _normalized(reference.text) not in _normalized(act.evidence.raw_text):
            raise ETTAmendmentInventoryError("amendment link label contradicts the declaration")
        if reference.url in assigned_urls and assigned_urls[reference.url] != _identity(act):
            raise ETTAmendmentInventoryError("one amendment URL is assigned to different acts")
        assigned_urls[reference.url] = _identity(act)
        amendments[position] = replace(act, direct_references=act.direct_references + (reference,))
    linked = sum(bool(act.direct_references) for act in amendments)
    return ETTAmendmentInventory(
        source_url=index.source_url, source_sha256=index.source_sha256,
        size_bytes=index.size_bytes, declaration_text=text, declaration_sha256=index.declaration_sha256,
        founding_act=founding, amendments=tuple(amendments), named_count=len(amendments),
        linked_count=linked, missing_link_count=len(amendments) - linked,
    )
