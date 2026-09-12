"""Independent detail-page corroboration, disconnected from production paths.

An unresolved short title is retained verbatim. The candidate instead requires
agreement between explicit category/number/adoption fields and a descriptive PDF
anchor in this document's primary attachment group. Original search evidence is
replayed; neither a caller's claimed verification nor a filename is evidence.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import date
import hashlib
import re
from urllib.parse import unquote, urlsplit

from bs4 import BeautifulSoup

from app.services.ett_index import _visible, validate_source_url
from app.services.ett_legal_attachments import _AttachmentGuard, _EEC_DECISION_CATEGORY, _attachment_target
from app.services.ett_legal_metadata import parse_legal_metadata
from app.services.ett_legal_search import parse_legal_search

MAX_PDF_REFERENCES = 128
MAX_ANCHOR_TEXT = 8192
_MONTHS = {"января": 1, "февраля": 2, "марта": 3, "апреля": 4,
           "мая": 5, "июня": 6, "июля": 7, "августа": 8,
           "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12}
_ORGANIZATION = r"(?:ЕЭК|Евразийской экономической комиссии)"
_TITLE = re.compile(r"Решение (Коллегии|Совета) (?:" + _ORGANIZATION + r" )?№\s*([1-9][0-9]{0,5})(?!\w)")
_UNRESOLVED_TITLE_SHAPE = re.compile(r"Решение [А-Яа-яЁё]{1,40} " + _ORGANIZATION + r" №\s*([1-9][0-9]{0,5})")
_DESCRIPTION = re.compile(
    r"Решение (Коллегии|Совета) (?:" + _ORGANIZATION + r" )?№\s*([1-9][0-9]{0,5}) от "
    r"(?P<date>[0-9]{2}\.[0-9]{2}\.[0-9]{4}|[0-9]{1,2} (?:" + "|".join(_MONTHS) +
    r") [0-9]{4})(?: (?:г\.?|года))?",
)


class ETTDetailIdentityError(ValueError):
    """Original sources do not support this narrow corroboration contract."""


def _require(value: bool, reason: str) -> None:
    if not value:
        raise ETTDetailIdentityError(reason)


def _identity(body: str, adopted: str, number: str) -> dict:
    return {"issuing_body": body, "adoption_date": adopted, "number": number}


def _body(value: str) -> str:
    return "collegium" if value in ("Коллегия", "Коллегии") else "council"


def _expected(value: dict) -> dict:
    _require(type(value) is dict and set(value) == {"issuing_body", "adoption_date", "number"}, "invalid_expected_identity")
    _require(value["issuing_body"] in ("collegium", "council"), "invalid_expected_identity")
    _require(isinstance(value["adoption_date"], str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value["adoption_date"]) is not None,
             "invalid_expected_identity")
    date.fromisoformat(value["adoption_date"])
    _require(isinstance(value["number"], str) and re.fullmatch(r"[1-9][0-9]{0,5}", value["number"]) is not None,
             "invalid_expected_identity")
    return dict(value)


def _title_status(text: str, expected: dict, source: str) -> str:
    # A recognized contradictory prefix is still a contradiction when trailing
    # text prevents a full match. This never fuzzy-matches an unknown body token.
    recognized = list(_TITLE.finditer(text))
    for match in recognized:
        _require(_body(match[1]) == expected["issuing_body"] and match[2] == expected["number"],
                 f"contradictory_{source}_title")
    if len(recognized) == 1 and recognized[0].span() == (0, len(text)):
        return "strict_identity_agrees"
    _require(not recognized and _UNRESOLVED_TITLE_SHAPE.fullmatch(text) is not None,
             f"unsupported_{source}_title_shape")
    marker = _UNRESOLVED_TITLE_SHAPE.fullmatch(text)
    _require(marker[1] == expected["number"], f"contradictory_{source}_title_number")
    return "unresolved_original_spelling"


def _category(value: str, expected: dict, source: str) -> None:
    match = _EEC_DECISION_CATEGORY.fullmatch(value)
    _require(match is not None and _body(match[1]) == expected["issuing_body"]
             and match[2] == expected["adoption_date"][:4], f"contradictory_or_unsupported_{source}_category")


def _text(node) -> str:
    from bs4 import NavigableString
    return " ".join(" ".join(str(child) for child in node.descendants
                              if type(child) is NavigableString and _visible(child)).split())


def _anchor_identity(text: str) -> dict | None:
    match = _DESCRIPTION.fullmatch(text)
    if match is None:
        return None
    literal = match["date"]
    if "." in literal:
        day, month, year = map(int, literal.split("."))
    else:
        day_raw, month_raw, year_raw = literal.split()
        day, month, year = int(day_raw), _MONTHS[month_raw], int(year_raw)
    return _identity(_body(match[1]), date(year, month, day).isoformat(), match[2])


def corroborate_detail_identity(detail_raw: bytes, page_url: str, expected_identity: dict, *,
                                search_raw: bytes, search_page_url: str, search_row_evidence: dict) -> dict:
    """Return a deterministic review candidate after replaying both HTML sources.

    ``search_row_evidence`` must be the exact ``asdict(document.evidence)`` from
    the independent search parser. The expected identity is a caller-selected
    target, not a caller-provided assertion of legal verification.
    """
    try:
        expected = _expected(expected_identity)
        validate_source_url(page_url, allow_portal=True)
        parsed_url = urlsplit(page_url)
        _require(parsed_url.netloc == "docs.eaeunion.org" and re.fullmatch(r"/documents/[1-9][0-9]*/[1-9][0-9]*/", parsed_url.path) is not None,
                 "invalid_detail_page_url")
        search = parse_legal_search(search_raw, search_page_url)
        _require(type(search_row_evidence) is dict and set(search_row_evidence) == {"locator", "text", "text_sha256"},
                 "invalid_search_row_evidence")
        rows = [row for row in search.documents if asdict(row.evidence) == search_row_evidence]
        _require(len(rows) == 1 and rows[0].document_link.url == page_url, "search_row_does_not_replay_for_detail_url")
        selected = rows[0]
        _category(selected.category, expected, "search")
        _require(selected.observed_adoption_date is not None and selected.observed_adoption_date.isoformat() == expected["adoption_date"],
                 "contradictory_or_missing_search_adoption_date")
        search_title_status = _title_status(selected.document_link.text, expected, "search")
        metadata = parse_legal_metadata(detail_raw, page_url)
        _require(metadata["container_count"] == 1 and not any(row["issues"] for row in metadata["rows"]),
                 "ambiguous_detail_metadata")
        labels = [row["labels"][0]["text"] for row in metadata["rows"]]
        _require(len(set(labels)) == len(labels), "duplicate_detail_metadata_label")
        fields = metadata["fields"]
        for name in ("short_title", "document_number", "adoption_date", "document_type"):
            _require(fields[name]["status"] == "observed", "missing_or_ambiguous_required_detail_field")
        _require(fields["document_number"]["observed_text"] == expected["number"]
                 and fields["adoption_date"]["observed_iso_date"] == expected["adoption_date"], "contradictory_detail_identity_fields")
        _category(fields["document_type"]["observed_text"], expected, "detail")
        detail_title_status = _title_status(fields["short_title"]["observed_text"], expected, "detail")
        source = detail_raw.decode("utf-8-sig", errors="strict")
        guard = _AttachmentGuard()
        guard.feed(source)
        guard.close()
        guard.verify()
        soup = BeautifulSoup(source, "html.parser")
        info = next(node for node in soup.select(".DocDetail_Info") if _visible(node))
        detail = info.find_parent(class_="DocDetail")
        _require(detail is not None, "metadata_has_no_own_document_attachment_scope")
        files = [node for node in detail.select(".DocDetail_Files") if _visible(node) and node.find_parent(class_="DocDetail") is detail]
        _require(len(files) == 1, "ambiguous_document_attachment_scope")
        groups = []
        for group in files[0].select(".DocDetail_Files_Group"):
            if not _visible(group) or group.find_parent(class_="DocDetail_Files") is not files[0]:
                continue
            _require(group.find_parent(class_="DocDetail_Files_Group") is None, "nested_document_attachment_group")
            titles = [node for node in group.select(".DocDetail_Files_Title") if _visible(node)]
            if len(titles) == 1 and _text(titles[0]) == "Документ":
                groups.append(group)
        _require(len(groups) == 1, "ambiguous_or_missing_primary_document_group")
        references, qualifying = [], []
        for position, anchor in enumerate(soup.body.find_all("a"), 1):
            if (not _visible(anchor) or anchor.find_parent(class_="DocDetail_Files_Group") is not groups[0]
                    or anchor.find_parent(class_="DocDetail") is not detail
                    or anchor.find_parent(class_="DocDetail_Files") is not files[0]):
                continue
            href = anchor.get("href")
            if not isinstance(href, str) or not re.search(r"\.pdf(?:$|[?#])", unquote(href).strip(), re.I):
                continue
            target = _attachment_target(href, page_url)
            text = _text(anchor)
            _require(len(text) <= MAX_ANCHOR_TEXT and len(references) < MAX_PDF_REFERENCES, "pdf_anchor_bound_exceeded")
            literal = guard.href_literals.get((anchor.sourceline, anchor.sourcepos))
            _require(isinstance(literal, str), "pdf_anchor_literal_missing")
            identity = _anchor_identity(text)
            if identity is not None:
                _require(identity == expected, "contradictory_descriptive_pdf_anchor")
            elif re.search(r"Решени[ея]|Распоряжение|Протокол", text, re.I):
                raise ETTDetailIdentityError("unsupported_descriptive_pdf_anchor")
            reference = {"url": target, "href": href, "raw_href": literal, "text": text,
                         "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                         "locator": f"html:a:{position}:line:{anchor.sourceline}:column:{anchor.sourcepos}",
                         "observed_anchor_identity": identity, "primary_pdf_bytes_verified": False}
            references.append(reference)
            if identity is not None:
                qualifying.append(len(references) - 1)
        urls = {references[i]["url"] for i in qualifying}
        _require(len(urls) == 1, "missing_or_ambiguous_descriptive_pdf_target")
    except ETTDetailIdentityError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, StopIteration):
        raise ETTDetailIdentityError("source_corroboration_failed") from None
    return {
        "schema_version": 1, "kind": "corroborated_detail_candidate", "status": "primary_pdf_body_review_required",
        "expected_identity": expected, "corroborated_metadata_identity": dict(expected),
        "source_url": page_url, "source_sha256": metadata["source_sha256"], "size_bytes": len(detail_raw),
        "metadata_evidence": metadata, "original_short_title": fields["short_title"]["observed_text"],
        "strict_detail_title_status": detail_title_status, "strict_search_title_status": search_title_status,
        "search_source_url": search.source_url, "search_source_sha256": search.source_sha256,
        "search_source_size_bytes": search.size_bytes, "original_search_identity_status": selected.identity_status,
        "search_row_evidence": asdict(selected.evidence), "search_document_link": asdict(selected.document_link),
        "observed_primary_group_pdf_references": references, "qualifying_reference_indices_zero_based": qualifying,
        "candidate_pdf_url": next(iter(urls)), "original_short_title_modified": False,
        "original_search_classification_modified": False, "independent_metadata_and_anchor_agree": True,
        "source_inputs_replayed": True, "index_inventory_replayed_by_this_helper": False,
        "primary_pdf_body_identity_verified": False, "official_publication_event_verified": False,
        "adoption_dates_verified": False, "effective_dates_verified": False, "legal_identity_approval": False,
        "legal_inventory_complete": False, "can_promote": False, "production_ready": False, "active_rates_written": False,
    }
