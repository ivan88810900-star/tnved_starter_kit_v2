"""Reproducible PDF text evidence; never a legal-rate importer.

Words retain their extracted Unicode and coordinates. ``raw_text`` is explicitly
the words joined by one space, not a claim about the PDF's original whitespace.
Leaf-code candidates and cell *fragments* are useful review locators; effective
dates, hierarchy, continuation and footnote interpretation remain unresolved.
Extraction runs in a bounded child process. Resource limits are not an OS
security sandbox and this module makes no archival/authenticity attestation.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any


PARSER_NAME = "ett_pdf_physical_rows"
PARSER_VERSION = "2"
MAX_PDF_BYTES = 64 * 1024 * 1024
MAX_OUTPUT_BYTES = 32 * 1024 * 1024
MAX_PAGES = 1000
MAX_WORDS = 200_000
MAX_WORD_LENGTH = 20_000
MAX_SPANS = 250_000
WORKER_TIMEOUT_SECONDS = 45
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_LEAF = re.compile(r"^(?:\+ )?([0-9]{4} [0-9]{2} [0-9]{3} [0-9]|[0-9]{10})(?= |$)")
_HEADING = re.compile(r"^(?:\+ )?([0-9]{4}(?: [0-9]{2})?(?: [0-9]{3})?)(?= |$)")


class PDFEvidenceError(ValueError):
    """Bounded, sanitized extraction failure."""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _validate_input(data: bytes, artifact_id: str, chapter: str | None) -> None:
    if not isinstance(data, bytes) or not 8 <= len(data) <= MAX_PDF_BYTES:
        raise PDFEvidenceError("PDF input size is invalid")
    if not data.startswith(b"%PDF-") or b"%%EOF" not in data[-2048:]:
        raise PDFEvidenceError("A complete PDF body is required")
    if not isinstance(artifact_id, str) or not _IDENTIFIER.fullmatch(artifact_id):
        raise PDFEvidenceError("Artifact identifier is invalid")
    if chapter is not None and (not isinstance(chapter, str) or not re.fullmatch(r"[0-9]{2}", chapter) or not 1 <= int(chapter) <= 97 or chapter == "77"):
        raise PDFEvidenceError("Chapter is invalid")


def extract_pdf_evidence(data: bytes, *, artifact_id: str, chapter: str | None = None) -> dict[str, Any]:
    """Extract original bytes into a deterministic, review-only JSON report.

    The input is never opened by the PDF engine in the server process. Child CPU,
    address space, file size, descriptor count and wall-clock time are bounded.
    No caller-controlled executable, PDF filename or command argument is used.
    POSIX resource limits are required; unsupported platforms fail explicitly.
    """
    _validate_input(data, artifact_id, chapter)
    if os.name != "posix":
        raise PDFEvidenceError("PDF extraction requires POSIX resource limits")
    with tempfile.TemporaryDirectory(prefix="ett-pdf-evidence-") as directory:
        root = Path(directory)
        source = root / "source.pdf"
        output = root / "evidence.json"
        source.write_bytes(data)
        # Retain Python's explicit import path for the project's existing venv
        # execution convention. No source URL, cloud credential or app secret is
        # passed to the worker, and the worker changes to a private directory.
        env = {"PATH": os.defpath, "PYTHONPATH": os.pathsep.join(str(Path(p).resolve()) for p in sys.path if p), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8", "LC_ALL": "C.UTF-8"}
        try:
            completed = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), "--worker", str(source), str(output), artifact_id, chapter or ""],
                cwd=root, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, timeout=WORKER_TIMEOUT_SECONDS, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise PDFEvidenceError("PDF extraction exceeded its time limit") from exc
        except OSError as exc:
            raise PDFEvidenceError("PDF extraction worker is unavailable") from exc
        if completed.returncode != 0 or not output.is_file():
            raise PDFEvidenceError("PDF extraction failed or exceeded a resource limit")
        with output.open("rb") as stream:
            result_bytes = stream.read(MAX_OUTPUT_BYTES + 1)
        if len(result_bytes) > MAX_OUTPUT_BYTES:
            raise PDFEvidenceError("PDF evidence exceeds its output limit")
        try:
            report = json.loads(result_bytes)
        except (ValueError, UnicodeError) as exc:
            raise PDFEvidenceError("PDF extraction produced invalid evidence") from exc
        if not isinstance(report, dict) or report.get("artifact_sha256") != _sha(data) or report.get("artifact_id") != artifact_id or report.get("chapter") != chapter:
            raise PDFEvidenceError("PDF extraction provenance mismatch")
        return report


def verify_pdf_evidence(data: bytes, report: dict[str, Any]) -> bool:
    """Re-extract bytes and compare *every* field, including locators and engine.

    Hashing caller-supplied text alone cannot establish that it came from a PDF.
    Evidence produced by a different parser/engine needs an explicit new review.
    """
    if not isinstance(report, dict):
        raise PDFEvidenceError("PDF evidence must be an object")
    try:
        claimed = _canonical(report)
        artifact_id = report["artifact_id"]
        chapter = report["chapter"]
    except (KeyError, TypeError, ValueError, UnicodeError) as exc:
        raise PDFEvidenceError("PDF evidence is invalid") from exc
    if len(claimed) > MAX_OUTPUT_BYTES:
        raise PDFEvidenceError("PDF evidence exceeds its output limit")
    actual = extract_pdf_evidence(data, artifact_id=artifact_id, chapter=chapter)
    if claimed != _canonical(actual):
        raise PDFEvidenceError("PDF evidence does not reproduce from source bytes")
    return True


def _physical_rows(words: list[dict[str, Any]], page_number: int) -> list[dict[str, Any]]:
    """Join co-baseline words; keep word boxes so grouping is independently visible."""
    groups: list[list[dict[str, Any]]] = []
    for word in sorted(words, key=lambda item: (item["bbox"][1], item["bbox"][0], item["source_index"])):
        box = word["bbox"]
        matches: list[list[dict[str, Any]]] = []
        for group in reversed(groups[-4:]):
            anchor = max(group, key=lambda item: item["bbox"][3] - item["bbox"][1])["bbox"]
            overlap = min(box[3], anchor[3]) - max(box[1], anchor[1])
            if overlap >= 0.6 * min(box[3] - box[1], anchor[3] - anchor[1]) and abs(box[3] - anchor[3]) <= 0.6 * max(box[3] - box[1], anchor[3] - anchor[1]):
                matches.append(group)
        if len(matches) == 1:
            matches[0].append(word)
        else:
            groups.append([word])
    groups.sort(key=lambda group: (min(w["bbox"][1] for w in group), min(w["bbox"][0] for w in group)))
    rows = []
    for index, group in enumerate(groups, 1):
        group.sort(key=lambda item: (item["bbox"][0], item["bbox"][1], item["source_index"]))
        raw_text = " ".join(item["text"] for item in group)
        rows.append({"row": f"p{page_number:04d}:r{index:05d}", "raw_text": raw_text, "raw_text_sha256": _sha(raw_text.encode("utf-8")), "bbox": [min(w["bbox"][0] for w in group), min(w["bbox"][1] for w in group), max(w["bbox"][2] for w in group), max(w["bbox"][3] for w in group)], "words": group})
    return rows


def _table_header(rows: list[dict[str, Any]], width: float) -> dict[str, Any] | None:
    words = [word for row in rows for word in row["words"]]
    names = [w for w in words if w["text"] == "Наименование" and width * .25 < w["bbox"][0] < width * .65]
    headers = []
    for name in names:
        nearby = [w for w in words if abs(w["bbox"][1] - name["bbox"][1]) <= 85]
        required = {}
        for token in ("Код", "ТН", "ВЭД", "позиции", "Ставка", "ввозной", "Доп.", "ед.", "изм.", "США)"):
            matches = [w for w in nearby if w["text"] == token]
            if len(matches) != 1:
                break
            required[token] = matches[0]
        if len(required) != 10:
            continue
        unit = [required[token]["bbox"] for token in ("Доп.", "ед.", "изм.")]
        unit_left, unit_right = min(b[0] for b in unit) - 4, max(b[2] for b in unit) + 4
        if not (required["Код"]["bbox"][0] < name["bbox"][0] < unit_left < unit_right < required["Ставка"]["bbox"][0]):
            continue
        header_words = [name, *required.values()]
        headers.append({"top": min(w["bbox"][1] for w in header_words), "bottom": max(w["bbox"][3] for w in header_words), "unit_left": unit_left, "unit_right": unit_right, "evidence_rows": [r["row"] for r in rows if any(w in header_words for w in r["words"])]})
    return headers[0] if len(headers) == 1 else None


def _candidate(row: dict[str, Any], width: float, header: dict[str, Any] | None, chapter: str | None) -> dict[str, Any] | None:
    match = _LEAF.match(row["raw_text"])
    if match is None or row["bbox"][0] > min(190, width * .34):
        return None
    code = match.group(1).replace(" ", "")
    if not 1 <= int(code[:2]) <= 97 or code[:2] == "77":
        return None
    reasons = ["effective_dates_unresolved", "footnote_interpretation_unresolved", "hierarchy_description_unresolved", "continuation_binding_unresolved"]
    result: dict[str, Any] = {"code": code, "row": row["row"], "raw_text_sha256": row["raw_text_sha256"], "status": "unreviewed", "description_fragment": None, "unit_fragment": None, "rate_fragment": None, "unresolved_reasons": reasons}
    if chapter is not None and code[:2] != chapter:
        reasons.append("chapter_mismatch")
    if header is None or row["bbox"][1] < header["bottom"]:
        reasons.append("table_header_unconfirmed")
        return result
    prefix_words = len(match.group(0).split(" "))
    remainder = row["words"][prefix_words:]
    code_words = row["words"][:prefix_words]
    # The full code must be in the left column; clipping into another column or
    # overlapping glyphs makes extraction ambiguous, not a guessed rate.
    if not remainder or max(w["bbox"][2] for w in code_words) >= header["unit_left"] or any(a["bbox"][2] > b["bbox"][0] + 0.5 for a, b in zip(row["words"], row["words"][1:])):
        reasons.append("ambiguous_cell_layout")
        return result
    for field, low, high in (("description_fragment", 0, header["unit_left"]), ("unit_fragment", header["unit_left"], header["unit_right"]), ("rate_fragment", header["unit_right"], width)):
        selected = [w for w in remainder if w["bbox"][0] >= low and w["bbox"][2] <= high]
        crossing = [w for w in remainder if w["bbox"][0] < high and w["bbox"][2] > low and w not in selected]
        if crossing:
            reasons.append("ambiguous_cell_layout")
            result.update(description_fragment=None, unit_fragment=None, rate_fragment=None)
            return result
        result[field] = " ".join(w["text"] for w in selected) or None
    if result["rate_fragment"] is None:
        reasons.append("rate_cell_empty_or_continued")
    return result


def _typography(page, pymupdf, dimensions: list[float]) -> list[dict[str, Any]]:
    """Keep PDF span typography so superscripts are not guessed from digits.

    A word such as '563С)' can contain a base-size '5' and a raised '63С)'.
    Physical row text remains unchanged; this independent coordinate evidence
    lets later assembly distinguish them without slicing arbitrary strings.
    Image payloads are explicitly excluded from this text-only extraction.
    """
    blocks = page.get_text("dict", flags=pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES)["blocks"]
    spans = []
    for block_index, block in enumerate(blocks):
        for line_index, line in enumerate(block.get("lines", [])):
            direction = [round(float(value), 6) for value in line["dir"]]
            if len(direction) != 2 or any(not math.isfinite(value) for value in direction):
                raise PDFEvidenceError("Unsupported text direction")
            for span_index, span in enumerate(line["spans"]):
                if not span["text"]:
                    continue
                box = [round(float(value), 6) for value in span["bbox"]]
                origin = [round(float(value), 6) for value in span["origin"]]
                size = round(float(span["size"]), 6)
                if (len(span["text"]) > MAX_WORD_LENGTH or len(span["font"]) > 512
                    or len(origin) != 2 or any(not math.isfinite(value) for value in (*box, *origin, size))
                    or not 0 < size <= 1000 or box[2] <= box[0] or box[3] <= box[1]
                    or box[0] < -1 or box[1] < -1 or box[2] > dimensions[0] + 1 or box[3] > dimensions[1] + 1):
                    raise PDFEvidenceError("Unsupported PDF span geometry")
                spans.append({"span": f"p{page.number + 1:04d}:s{len(spans) + 1:05d}",
                              "text": span["text"], "bbox": box, "origin": origin,
                              "size": size, "font": span["font"], "flags": span["flags"],
                              "direction": direction, "block": block.get("number", block_index),
                              "line": line_index, "source_index": span_index})
                if len(spans) > MAX_SPANS:
                    raise PDFEvidenceError("PDF span count exceeds its limit")
    return spans


def _extract_worker(data: bytes, artifact_id: str, chapter: str | None) -> dict[str, Any]:
    # Imported only after resource limits are installed by _worker_main.
    import pymupdf

    _validate_input(data, artifact_id, chapter)
    pymupdf.TOOLS.mupdf_display_errors(False)
    pymupdf.TOOLS.mupdf_display_warnings(False)
    with pymupdf.open(stream=data, filetype="pdf") as document:
        if document.needs_pass or document.is_repaired or not 1 <= len(document) <= MAX_PAGES:
            raise PDFEvidenceError("Encrypted, repaired or oversized PDF is unsupported")
        pages = []
        total_words = 0
        total_spans = 0
        all_candidates = []
        for page in document:
            dimensions = [round(float(page.rect.width), 6), round(float(page.rect.height), 6)]
            if page.rotation != 0 or any(not math.isfinite(v) or not 1 <= v <= 20000 for v in dimensions):
                raise PDFEvidenceError("Unsupported PDF page geometry")
            words = []
            for index, item in enumerate(page.get_text("words", sort=False)):
                box = [round(float(v), 6) for v in item[:4]]
                if not item[4] or len(item[4]) > MAX_WORD_LENGTH or any(not math.isfinite(v) for v in box) or box[2] <= box[0] or box[3] <= box[1] or box[0] < -1 or box[1] < -1 or box[2] > dimensions[0] + 1 or box[3] > dimensions[1] + 1:
                    raise PDFEvidenceError("Unsupported PDF text geometry")
                words.append({"text": item[4], "bbox": box, "source_index": index, "block": item[5], "line": item[6], "word": item[7]})
                total_words += 1
                if total_words > MAX_WORDS:
                    raise PDFEvidenceError("PDF word count exceeds its limit")
            rows = _physical_rows(words, page.number + 1)
            text_spans = _typography(page, pymupdf, dimensions)
            total_spans += len(text_spans)
            if total_spans > MAX_SPANS:
                raise PDFEvidenceError("PDF span count exceeds its limit")
            header = _table_header(rows, dimensions[0])
            candidates = []
            hierarchy_count = 0
            for row in rows:
                candidate = _candidate(row, dimensions[0], header, chapter)
                if candidate is not None:
                    candidate["page"] = page.number + 1
                    candidates.append(candidate)
                elif _HEADING.match(row["raw_text"]) and row["bbox"][0] < dimensions[0] * .34:
                    hierarchy_count += 1
            all_candidates.extend(candidates)
            pages.append({"page": page.number + 1, "width": dimensions[0], "height": dimensions[1], "rows": rows, "text_spans": text_spans, "table_header": header, "candidates": candidates, "hierarchy_row_count": hierarchy_count, "unresolved_reasons": [] if words else ["no_extractable_text"]})
        counts: dict[str, int] = {}
        for candidate in all_candidates:
            counts[candidate["code"]] = counts.get(candidate["code"], 0) + 1
        return {"schema_version": 1, "mode": "extraction_review", "artifact_id": artifact_id, "artifact_sha256": _sha(data), "size_bytes": len(data), "chapter": chapter, "parser": {"name": PARSER_NAME, "version": PARSER_VERSION, "sha256": _sha(Path(__file__).read_bytes()), "engine": "pymupdf", "engine_version": pymupdf.VersionBind, "mupdf_version": pymupdf.VersionFitz}, "text_serialization": "physical-row words joined with U+0020; original word text retained", "page_count": len(pages), "word_count": total_words, "candidate_count": len(all_candidates), "unique_candidate_count": len(counts), "duplicate_candidate_codes": sorted(code for code, count in counts.items() if count > 1), "pages": pages, "legal_rates_resolved": 0, "can_promote": False, "unresolved_reasons": ["effective_dates_not_interpreted", "footnotes_not_interpreted", "cross_row_and_page_continuations_not_bound", "full_hierarchy_descriptions_not_resolved", "current_legal_inventory_not_verified"]}


if __name__ == "__main__":
    # This fixed-file private worker interface is intentionally not a public CLI.
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (1024 * 1024 * 1024,) * 2)
        resource.setrlimit(resource.RLIMIT_CPU, (30, 30))
        resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_OUTPUT_BYTES, MAX_OUTPUT_BYTES))
        resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        if len(sys.argv) != 6 or sys.argv[1] != "--worker":
            raise PDFEvidenceError("Invalid worker invocation")
        source, output, artifact_id, chapter = sys.argv[2:6]
        with Path(source).open("rb") as stream:
            body = stream.read(MAX_PDF_BYTES + 1)
        result = _canonical(_extract_worker(body, artifact_id, chapter or None))
        if len(result) > MAX_OUTPUT_BYTES:
            raise PDFEvidenceError("PDF evidence exceeds its output limit")
        Path(output).write_bytes(result)
    except Exception:
        sys.exit(2)
