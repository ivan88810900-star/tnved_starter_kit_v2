"""Assemble evidence-backed ETT table cells; no rate or date interpretation.

Only the public byte-input function establishes extraction provenance. Physical
rows remain unchanged and all joins are explicit U+0020 joins. Hierarchy is a
display path of source labels, never a new legal description. Tables without a
complete header, broken continuations and ambiguous cells remain unresolved.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from app.services.ett_pdf_evidence import PDFEvidenceError, extract_pdf_evidence


ASSEMBLER_NAME = "ett_coordinate_table_rows"
ASSEMBLER_VERSION = "1"
MAX_ASSEMBLY_BYTES = 64 * 1024 * 1024
_CODE = re.compile(r"^(?:\+ )?([0-9]{4}(?: [0-9]{2}(?: (?:[0-9]{3}(?: [0-9])?|[0-9]{2}))?)?|[0-9]{10})(?= |$)")
_DASHES = re.compile(r"^(?P<dashes>(?:[–−-]\s*)+)(?P<label>.*)$")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def assemble_pdf_table(data: bytes, *, artifact_id: str, chapter: str) -> dict[str, Any]:
    """Extract source bytes afresh and return candidate table rows with evidence.

    No public entry point accepts an alleged verified report. The resulting
    report contains no legally resolved rates, dates or promotion permission.
    """
    if not isinstance(chapter, str) or not re.fullmatch(r"[0-9]{2}", chapter) or not 1 <= int(chapter) <= 97 or chapter == "77":
        raise PDFEvidenceError("Table assembly requires a valid explicit chapter")
    report = extract_pdf_evidence(data, artifact_id=artifact_id, chapter=chapter)
    result = _assemble_report(report)
    size = 0
    for chunk in json.JSONEncoder(ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).iterencode(result):
        size += len(chunk.encode())
        if size > MAX_ASSEMBLY_BYTES:
            raise PDFEvidenceError("Table assembly exceeds its output limit")
    return result


def _header(page: dict[str, Any]) -> dict[str, Any] | None:
    """Confirm labels by both column and baseline, excluding body occurrences.

    The header text supplies an explicit conservative coordinate band around the
    unit labels. Any word crossing a boundary invalidates cell assembly; a body
    occurrence of 'позиции' cannot invalidate an otherwise complete header.
    """
    words = [word for row in page["rows"] for word in row["words"]]
    found = []
    names = [word for word in words if word["text"] == "Наименование" and page["width"] * .25 < word["bbox"][0] < page["width"] * .65]
    if len(names) > 8:
        return None
    for name in names:
        ny, nx = name["bbox"][1], name["bbox"][0]
        selected = {"Наименование": name}
        for token, region, y_min, y_max in (
            ("позиции", "description", -3, 3), ("Код", "code", -20, 0),
            ("ТН", "code", 0, 20), ("ВЭД", "code", 0, 20),
            ("Доп.", "unit", -25, 0), ("ед.", "unit", -3, 3),
            ("изм.", "unit", 0, 25), ("Ставка", "rate", -70, -20),
            ("ввозной", "rate", -70, -20), ("США)", "rate", 30, 75),
        ):
            choices = []
            for word in words:
                x, y, right, _ = word["bbox"]
                spatial = (right < nx if region == "code" else
                           nx <= x < page["width"] * .67 if region == "description" else
                           page["width"] * .66 < x < page["width"] * .74 if region == "unit" else
                           x > page["width"] * .74)
                if word["text"] == token and spatial and y_min <= y - ny <= y_max:
                    choices.append(word)
            if len(choices) != 1:
                break
            selected[token] = choices[0]
        if len(selected) != 11:
            continue
        unit_boxes = [selected[t]["bbox"] for t in ("Доп.", "ед.", "изм.")]
        top = min(w["bbox"][1] for w in selected.values())
        bottom = max(w["bbox"][3] for w in selected.values())
        unit_left = min(b[0] for b in unit_boxes) - 8
        unit_right = max(b[2] for b in unit_boxes) + 8
        percent = [w for w in words if w["text"] == "процентах" and w["bbox"][0] > unit_right and top <= w["bbox"][1] <= bottom]
        if not selected["позиции"]["bbox"][2] < unit_left < unit_right < selected["Ставка"]["bbox"][0] or len(percent) != 1:
            continue
        description_starts = []
        for row in page["rows"]:
            code, prefix_count = _code_prefix(row, page["width"])
            if code and row["bbox"][1] >= bottom and len(row["words"]) > prefix_count:
                first = row["words"][prefix_count]
                if first["bbox"][2] < unit_left:
                    description_starts.append((first["bbox"][0], _reference(page, row)))
        anchor = min((start[0] for start in description_starts), default=None)
        found.append({"page": page["page"], "top": top, "bottom": bottom,
                      "unit_left": unit_left, "unit_right": unit_right,
                      "description_anchor": anchor,
                      "description_anchor_source": next((ref for x, ref in description_starts if x == anchor), None),
                      "percent_header_confirmed": True,
                      "source_rows": [_reference(page, row) for row in page["rows"] if row["bbox"][1] >= top - .5 and row["bbox"][3] <= bottom + .5]})
    return found[0] if len(found) == 1 else None


def _reference(page: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    return {"page": page["page"], "row": row["row"], "raw_text": row["raw_text"],
            "raw_text_sha256": row["raw_text_sha256"], "bbox": row["bbox"]}


def _code_prefix(row: dict[str, Any], width: float) -> tuple[str | None, int]:
    match = _CODE.match(row["raw_text"])
    if match is None or row["bbox"][0] >= width * .30:
        return None, 0
    code = match.group(1).replace(" ", "")
    if len(code) not in {4, 6, 8, 9, 10} or not 1 <= int(code[:2]) <= 97 or code[:2] == "77":
        return None, 0
    return code, len(match.group(0).split())


def _cells(row: dict[str, Any], header: dict[str, Any], prefix_words: int) -> tuple[dict[str, list[dict]], list[str]]:
    result: dict[str, list[dict]] = {"description": [], "unit": [], "duty": []}
    issues = []
    for word in row["words"][prefix_words:]:
        left, _, right, _ = word["bbox"]
        if right <= header["unit_left"]:
            field = "description"
        elif left >= header["unit_left"] and right <= header["unit_right"]:
            field = "unit"
        elif left >= header["unit_right"]:
            field = "duty"
        else:
            # A long description word can protrude into the padding around the
            # unit header. Its original PDF text-line identity can bind it only
            # when another word in that same text line anchors the description,
            # and the protrusion ends before the actual unit header starts.
            anchors = [w for w in row["words"][prefix_words:] if w is not word and
                       (w["block"], w["line"]) == (word["block"], word["line"]) and
                       w["bbox"][2] < header["unit_left"]]
            if left < header["unit_left"] - 8 and right <= header["unit_left"] + 8 and (anchors or left < header["unit_left"] - 40):
                field = "description"
            else:
                issues.append("word_crosses_cell_boundary")
                continue
        result[field].append(word)
    # Overlap within a cell (including overprinted text) has no unique reading.
    for words in result.values():
        if any(a["bbox"][2] > b["bbox"][0] + .5 for a, b in zip(words, words[1:])):
            issues.append("overlapping_cell_words")
    remainder = row["words"][prefix_words:]
    if any(a["bbox"][2] > b["bbox"][0] + .5 for a, b in zip(remainder, remainder[1:])):
        issues.append("overlapping_cell_words")
    return result, sorted(set(issues))


def _text(words: list[dict]) -> str:
    return " ".join(w["text"] for w in words)


def _depth(text: str) -> tuple[int, str]:
    match = _DASHES.match(text)
    if match is None:
        return 0, text
    return sum(c in "–−-" for c in match.group("dashes")), match.group("label")


def _assemble_report(report: dict[str, Any]) -> dict[str, Any]:
    """Private transformation; callers must use source bytes for provenance."""
    records: list[dict[str, Any]] = []
    headings: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    headers: list[dict[str, Any]] = []
    stack: dict[int, dict[str, Any]] = {}
    current: dict[str, Any] | None = None
    subchapter: dict[str, Any] | None = None
    previous_header: dict[str, Any] | None = None
    page_headers = [_header(page) for page in report["pages"]]
    for header in page_headers:
        if header is None or header["description_anchor"] is not None:
            continue
        # Some opening table pages contain only a Roman subchapter title. Use an
        # actual coded row in this same PDF only when every compatible page
        # agrees on the column anchor; retain the exact anchor's source locator.
        peers = [h for h in page_headers if h is not None and h["description_anchor"] is not None and
                 all(abs(h[k] - header[k]) <= .75 for k in ("unit_left", "unit_right"))]
        if peers and max(h["description_anchor"] for h in peers) - min(h["description_anchor"] for h in peers) <= .75:
            header["description_anchor"] = peers[0]["description_anchor"]
            header["description_anchor_source"] = peers[0]["description_anchor_source"]

    def finish() -> None:
        nonlocal current, subchapter
        if current is None:
            return
        raw_description = " ".join(current.pop("description_parts"))
        _, description = _depth(raw_description)
        current["description_raw"] = raw_description or None
        current["leaf_description"] = description or None
        current["unit_raw"] = " ".join(current.pop("unit_parts")) or None
        current["duty_raw"] = " ".join(current.pop("duty_parts")) or None
        depth = current["depth"]
        if current["kind"] == "subchapter":
            current["issues"] = sorted(set(current["issues"]))
            subchapter = {"description": description, "source_rows": current["source_rows"], "issues": current["issues"]}
            headings.append(current)
            current = None
            return
        # A node supersedes only siblings and descendants, never a lower parent.
        for level in list(stack):
            if level >= depth:
                del stack[level]
        parents = [stack[level] for level in sorted(stack)]
        hierarchy_ok = sorted(stack) == list(range(depth)) and bool(description) and not current["issues"]
        if any(p["issues"] or not p["leaf_description"] for p in parents):
            hierarchy_ok = False
        if current["code"] and any(p["code"] and not current["code"].startswith(p["code"]) for p in parents):
            hierarchy_ok = False
        current["heading_contexts"] = [{"code": p["code"], "depth": p["depth"], "description": p["leaf_description"], "source_rows": p["source_rows"]} for p in parents]
        current["subchapter_context"] = subchapter
        if subchapter and subchapter["issues"]:
            hierarchy_ok = False
        if not hierarchy_ok:
            current["issues"].append("hierarchy_unresolved")
        if not description:
            current["issues"].append("description_empty")
        if current["kind"] == "commodity":
            if not current["duty_raw"]:
                current["issues"].append("duty_cell_empty")
            if not current["unit_raw"]:
                current["issues"].append("unit_cell_empty")
            current["full_description"] = " / ".join([p["leaf_description"].rstrip(":") for p in parents] + [description]) if hierarchy_ok else None
            layout_issues = set(current["issues"]) - {"hierarchy_unresolved"}
            current["cell_status"] = "assembled" if not layout_issues else "unresolved"
            records.append(current)
        else:
            if current["duty_raw"] or current["unit_raw"]:
                current["issues"].append("non_leaf_has_payment_cell")
            headings.append(current)
            stack[depth] = current
        current["issues"] = sorted(set(current["issues"]))
        current = None

    for page, header in zip(report["pages"], page_headers):
        if header is None:
            if current is not None:
                current["issues"].append("unconfirmed_page_break")
            finish()
            stack.clear()
            subchapter = None
            previous_header = None
            for candidate in page["candidates"]:
                excluded.append({"code": candidate["code"], "page": page["page"], "row": candidate["row"], "reason": "outside_confirmed_table"})
            continue
        headers.append(header)
        compatible = previous_header is not None and previous_header["page"] + 1 == page["page"] and all(abs(previous_header[k] - header[k]) <= .75 for k in ("unit_left", "unit_right"))
        if current is not None and not compatible:
            current["issues"].append("unconfirmed_page_break")
            finish()
            stack.clear()
        previous_header = header
        table_active = True
        for row in page["rows"]:
            if row["bbox"][1] < header["bottom"]:
                for candidate in page["candidates"]:
                    if candidate["row"] == row["row"]:
                        excluded.append({"code": candidate["code"], "page": page["page"], "row": row["row"], "reason": "before_table_header"})
                continue
            if re.fullmatch(r"\[[0-9]{4}\]", row["raw_text"]) and row["bbox"][0] < page["width"] * .30:
                # Reserved/deleted headings are printed in brackets. Retain the
                # boundary, but never pad one into an invented commodity code.
                finish()
                stack.clear()
                issues.append({"page": page["page"], "row": row["row"], "reason": "reserved_heading", "source": _reference(page, row)})
                continue
            code, prefix_words = _code_prefix(row, page["width"])
            if not table_active:
                if code and len(code) == 10:
                    excluded.append({"code": code, "page": page["page"], "row": row["row"], "reason": "after_table_narrative"})
                continue
            cells, cell_issues = _cells(row, header, prefix_words)
            description = _text(cells["description"])
            depth, label = _depth(description)
            # The dash hierarchy starts at the same horizontal anchor as coded
            # descriptions. An indented dash inside a product's multi-line
            # composition is part of that product, not a new hierarchy node.
            uncoded_heading = code is None and depth > 0 and header["description_anchor"] is not None and abs(row["bbox"][0] - header["description_anchor"]) <= 1 and not cells["unit"] and not cells["duty"] and not cell_issues
            section_heading = code is None and re.match(r"^[IVX]+\. [А-ЯЁA-Z]", description) is not None and header["description_anchor"] is not None and abs(row["bbox"][0] - header["description_anchor"]) <= 1 and not cells["unit"] and not cells["duty"] and not cell_issues
            if code and code[:2] != report["chapter"]:
                if current is not None:
                    current["issues"].append("cross_chapter_row")
                finish()
                stack.clear()
                excluded.append({"code": code, "page": page["page"], "row": row["row"], "reason": "chapter_mismatch"})
                continue
            # Full-width narrative/footnotes are outside the commodity columns.
            # A page number is also not a description continuation.
            if code is None and not uncoded_heading and (row["bbox"][0] < page["width"] * .30 or (row["raw_text"].isdigit() and row["bbox"][1] > page["height"] * .93)):
                if current is not None:
                    current["issues"].append("unconfirmed_table_end")
                finish()
                stack.clear()
                table_active = False
                issues.append({"page": page["page"], "row": row["row"], "reason": "table_ended_at_narrative"})
                continue
            if code is not None or uncoded_heading or section_heading:
                finish()
                if section_heading:
                    stack.clear()
                current = {"kind": "subchapter" if section_heading else "commodity" if code and len(code) == 10 else "heading",
                           "code": code, "depth": depth, "description_parts": [], "unit_parts": [], "duty_parts": [],
                           "source_rows": [], "cell_rows": [], "header_pages": [], "issues": [], "percent_header_confirmed": True}
            if current is None:
                issues.append({"page": page["page"], "row": row["row"], "reason": "orphan_table_continuation"})
                continue
            if code is None and depth > 0 and header["description_anchor"] is not None and abs(row["bbox"][0] - header["description_anchor"]) <= 1 and (cells["unit"] or cells["duty"]):
                cell_issues.append("uncoded_row_has_payment_cells")
            current["issues"].extend(cell_issues)
            current["source_rows"].append(_reference(page, row))
            duty_lines = {(w["block"], w["line"]) for w in cells["duty"]}
            duty_spans = [span for span in page.get("text_spans", []) if (span["block"], span["line"]) in duty_lines and span["bbox"][0] >= header["unit_right"]]
            current["cell_rows"].append({"page": page["page"], "row": row["row"], "description_words": cells["description"], "unit_words": cells["unit"], "duty_words": cells["duty"], "duty_spans": duty_spans})
            if page["page"] not in current["header_pages"]:
                current["header_pages"].append(page["page"])
            for field in ("description", "unit", "duty"):
                text = _text(cells[field])
                if text:
                    current[f"{field}_parts"].append(text)
    finish()
    counts = Counter(row["code"] for row in records)
    duplicates = sorted(code for code, count in counts.items() if count > 1)
    duplicate_set = set(duplicates)
    for row in records:
        if row["code"] in duplicate_set:
            row["issues"] = sorted(set(row["issues"]) | {"duplicate_table_code"})
            row["cell_status"] = "unresolved"
    return {"schema_version": 1, "mode": "table_assembly_review", "artifact_id": report["artifact_id"],
            "artifact_sha256": report["artifact_sha256"], "chapter": report["chapter"], "size_bytes": report["size_bytes"],
            "extraction_parser": report["parser"], "extraction_report_sha256": _sha(_canonical(report)),
            "assembler": {"name": ASSEMBLER_NAME, "version": ASSEMBLER_VERSION, "sha256": _sha(Path(__file__).read_bytes())},
            "text_serialization": "Cell rows joined by U+0020; hierarchy labels joined by ' / '; source text is retained",
            "page_count": report["page_count"], "headers": headers, "records": records, "headings": headings,
            "source_pages_without_text": [page["page"] for page in report["pages"] if not page["rows"]],
            # Notes/narrative pages legitimately lack a table header. This list
            # preserves coverage diagnostics without pretending every such page
            # is a missing commodity table or silently dropping image-only pages.
            "source_pages_without_headers": [page["page"] for page, header in zip(report["pages"], page_headers) if header is None],
            "excluded_candidates": excluded, "issues": issues, "record_count": len(records), "unique_code_count": len(counts),
            "duplicate_codes": duplicates, "assembled_cell_count": sum(r["cell_status"] == "assembled" for r in records),
            "resolved_description_count": sum(r["full_description"] is not None for r in records),
            "legal_rates_resolved": 0, "current_edition_verified": False, "can_promote": False}
