#!/usr/bin/env python3
"""Read-only audit of an explicitly selected, retained historical ETT PDF corpus.

Requires exactly one ru.XX_*.pdf per chapter (01-97 except 77). The report is
technical evidence, never proof of a current or legally complete rate catalog.
No database, source URL, publication date or active-rate write is involved.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.ett_analysis import analyze_chapter
from app.services.ett_notes import extract_tariff_notes


CHAPTERS = tuple(f"{number:02d}" for number in range(1, 98) if number != 77)
MAX_DIRECTORY_ENTRIES = 4096
MAX_SOURCE_BYTES = 64 * 1024 * 1024
MAX_TOTAL_SOURCE_BYTES = 512 * 1024 * 1024
MAX_SINGLE_REPORT_BYTES = 64 * 1024 * 1024
MAX_TOTAL_REPORT_BYTES = 768 * 1024 * 1024
MAX_SUMMARY_BYTES = 4 * 1024 * 1024
MAX_SECONDS = 30 * 60
MAX_RECORDS = 100_000
_CHAPTER_FILE = re.compile(r"ru\.([0-9]{2})_.+\.pdf\Z")
WATCH_CODE = "0406900000"


class AuditError(ValueError):
    pass


def _canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _file_state(path: Path) -> tuple:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or not 8 <= info.st_size <= MAX_SOURCE_BYTES:
        raise AuditError("Source must be a bounded regular PDF file")
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def discover_corpus(corpus: Path) -> dict[str, Path]:
    if not stat.S_ISDIR(corpus.lstat().st_mode):
        raise AuditError("Corpus must be an explicit existing directory, not a symbolic link")
    discovered: dict[str, list[Path]] = {}
    with os.scandir(corpus) as entries:
        for index, entry in enumerate(entries, 1):
            if index > MAX_DIRECTORY_ENTRIES:
                raise AuditError("Corpus directory exceeds its entry limit")
            if not (entry.name.startswith("ru.") and entry.name.endswith(".pdf")):
                continue
            match = _CHAPTER_FILE.fullmatch(entry.name)
            if match is None or match[1] not in CHAPTERS:
                raise AuditError("Corpus contains an unsupported chapter PDF name")
            path = corpus / entry.name
            _file_state(path)
            discovered.setdefault(match[1], []).append(path)
    if set(discovered) != set(CHAPTERS) or any(len(paths) != 1 for paths in discovered.values()):
        raise AuditError("Corpus requires exactly one unambiguous PDF for each of 96 chapters")
    return {chapter: discovered[chapter][0] for chapter in CHAPTERS}


def _read_pdf(path: Path) -> tuple[bytes, tuple]:
    before = _file_state(path)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as stream:
        opened = os.fstat(stream.fileno())
        identity = (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns)
        if not stat.S_ISREG(opened.st_mode) or identity != before:
            raise AuditError("Source identity changed before reading")
        data = stream.read(MAX_SOURCE_BYTES + 1)
        finished = os.fstat(stream.fileno())
        after = (finished.st_dev, finished.st_ino, finished.st_size, finished.st_mtime_ns, finished.st_ctime_ns)
    if before != after or before != _file_state(path) or len(data) != before[2]:
        raise AuditError("Source changed during reading")
    if not data.startswith(b"%PDF-") or b"%%EOF" not in data[-2048:]:
        raise AuditError("Source requires complete PDF framing")
    return data, before


def audit_corpus(corpus: Path, *, tariff_notes: Path | None = None) -> dict:
    started = time.monotonic()
    parser_sha = _sha(Path(__file__).read_bytes())
    sources = discover_corpus(corpus)
    paths = list(sources.values())
    if tariff_notes is not None:
        if any(os.path.samefile(tariff_notes, path) for path in paths):
            raise AuditError("Tariff notes must be a separately selected source")
        paths.append(tariff_notes)
    source_states = {path: _file_state(path) for path in paths}
    if sum(state[2] for state in source_states.values()) > MAX_TOTAL_SOURCE_BYTES:
        raise AuditError("Corpus exceeds its aggregate source budget")
    total_report_bytes = 0
    total_source_bytes = 0

    def budget():
        if time.monotonic() - started > MAX_SECONDS:
            raise AuditError("Corpus audit exceeded its elapsed-time budget")

    def read(path):
        nonlocal total_source_bytes
        budget()
        body, state = _read_pdf(path)
        if state != source_states[path]:
            raise AuditError("Source changed after corpus validation")
        total_source_bytes += len(body)
        if total_source_bytes > MAX_TOTAL_SOURCE_BYTES:
            raise AuditError("Corpus exceeds its aggregate source budget")
        return body

    def fingerprint(report):
        nonlocal total_report_bytes
        digest = hashlib.sha256()
        report_bytes = 0
        encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        # Report dictionaries contain bounded source rows, but their serialized
        # combination can be large. Do not allocate the full JSON merely to
        # discover that it exceeds a single-report or aggregate bound.
        for chunk in encoder.iterencode(report):
            budget()
            raw = chunk.encode("utf-8")
            report_bytes += len(raw)
            total_report_bytes += len(raw)
            if report_bytes > MAX_SINGLE_REPORT_BYTES:
                raise AuditError("Corpus audit exceeds its single-report budget")
            if total_report_bytes > MAX_TOTAL_REPORT_BYTES:
                raise AuditError("Corpus audit exceeds its aggregate report budget")
            digest.update(raw)
        return digest.hexdigest(), report_bytes

    notes_summary = None
    known_ids = set()
    if tariff_notes is not None:
        body = read(tariff_notes)
        notes_report = extract_tariff_notes(body, artifact_id="historical-tariff-notes")
        digest, size = fingerprint(notes_report)
        known_ids = set(notes_report["observed_note_ids"]) - set(notes_report["duplicate_note_ids"])
        notes_summary = {
            "source_file": tariff_notes.name, "source_sha256": _sha(body), "source_bytes": len(body),
            "report_sha256": digest, "report_bytes": size, "page_count": notes_report["page_count"],
            "parser": notes_report["parser"], "pdf_parser": notes_report["pdf_parser"],
            "note_count": notes_report["note_count"], "unique_note_count": notes_report["unique_note_count"],
            "observed_note_ids": notes_report["observed_note_ids"], "duplicate_note_ids": notes_report["duplicate_note_ids"],
            "numbering_gaps": notes_report["numbering_gaps"], "numbering_gaps_imply_missing_source": False,
            "source_row_count": notes_report["source_row_count"],
            "all_source_rows_accounted": notes_report["all_source_rows_accounted"],
            "unassigned_rows": len(notes_report["unassigned_rows"]), "inventory_issues": notes_report["issues"],
            "note_issue_counts": dict(sorted(Counter(issue for note in notes_report["notes"] for issue in note["issues"]).items())),
            "temporal_candidate_counts": dict(sorted(Counter(clause["kind"] for note in notes_report["notes"] for clause in note["temporal_candidates"]).items())),
            "temporal_issue_counts": dict(sorted(Counter(issue for note in notes_report["notes"] for clause in note["temporal_candidates"] for issue in clause["issues"]).items())),
            "context_signal_counts": dict(sorted(Counter(signal["kind"] for note in notes_report["notes"] for signal in note["context_signals"]).items())),
            "legal_dates_verified": False,
        }
        del notes_report, body
    chapters = []
    codes = []
    totals = Counter()
    histograms = {name: Counter() for name in ("assembly_issues", "row_issues", "lexical_statuses", "lexical_types", "lexical_unresolved_reasons", "typography_statuses", "typography_issues", "superscript_markers", "unbound_footnotes")}
    uniform_parsers = None
    heading_matches = []
    for chapter, path in sources.items():
        body = read(path)
        report = analyze_chapter(body, artifact_id=f"historical-chapter-{chapter}", chapter=chapter, known_note_ids=known_ids)
        parsers = {"extraction": report["extraction_parser"], "assembly": report["assembler"], "analysis": report["analysis_component_sha256"]}
        if uniform_parsers is not None and parsers != uniform_parsers:
            raise AuditError("Parser identity changed during the corpus audit")
        if notes_summary is not None and notes_summary["pdf_parser"] != parsers["extraction"]:
            raise AuditError("Notes and chapters use different PDF parser identities")
        uniform_parsers = parsers
        digest, size = fingerprint(report)
        records = report["records"]
        codes.extend(row["code"] for row in records)
        if len(codes) > MAX_RECORDS:
            raise AuditError("Corpus audit exceeds its record budget")
        chapter_counts = Counter(issue["reason"] for issue in report["issues"])
        histograms["assembly_issues"].update(chapter_counts)
        for row in records:
            cell, typography = row["duty_cell_analysis"], row["duty_typography"]
            histograms["row_issues"].update(row["issues"])
            histograms["lexical_statuses"].update([cell["status"]])
            if cell.get("duty"):
                histograms["lexical_types"].update([cell["duty"]["kind"]])
            if cell.get("unparsed_reason"):
                histograms["lexical_unresolved_reasons"].update([cell["unparsed_reason"]])
            histograms["typography_statuses"].update([typography["status"]])
            histograms["typography_issues"].update(typography["issues"])
            histograms["superscript_markers"].update(marker["footnote_id"] for marker in typography["footnote_evidence"])
            histograms["unbound_footnotes"].update(row["unbound_footnote_ids"])
        for heading in report["headings"]:
            code = heading.get("code")
            if code and len(code) < len(WATCH_CODE) and WATCH_CODE.startswith(code) and set(WATCH_CODE[len(code):]) == {"0"}:
                heading_matches.append({"code": code, "description": heading["leaf_description"],
                    "source_sha256": report["artifact_sha256"], "source_rows": heading["source_rows"]})
        totals.update({"pages": report["page_count"], "records": report["record_count"],
            "assembled_cells": report["assembled_cell_count"], "description_paths": report["resolved_description_count"],
            "excluded_code_mentions": len(report["excluded_candidates"]), "headings": len(report["headings"]),
            "pages_without_text": len(report["source_pages_without_text"]),
            "pages_without_headers": len(report["source_pages_without_headers"])})
        chapters.append({"chapter": chapter, "source_file": path.name, "source_sha256": _sha(body),
            "source_bytes": len(body), "report_sha256": digest, "report_bytes": size,
            "extraction_report_sha256": report["extraction_report_sha256"], "page_count": report["page_count"],
            "source_pages_without_text": report["source_pages_without_text"],
            "source_pages_without_headers": report["source_pages_without_headers"],
            "records": report["record_count"], "unique_codes": report["unique_code_count"],
            "assembled_cells": report["assembled_cell_count"], "full_description_paths": report["resolved_description_count"],
            "duty_cell_summary": report["duty_cell_summary"], "assembly_issue_counts": dict(sorted(chapter_counts.items()))})
        del report, body
    budget()
    if any(_file_state(path) != state for path, state in source_states.items()):
        raise AuditError("Retained sources changed during the corpus audit")
    if parser_sha != _sha(Path(__file__).read_bytes()):
        raise AuditError("Audit script changed during execution")
    unique_codes = sorted(set(codes))
    result = {"schema_version": 1, "kind": "retained_historical_ett_cells_audit",
        "status": "technical_audit_completed", "scope": "explicitly_selected_retained_historical_files",
        "audit_script_sha256": parser_sha, "component_parsers": uniform_parsers,
        "chapter_count": len(chapters), "chapters": chapters, "tariff_notes": notes_summary,
        "empty_table_chapters": [chapter["chapter"] for chapter in chapters if chapter["records"] == 0],
        "total_source_bytes": total_source_bytes, "total_analysis_report_bytes": total_report_bytes,
        "totals": dict(sorted(totals.items())), "histograms": {key: dict(sorted(value.items())) for key, value in histograms.items()},
        "unique_table_code_count": len(unique_codes), "table_code_list_sha256": _sha(_canonical(unique_codes)),
        "table_code_list_serialization": "UTF-8 compact JSON array of sorted unique exact table codes",
        "duplicate_table_codes": sorted(code for code, count in Counter(codes).items() if count > 1),
        "diagnostic_codes": {WATCH_CODE: {"table_occurrences": codes.count(WATCH_CODE), "unpadded_heading_matches": heading_matches,
            "meaning": "Observed source structure only; a shorter heading does not create a zero-padded declarable code."}},
        "complete_current_legal_inventory": False, "current_edition_verified": False,
        "current_rates_verified": False, "legal_rates_resolved": 0,
        "production_ready": False, "can_promote": False, "active_rates_written": False,
        "limitations": ["Historical retained files are not a current official acquisition.",
            "Matching note IDs and parsed monetary syntax do not establish legal applicability or effective dates.",
            "Unresolved rows and conditions remain explicit; no rates are activated."]}
    if len(_canonical(result)) > MAX_SUMMARY_BYTES:
        raise AuditError("Corpus audit summary exceeds its output budget")
    return result


def _validate_output(path: Path, sources: list[Path]) -> None:
    if path.suffix.lower() != ".json":
        raise AuditError("Output must be a JSON report")
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file() or any(os.path.samefile(path, source) for source in sources):
            raise AuditError("Output must not replace a source, symbolic link or nonregular file")
    if not path.parent.is_dir():
        raise AuditError("Output parent must already exist")


def _write_output(path: Path, raw: bytes, sources: list[Path]) -> None:
    _validate_output(path, sources)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent, prefix=".ett-audit-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", required=True, type=Path)
    parser.add_argument("--tariff-notes", type=Path, help="Explicit historical tariff-notes PDF; omitted notes remain unbound")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        source_paths = list(discover_corpus(args.corpus).values())
        if args.tariff_notes is not None:
            source_paths.append(args.tariff_notes)
        _validate_output(args.output, source_paths)
        result = audit_corpus(args.corpus, tariff_notes=args.tariff_notes)
        raw = _canonical(result)
        _write_output(args.output, raw, source_paths)
        print(json.dumps({"status": result["status"], "chapter_count": result["chapter_count"],
            "table_records": result["totals"]["records"], "report_sha256": _sha(raw),
            "current_rates_verified": False, "production_ready": False}, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "error": "Retained ETT corpus audit failed",
            "error_type": type(exc).__name__, "current_rates_verified": False, "production_ready": False}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
