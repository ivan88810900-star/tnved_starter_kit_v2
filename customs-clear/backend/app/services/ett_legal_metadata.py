"""Source-bound metadata observations from retained EAEU legal-portal HTML.

The portal's labelled publication date is separate from page clocks, retrieval
timestamps and filenames. It remains an observed metadata value, not independent
proof of official publication or a verified legal effective date. No attachment
is fetched and no date arithmetic or fallback between fields is performed.
"""
from __future__ import annotations

from datetime import date
import hashlib
import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup, NavigableString

from app.services.ett_index import ETTIndexError, MAX_INDEX_BYTES, _StructureGuard, _visible, validate_source_url

MAX_METADATA_CONTAINERS = 8
MAX_METADATA_ROWS = 256
MAX_FIELD_TEXT = 128 * 1024
MAX_ROW_CELLS = 16
_FIELDS = {
    "Полный заголовок документа": "full_title",
    "Короткий заголовок документа": "short_title",
    "Номер документа": "document_number",
    "Вид документа": "document_type",
    "Дата принятия документа": "adoption_date",
    "Дата опубликования": "publication_date",
    "Дата вступления в силу": "entry_into_force_date_metadata",
    "Комментарий": "comment",
}
_DATE_FIELDS = {"adoption_date", "publication_date", "entry_into_force_date_metadata"}


class ETTLegalMetadataError(ValueError):
    """The original page cannot provide bounded, attributable metadata evidence."""


class _MetadataGuard(_StructureGuard):
    def __init__(self):
        super().__init__()
        self.counts.update({"div": [0, 0], "title": [0, 0]})

    def handle_starttag(self, tag, attrs):
        if len([key for key, _ in attrs if key == "class"]) > 1:
            raise ETTIndexError("metadata element has duplicate class attributes")
        super().handle_starttag(tag, attrs)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _raw_text(node) -> str:
    # Decoded visible text-node content, retaining source whitespace. This is a
    # declared DOM projection, not a claim that serialized HTML was copied.
    return "".join(str(child) for child in node.descendants
                   if type(child) is NavigableString and _visible(child))


def _evidence(node, role: str, position: int) -> dict:
    raw = _raw_text(node)
    if len(raw) > MAX_FIELD_TEXT:
        raise ETTLegalMetadataError("metadata text exceeds its bound")
    return {"locator": f"html:{role}:{position}:line:{node.sourceline}:column:{node.sourcepos}",
            "raw_text": raw, "raw_text_sha256": _sha(raw),
            "text": " ".join(raw.split())}


def _date_literal(value: str) -> str | None:
    if re.fullmatch(r"[0-9]{2}\.[0-9]{2}\.[0-9]{4}", value) is None:
        return None
    try:
        return date(int(value[6:10]), int(value[3:5]), int(value[:2])).isoformat()
    except ValueError:
        return None


