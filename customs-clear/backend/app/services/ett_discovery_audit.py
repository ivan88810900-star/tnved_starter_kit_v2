"""Replay retained search evidence into a bounded legal-document capture plan.

An exact metadata match is a discovery candidate, never verified law. This pure
module performs no requests or writes. Index identities are regenerated from
original HTML. Fresh note extractions are replayed from original PDFs. Legacy
notes censuses remain report-bound and cannot independently authorize targets.
Neither path validates an act's legal effect.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import date
import hashlib
import json
import re
from typing import Callable

from app.services.ett_amendment_inventory import parse_amendment_inventory
from app.services.ett_legal_search import parse_legal_search, validate_search_result_url

MAX_REPORT_BYTES = 16 * 1024 * 1024
MAX_PAGES = 20
MAX_TOTAL_BYTES = 80 * 1024 * 1024
MAX_ROWS = 1000
MAX_IDENTITIES = 2048
MAX_REFERENCES = 10_000
_BODIES = {"Коллегии": "collegium", "Совета": "council"}
_MONTHS = {"января": 1, "февраля": 2, "марта": 3, "апреля": 4,
           "мая": 5, "июня": 6, "июля": 7, "августа": 8,
           "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12}
_CITATION = re.compile(
    r"Решени(?:я|ем)\s+(Коллегии|Совета)\s+Евразийской\s+экономической\s+"
    r"комиссии\s+(?:от\s+)?([0-9]{1,2})\s+(" + "|".join(_MONTHS) +
    r")\s+([0-9]{4})\s+г\.\s+№\s*([1-9][0-9]{0,5})(?!\w)")


class ETTDiscoveryAuditError(ValueError):
    """Retained inputs do not support an unambiguous bounded discovery audit."""


def canonical_json_bytes(value: object) -> bytes:
    """Stable plan encoding; dates must already be ISO strings."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ETTDiscoveryAuditError(message)


def _json(raw: bytes, name: str) -> dict:
    _require(type(raw) is bytes and 0 < len(raw) <= MAX_REPORT_BYTES, f"{name}: invalid report size")

    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, f"{name}: duplicate JSON key")
            result[key] = value
        return result

    def constant(value):
        raise ETTDiscoveryAuditError(f"{name}: non-finite JSON value")

    try:
        result = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        raise ETTDiscoveryAuditError(f"{name}: invalid JSON") from None
    _require(type(result) is dict, f"{name}: report must be an object")
    return result


