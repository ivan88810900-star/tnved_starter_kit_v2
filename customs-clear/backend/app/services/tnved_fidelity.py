"""Source-ordered structural projection. PDF input is never a legal admission.

Extraction uses Poppler word coordinates, independently of the old layout-text
catalog/SQLite. Only header-gated table code cells may introduce tariff codes.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET

NS = {"p": "http://www.w3.org/1999/xhtml"}


def compact(text: str) -> str:
    return re.sub(r"[\s\u00ad\u200b]", "", text)


def extract_pdf_rows(pdf: Path, chapter: str, pdftotext: str) -> dict:
    raw = pdf.read_bytes()
    source_sha = hashlib.sha256(raw).hexdigest()
    xml = subprocess.check_output([pdftotext, "-bbox", "-enc", "UTF-8", str(pdf), "-"], stderr=subprocess.PIPE)
    pages = ET.fromstring(xml).findall(".//p:page", NS)
    rows, reserved, issues, table_pages = [], [], [], []
    pending = None
    for page_number, page in enumerate(pages, 1):
        words = [(float(w.get("xMin")), float(w.get("yMin")), float(w.get("xMax")), float(w.get("yMax")), w.text or "") for w in page.findall(".//p:word", NS)]
        names = [w for w in words if w[4] == "Наименование"]
        bottoms = [w for w in words if w[4] == "долларах"]
        if not names:
            continue
        if len(names) != 1 or len(bottoms) != 1:
            issues.append({"page": page_number, "kind": "ambiguous_table_header"})
            continue
        table_pages.append(page_number)
        # These gaps are validated against every full code cell and the separate
        # retained physical-cell inventory. Neither rates nor prose references
        # outside the code column can become codes.
        body = [w for w in words if w[1] >= bottoms[0][3] and w[0] < 399]
        lines = []
        for word in sorted((w for w in body if w[3] - w[1] > 10), key=lambda w: (w[3], w[0])):
            match = next((line for line in reversed(lines[-3:]) if abs(line[0] - word[3]) < 3), None)
            if match is None:
                lines.append([word[3], [word]])
            else:
                match[1].append(word)
        for word in (w for w in body if w[3] - w[1] <= 10):
            if not lines:
                issues.append({"page": page_number, "kind": "unattached_small_glyph", "text": word[4]})
                continue
            def overlap(line):
                top, bottom = min(w[1] for w in line[1]), max(w[3] for w in line[1])
                return max(0, min(bottom, word[3]) - max(top, word[1])), -abs(top + bottom - word[1] - word[3])
            max(lines, key=overlap)[1].append(word)
        for baseline, words_on_line in lines:
            words_on_line.sort(key=lambda w: w[0])
            code_cell = "".join(w[4] for w in words_on_line if w[0] < 180)
            label = " ".join(w[4] for w in words_on_line if w[0] >= 180)
            symbol = "+" if "+" in code_cell else ""
            cell = code_cell.replace("+", "")
            if re.fullmatch(r"\[\d{4}\]", cell):
                if pending is not None:
                    rows.append(pending)
                    pending = None
                reserved.append({"code": cell[1:-1], "page": page_number})
                continue
            if cell and not (cell.isascii() and cell.isdigit() and len(cell) in (4, 6, 8, 9, 10) and cell.startswith(chapter)):
                issues.append({"page": page_number, "kind": "unparsed_code_cell", "cell": code_cell, "label": label})
                continue
            is_caption = bool(re.match(r"^[IVX]+\.\s+[А-ЯЁ]", label))
            is_dash = bool(re.match(r"^–(?:\s|$)", label))
            if cell or is_caption or is_dash:
                if pending is not None:
                    rows.append(pending)
                pending = {"code": cell or None, "label": label, "page": page_number, "baseline": round(baseline, 3), "change_symbol": symbol, "kind": "caption" if is_caption else "coded" if cell else "codeless"}
            elif label:
                if pending is None:
                    issues.append({"page": page_number, "kind": "orphan_continuation", "label": label})
                else:
                    pending["label"] += " " + label
    if pending is not None:
        rows.append(pending)
    stack = []
    for order, row in enumerate(rows):
        row["source_order"] = order
        prefix = re.match(r"^(?:–\s*)*", row["label"]).group()
        row["depth"] = -1 if row["kind"] == "caption" else prefix.count("–")
        row["label"] = row["label"][len(prefix):].strip()
        row["source_row_id"] = f"p{row['page']}-y{row['baseline']:.3f}"
        row["id"] = row["code"] or "u-" + hashlib.sha256(f"{source_sha}:{row['source_row_id']}".encode()).hexdigest()[:24]
        while stack and stack[-1]["depth"] >= row["depth"]:
            stack.pop()
        row["parent_id"] = stack[-1]["id"] if stack else chapter
        row["path"] = [item["label"] for item in stack] + [row["label"]]
        row["code_parent"] = next((item["code"] for item in reversed(stack) if item["code"]), chapter)
        stack.append(row)
    return {"chapter": chapter, "source_sha256": source_sha, "pages": len(pages), "table_pages": table_pages, "rows": rows, "reserved": reserved, "issues": issues}


NAVIGATION_SCHEMA = """
CREATE TABLE recovery_navigation (
 id TEXT PRIMARY KEY, code TEXT UNIQUE, label TEXT NOT NULL, parent_id TEXT,
 chapter TEXT, source_order INTEGER NOT NULL, source_id TEXT NOT NULL,
 page INTEGER, source_row_id TEXT, kind TEXT NOT NULL, path_json TEXT NOT NULL,
 printed_code TEXT NOT NULL, change_symbol TEXT NOT NULL,
 FOREIGN KEY(parent_id) REFERENCES recovery_navigation(id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(source_id) REFERENCES recovery_sources(id)
);
CREATE INDEX recovery_navigation_parent ON recovery_navigation(parent_id,source_order);
CREATE INDEX recovery_navigation_chapter ON recovery_navigation(chapter,source_order);
CREATE TABLE recovery_heading_aliases (
 heading_code TEXT PRIMARY KEY, node_id TEXT NOT NULL,
 FOREIGN KEY(node_id) REFERENCES recovery_navigation(id)
);
"""


def printed_code(code: str) -> str:
    if len(code) <= 4:
        return code
    groups = [code[:4], code[4:6]]
    if len(code) > 6:
        groups.append(code[6:9])
    if len(code) > 9:
        groups.append(code[9:])
    return " ".join(groups)