def parse_legal_metadata(raw: bytes, page_url: str) -> dict:
    """Retain every visible metadata row and diagnose missing/ambiguous fields.

    Source locators point to original HTML line/column positions. ``raw_text``
    concatenates decoded visible descendant text nodes without inserting spaces;
    ``text`` is its whitespace-normalized display projection. The original byte
    hash must remain available to replay either projection.
    """
    try:
        validate_source_url(page_url, allow_portal=True)
        if urlsplit(page_url).netloc != "docs.eaeunion.org":
            raise ETTIndexError("metadata source must be a legal-portal document")
        if type(raw) is not bytes or not 0 < len(raw) <= MAX_INDEX_BYTES:
            raise ETTIndexError("metadata requires bounded original bytes")
        source = raw.decode("utf-8-sig", errors="strict")
        if "\x00" in source or re.search(r"<!\s*(?:ENTITY|DOCTYPE[^>]*\[)", source, re.I):
            raise ETTIndexError("metadata has an invalid declaration")
        if not re.search(r"<html(?:\s|>)", source, re.I) or not re.search(r"</html\s*>\s*$", source, re.I):
            raise ETTIndexError("metadata HTML is incomplete")
        guard = _MetadataGuard()
        guard.feed(source)
        guard.close()
        guard.verify()
    except (ETTIndexError, UnicodeError) as exc:
        raise ETTLegalMetadataError("invalid retained legal-portal HTML or URL") from exc
    soup = BeautifulSoup(source, "html.parser")
    if len(soup.find_all("html")) != 1 or len(soup.find_all("body")) != 1 or len(soup.find_all("title")) != 1 or soup.find("base"):
        raise ETTLegalMetadataError("ambiguous metadata document structure")
    brand = [node for node in soup.select(".Header_Bottom__Title") if _visible(node)
             and " ".join(_raw_text(node).split()) == "Правовой портал"]
    boxes = [node for node in soup.select(".Box_Title") if _visible(node)
             and " ".join(_raw_text(node).split()) == "Информация о документе"]
    if len(brand) != 1 or not boxes:
        raise ETTLegalMetadataError("legal-portal document-information shape is missing")
    infos = [node for node in soup.select(".DocDetail_Info") if _visible(node)]
    if len(infos) > MAX_METADATA_CONTAINERS:
        raise ETTLegalMetadataError("metadata container bound exceeded")
    rows, unknown, problems = [], [], []
    fields = {name: [] for name in _FIELDS.values()}
    if len(infos) != 1:
        problems.append("metadata_container_missing" if not infos else "metadata_container_ambiguous")
    # Nested rows/containers cannot silently inherit another row's value.
    seen = set()
    for container_position, info in enumerate(infos, 1):
        candidates = [node for node in info.select(".DocDetail_Row") if _visible(node)]
        for row in candidates:
            if id(row) in seen:
                continue
            seen.add(id(row))
            if len(rows) >= MAX_METADATA_ROWS:
                raise ETTLegalMetadataError("metadata row bound exceeded")
            position = len(rows) + 1
            labels = [node for node in row.select(".DocDetail_Col._title") if _visible(node)]
            values = [node for node in row.select(".DocDetail_Col._value") if _visible(node)]
            if len(labels) + len(values) > MAX_ROW_CELLS:
                raise ETTLegalMetadataError("metadata row cell bound exceeded")
            observation = {"row_index": position, "container_index": container_position,
                           "row_evidence": _evidence(row, "metadata-row", position),
                           "labels": [_evidence(node, "metadata-label", i) for i, node in enumerate(labels, 1)],
                           "values": [_evidence(node, "metadata-value", i) for i, node in enumerate(values, 1)],
                           "issues": []}
            if len(labels) != 1 or len(values) != 1:
                observation["issues"].append("metadata_cell_cardinality_ambiguous")
            if any(parent in infos for parent in info.parents) or row.select(".DocDetail_Row"):
                observation["issues"].append("nested_metadata_structure")
            keys = {_FIELDS[label["text"]] for label in observation["labels"] if label["text"] in _FIELDS}
            for key in sorted(keys):
                fields[key].append(position)
            if not keys:
                unknown.append(position)
            rows.append(observation)
    field_results = {}
    for name, positions in fields.items():
        observations = [rows[i - 1] for i in positions]
        status, value, iso = "missing", None, None
        if observations:
            if len(observations) != 1 or len(infos) != 1 or observations[0]["issues"]:
                status = "ambiguous"
            else:
                value = observations[0]["values"][0]["text"]
                status = "observed" if value else "empty"
                if name in _DATE_FIELDS and value:
                    iso = _date_literal(value)
                    if iso is None:
                        status = "unresolved_date_literal"
        field_results[name] = {"status": status, "observation_rows": positions,
                               "observed_text": value, "observed_iso_date": iso,
                               "legal_semantics_verified": False}
    if unknown:
        problems.append("unknown_metadata_labels_retained")
    if any(row["issues"] for row in rows):
        problems.append("ambiguous_metadata_rows_retained")
    return {
        "schema_version": 1, "kind": "retained_legal_page_metadata_evidence",
        "source_url": page_url, "source_sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw),
        "text_projection": "raw_text concatenates exact decoded visible text nodes; text normalizes whitespace",
        "container_count": len(infos), "rows": rows, "fields": field_results,
        "unknown_row_indices": unknown, "issues": problems,
        "status": "review_required", "source_identity_verified": False,
        "official_publication_event_verified": False, "primary_body_identity_verified": False,
        "adoption_dates_verified": False, "effective_dates_verified": False,
        "legal_inventory_complete": False, "production_ready": False,
    }
