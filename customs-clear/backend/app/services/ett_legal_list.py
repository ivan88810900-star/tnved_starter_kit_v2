"""Source-bound discovery from observed EAEU legal-portal year-list pages.

List metadata identifies document candidates, not verified primary legal dates.
No request is performed and no missing page, query parameter or document URL is
generated. Row text is a deterministic HTML text projection, not source bytes.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag

from app.services.ett_index import ETTIndexError, MAX_INDEX_BYTES, _text, _visible, validate_source_url
from app.services.ett_legal_attachments import (
    ETTLegalAttachmentError, ETTLegalAttachmentReference, _AttachmentGuard,
    _FILE_TYPES, _attachment_target,
)
from app.services.ett_transport import OfficialTransportError, validate_official_url

MAX_LIST_DOCUMENTS = 1000
MAX_ROW_REFERENCES = 128
_CATEGORY = re.compile(
    r"Акты Евразийской экономической комиссии\s+[–-]\s+"
    r"(Коллегия|Совет) Евразийской экономической комиссии\s+[–-]\s+"
    r"Решения\s+[–-]\s+([0-9]{4})",
)
_IDENTITY = re.compile(r"Решение (Коллегии|Совета) (?:ЕЭК )?№\s*([1-9][0-9]{0,5})")
_DATE = re.compile(r"([0-9]{2})\.([0-9]{2})\.([0-9]{4})")


class ETTLegalListError(ValueError):
    """An observed list cannot be attributed or enumerated unambiguously."""


@dataclass(frozen=True)
class ETTListEvidence:
    locator: str
    text: str
    text_sha256: str


@dataclass(frozen=True)
class ETTListLink:
    url: str
    href: str
    text: str
    locator: str


@dataclass(frozen=True)
class ETTLegalListDocument:
    issuing_body: str
    number: str
    observed_adoption_date: date
    observed_publication_date: date
    observed_entry_into_force_date: date | None
    title: str
    document_link: ETTListLink
    evidence: ETTListEvidence
    pdf_references: tuple[ETTLegalAttachmentReference, ...]
    unsupported_references: tuple[ETTLegalAttachmentReference, ...]
    primary_body_verified: bool = field(default=False, init=False)
    legal_dates_verified: bool = field(default=False, init=False)


@dataclass(frozen=True)
class ETTLegalList:
    source_url: str
    source_sha256: str
    size_bytes: int
    category: str
    issuing_body: str
    observed_year: int
    reported_result_count: int
    documents: tuple[ETTLegalListDocument, ...]
    pagination_links: tuple[ETTListLink, ...]
    all_pages_captured: bool = field(default=False, init=False)
    legal_inventory_complete: bool = field(default=False, init=False)
    primary_bodies_verified: bool = field(default=False, init=False)


def validate_list_url(url: str) -> str:
    """Validate a supplied list URL, including only observed pagination syntax."""
    if not isinstance(url, str) or len(url) > 4096 or any(c in url for c in "\\#"):
        raise ETTLegalListError("invalid legal-list URL")
    try:
        parts = urlsplit(url)
        validate_official_url(urlunsplit((parts.scheme, parts.netloc, parts.path, "", "")))
        if parts.netloc != "docs.eaeunion.org" or not re.fullmatch(r"/documents/[1-9][0-9]*/", parts.path):
            raise ValueError
        if "?" in url:
            if not parts.query or not re.fullmatch(r"(?:sphrase_id=[0-9]{1,12}&)?PAGEN_1=[1-9][0-9]{0,5}", parts.query):
                raise ValueError
        if any(ord(c) < 33 or ord(c) == 127 for c in url):
            raise ValueError
    except (ValueError, OfficialTransportError):
        raise ETTLegalListError("unsupported legal-list URL or pagination parameters") from None
    return url


def _one(parent: Tag, selector: str) -> Tag:
    matches = [node for node in parent.select(selector) if _visible(node)]
    if len(matches) != 1:
        raise ETTLegalListError("list row has missing or ambiguous required fields")
    return matches[0]


def _date_literal(value: str) -> date:
    match = _DATE.fullmatch(value)
    if match is None:
        raise ETTLegalListError("list date field has unsupported syntax")
    try:
        return date(int(match[3]), int(match[2]), int(match[1]))
    except ValueError:
        raise ETTLegalListError("list contains an invalid date literal") from None


def _href(anchor: Tag) -> str:
    value = anchor.get("href")
    if not isinstance(value, str) or not 1 <= len(value) <= 4096:
        raise ETTLegalListError("list link has no bounded href")
    if any(ord(c) < 32 or ord(c) == 127 for c in value) or "\\" in value or re.search(r"(?:^|/)(?:\.|\.\.)(?:/|$)", value):
        raise ETTLegalListError("list href contains controls or traversal")
    return value


def parse_legal_list(raw: bytes, page_url: str) -> ETTLegalList:
    """Enumerate one complete retained page; preserve missing-page uncertainty."""
    validate_list_url(page_url)
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_INDEX_BYTES:
        raise ETTLegalListError("list requires bounded original HTML bytes")
    try:
        source = raw.decode("utf-8-sig", errors="strict")
    except UnicodeError:
        raise ETTLegalListError("list HTML must be valid UTF-8") from None
    if "\x00" in source or re.search(r"<!\s*(?:ENTITY|DOCTYPE[^>]*\[)", source, re.I):
        raise ETTLegalListError("list HTML contains an invalid declaration")
    if not re.search(r"<html(?:\s|>)", source, re.I) or not re.search(r"</html\s*>\s*$", source, re.I):
        raise ETTLegalListError("list HTML is incomplete")
    guard = _AttachmentGuard()
    try:
        guard.feed(source)
        guard.close()
        guard.verify()
    except ETTIndexError:
        raise ETTLegalListError("list HTML structure is invalid") from None
    soup = BeautifulSoup(source, "html.parser")
    if len(soup.find_all("html")) != 1 or len(soup.find_all("body")) != 1 or soup.find("base"):
        raise ETTLegalListError("list document structure is ambiguous")
    if len(soup.find_all("title")) != 1:
        raise ETTLegalListError("list category is missing or ambiguous")
    category = _text(soup.title)
    category_match = _CATEGORY.fullmatch(category)
    if category_match is None:
        raise ETTLegalListError("list title is not a supported decision-year category")
    body = "collegium" if category_match[1] == "Коллегия" else "council"
    year = int(category_match[2])
    container = _one(soup.body, ".DocSearchResult_Items")
    rows = [r for r in container.select(".DocSearchResult_Item") if _visible(r)]
    if not 1 <= len(rows) <= MAX_LIST_DOCUMENTS:
        raise ETTLegalListError("list has no rows or exceeds its row bound")
    counter = _text(_one(soup.body, ".SearchResult_Heading__Counter"))
    count_match = re.fullmatch(r"Результаты: найдено ([0-9]{1,8})", counter)
    if count_match is None or int(count_match[1]) < len(rows):
        raise ETTLegalListError("reported list result count is invalid")
    all_anchors = soup.body.find_all("a")
    positions = {id(a): n for n, a in enumerate(all_anchors, 1)}
    def locator(a: Tag) -> str:
        return f"html:a:{positions[id(a)]}:line:{a.sourceline}:column:{a.sourcepos}"
    documents: list[ETTLegalListDocument] = []
    identities: set[tuple[str, date, str]] = set()
    urls: set[str] = set()
    for number, row in enumerate(rows, 1):
        if row.find_parent(class_="DocSearchResult_Item") is not None:
            raise ETTLegalListError("nested list rows are ambiguous")
        row_category = _CATEGORY.fullmatch(_text(_one(row, ".DocSearchResult_Item__Date")))
        if row_category is None or row_category.groups() != category_match.groups():
            raise ETTLegalListError("row category disagrees with its list authority or year")
        anchor = _one(row, ".DocSearchResult_Item__Link")
        label = _text(anchor)
        identity = _IDENTITY.fullmatch(label)
        if identity is None or identity[1] != ("Коллегии" if body == "collegium" else "Совета"):
            raise ETTLegalListError("list document identity disagrees with its authority")
        href = _href(anchor)
        target = urljoin(page_url, href)
        try:
            validate_source_url(target, allow_portal=True)
        except ETTIndexError:
            raise ETTLegalListError("list document URL is unsafe") from None
        if urlsplit(target).netloc != "docs.eaeunion.org" or not re.fullmatch(r"/documents/[1-9][0-9]*/[1-9][0-9]*/", urlsplit(target).path):
            raise ETTLegalListError("list document URL is outside modern portal document paths")
        title = _text(_one(row, ".DocSearchResult_Item__Text"))
        if not title or len(title) > 32_768:
            raise ETTLegalListError("list document title is missing or oversized")
        dates = _one(row, ".DocSearchResult_Item__Dates")
        fields = {}
        for node in dates.find_all("div"):
            if node.find("div") is not None or not _visible(node):
                continue
            value = _text(node)
            if not value:
                continue
            field_match = re.fullmatch(r"(Дата принятия документа|Дата опубликования документа|Дата вступления в силу): (.+)", value)
            if field_match is None or field_match[1] in fields:
                raise ETTLegalListError("list date fields are unsupported or duplicated")
            fields[field_match[1]] = _date_literal(field_match[2])
        if not {"Дата принятия документа", "Дата опубликования документа"}.issubset(fields):
            raise ETTLegalListError("required list date metadata is absent")
        adopted = fields["Дата принятия документа"]
        if adopted.year != year:
            raise ETTLegalListError("observed adoption date disagrees with the category year")
        key = body, adopted, identity[2]
        if key in identities or target in urls:
            raise ETTLegalListError("list contains duplicate act identities or document URLs")
        identities.add(key)
        urls.add(target)
        pdfs: list[ETTLegalAttachmentReference] = []
        unsupported: list[ETTLegalAttachmentReference] = []
        for attachment in row.find_all("a", href=True):
            if attachment is anchor or not _visible(attachment):
                continue
            raw_href = _href(attachment)
            probe = unquote(raw_href).strip()
            if "/upload/iblock/" not in probe and not re.search(r"\.(?:pdf|docx?|zip|xlsx?|rtf)(?:$|[?#])", probe, re.I):
                continue
            try:
                attachment_url = _attachment_target(raw_href, page_url)
            except ETTLegalAttachmentError:
                raise ETTLegalListError("list attachment URL is unsafe") from None
            literal = guard.href_literals.get((attachment.sourceline, attachment.sourcepos))
            if literal is None:
                raise ETTLegalListError("list attachment lacks a literal href")
            extension = unquote(urlsplit(attachment_url).path).rsplit(".", 1)[-1].lower()
            supported = extension == "pdf"
            reference = ETTLegalAttachmentReference(
                attachment_url, raw_href, literal, _text(attachment), locator(attachment),
                _FILE_TYPES.get(extension, "application/octet-stream"),
                "legal_attachment_pdf" if supported else "unsupported_legal_attachment",
            )
            (pdfs if supported else unsupported).append(reference)
            if len(pdfs) + len(unsupported) > MAX_ROW_REFERENCES:
                raise ETTLegalListError("list row attachment count exceeds its bound")
        text = _text(row)
        if len(text) > 128 * 1024:
            raise ETTLegalListError("list row evidence exceeds its bound")
        documents.append(ETTLegalListDocument(
            issuing_body=body, number=identity[2], observed_adoption_date=adopted,
            observed_publication_date=fields["Дата опубликования документа"],
            observed_entry_into_force_date=fields.get("Дата вступления в силу"), title=title,
            document_link=ETTListLink(target, href, label, locator(anchor)),
            evidence=ETTListEvidence(f"html:list-row:{number}:line:{row.sourceline}:column:{row.sourcepos}", text, hashlib.sha256(text.encode()).hexdigest()),
            pdf_references=tuple(pdfs), unsupported_references=tuple(unsupported),
        ))
    pagination = []
    for anchor in all_anchors:
        href = anchor.get("href")
        if not isinstance(href, str) or "PAGEN_" not in href or not _visible(anchor):
            continue
        target = urljoin(page_url, _href(anchor))
        validate_list_url(target)
        if urlsplit(target).path != urlsplit(page_url).path:
            raise ETTLegalListError("pagination changes the observed list path")
        pagination.append(ETTListLink(target, href, _text(anchor), locator(anchor)))
    return ETTLegalList(
        page_url, hashlib.sha256(raw).hexdigest(), len(raw), category, body, year,
        int(count_match[1]), tuple(documents), tuple(pagination),
    )
