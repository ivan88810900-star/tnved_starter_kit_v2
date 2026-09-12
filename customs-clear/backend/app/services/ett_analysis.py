"""Assemble a captured ETT source set into reviewable cells and note references.

The output is technical analysis, not a legal manifest. No effective interval,
approval, production rate, VAT or database record is inferred or written.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re
import time

from fastapi.encoders import jsonable_encoder

from app.services.ett_acquisition import (
    AcquisitionError, ExpandedAcquisitionReceipt, load_acquisition,
)
from app.services.ett_artifacts import LocalArtifactStore
from app.services.ett_amendment_inventory import parse_amendment_inventory
from app.services.ett_duty_cells import parse_duty_cell
from app.services.ett_duty_typography import normalize_duty_typography
from app.services.ett_notes import extract_tariff_notes
from app.services.ett_table_assembly import assemble_pdf_table

MAX_REPORT_BYTES = 512 * 1024 * 1024
MAX_ANALYSIS_SECONDS = 20 * 60
MAX_RECORDS = 100_000
MAX_SINGLE_REPORT_BYTES = 64 * 1024 * 1024


def _parser_hashes() -> dict[str, str]:
    return {name: hashlib.sha256(Path(__file__).with_name(name + ".py").read_bytes()).hexdigest()
            for name in ("ett_analysis", "ett_duty_cells", "ett_duty_typography", "ett_manifest", "ett_amendment_inventory")}


def _bounded_json(report, *, maximum: int, started: float) -> bytes:
    result = bytearray()
    encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    for chunk in encoder.iterencode(report):
        encoded = chunk.encode("utf-8")
        if len(result) + len(encoded) > maximum or time.monotonic() - started > MAX_ANALYSIS_SECONDS:
            raise AcquisitionError("ETT analysis exceeded its aggregate resource budget")
        result.extend(encoded)
    return bytes(result)


def analyze_chapter(data: bytes, *, artifact_id: str, chapter: str, known_note_ids=()) -> dict:
    """Always establish table/typography evidence from original source bytes."""
    if not isinstance(known_note_ids, (tuple, list, set, frozenset)) or len(known_note_ids) > 10_000:
        raise ValueError("known note IDs must be a bounded collection")
    if any(type(note) is not str or not re.fullmatch(r"[1-9][0-9]{0,3}C", note) for note in known_note_ids):
        raise ValueError("known note IDs must use canonical numeric C labels")
    table = assemble_pdf_table(data, artifact_id=artifact_id, chapter=chapter)
    known = frozenset(known_note_ids)
    counts = Counter()
    unknown_notes = Counter()
    for row in table["records"]:
        typography = normalize_duty_typography(row)
        row["duty_typography"] = typography
        if typography["status"] == "normalized":
            cell = parse_duty_cell(typography["normalized_text"], percent_header_confirmed=row["percent_header_confirmed"])
        else:
            cell = {"status": "unresolved", "raw_text": row["duty_raw"], "duty": None,
                    "footnote_ids": [], "unparsed_reason": "cell_or_typography_unresolved",
                    "legal_interpretation_verified": False, "can_promote": False}
        row["duty_cell_analysis"] = cell
        row["unbound_footnote_ids"] = [note for note in cell["footnote_ids"] if note not in known]
        row["rate_applicability_verified"] = False
        counts[cell["status"]] += 1
        unknown_notes.update(row["unbound_footnote_ids"])
    table["mode"] = "duty_cell_analysis_review"
    table["duty_cell_summary"] = {"parsed": counts["parsed"], "unresolved": counts["unresolved"],
                                  "unbound_footnote_references": dict(sorted(unknown_notes.items())),
                                  "note_id_match_does_not_verify_interpretation": True}
    table["analysis_parser_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    table["analysis_component_sha256"] = _parser_hashes()
    table["current_rates_verified"] = False
    return table


def analyze_acquisition(store: LocalArtifactStore, digest: str) -> dict:
    """Publish an analysis-set index only after every chapter has been examined."""
    receipt, discovery = load_acquisition(store, digest)
    return _analyze_captured_records(store, digest, receipt, discovery, complete=True)


def analyze_incomplete_capture(store: LocalArtifactStore, digest: str) -> dict:
    """Analyze fully captured core PDFs while retaining the failed legal capture."""
    from app.services.ett_acquisition import load_incomplete_capture
    receipt, discovery = load_incomplete_capture(store, digest)
    present = {record.requested_url for record in receipt.downloads}
    if discovery is None or receipt.index_start is None or any(ref.url not in present for ref in discovery.documents):
        raise AcquisitionError("Incomplete capture lacks the full core PDF source set")
    return _analyze_captured_records(store, digest, receipt, discovery, complete=False)


def _analyze_captured_records(store, digest, receipt, discovery, *, complete):
    records_by_url = {record.requested_url: record for record in receipt.downloads}
    started = time.monotonic()
    total_bytes = 0

    def publish(report):
        nonlocal total_bytes
        raw = _bounded_json(report, maximum=min(MAX_SINGLE_REPORT_BYTES, MAX_REPORT_BYTES - total_bytes), started=started)
        total_bytes += len(raw)
        if total_bytes > MAX_REPORT_BYTES or time.monotonic() - started > MAX_ANALYSIS_SECONDS:
            raise AcquisitionError("ETT analysis exceeded its aggregate resource budget")
        return store.put(raw)

    amendments = parse_amendment_inventory(store.read(receipt.index_start.sha256))
    amendments_sha = publish(jsonable_encoder(asdict(amendments)))
    notes_record = records_by_url[discovery.tariff_notes.url]
    notes = extract_tariff_notes(store.read(notes_record.sha256), artifact_id="tariff-notes")
    notes_sha = publish(notes)
    known_ids = set(notes["observed_note_ids"]) - set(notes["duplicate_note_ids"])
    chapters = []
    all_codes = []
    unresolved_refs = Counter()
    assembly_diagnostics = Counter()
    row_diagnostics = Counter()
    empty_chapters = []
    totals = Counter()
    for reference in discovery.chapters:
        if time.monotonic() - started > MAX_ANALYSIS_SECONDS:
            raise AcquisitionError("ETT analysis exceeded its elapsed-time budget")
        record = records_by_url[reference.url]
        report = analyze_chapter(store.read(record.sha256), artifact_id=f"chapter-{reference.chapter}",
                                 chapter=reference.chapter, known_note_ids=known_ids)
        if report["record_count"] == 0:
            empty_chapters.append(reference.chapter)
        all_codes.extend(row["code"] for row in report["records"])
        if len(all_codes) > MAX_RECORDS:
            raise AcquisitionError("ETT analysis exceeds its record count bound")
        analysis_sha = publish(report)
        cells = report["duty_cell_summary"]
        chapter_diagnostics = Counter(issue["reason"] for issue in report["issues"])
        assembly_diagnostics.update(chapter_diagnostics)
        row_diagnostics.update(issue for row in report["records"] for issue in row["issues"])
        chapters.append({"chapter": reference.chapter, "source_sha256": record.sha256,
                         "report_sha256": analysis_sha, "table_records": report["record_count"],
                         "parsed_cells": cells["parsed"], "unresolved_cells": cells["unresolved"],
                         "source_pages_without_text": report["source_pages_without_text"],
                         "source_pages_without_headers": report["source_pages_without_headers"],
                         "assembly_diagnostics": dict(sorted(chapter_diagnostics.items()))})
        totals.update({"records": report["record_count"], "parsed": cells["parsed"],
                       "unresolved": cells["unresolved"], "full_descriptions": report["resolved_description_count"],
                       "pages_without_text": len(report["source_pages_without_text"]),
                       "pages_without_headers": len(report["source_pages_without_headers"]),
                       "excluded_mentions": len(report["excluded_candidates"])})
        unresolved_refs.update(cells["unbound_footnote_references"])
    duplicate_codes = sorted(code for code, count in Counter(all_codes).items() if count > 1)
    summary = {
        "schema_version": 1, "kind": "ett_acquisition_analysis" if complete else "ett_incomplete_capture_analysis",
        "status": "analyzed_for_review" if complete else "incomplete_capture_analyzed_for_review",
        "acquisition_complete": complete,
        "receipt_sha256": digest if complete else None,
        "incomplete_capture_report_sha256": None if complete else digest,
        "tariff_notes_report_sha256": notes_sha,
        "amendment_inventory_report_sha256": amendments_sha,
        "amendment_inventory_named_count": amendments.named_count,
        "amendment_inventory_linked_count": amendments.linked_count,
        "amendment_inventory_missing_link_count": amendments.missing_link_count,
        "amendment_effective_clauses_verified": 0,
        "notes": notes["note_count"], "duplicate_note_ids": notes["duplicate_note_ids"],
        "note_inventory_diagnostics": notes["issues"], "unassigned_note_rows": len(notes["unassigned_rows"]),
        "all_note_source_rows_accounted": notes["all_source_rows_accounted"],
        "chapters": chapters, "chapter_count": len(chapters),
        "table_records": totals["records"], "unique_table_codes": len(set(all_codes)),
        "parsed_duty_cells": totals["parsed"], "unresolved_duty_cells": totals["unresolved"],
        "full_description_paths": totals["full_descriptions"], "excluded_code_mentions": totals["excluded_mentions"],
        "duplicate_table_codes": duplicate_codes,
        "empty_table_chapters": empty_chapters,
        "source_pages_without_text_count": totals["pages_without_text"],
        "source_pages_without_headers_count": totals["pages_without_headers"],
        "assembly_diagnostics": dict(sorted(assembly_diagnostics.items())),
        "row_diagnostics": dict(sorted(row_diagnostics.items())),
        "analysis_component_sha256": _parser_hashes(),
        "unbound_footnote_references": dict(sorted(unresolved_refs.items())),
        "legal_attachment_inventory_bound": isinstance(receipt, ExpandedAcquisitionReceipt),
        "linked_legal_pdf_capture": bool(receipt.attachment_downloads) if isinstance(receipt, ExpandedAcquisitionReceipt) else False,
        "additional_legal_pdfs_captured": len(receipt.attachment_downloads) if isinstance(receipt, ExpandedAcquisitionReceipt) else 0,
        "blockers": ([] if complete else ["incomplete_acquisition"]) + (["empty_table_chapters"] if empty_chapters else []) + ["current_edition_and_complete_amendments_not_legally_verified",
                     "note_conditions_and_effective_dates_require_interpretation",
                     "manifest_bound_legal_review_missing", "production_promotion_not_implemented"],
        "legal_rates_resolved": 0, "complete_rate_catalog_verified": False,
        "production_ready": False, "active_rates_written": False,
    }
    summary_sha = publish(summary)
    return {key: value for key, value in summary.items() if key != "chapters"} | {"report_sha256": summary_sha}
