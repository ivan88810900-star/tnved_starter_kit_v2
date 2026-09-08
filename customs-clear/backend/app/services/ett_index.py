"""Discover retained links from the official EEC ETT index, without guessing URLs.

This parser proves the shape of supplied HTML, not its network provenance or the
completeness/current legal effect of the amendment inventory. Dates in the page or
filenames are retained as source text and never become effective dates. Downloading,
PDF interpretation, approval and serving are separate stages.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

from app.services.ett_manifest import EXPECTED_CHAPTERS

INDEX_URL = "https://eec.eaeunion.org/comission/department/catr/ett/"
MAX_INDEX_BYTES = 4 * 1024 * 1024
MAX_INDEX_ELEMENTS = 50_000
_EEC_PATHS = ("/comission/department/catr/ett/", "/upload/files/catr/ett/")
_ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u200d\ufeff"))
_GROUP = re.compile(r"Группа\s+([0-9]{2})", re.IGNORECASE)


class ETTIndexError(ValueError):
    """The index does not satisfy the bounded discovery contract."""


class _StructureGuard(HTMLParser):
    """Reject malformed required structures before a forgiving DOM parser repairs them."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.counts = {tag: [0, 0] for tag in ("html", "body", "a", "table", "tr", "td", "th")}
        self.structure: list[str] = []
        self.depth: list[str] = []
        self.elements = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.elements += 1
        if self.elements > MAX_INDEX_ELEMENTS:
            raise ETTIndexError("index document contains too many elements")
        if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            self.depth.append(tag)
        if len(self.depth) > 256:
            raise ETTIndexError("index document nesting exceeds its bound")
        if tag in self.counts:
            self.counts[tag][0] += 1
            self.structure.append(tag)
        if tag == "a" and sum(name == "href" for name, _ in attrs) > 1:
            raise ETTIndexError("anchor contains duplicate href attributes")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.counts:
            if not self.structure or self.structure.pop() != tag:
                raise ETTIndexError("required HTML structures are improperly nested")
            self.counts[tag][1] += 1
        if tag in self.depth:
            index = len(self.depth) - 1 - self.depth[::-1].index(tag)
            del self.depth[index:]

    def verify(self) -> None:
        if any(start != end for start, end in self.counts.values()):
            raise ETTIndexError("required HTML structures have unmatched closing tags")


@dataclass(frozen=True)
class ETTIndexReference:
    role: str
    url: str
    href: str
    text: str
    locator: str
    chapter: str | None = None


@dataclass(frozen=True)
class ETTIndexDiscovery:
    source_url: str
    source_sha256: str
    size_bytes: int
    chapters: tuple[ETTIndexReference, ...]
    nomenclature_notes: ETTIndexReference
    tariff_notes: ETTIndexReference
    additional_documents: tuple[ETTIndexReference, ...]
    amendment_links: tuple[ETTIndexReference, ...]
    declaration_text: str
    declaration_sha256: str
    amendment_inventory_complete: bool = field(default=False, init=False)

    @property
    def documents(self) -> tuple[ETTIndexReference, ...]:
        """All PDF references in scope, including unlabeled/older extra links."""
        return self.chapters + (self.nomenclature_notes, self.tariff_notes) + self.additional_documents


def validate_source_url(url: str, *, allow_portal: bool = False) -> str:
    """Validate one absolute retained URL; no redirects or network are performed.

    Spaces/Unicode in original HTML href paths may be percent-encoded before this
    call. Encoded separators, traversal and ambiguous double encoding are rejected.
    """
    if not isinstance(url, str) or not 1 <= len(url) <= 4096:
        raise ETTIndexError("source URL is missing or exceeds its bound")
    if any(ord(c) < 33 or ord(c) == 127 for c in url) or any(c in url for c in "\\?#"):
        raise ETTIndexError("source URL contains whitespace, controls, query, fragment or backslash")
    try:
        parsed = urlsplit(url)
    except ValueError as exc:
        raise ETTIndexError("source URL is malformed") from exc
    hosts = {"eec.eaeunion.org", "docs.eaeunion.org"} if allow_portal else {"eec.eaeunion.org"}
    if parsed.scheme != "https" or parsed.netloc not in hosts or not parsed.path.startswith("/"):
        raise ETTIndexError("source URL must use an exact official HTTPS host without a port or credentials")
    if re.search(r"%(?![0-9a-fA-F]{2})", parsed.path) or re.search(r"%(?:2f|5c|25|3f|23)", parsed.path, re.I):
        raise ETTIndexError("source URL has invalid or ambiguous path encoding")
    try:
        decoded = unquote(parsed.path, encoding="utf-8", errors="strict")
    except UnicodeError as exc:
        raise ETTIndexError("source URL has invalid UTF-8 path encoding") from exc
    if any(ord(c) < 32 or ord(c) == 127 for c in decoded) or any(p in {".", ".."} for p in decoded.split("/")):
        raise ETTIndexError("source URL has encoded controls or traversal")
    if "//" in decoded:
        raise ETTIndexError("source URL contains an ambiguous repeated separator")
    if parsed.netloc == "eec.eaeunion.org":
        if not decoded.startswith(_EEC_PATHS):
            raise ETTIndexError("EEC reference is outside the ETT document paths")
    elif not re.fullmatch(r"/(?:docs/ru-ru/[A-Za-z0-9_/-]+|documents/[0-9]+/[0-9]+/?)", decoded):
        raise ETTIndexError("legal portal reference is outside the document paths")
    return url


