"""Source-bound tariff-note blocks and *syntactic* date-clause candidates.

This module never establishes an effective legal interval. In particular, an act's
adoption date is not its entry-into-force date. Separate clauses, rates, countries,
conditions and repeal statements are retained for review rather than flattened
into one rule. Inputs are original PDF bytes, not caller-supplied extracted text.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from app.services.ett_pdf_evidence import PDFEvidenceError, extract_pdf_evidence


PARSER_NAME = "ett_tariff_note_clauses"
PARSER_VERSION = "1"
MAX_NOTES = 10_000
MAX_NOTE_TEXT = 100_000
MAX_DATE_TOKENS = 512
MAX_REPORT_BYTES = 64 * 1024 * 1024
_HEADER = re.compile(r"^(?P<number>[0-9]{1,4})\s*(?P<letter>[СC])\)(?=\s|$)")
_MARKER_LIKE = re.compile(r"^[0-9]{1,6}\s*[A-Za-zА-Яа-я]\)")
_MONTHS = {"января": 1, "февраля": 2, "марта": 3, "апреля": 4,
           "мая": 5, "июня": 6, "июля": 7, "августа": 8,
           "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12}
_MONTH = "(?:" + "|".join(_MONTHS) + ")"
_DATE = (r"(?:[0-9]{2}\.[0-9]{2}\.[0-9]{4}|[0-9]{1,2}\s+" + _MONTH
         + r"\s+[0-9]{4}(?:\s+(?:года|г\.?))?)")
_DATE_END = r"(?![\w]|\.[0-9])"
_TOKEN = re.compile(r"(?<![\w.])" + _DATE + _DATE_END, re.I)
_WINDOW = re.compile(r"\bс\s+(?P<start>" + _DATE + r")\s+по\s+(?P<end>" + _DATE
                     + r")" + _DATE_END + r"(?P<inclusive>\s+включительно\b)?", re.I)
_LOWER = re.compile(r"\bс\s+(?P<start>" + _DATE + r")" + _DATE_END, re.I)
_UPPER = re.compile(r"\bпо\s+(?P<end>" + _DATE + r")" + _DATE_END + r"(?P<inclusive>\s+включительно\b)?", re.I)
_RELATIVE = re.compile(r"\bс\s+(?:даты|дня)\s+вступления\s+в\s+силу\b|"
                       r"\bпо\s+истечении\b|\bпосле\s+(?:дня\s+)?(?:официального\s+)?опубликования\b", re.I)
_REPEAL = re.compile(r"\b(?:примечание\s+утратило\s+силу|признать\s+утратившим\s+силу)\b", re.I)
_CONDITION = re.compile(r"\b(?:в\s+отношении|при\s+условии|за\s+исключением|если|"
                        r"предназначенн\w*|ввозим\w*|квот\w*)\b", re.I)
_COUNTRIES = {
    "RU": re.compile(r"\bРоссийск\w*\s+Федераци\w*\b", re.I),
    "AM": re.compile(r"\bРеспублик\w*\s+Армени\w*\b", re.I),
    "BY": re.compile(r"\bРеспублик\w*\s+Беларус\w*\b", re.I),
    "KZ": re.compile(r"\bРеспублик\w*\s+Казахстан\w*\b", re.I),
    "KG": re.compile(r"\bКыргызск\w*\s+Республик\w*\b", re.I),
}


class TariffNotesError(PDFEvidenceError):
    """A bounded source-note extraction cannot be completed without loss."""


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _date_value(token: str) -> date:
    if re.fullmatch(r"[0-9]{2}\.[0-9]{2}\.[0-9]{4}", token):
        day, month, year = map(int, token.split("."))
    else:
        pieces = token.casefold().split()
        day, month, year = int(pieces[0]), _MONTHS[pieces[1]], int(pieces[2])
    return date(year, month, day)


def _row_ref(report: dict[str, Any], page: int, row: dict[str, Any]) -> dict[str, Any]:
    return {"artifact_id": report["artifact_id"], "artifact_sha256": report["artifact_sha256"],
            "page": page, "row": row["row"], "raw_text": row["raw_text"],
            "raw_text_sha256": row["raw_text_sha256"]}


def _quotes(rows: list[dict[str, Any]], start: int, end: int) -> list[dict[str, Any]]:
    offset = 0
    selected = []
    for row in rows:
        stop = offset + len(row["raw_text"])
        if offset < end and stop > start:
            selected.append(row)
        offset = stop + 1  # Newline in raw_text; a single space in logical_text.
    return selected


def _span(text: str, rows: list[dict[str, Any]], start: int, end: int) -> dict[str, Any]:
    quote = text[start:end]
    return {"quote": quote, "quote_sha256": _sha(quote.encode("utf-8")),
            "logical_text_span": {"start": start, "end": end},
            "source_rows": _quotes(rows, start, end)}


def _temporal_candidates(text: str, rows: list[dict[str, Any]]) -> tuple[list, list]:
    candidates = []
    covered = []
    tokens = list(_TOKEN.finditer(text))
    if len(tokens) > MAX_DATE_TOKENS:
        raise TariffNotesError("Tariff note exceeds its date-token limit")
    for kind, pattern in (("absolute_window", _WINDOW), ("absolute_start", _LOWER), ("absolute_end", _UPPER)):
        for match in pattern.finditer(text):
            if any(match.start() < end and match.end() > start for start, end in covered):
                continue
            fields = match.groupdict()
            issues = []
            parsed = {}
            for field in ("start", "end"):
                token = fields.get(field)
                if token is not None:
                    try:
                        parsed[field] = _date_value(token)
                    except (ValueError, KeyError, OverflowError):
                        issues.append(f"invalid_{field}_calendar_date")
            inclusive = True if fields.get("inclusive") else None
            end_exclusive = None
            if "end" in parsed and inclusive:
                try:
                    end_exclusive = parsed["end"] + timedelta(days=1)
                except OverflowError:
                    issues.append("exclusive_end_out_of_calendar_range")
            if "start" in parsed and "end" in parsed and parsed["start"] > parsed["end"]:
                issues.append("reversed_date_window")
            if fields.get("end") is not None and inclusive is None:
                issues.append("end_inclusiveness_not_explicit")
            if kind != "absolute_window":
                issues.append("other_interval_boundary_unresolved")
            if issues:
                # Keep valid literal dates visible, but do not return a converted
                # interval where even its syntactic range is contradictory.
                if any(issue in issues for issue in ("invalid_start_calendar_date", "invalid_end_calendar_date", "reversed_date_window")):
                    end_exclusive = None
            candidates.append({"kind": kind, "status": "review_required",
                "start_date_literal": parsed["start"].isoformat() if "start" in parsed else None,
                "end_date_literal": parsed["end"].isoformat() if "end" in parsed else None,
                "end_inclusive_explicit": inclusive,
                "end_date_exclusive_arithmetic": end_exclusive.isoformat() if end_exclusive else None,
                "conversion": "explicit inclusive end + one calendar day" if end_exclusive else None,
                "legal_dates_verified": False, "issues": issues,
                **_span(text, rows, match.start(), match.end())})
            covered.append(match.span())
    candidates.sort(key=lambda value: value["logical_text_span"]["start"])
    date_mentions = []
    for token in tokens:
        try:
            parsed_date = _date_value(token.group()).isoformat()
            issue = None
        except (ValueError, KeyError, OverflowError):
            parsed_date, issue = None, "invalid_calendar_date"
        date_mentions.append({"date_literal": parsed_date,
            "context": "temporal_candidate" if any(start <= token.start() and token.end() <= end for start, end in covered) else "unassigned_date_mention",
            "issue": issue, **_span(text, rows, token.start(), token.end())})
    return candidates, date_mentions


def _note(note: dict[str, Any]) -> dict[str, Any]:
    rows = note["source_rows"]
    raw_text = "\n".join(row["raw_text"] for row in rows)
    if len(raw_text) > MAX_NOTE_TEXT:
        raise TariffNotesError("Tariff note exceeds its text limit")
    logical_text = " ".join(row["raw_text"] for row in rows)
    temporal, mentions = _temporal_candidates(logical_text, rows)
    signals = []
    for kind, expression in (("act_dependent_timing", _RELATIVE), ("repeal_statement", _REPEAL), ("conditional_context", _CONDITION)):
        for match in expression.finditer(logical_text):
            signals.append({"kind": kind, **_span(logical_text, rows, match.start(), match.end())})
    for country, expression in _COUNTRIES.items():
        for match in expression.finditer(logical_text):
            signals.append({"kind": "country_mention", "country": country,
                            "scope_verified": False, **_span(logical_text, rows, match.start(), match.end())})
    signals.sort(key=lambda signal: signal["logical_text_span"]["start"])
    issues = list(note["issues"])
    if any(signal["kind"] == "act_dependent_timing" for signal in signals):
        issues.append("act_entry_into_force_unresolved")
    if any(signal["kind"] == "repeal_statement" for signal in signals):
        issues.append("repeal_effective_date_unresolved")
    if any(signal["kind"] == "country_mention" for signal in signals):
        issues.append("country_scope_unresolved")
    if any(signal["kind"] == "conditional_context" for signal in signals):
        issues.append("conditions_unresolved")
    if len(temporal) > 1:
        issues.append("multiple_temporal_clauses_preserved")
    if not temporal:
        issues.append("no_absolute_temporal_clause_identified")
    issues.extend(("rate_clause_binding_unresolved", "legal_applicability_unresolved"))
    return {**note, "raw_text": raw_text, "raw_text_sha256": _sha(raw_text.encode("utf-8")),
            "logical_text": logical_text, "temporal_candidates": temporal,
            "date_mentions": mentions, "context_signals": signals,
            "issues": list(dict.fromkeys(issues)), "status": "review_required",
            "legal_dates_verified": False, "can_compile_rate_rule": False}


def extract_tariff_notes(data: bytes, *, artifact_id: str) -> dict[str, Any]:
    """Retain every source row and note occurrence; never infer missing note IDs.

    Latin C and Cyrillic С are source glyph variants for a canonical ``numberC``
    reference. Original labels remain visible. Noncontiguous numbering is allowed:
    a gap is not evidence of a missing note or an incomplete official inventory.
    """
    evidence = extract_pdf_evidence(data, artifact_id=artifact_id)
    notes = []
    unassigned = []
    decoration = []
    issues = []
    current = None
    total_rows = 0
    for page in evidence["pages"]:
        if not page["rows"]:
            issues.append("page_without_extractable_text")
        for row in page["rows"]:
            total_rows += 1
            ref = _row_ref(evidence, page["page"], row)
            text = row["raw_text"]
            if re.fullmatch(r"[_—–-]{3,}", text):
                decoration.append({"kind": "separator", "source_row": ref})
                continue
            centered = abs((row["bbox"][0] + row["bbox"][2]) / 2 - page["width"] / 2) < page["width"] * .15
            margin = row["bbox"][3] < 40 or row["bbox"][1] > page["height"] - 40
            if text == str(page["page"]) and centered and margin:
                decoration.append({"kind": "page_number", "source_row": ref})
                continue
            header = _HEADER.match(text)
            if header:
                number = int(header["number"])
                current = {"footnote_id": f"{number}C", "source_label": header.group(),
                           "number": number, "source_rows": [], "issues": []}
                if number == 0 or header["number"] != str(number):
                    current["issues"].append("noncanonical_numeric_label")
                notes.append(current)
                if len(notes) > MAX_NOTES:
                    raise TariffNotesError("Tariff notes exceed their count limit")
            elif _MARKER_LIKE.match(text):
                issues.append("unsupported_note_marker_retained")
                if current is not None:
                    current["issues"].append("unsupported_note_marker_retained")
            if current is None:
                unassigned.append(ref)
            else:
                current["source_rows"].append(ref)
    counts = Counter(note["footnote_id"] for note in notes)
    duplicates = sorted(key for key, count in counts.items() if count > 1)
    for note in notes:
        if note["footnote_id"] in duplicates:
            note["issues"].append("duplicate_note_id")
    if duplicates:
        issues.append("duplicate_note_ids")
    if not notes:
        issues.append("no_tariff_note_headers_identified")
    observed = [note["number"] for note in notes]
    nonascending = any(before >= after for before, after in zip(observed, observed[1:]))
    if nonascending:
        issues.append("note_number_order_unresolved")
    result = {"schema_version": 1, "mode": "tariff_notes_review", "status": "review_required",
        "artifact_id": evidence["artifact_id"], "artifact_sha256": evidence["artifact_sha256"],
        "size_bytes": evidence["size_bytes"], "page_count": evidence["page_count"],
        "parser": {"name": PARSER_NAME, "version": PARSER_VERSION, "sha256": _sha(Path(__file__).read_bytes())},
        "pdf_parser": evidence["parser"],
        "text_serialization": "raw_text joins exact physical rows with U+000A; logical_text substitutes one U+0020 per row boundary",
        "note_count": len(notes), "unique_note_count": len(counts),
        "duplicate_note_ids": duplicates, "observed_note_ids": [note["footnote_id"] for note in notes],
        "numbering_gaps": [{"after": f"{before}C", "before": f"{after}C"} for before, after in zip(observed, observed[1:]) if after > before + 1],
        "numbering_gaps_imply_missing_source": False,
        "notes": [_note(note) for note in notes], "unassigned_rows": unassigned,
        "decoration_rows": decoration, "source_row_count": total_rows,
        "all_source_rows_accounted": total_rows == len(unassigned) + len(decoration) + sum(len(note["source_rows"]) for note in notes),
        "issues": list(dict.fromkeys(issues)), "legal_inventory_complete": False,
        "legal_dates_verified": False, "can_promote": False, "legal_rates_resolved": 0}
    encoded = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(encoded) > MAX_REPORT_BYTES:
        raise TariffNotesError("Tariff note report exceeds its output limit")
    return result
