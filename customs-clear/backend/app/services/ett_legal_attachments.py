"""Discover attachments in retained legal-portal HTML; never infer legal effect.

The page hash and anchor locators bind references to supplied original bytes.
Neither document labels nor official-looking URLs attest network provenance,
completeness, attachment contents or a legally effective date. Unsupported files
remain explicit references instead of being silently counted as captured acts.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, NavigableString

from app.services.ett_index import (
    ETTIndexError, MAX_INDEX_BYTES, _StructureGuard, _text, _visible,
    validate_source_url,
)
from app.services.ett_transport import OfficialTransportError, validate_official_url

MAX_ATTACHMENT_REFERENCES = 256
_DOCUMENT_IDENTITY = re.compile(
    r"Решение\s+(?:Коллегии|Совета)\s+"
    r"(?:ЕЭК|Евразийской\s+экономической\s+комиссии)\s*№\s*[0-9]{1,6}(?![0-9])",
    re.I,
)
_FILE_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "doc": "application/msword",
    "zip": "application/zip",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "xls": "application/vnd.ms-excel",
    "rtf": "application/rtf",
}
_RAW_ATTRIBUTE = re.compile(
    r"([^\s=/>]+)(?:\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+)))?", re.I,
)


class ETTLegalAttachmentError(ValueError):
    """Retained HTML or its attachment references are unsafe or ambiguous."""


class _AttachmentGuard(_StructureGuard):
    def __init__(self) -> None:
        super().__init__()
        self.href_literals: dict[tuple[int, int], str | None] = {}

    def handle_starttag(self, tag, attrs):
        super().handle_starttag(tag, attrs)
        if tag == "a":
            lexical = re.sub(r"^<a\b", "", self.get_starttag_text(), count=1, flags=re.I)
            match = next((m for m in _RAW_ATTRIBUTE.finditer(lexical)
                          if m.group(1).lower() == "href"), None)
            self.href_literals[self.getpos()] = (
                next((part for part in match.groups()[1:] if part is not None), None)
                if match is not None else None
            )


@dataclass(frozen=True)
class ETTLegalAttachmentReference:
    url: str
    href: str
    raw_href: str
    text: str
    locator: str
    media_type: str
    role: str


@dataclass(frozen=True)
class ETTLegalAttachmentDiscovery:
    source_url: str
    source_sha256: str
    size_bytes: int
    document_identity: str
    identity_sha256: str
    documents: tuple[ETTLegalAttachmentReference, ...]
    unsupported_references: tuple[ETTLegalAttachmentReference, ...]
    legal_inventory_complete: bool = field(default=False, init=False)
    semantic_verified: bool = field(default=False, init=False)


def validate_attachment_url(url: str) -> str:
    """Allow only literal official legal-portal attachment paths, without I/O."""
    try:
        validate_official_url(url)
    except OfficialTransportError as exc:
        raise ETTLegalAttachmentError("attachment URL is not a safe official URL") from exc
    parsed = urlsplit(url)
    decoded = unquote(parsed.path, encoding="utf-8", errors="strict")
    if (
        parsed.netloc != "docs.eaeunion.org"
        or not decoded.startswith("/upload/iblock/")
        or "//" in decoded
        or not re.fullmatch(r"/upload/iblock/[^/]+/(?:[^/]+/)*[^/]+\.[A-Za-z0-9]+", decoded)
    ):
        raise ETTLegalAttachmentError("attachment is outside legal-portal file paths")
    return url


def _attachment_target(href: str, page_url: str) -> str:
    if not 1 <= len(href) <= 4096:
        raise ETTLegalAttachmentError("attachment href is missing or oversized")
    if (
        any(ord(c) < 32 or ord(c) == 127 for c in href)
        or any(c in href for c in "\\?#")
        or re.search(r"(?:^|/)(?:\.|\.\.)(?:/|$)", href.strip())
    ):
        raise ETTLegalAttachmentError("attachment href has controls, traversal or URL modifiers")
    target = href.strip()
    absolute = urljoin(page_url, target)
    parsed = urlsplit(absolute)
    absolute = urlunsplit((
        parsed.scheme, parsed.netloc,
        quote(parsed.path, safe="/%:@!$&'()*+,;=-._~"), parsed.query, parsed.fragment,
    ))
    return validate_attachment_url(absolute)


def parse_legal_attachments(raw: bytes, page_url: str) -> ETTLegalAttachmentDiscovery:
    """Retain visible PDF references and explicit unsupported attachment links.

    No attachment is fetched. Repeated links (language tabs/download buttons)
    remain individually attributable. Missing PDFs return an empty tuple and
    cannot confer completeness. Visible decision labels only identify page shape;
    dates in its title, metadata or filenames are never interpreted.
    """
    try:
        validate_source_url(page_url, allow_portal=True)
    except ETTIndexError as exc:
        raise ETTLegalAttachmentError("invalid legal-portal document URL") from exc
    if urlsplit(page_url).netloc != "docs.eaeunion.org":
        raise ETTLegalAttachmentError("document page must belong to the legal portal")
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_INDEX_BYTES:
        raise ETTLegalAttachmentError("legal portal requires bounded original HTML bytes")
    try:
        source = raw.decode("utf-8-sig", errors="strict")
    except UnicodeError as exc:
        raise ETTLegalAttachmentError("legal portal HTML must be valid UTF-8") from exc
    if "\x00" in source or re.search(r"<!\s*(?:ENTITY|DOCTYPE[^>]*\[)", source, re.I):
        raise ETTLegalAttachmentError("legal portal HTML contains an invalid entity declaration")
    if not re.search(r"<html(?:\s|>)", source, re.I) or not re.search(r"</html\s*>\s*$", source, re.I):
        raise ETTLegalAttachmentError("legal portal HTML document is incomplete")
    guard = _AttachmentGuard()
    try:
        guard.feed(source)
        guard.close()
        guard.verify()
    except ETTIndexError as exc:
        raise ETTLegalAttachmentError("legal portal HTML structure is invalid") from exc
    soup = BeautifulSoup(source, "html.parser")
    if len(soup.find_all("html")) != 1 or len(soup.find_all("body")) != 1 or soup.find("base"):
        raise ETTLegalAttachmentError("legal portal HTML has an ambiguous document structure")
    body = soup.body
    visible_text = " ".join(" ".join(
        " ".join(str(node).split()) for node in body.descendants
        if type(node) is NavigableString and _visible(node)
    ).split())
    identity_fields = re.findall(
        r"Короткий заголовок документа\s+(.{1,500}?)\s+Вид документа", visible_text,
    )
    identities = _DOCUMENT_IDENTITY.findall(identity_fields[0]) if len(identity_fields) == 1 else []
    if (
        any(label not in visible_text for label in (
            "Правовой портал", "Информация о документе", "Номер документа",
        ))
        or len(identities) != 1
    ):
        raise ETTLegalAttachmentError("legal portal decision identity is missing or ambiguous")
    identity = next(iter(identities))
    documents: list[ETTLegalAttachmentReference] = []
    unsupported: list[ETTLegalAttachmentReference] = []
    for number, anchor in enumerate(body.find_all("a"), 1):
        if not _visible(anchor):
            continue
        href = anchor.get("href")
        if not isinstance(href, str):
            continue
        # Inspect candidate links before joining, so unsafe URL modifiers cannot
        # hide a referenced PDF and urljoin cannot erase path traversal.
        probe = unquote(href).lower().strip()
        if "/upload/iblock/" not in probe and not re.search(
            r"\.(?:pdf|docx?|zip|xlsx?|rtf)(?:$|[?#])", probe,
        ):
            continue
        target = _attachment_target(href, page_url)
        extension = unquote(urlsplit(target).path).rsplit(".", 1)[-1].lower()
        supported = extension == "pdf"
        literal = guard.href_literals.get((anchor.sourceline, anchor.sourcepos))
        if literal is None:
            raise ETTLegalAttachmentError("attachment has no attributable literal href")
        text = _text(anchor)
        if len(text) > 8192:
            raise ETTLegalAttachmentError("attachment label exceeds its bound")
        reference = ETTLegalAttachmentReference(
            url=target, href=href, raw_href=literal, text=text,
            locator=f"html:a:{number}:line:{anchor.sourceline}:column:{anchor.sourcepos}",
            media_type=_FILE_TYPES.get(extension, "application/octet-stream"),
            role="legal_attachment_pdf" if supported else "unsupported_legal_attachment",
        )
        (documents if supported else unsupported).append(reference)
        if len(documents) + len(unsupported) > MAX_ATTACHMENT_REFERENCES:
            raise ETTLegalAttachmentError("legal attachment reference count exceeds its bound")
    return ETTLegalAttachmentDiscovery(
        source_url=page_url, source_sha256=hashlib.sha256(raw).hexdigest(),
        size_bytes=len(raw), document_identity=identity,
        identity_sha256=hashlib.sha256(identity.encode()).hexdigest(),
        documents=tuple(documents), unsupported_references=tuple(unsupported),
    )
