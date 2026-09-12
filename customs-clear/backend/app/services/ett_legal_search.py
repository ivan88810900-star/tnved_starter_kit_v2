"""Replay observed public-portal search HTML; result absence is never legal absence.

Unlike year lists, search mixes decisions, protocols, orders and other documents.
All rows are retained; only explicit, consistent EEC decision labels produce a
candidate identity. Dates remain unverified list metadata until primary-body review.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date
from urllib.parse import parse_qsl, unquote, urljoin, urlsplit

from bs4 import BeautifulSoup

from app.services.ett_index import ETTIndexError, MAX_INDEX_BYTES, _text, _visible, validate_source_url
from app.services.ett_legal_attachments import (
    ETTLegalAttachmentError, ETTLegalAttachmentReference, _AttachmentGuard, _FILE_TYPES, _attachment_target,
)
from app.services.ett_legal_list import (
    ETTListEvidence, ETTListLink, ETTLegalListError, _CATEGORY, _IDENTITY, _date_literal, _href, _one,
)
from app.services.ett_portal_search import validate_portal_search_page_url
from app.services.ett_transport import OfficialTransportError

MAX_SEARCH_ROWS = 1000
MAX_ROW_REFERENCES = 128
EMPTY_RESULT_NOTICE = "К сожалению, на ваш поисковый запрос ничего не найдено."


class ETTLegalSearchError(ValueError):
    """Original search response has unsafe, missing or ambiguous evidence."""


@dataclass(frozen=True)
class ETTLegalSearchDocument:
    category: str
    identity_status: str
    issuing_body: str | None
    number: str | None
    observed_adoption_date: date | None
    observed_publication_date: date | None
    observed_entry_into_force_date: date | None
    title: str
    document_link: ETTListLink
    evidence: ETTListEvidence
    pdf_references: tuple[ETTLegalAttachmentReference, ...]
    unsupported_references: tuple[ETTLegalAttachmentReference, ...]
    issues: tuple[str, ...]
    primary_body_verified: bool = field(default=False, init=False)
    legal_dates_verified: bool = field(default=False, init=False)


@dataclass(frozen=True)
class ETTLegalSearch:
    source_url: str
    source_sha256: str
    size_bytes: int
    observed_query: str
    requested_page_literal: int | None
    documents: tuple[ETTLegalSearchDocument, ...]
    observed_identity_count: int
    pagination_links: tuple[ETTListLink, ...]
    empty_result_notice: bool
    reported_result_count: None = field(default=None, init=False)
    all_pages_captured: bool = field(default=False, init=False)
    document_absence_verified: bool = field(default=False, init=False)
    legal_inventory_complete: bool = field(default=False, init=False)


def validate_search_result_url(url: str) -> tuple[str, int | None]:
    """Validate supplied canonical q URL plus an observed optional page suffix.

    Validation authorizes no fetch and generates no URL. Ordinary ETT source
    validators retain their query-free contract.
    """
    try:
        validate_portal_search_page_url(url)
    except OfficialTransportError:
        raise ETTLegalSearchError("search URL is outside the observed public form") from None
    page = None
    base = url
    if "&PAGEN_1=" in url:
        base, suffix = url.rsplit("&PAGEN_1=", 1)
        page = int(suffix)
    query = parse_qsl(urlsplit(base).query, encoding="utf-8", errors="strict")[0][1]
    return query, page


def parse_legal_search(raw: bytes, page_url: str) -> ETTLegalSearch:
    """Parse original HTML without fetching, executing scripts or inferring dates."""
    query, requested_page = validate_search_result_url(page_url)
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_INDEX_BYTES:
        raise ETTLegalSearchError("search requires bounded original HTML bytes")
    try:
        source = raw.decode("utf-8-sig", errors="strict")
    except UnicodeError:
        raise ETTLegalSearchError("search HTML must be valid UTF-8") from None
    if "\x00" in source or re.search(r"<!\s*(?:ENTITY|DOCTYPE[^>]*\[)", source, re.I):
        raise ETTLegalSearchError("search HTML contains an invalid declaration")
    if not re.search(r"<html(?:\s|>)", source, re.I) or not re.search(r"</html\s*>\s*$", source, re.I):
        raise ETTLegalSearchError("search HTML is incomplete")
    guard = _AttachmentGuard()
    try:
        guard.feed(source)
        guard.close()
        guard.verify()
    except ETTIndexError:
        raise ETTLegalSearchError("search HTML structure is invalid") from None
    soup = BeautifulSoup(source, "html.parser")
    if len(soup.find_all("html")) != 1 or len(soup.find_all("body")) != 1 or soup.find("base"):
        raise ETTLegalSearchError("search document structure is ambiguous")
    if len(soup.find_all("title")) != 1 or _text(soup.title) != "Правовой портал":
        raise ETTLegalSearchError("search portal identity is missing")
    try:
        form = _one(soup.body, "form.SearchForm._documents")
        if form.get("action") != "/documents/search/" or form.get("method", "get").lower() != "get":
            raise ETTLegalSearchError("search form differs from the observed public GET form")
        inputs = [i for i in form.find_all("input") if i.get("name") == "q" and _visible(i)]
        if len(inputs) != 1 or inputs[0].get("value") != query:
            raise ETTLegalSearchError("search query echo is missing or disagrees with the request")
        container = _one(soup.body, ".DocSearchResult_Items")
    except ETTLegalListError:
        raise ETTLegalSearchError("search form or result container is ambiguous") from None
    rows = [r for r in container.select(".DocSearchResult_Item") if _visible(r)]
    if len(rows) > MAX_SEARCH_ROWS:
        raise ETTLegalSearchError("search exceeds its row bound")
    notices = [n for n in soup.select(".notetext") if _visible(n) and _text(n) == EMPTY_RESULT_NOTICE]
    if (not rows and len(notices) != 1) or (rows and notices):
        raise ETTLegalSearchError("search rows and empty-result notice are inconsistent")
    anchors = soup.body.find_all("a")
    positions = {id(a): n for n, a in enumerate(anchors, 1)}
    def locator(a):
        return f"html:a:{positions[id(a)]}:line:{a.sourceline}:column:{a.sourcepos}"
    documents = []
    seen_urls = set()
    for row_number, row in enumerate(rows, 1):
        if row.find_parent(class_="DocSearchResult_Item") is not None:
            raise ETTLegalSearchError("nested search rows are ambiguous")
        try:
            category = _text(_one(row, ".DocSearchResult_Item__Date"))
            anchor = _one(row, ".DocSearchResult_Item__Link")
            label = _text(anchor)
            title = _text(_one(row, ".DocSearchResult_Item__Text"))
            href = _href(anchor)
            dates = _one(row, ".DocSearchResult_Item__Dates")
        except ETTLegalListError:
            raise ETTLegalSearchError("search row fields are missing or ambiguous") from None
        if not category or not label or not title or max(map(len, (category, label, title))) > 32_768:
            raise ETTLegalSearchError("search row text is missing or oversized")
        target = urljoin(page_url, href)
        try:
            validate_source_url(target, allow_portal=True)
        except ETTIndexError:
            raise ETTLegalSearchError("search document URL is unsafe") from None
        if urlsplit(target).netloc != "docs.eaeunion.org" or not re.fullmatch(r"/documents/[1-9][0-9]*/[1-9][0-9]*/", urlsplit(target).path):
            raise ETTLegalSearchError("search document URL is outside modern portal paths")
        if target in seen_urls:
            raise ETTLegalSearchError("search repeats the same document URL ambiguously")
        seen_urls.add(target)
        fields, issues = {}, []
        for node in dates.find_all("div"):
            if node.find("div") is not None or not _visible(node) or not _text(node):
                continue
            value = _text(node)
            match = re.fullmatch(r"(Дата принятия документа|Дата опубликования документа|Дата вступления в силу): (.+)", value)
            if match is None:
                issues.append("unsupported_date_metadata")
                continue
            if match[1] in fields:
                raise ETTLegalSearchError("search date metadata is duplicated")
            try:
                fields[match[1]] = _date_literal(match[2])
            except ETTLegalListError:
                fields[match[1]] = None
                issues.append("unparsed_date_literal")
        adopted = fields.get("Дата принятия документа")
        cat = _CATEGORY.fullmatch(category)
        identity = _IDENTITY.fullmatch(label)
        body = number = None
        status = "outside_supported_decision_category"
        if cat:
            status = "unresolved_decision_identity"
            if identity and identity[1] == ("Коллегии" if cat[1] == "Коллегия" else "Совета") and adopted and adopted.year == int(cat[2]):
                status = "observed_decision_identity"
                body = "collegium" if cat[1] == "Коллегия" else "council"
                number = identity[2]
            else:
                issues.append("decision_identity_or_adoption_metadata_conflict")
        pdfs, unsupported = [], []
        for attachment in row.find_all("a", href=True):
            if attachment is anchor or not _visible(attachment):
                continue
            try:
                ahref = _href(attachment)
            except ETTLegalListError:
                raise ETTLegalSearchError("search attachment href is invalid") from None
            probe = unquote(ahref).strip()
            if "/upload/iblock/" not in probe and not re.search(r"\.(?:pdf|docx?|zip|xlsx?|rtf)(?:$|[?#])", probe, re.I):
                continue
            try:
                aurl = _attachment_target(ahref, page_url)
            except ETTLegalAttachmentError:
                raise ETTLegalSearchError("search attachment URL is unsafe") from None
            literal = guard.href_literals.get((attachment.sourceline, attachment.sourcepos))
            if literal is None:
                raise ETTLegalSearchError("search attachment has no attributable href")
            extension = unquote(urlsplit(aurl).path).rsplit(".", 1)[-1].lower()
            supported = extension == "pdf"
            ref = ETTLegalAttachmentReference(aurl, ahref, literal, _text(attachment), locator(attachment), _FILE_TYPES.get(extension, "application/octet-stream"), "legal_attachment_pdf" if supported else "unsupported_legal_attachment")
            (pdfs if supported else unsupported).append(ref)
            if len(pdfs) + len(unsupported) > MAX_ROW_REFERENCES:
                raise ETTLegalSearchError("search row attachment count exceeds its bound")
        text = _text(row)
        if len(text) > 128 * 1024:
            raise ETTLegalSearchError("search row evidence exceeds its bound")
        documents.append(ETTLegalSearchDocument(
            category, status, body, number, adopted, fields.get("Дата опубликования документа"), fields.get("Дата вступления в силу"), title,
            ETTListLink(target, href, label, locator(anchor)),
            ETTListEvidence(f"html:search-row:{row_number}:line:{row.sourceline}:column:{row.sourcepos}", text, hashlib.sha256(text.encode()).hexdigest()),
            tuple(pdfs), tuple(unsupported), tuple(issues),
        ))
    pagination = []
    for anchor in anchors:
        href = anchor.get("href")
        if not isinstance(href, str) or "PAGEN_" not in href or not _visible(anchor):
            continue
        try:
            target = urljoin(page_url, _href(anchor))
        except ETTLegalListError:
            raise ETTLegalSearchError("search pagination href is unsafe") from None
        observed_query, observed_page = validate_search_result_url(target)
        if observed_query != query or observed_page is None:
            raise ETTLegalSearchError("pagination changes the observed search query")
        pagination.append(ETTListLink(target, href, _text(anchor), locator(anchor)))
    return ETTLegalSearch(
        page_url, hashlib.sha256(raw).hexdigest(), len(raw), query, requested_page,
        tuple(documents), sum(d.identity_status == "observed_decision_identity" for d in documents), tuple(pagination), bool(notices),
    )