def _digest(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _integer(value: object, minimum: int, maximum: int) -> bool:
    return type(value) is int and minimum <= value <= maximum


def _key(body: str, adopted: str, number: str) -> tuple[str, str, str]:
    _require(body in ("collegium", "council"), "unsupported issuing body")
    _require(isinstance(adopted, str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", adopted) is not None,
             "invalid adoption-date spelling")
    try:
        date.fromisoformat(adopted)
    except ValueError:
        raise ETTDiscoveryAuditError("invalid adoption date") from None
    _require(isinstance(number, str) and re.fullmatch(r"[1-9][0-9]{0,5}", number) is not None,
             "invalid act number")
    return body, adopted, number


def _identity(key: tuple[str, str, str]) -> dict:
    return dict(zip(("issuing_body", "adoption_date", "number"), key))


def build_notes_census(report: dict) -> dict:
    """Enumerate literal act citations from a previously revalidated extraction.

    This helper alone does not attest original PDF bytes. The public audit first
    re-extracts and compares the supplied report before using this projection.
    Unknown act-like wording is retained as a diagnostic, never repaired.
    """
    _require(report.get("mode") == "tariff_notes_review", "unsupported notes extraction")
    notes = report.get("notes")
    _require(type(notes) is list and len(notes) <= 10_000, "invalid notes extraction size")
    acts, unknown = {}, []
    total = 0
    for note in notes:
        text, rows = note["logical_text"], note["source_rows"]
        matches = list(_CITATION.finditer(text))
        for match in matches:
            key = _key(_BODIES[match[1]], date(int(match[4]), _MONTHS[match[3]], int(match[2])).isoformat(), match[5])
            selected, offset = [], 0
            for row in rows:
                end = offset + len(row["raw_text"])
                if offset < match.end() and end > match.start():
                    selected.append({name: row[name] for name in ("page", "row", "raw_text_sha256")})
                offset = end + 1
            kinds = {signal["kind"] for signal in note.get("context_signals", [])}
            reason = ("repeal_statement" if "repeal_statement" in kinds else
                      "act_dependent_start" if "act_dependent_timing" in kinds else "act_citation")
            reference = {"footnote_id": note["footnote_id"], "reason": reason,
                         "logical_text_quote": match[0], "logical_text_quote_sha256": _sha(match[0].encode()),
                         "logical_text_span": [match.start(), match.end()], "source_rows": selected}
            act = acts.setdefault(key, {"issuing_body": match[1], "adopted_on": key[1], "number": key[2],
                                       "effective_date_verified": False, "primary_act_body_verified": False,
                                       "needs_primary_body_review": True, "references": []})
            act["references"].append(reference)
            total += 1
            _require(total <= MAX_REFERENCES, "notes citation bound exceeded")
        residue = _CITATION.sub("", text)
        if re.search(r"Решени[ея]", residue, re.I):
            unknown.append({"footnote_id": note["footnote_id"], "status": "unparsed_act_like_wording",
                            "logical_text": text, "source_rows": [{name: r[name] for name in ("page", "row", "raw_text_sha256")} for r in rows]})
    return {"source_document_sha256": report["artifact_sha256"], "act_identities": [acts[k] for k in sorted(acts)],
            "unique_act_identities_requiring_primary_body_review": len(acts), "act_reference_count": total,
            "legal_dates_verified": False, "legal_inventory_complete": False, "unparsed_citation_diagnostics": unknown}


def _notes(report: dict) -> dict:
    _require(report.get("legal_dates_verified") is False and report.get("legal_inventory_complete") is False,
             "notes report must retain unverified legal status")
    _require(_digest(report.get("source_document_sha256")), "notes PDF digest is missing")
    acts = report.get("act_identities")
    _require(type(acts) is list and len(acts) <= MAX_IDENTITIES, "invalid notes identity inventory")
    _require(report.get("unique_act_identities_requiring_primary_body_review") == len(acts),
             "notes identity count disagrees")
    result = {}
    references_seen = set()
    for act in acts:
        _require(type(act) is dict and act.get("issuing_body") in _BODIES, "invalid notes authority")
        key = _key(_BODIES[act["issuing_body"]], act.get("adopted_on"), act.get("number"))
        _require(key not in result, "duplicate notes identity")
        _require(act.get("primary_act_body_verified") is False and act.get("effective_date_verified") is False,
                 "notes act is unexpectedly marked verified")
        refs = act.get("references")
        _require(type(refs) is list and 0 < len(refs) <= MAX_REFERENCES, "notes references are missing or excessive")
        for ref in refs:
            _require(type(ref) is dict, "invalid notes reference")
            quote, span = ref.get("logical_text_quote"), ref.get("logical_text_span")
            _require(isinstance(quote, str) and 0 < len(quote) <= 4096 and _sha(quote.encode()) == ref.get("logical_text_quote_sha256"),
                     "notes quote hash disagrees")
            _require(type(span) is list and len(span) == 2 and all(_integer(v, 0, 100_000) for v in span)
                     and span[1] - span[0] == len(quote), "notes quote span is invalid")
            match = _CITATION.fullmatch(quote)
            _require(match is not None, "notes citation grammar is unsupported")
            try:
                quoted = (_BODIES[match[1]], date(int(match[4]), _MONTHS[match[3]], int(match[2])).isoformat(), match[5])
            except ValueError:
                raise ETTDiscoveryAuditError("notes citation date is invalid") from None
            _require(key == quoted, "notes citation identity disagrees")
            _require(isinstance(ref.get("footnote_id"), str) and re.fullmatch(r"[1-9][0-9]{0,3}C", ref["footnote_id"]) is not None,
                     "notes footnote identifier is invalid")
            _require(ref.get("reason") in ("act_dependent_start", "repeal_statement", "act_citation"), "unsupported notes citation reason")
            rows = ref.get("source_rows")
            _require(type(rows) is list and 0 < len(rows) <= 512, "notes source rows are missing or excessive")
            for row in rows:
                _require(type(row) is dict and _integer(row.get("page"), 1, 100_000)
                         and isinstance(row.get("row"), str) and re.fullmatch(r"p[0-9]{4,}:r[0-9]{5,}", row["row"]) is not None
                         and _digest(row.get("raw_text_sha256")), "notes source-row reference is invalid")
            encoded = canonical_json_bytes(ref)
            _require(encoded not in references_seen, "duplicate notes citation reference")
            references_seen.add(encoded)
            _require(len(references_seen) <= MAX_REFERENCES, "notes reference bound exceeded")
        result[key] = act
    _require(report.get("act_reference_count") == len(references_seen), "notes reference count disagrees")
    return result


def _supplementary(raw_reports: tuple[bytes, ...], read_object: Callable[[str], bytes], *,
                   remaining_bytes: int, remaining_rows: int) -> tuple[list, list]:
    _require(type(raw_reports) is tuple and len(raw_reports) <= 4, "supplementary report bound exceeded")
    pages, diagnostics, attempts = [], [], 0
    seen_reports = set()
    for raw_report in raw_reports:
        digest = _sha(raw_report)
        _require(digest not in seen_reports, "duplicate supplementary report")
        seen_reports.add(digest)
        report = _json(raw_report, "supplementary search")
        _require(report.get("schema_version") == 1 and report.get("probe_kind") == "observed_official_portal_search",
                 "unsupported supplementary report")
        for flag in ("source_identity_verified", "adoption_dates_verified", "effective_dates_verified",
                     "document_absence_verified", "production_ready", "active_rates_written", "amendment_inventory_complete"):
            _require(report.get(flag) is False, "supplementary report contains a verified claim")
        records = report.get("results")
        _require(type(records) is list, "invalid supplementary results")
        attempts += len(records)
        _require(attempts <= 20, "supplementary query bound exceeded")
        captured = 0
        for record in records:
            _require(type(record) is dict, "invalid supplementary record")
            query, number = validate_search_result_url(record.get("requested_url"))
            _require(number is None and query == record.get("query"), "supplementary query disagrees")
            if record.get("status") == "failed":
                diagnostics.append({"status": "supplementary_query_failed", "report_sha256": digest,
                                    "requested_url": record["requested_url"], "query": query})
                continue
            _require(record.get("status") == "captured", "unsupported supplementary capture status")
            captured += 1
            source_digest, size = record.get("sha256"), record.get("size_bytes")
            _require(_digest(source_digest) and _integer(size, 1, 4 * 1024 * 1024)
                     and record.get("media_type") == "text/html", "invalid supplementary source metadata")
            _require(size <= remaining_bytes, "aggregate discovery byte bound exceeded")
            remaining_bytes -= size
            redirects = record.get("redirect_chain")
            _require(type(redirects) is list and len(redirects) <= 5, "invalid supplementary redirects")
            chain = [record["requested_url"], *redirects]
            _require(len(set(chain)) == len(chain) and record.get("response_url") == chain[-1], "supplementary redirect chain disagrees")
            for url in chain:
                _require(validate_search_result_url(url) == (query, None), "supplementary redirect changed query")
            raw = read_object(source_digest)
            _require(type(raw) is bytes and len(raw) == size and _sha(raw) == source_digest,
                     "supplementary original bytes disagree")
            parsed = parse_legal_search(raw, record["response_url"])
            remaining_rows -= len(parsed.documents)
            _require(remaining_rows >= 0, "aggregate discovery row bound exceeded")
            pages.append(parsed)
        _require(report.get("attempted_queries") == len(records) and report.get("captured_queries") == captured
                 and report.get("failed_queries") == len(records) - captured
                 and report.get("all_queries_captured") is (captured == len(records)), "supplementary counters disagree")
    return pages, diagnostics


def _replay(report: dict, read_object: Callable[[str], bytes]) -> list:
    """Support the completed bounded capture schema; reject unverifiable chains."""
    _require(report.get("schema_version") == 1 and report.get("capture_kind") == "observed_official_portal_search_chain",
             "unsupported pagination report")
    _require(report.get("status") == "observed_chain_captured" and report.get("observed_chain_exhausted") is True
             and report.get("stop_reason") == "observed_chain_exhausted", "pagination chain is incomplete")
    _require(report.get("pending_next_url") is None and report.get("pending_followed_from") is None,
             "exhausted chain has a pending link")
    for flag in ("source_identity_verified", "adoption_dates_verified", "effective_dates_verified",
                 "legal_inventory_complete", "amendment_inventory_complete", "document_absence_verified",
                 "cross_page_snapshot_consistency_verified", "production_ready", "active_rates_written"):
        _require(report.get(flag) is False, f"pagination flag must remain false: {flag}")
    records = report.get("results")
    _require(type(records) is list and 0 < len(records) <= MAX_PAGES, "invalid pagination page count")
    query, page = validate_search_result_url(report.get("initial_url"))
    _require(page is None and query == report.get("query"), "initial search query disagrees")
    parsed_pages, seen_hashes, seen_row_sets = [], set(), set()
    total_bytes = total_rows = highest = 0
    for i, record in enumerate(records, 1):
        _require(type(record) is dict and record.get("status") == "captured" and record.get("parse_status") == "parsed",
                 "pagination contains an unaccepted page")
        _require(type(record.get("page_number")) is int and record["page_number"] == i, "pagination order disagrees")
        requested = record.get("requested_url")
        q, literal = validate_search_result_url(requested)
        _require(q == query and (literal or 1) == i, "pagination request identity disagrees")
        if i == 1:
            _require(requested == report["initial_url"] and record.get("followed_from") is None, "initial page parent is invalid")
        else:
            parent = parsed_pages[-1]
            proof = record.get("followed_from")
            _require(type(proof) is dict and proof.get("page_sha256") == parent.source_sha256
                     and proof.get("page_url") == parent.source_url, "pagination parent source disagrees")
            _require(any(asdict(link) == proof.get("link") and link.url == requested for link in parent.pagination_links),
                     "pagination link is not observed in its original parent")
        redirects = record.get("redirect_chain")
        _require(type(redirects) is list and len(redirects) <= 5, "invalid pagination redirects")
        chain = [requested, *redirects]
        _require(len(set(chain)) == len(chain) and record.get("response_url") == chain[-1], "pagination redirect chain disagrees")
        for url in chain:
            q, literal = validate_search_result_url(url)
            _require(q == query and (literal or 1) == i, "pagination redirect changed query or page")
        digest, size = record.get("sha256"), record.get("size_bytes")
        _require(_digest(digest) and _integer(size, 1, 4 * 1024 * 1024) and record.get("media_type") == "text/html",
                 "invalid pagination source metadata")
        total_bytes += size
        _require(total_bytes <= MAX_TOTAL_BYTES and digest not in seen_hashes, "pagination bytes repeat or exceed bound")
        raw = read_object(digest)
        _require(type(raw) is bytes and len(raw) == size and _sha(raw) == digest, "pagination original bytes disagree")
        seen_hashes.add(digest)
        parsed = parse_legal_search(raw, record["response_url"])
        rows = len(parsed.documents)
        total_rows += rows
        _require(total_rows <= MAX_ROWS, "pagination row bound exceeded")
        for name in ("observed_raw_rows", "accepted_raw_rows"):
            _require(type(record.get(name)) is int and record[name] == rows, "pagination row count disagrees")
        _require(record.get("row_identity_counts") == dict(Counter(d.identity_status for d in parsed.documents)),
                 "pagination identity counters disagree")
        _require(record.get("empty_result_notice") is parsed.empty_result_notice
                 and record.get("observed_pagination_link_count") == len(parsed.pagination_links), "pagination parser metadata disagrees")
        row_set = tuple(sorted(d.document_link.url for d in parsed.documents))
        _require(row_set not in seen_row_sets, "pagination repeats a result set")
        seen_row_sets.add(row_set)
        pages = [validate_search_result_url(link.url)[1] or 1 for link in parsed.pagination_links]
        highest = max(highest, i, *pages)
        next_urls = {link.url for link, number in zip(parsed.pagination_links, pages) if number == i + 1}
        if i < len(records):
            _require(len(next_urls) == 1 and records[i].get("requested_url") in next_urls,
                     "pagination does not follow its unique observed next page")
        else:
            _require(not next_urls and highest <= i, "pagination exhausted claim contradicts observed links")
        parsed_pages.append(parsed)
    for name, expected in (("attempted_pages", len(records)), ("captured_pages", len(records)),
                           ("accepted_pages", len(records)), ("accepted_raw_rows", total_rows),
                           ("captured_bytes", total_bytes), ("highest_observed_page_number", highest)):
        _require(type(report.get(name)) is int and report[name] == expected, f"pagination total disagrees: {name}")
    return parsed_pages


def audit_legal_discovery(index_raw: bytes, inventory_report_raw: bytes, notes_report_raw: bytes,
                         pagination_report_raw: bytes, read_object: Callable[[str], bytes], *,
                         supplementary_report_raws: tuple[bytes, ...] = ()) -> dict:
    """Return JSON-native discovery evidence and observed, unambiguous page URLs.

    ``read_object`` is a read-only SHA-256 lookup into retained original HTML.
    The returned plan is not authority to trust page identity or apply a rate.
    Consumers must re-run this audit from originals before executing a supplied
    plan; hashing a caller-edited plan alone does not establish provenance.
    """
    try:
        inventory = _json(inventory_report_raw, "index inventory")
        regenerated = json.loads(json.dumps(asdict(parse_amendment_inventory(index_raw)), default=str))
        _require(all(inventory.get(k) == v for k, v in regenerated.items()), "index inventory does not replay from original HTML")
        notes_report = _json(notes_report_raw, "notes")
        notes_pdf_replayed = notes_report.get("mode") == "tariff_notes_review"
        if notes_pdf_replayed:
            from app.services.ett_notes import extract_tariff_notes
            digest = notes_report.get("artifact_sha256")
            _require(_digest(digest), "notes PDF digest is invalid")
            pdf = read_object(digest)
            _require(type(pdf) is bytes and len(pdf) == notes_report.get("size_bytes") and _sha(pdf) == digest,
                     "notes original PDF bytes disagree")
            replayed = extract_tariff_notes(pdf, artifact_id=notes_report.get("artifact_id"))
            _require(replayed == notes_report, "notes extraction does not replay from original PDF")
            notes_report = build_notes_census(replayed)
        notes = _notes(notes_report)
        capture = _json(pagination_report_raw, "pagination")
        pages = _replay(capture, read_object)
        pagination_pages = len(pages)
        supplementary_pages, supplementary_diagnostics = _supplementary(
            supplementary_report_raws, read_object,
            remaining_bytes=MAX_TOTAL_BYTES - sum(p.size_bytes for p in pages),
            remaining_rows=MAX_ROWS - sum(len(p.documents) for p in pages))
        pages.extend(supplementary_pages)
        _require(sum(p.size_bytes for p in pages) <= MAX_TOTAL_BYTES and sum(len(p.documents) for p in pages) <= MAX_ROWS,
                 "aggregate discovery source bound exceeded")
    except ETTDiscoveryAuditError:
        raise
    except (ValueError, KeyError, TypeError, AttributeError, OSError, OverflowError):
        raise ETTDiscoveryAuditError("discovery input cannot be replayed safely") from None
    amendments = {_key(a["issuing_body"], a["adoption_date"], a["number"]): a for a in regenerated["amendments"]}
    founding = regenerated["founding_act"]
    founding_key = _key(founding["issuing_body"], founding["adoption_date"], founding["number"])
    by_identity, by_url, non_strict_by_url = defaultdict(list), defaultdict(set), defaultdict(list)
    diagnostics, page_summaries, all_statuses = list(supplementary_diagnostics), [], Counter()
    diagnostics.extend(notes_report.get("unparsed_citation_diagnostics", []))
    for page in pages:
        statuses = Counter(d.identity_status for d in page.documents)
        all_statuses.update(statuses)
        page_summaries.append({"source_url": page.source_url, "source_sha256": page.source_sha256,
                               "size_bytes": page.size_bytes, "row_count": len(page.documents),
                               "row_identity_counts": dict(statuses), "empty_result_notice": page.empty_result_notice})
        for position, document in enumerate(page.documents, 1):
            observation = {"source_url": page.source_url, "source_sha256": page.source_sha256,
                           "source_size_bytes": page.size_bytes, "row_index": position,
                           "document_link": asdict(document.document_link), "evidence": asdict(document.evidence),
                           "title": document.title,
                           "observed_adoption_date": str(document.observed_adoption_date) if document.observed_adoption_date else None,
                           "observed_publication_date": str(document.observed_publication_date) if document.observed_publication_date else None,
                           "observed_entry_into_force_date": str(document.observed_entry_into_force_date) if document.observed_entry_into_force_date else None}
            if document.identity_status == "observed_decision_identity":
                key = _key(document.issuing_body, document.observed_adoption_date.isoformat(), document.number)
                by_identity[key].append(observation)
                by_url[document.document_link.url].add(key)
                if key not in amendments and key not in notes and key != founding_key:
                    diagnostics.append({"status": "outside_target_inventory", "identity": _identity(key), **observation})
            else:
                # Includes malformed labels with plausible dates/numbers. Never
                # repair the wording silently or call the act itself absent.
                diagnostic = {"status": document.identity_status, "category": document.category,
                              "issues": list(document.issues), **observation}
                diagnostics.append(diagnostic)
                non_strict_by_url[document.document_link.url].append(diagnostic)
    conflicts, plan = [], []
    matched_amendments, matched_notes = set(), set()
    targets = amendments.keys() | notes.keys() | {founding_key}
    for key in sorted(targets):
        if key not in amendments and key != founding_key and not notes_pdf_replayed:
            diagnostics.append({"status": "notes_only_identity_requires_original_pdf_replay", "identity": _identity(key)})
            continue
        observations = by_identity.get(key, [])
        urls = {o["document_link"]["url"] for o in observations}
        if not urls:
            continue
        reasons = []
        if len(urls) != 1:
            reasons.append("identity_has_multiple_observed_urls")
        if any(len(by_url[url]) != 1 for url in urls):
            reasons.append("observed_url_has_multiple_identities")
        conflicting = [row for url in sorted(urls) for row in non_strict_by_url.get(url, [])]
        if conflicting:
            reasons.append("observed_url_has_non_strict_identity")
        if reasons:
            conflicts.append({"identity": _identity(key), "reasons": reasons, "observations": observations,
                              "conflicting_observations": conflicting})
            continue
        if key in amendments:
            matched_amendments.add(key)
        if key in notes:
            matched_notes.add(key)
        plan.append({"page_url": next(iter(urls)), "identity": _identity(key),
                     "amendment_references": [amendments[key]] if key in amendments else [],
                     "founding_references": [founding] if key == founding_key else [],
                     "note_references": [notes[key]] if key in notes else [], "observations": observations,
                     "primary_body_verified": False, "legal_dates_verified": False})
    return {
        "schema_version": 1, "kind": "original_search_discovery_capture_plan",
        "inputs": {"index_source_sha256": regenerated["source_sha256"],
                   "index_inventory_report_sha256": _sha(inventory_report_raw),
                   "notes_report_sha256": _sha(notes_report_raw),
                   "notes_source_document_sha256": notes_report["source_document_sha256"],
                   "pagination_report_sha256": _sha(pagination_report_raw),
                   "supplementary_probe_report_sha256s": [_sha(raw) for raw in supplementary_report_raws]},
        "pages": page_summaries, "page_count": len(pages),
        "pagination_page_count": pagination_pages, "supplementary_page_count": len(supplementary_pages),
        "row_count": sum(all_statuses.values()), "row_identity_counts": dict(all_statuses),
        "distinct_observed_identity_count": len(by_identity),
        "named_amendment_count": len(amendments), "notes_identity_count": len(notes),
        "founding_act_match": {"identity": _identity(founding_key),
                               "status": "observed_unambiguous_identity" if any(p["founding_references"] for p in plan) else
                               "ambiguous_observed_identity" if founding_key in by_identity else "not_observed_as_strict_identity",
                               "observations": by_identity.get(founding_key, []),
                               "primary_body_verified": False, "legal_dates_verified": False},
        "matched_amendment_count": len(matched_amendments), "matched_notes_identity_count": len(matched_notes),
        "amendments_not_observed_as_unambiguous_identity": [_identity(k) for k in sorted(amendments.keys() - matched_amendments)],
        "notes_not_observed_as_unambiguous_identity": [_identity(k) for k in sorted(notes.keys() - matched_notes)],
        "ambiguities": conflicts, "row_diagnostics": diagnostics,
        "capture_plan": plan, "capture_target_count": len(plan), "capture_plan_sha256": _sha(canonical_json_bytes(plan)),
        "index_source_replayed": True, "search_sources_replayed": True,
        "notes_original_pdf_replayed": notes_pdf_replayed, "notes_citations_report_bound": True,
        "observed_pagination_chain_replayed": True, "document_absence_verified": False,
        "source_identity_verified": False, "adoption_dates_verified": False, "effective_dates_verified": False,
        "legal_inventory_complete": False, "primary_bodies_verified": False,
        "cross_page_snapshot_consistency_verified": False, "production_ready": False, "active_rates_written": False,
    }