def _text(node: Tag) -> str:
    return " ".join(node.get_text(" ", strip=True).translate(_ZERO_WIDTH).split())


def _visible(node: Tag | NavigableString) -> bool:
    parent = node if isinstance(node, Tag) else node.parent
    while isinstance(parent, Tag):
        if parent.name in {"script", "style", "template", "noscript"} or parent.has_attr("hidden"):
            return False
        if str(parent.get("aria-hidden", "")).lower() == "true":
            return False
        if re.search(r"(?:display\s*:\s*none|visibility\s*:\s*hidden)", str(parent.get("style", "")), re.I):
            return False
        parent = parent.parent
    return True


def _reference(anchor: Tag, number: int, role: str, chapter: str | None = None) -> ETTIndexReference:
    href = anchor.get("href")
    if not isinstance(href, str) or not href.strip():
        raise ETTIndexError("required document anchor has no href")
    target = href.strip()
    # Reject rather than let urljoin erase traversal or urlsplit erase controls.
    if any(ord(c) < 32 or ord(c) == 127 for c in target) or "\\" in target or "?" in target or "#" in target:
        raise ETTIndexError("document href contains controls, query, fragment or backslash")
    if re.search(r"(?:^|/)(?:\.|\.\.)(?:/|$)", target):
        raise ETTIndexError("document href contains traversal")
    absolute = urljoin(INDEX_URL, target)
    parsed = urlsplit(absolute)
    absolute = urlunsplit((parsed.scheme, parsed.netloc, quote(parsed.path, safe="/%:@!$&'()*+,;=-._~"), parsed.query, parsed.fragment))
    validate_source_url(absolute, allow_portal=role == "amendment_reference")
    if role != "amendment_reference" and not urlsplit(absolute).path.lower().endswith(".pdf"):
        raise ETTIndexError("required ETT document is not a PDF reference")
    return ETTIndexReference(
        role=role, url=absolute, href=href, text=_text(anchor),
        locator=f"html:a:{number}:line:{anchor.sourceline}:column:{anchor.sourcepos}", chapter=chapter,
    )


def parse_index(html_bytes: bytes) -> ETTIndexDiscovery:
    """Require exact chapter topology and labeled notes in supplied UTF-8 HTML.

    The original-byte SHA plus deterministic anchor locators bind discovery to its
    input. ``declaration_text`` retains the visible text (including whitespace),
    not an inferred list of legally effective amendments. The full HTML must also
    be kept by the caller. Repeated chapter/note links are rejected; supplemental
    links are retained individually, even if they repeat another target URL.
    """
    if type(html_bytes) is not bytes or not 1 <= len(html_bytes) <= MAX_INDEX_BYTES:
        raise ETTIndexError("index requires bounded original HTML bytes")
    try:
        source = html_bytes.decode("utf-8-sig", errors="strict")
    except UnicodeError as exc:
        raise ETTIndexError("index must be valid UTF-8 HTML") from exc
    if "\x00" in source or re.search(r"<!\s*(?:ENTITY|DOCTYPE[^>]*\[)", source, re.I):
        raise ETTIndexError("index contains NUL or a non-HTML entity declaration")
    if not re.search(r"<html(?:\s|>)", source, re.I) or not re.search(r"</html\s*>\s*$", source, re.I):
        raise ETTIndexError("index is not a complete HTML document")
    guard = _StructureGuard()
    guard.feed(source)
    guard.close()
    guard.verify()
    soup = BeautifulSoup(source, "html.parser")
    if len(soup.find_all(True)) > MAX_INDEX_ELEMENTS or len(soup.find_all("html")) != 1 or len(soup.find_all("body")) != 1:
        raise ETTIndexError("index document structure is missing, duplicated or oversized")
    if soup.find("base"):
        raise ETTIndexError("index must not override its fixed document base URL")
    body = soup.body
    assert body is not None
    headings = [h for h in body.find_all("h1") if _visible(h) and _text(h) == "ТН ВЭД ЕАЭС и ЕТТ ЕАЭС"]
    if len(headings) != 1:
        raise ETTIndexError("official ETT index heading is missing or ambiguous")
    all_anchors = body.find_all("a")
    positions = {id(anchor): number for number, anchor in enumerate(all_anchors, 1)}
    chapters: dict[str, ETTIndexReference] = {}
    chapter_rows: list[Tag] = []
    used: set[int] = set()
    for row in body.find_all("tr"):
        if not _visible(row):
            continue
        cells = row.find_all(["td", "th"], recursive=False)
        if not cells:
            continue
        label = _text(cells[0])
        if not re.match(r"Группа\b", label, re.I):
            continue
        match = _GROUP.fullmatch(label)
        if match is None or match[1] not in EXPECTED_CHAPTERS:
            raise ETTIndexError("chapter row has an invalid or reserved chapter label")
        chapter = match[1]
        anchors = [a for a in row.find_all("a") if _visible(a)]
        if chapter in chapters or len(cells) < 2 or any(_text(c) or c.find("a") for c in cells[2:]) or len(anchors) != 1 or not _text(anchors[0]):
            raise ETTIndexError("chapter is duplicated or its document row is ambiguous")
        anchor = anchors[0]
        if anchor.find_parent(["td", "th"]) is not cells[1]:
            raise ETTIndexError("chapter document is not in the description cell")
        chapters[chapter] = _reference(anchor, positions[id(anchor)], "chapter", chapter)
        chapter_rows.append(row)
        used.add(id(anchor))
    if tuple(sorted(chapters)) != EXPECTED_CHAPTERS:
        raise ETTIndexError("index must contain exactly chapters 01–76 and 78–97")
    if len({r.url for r in chapters.values()}) != len(EXPECTED_CHAPTERS):
        raise ETTIndexError("different chapters must not share one document URL")
    # Scope is the smallest shared ancestor containing the heading, all chapter
    # rows and the two labeled note links. No site-wide footer is an amendment.
    note_patterns = {
        "nomenclature_notes": r"Примечания к единой Товарной номенклатуре внешнеэкономической деятельности Евразийского экономического союза",
        "tariff_notes": r"Примечания к Единому таможенному тарифу Евразийского экономического союза",
    }
    notes: dict[str, ETTIndexReference] = {}
    note_anchors: list[Tag] = []
    for role, pattern in note_patterns.items():
        matches = [a for a in all_anchors if _visible(a) and re.fullmatch(pattern, _text(a), re.I)]
        if len(matches) != 1:
            raise ETTIndexError("global note link is missing or ambiguous")
        anchor = matches[0]
        notes[role] = _reference(anchor, positions[id(anchor)], role)
        note_anchors.append(anchor)
        used.add(id(anchor))
    required = (headings[0], *chapter_rows, *note_anchors)
    scope = headings[0].parent
    while isinstance(scope, Tag) and not all(any(p is scope for p in node.parents) for node in required):
        scope = scope.parent
    if not isinstance(scope, Tag):
        raise ETTIndexError("cannot establish a common index content scope")
    # Bound legal declaration to content preceding the first chapter table. The
    # raw index remains primary evidence when retained whitespace is normalized
    # by an HTML entity decoder. No publication or effective date is assigned.
    preceding: list[str] = []
    first_row = chapter_rows[0]
    for node in scope.descendants:
        if node is first_row:
            break
        if isinstance(node, NavigableString) and not isinstance(node, Comment) and _visible(node):
            preceding.append(str(node))
    prefix = "\n".join(preceding)
    starts = list(re.finditer(r"УТВЕРЖДЕНЫ", prefix, re.I))
    if len(starts) != 1:
        raise ETTIndexError("index approval declaration is missing or ambiguous")
    declaration = prefix[starts[0].start():]
    if not re.search(r"в\s+ред\.", declaration, re.I) or not re.search(r"решени[йя]\s+Коллегии", declaration, re.I) or not re.search(r"решений\s+Совета", declaration, re.I):
        raise ETTIndexError("index revision declaration is missing or unsupported")
    if len(declaration) > 250_000:
        raise ETTIndexError("index revision declaration exceeds its bound")
    extra: list[ETTIndexReference] = []
    amendments: list[ETTIndexReference] = []
    for anchor in scope.find_all("a"):
        if id(anchor) in used or not _visible(anchor):
            continue
        href = anchor.get("href")
        if not isinstance(href, str):
            continue
        target = href.strip()
        parsed = urlsplit(urljoin(INDEX_URL, target))
        if parsed.path.lower().endswith(".pdf"):
            extra.append(_reference(anchor, positions[id(anchor)], "supplemental_pdf"))
        elif parsed.hostname == "docs.eaeunion.org" and parsed.path != "/":
            amendments.append(_reference(anchor, positions[id(anchor)], "amendment_reference"))
    required_urls = [r.url for r in chapters.values()] + [r.url for r in notes.values()]
    if len(set(required_urls)) != len(required_urls):
        raise ETTIndexError("required chapters and global notes must have distinct URLs")
    return ETTIndexDiscovery(
        source_url=INDEX_URL, source_sha256=hashlib.sha256(html_bytes).hexdigest(), size_bytes=len(html_bytes),
        chapters=tuple(chapters[c] for c in EXPECTED_CHAPTERS), nomenclature_notes=notes["nomenclature_notes"],
        tariff_notes=notes["tariff_notes"], additional_documents=tuple(extra), amendment_links=tuple(amendments),
        declaration_text=declaration, declaration_sha256=hashlib.sha256(declaration.encode("utf-8")).hexdigest(),
    )
