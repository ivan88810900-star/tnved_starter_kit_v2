"""Bounded metadata for explicitly selected original PDF pages.

This opt-in helper permits OCR review of selected pages when the full native
text extractor rejects a document's size or rotation. It produces no source
rows, quotes, OCR, legal interpretation, or replacement PDF. The PDF engine
opens the original bytes only inside a resource-limited child process.
"""
from __future__ import annotations

import hashlib
from importlib import metadata
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile


PARSER_NAME = "ett_selected_pdf_page_inspection"
PARSER_VERSION = "1"
MAX_PDF_BYTES = 64 * 1024 * 1024
MAX_SELECTED_PAGES = 64
MAX_PAGE_NUMBER = 2_147_483_647
MAX_OUTPUT_BYTES = 256 * 1024
MAX_PAGE_TEXT_BYTES = 2 * 1024 * 1024
WORKER_TIMEOUT_SECONDS = 45
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_VERSION = re.compile(r"[0-9][A-Za-z0-9.+_-]{0,63}\Z")
_FALSE_FLAGS = (
    "native_text_quotes_included", "native_text_rows_included",
    "legal_identity_verified", "legal_effective_dates_verified",
    "can_promote", "production_ready",
)


class PDFPageInspectionError(ValueError):
    """Sanitized metadata inspection failure; no legal evidence is produced."""


def _sha(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _validate_input(data: bytes, artifact_id: str, pages: tuple[int, ...]) -> None:
    if type(data) is not bytes or not 8 <= len(data) <= MAX_PDF_BYTES:
        raise PDFPageInspectionError("invalid_pdf_size")
    if not data.startswith(b"%PDF-") or b"%%EOF" not in data[-2048:]:
        raise PDFPageInspectionError("incomplete_pdf_input")
    if type(artifact_id) is not str or not _IDENTIFIER.fullmatch(artifact_id):
        raise PDFPageInspectionError("invalid_artifact_identifier")
    if (type(pages) is not tuple or not 1 <= len(pages) <= MAX_SELECTED_PAGES
            or any(type(page) is not int or not 1 <= page <= MAX_PAGE_NUMBER for page in pages)
            or len(set(pages)) != len(pages)):
        raise PDFPageInspectionError("invalid_page_selection")


def _parse_json(body: bytes):
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    def invalid_constant(_):
        raise ValueError("nonfinite number")

    return json.loads(body, object_pairs_hook=unique_pairs, parse_constant=invalid_constant)


def _validate_report(report, *, data: bytes, artifact_id: str, pages: tuple[int, ...], parser_sha256: str, engine_version: str) -> None:
    keys = {"schema_version", "kind", "artifact_id", "artifact_sha256", "size_bytes",
            "page_count", "selected_pages", "pages", "parser", *_FALSE_FLAGS}
    if type(report) is not dict or set(report) != keys:
        raise PDFPageInspectionError("invalid_page_inspection_shape")
    exact = {"schema_version": 1, "kind": PARSER_NAME, "artifact_id": artifact_id,
             "artifact_sha256": _sha(data), "size_bytes": len(data)}
    if any(type(report[key]) is not type(value) or report[key] != value for key, value in exact.items()):
        raise PDFPageInspectionError("page_inspection_provenance_mismatch")
    if any(report[key] is not False for key in _FALSE_FLAGS):
        raise PDFPageInspectionError("page_inspection_claims_not_allowed")
    page_count = report["page_count"]
    if type(page_count) is not int or not 1 <= page_count <= MAX_PAGE_NUMBER or any(page > page_count for page in pages):
        raise PDFPageInspectionError("invalid_page_count")
    selection = report["selected_pages"]
    if type(selection) is not list or any(type(page) is not int for page in selection) or selection != sorted(pages):
        raise PDFPageInspectionError("page_inspection_scope_mismatch")
    parser = report["parser"]
    if type(parser) is not dict or set(parser) != {"name", "version", "sha256", "engine", "engine_version", "mupdf_version"}:
        raise PDFPageInspectionError("invalid_page_inspection_parser")
    expected = {"name": PARSER_NAME, "version": PARSER_VERSION, "sha256": parser_sha256,
                "engine": "pymupdf", "engine_version": engine_version}
    if any(type(parser[key]) is not str or parser[key] != value for key, value in expected.items()):
        raise PDFPageInspectionError("page_inspection_parser_mismatch")
    if type(parser["mupdf_version"]) is not str or not _VERSION.fullmatch(parser["mupdf_version"]):
        raise PDFPageInspectionError("invalid_page_inspection_engine")
    items = report["pages"]
    if type(items) is not list or len(items) != len(pages):
        raise PDFPageInspectionError("page_inspection_scope_mismatch")
    for expected_page, item in zip(selection, items):
        if type(item) is not dict or set(item) != {"page", "width", "height", "rotation", "native_text_present"}:
            raise PDFPageInspectionError("invalid_selected_page_metadata")
        if type(item["page"]) is not int or item["page"] != expected_page:
            raise PDFPageInspectionError("page_inspection_scope_mismatch")
        if type(item["rotation"]) is not int or item["rotation"] not in (0, 90, 180, 270) or type(item["native_text_present"]) is not bool:
            raise PDFPageInspectionError("invalid_selected_page_metadata")
        if any(type(item[key]) not in (int, float) or not 1 <= item[key] <= 20000 or not math.isfinite(item[key]) or round(item[key], 6) != item[key] for key in ("width", "height")):
            raise PDFPageInspectionError("invalid_selected_page_geometry")


def _read_output(path: Path) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        before = os.fstat(descriptor)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid()
                or before.st_nlink != 1 or not 0 < before.st_size <= MAX_OUTPUT_BYTES):
            raise PDFPageInspectionError("invalid_page_inspection_output")
        with os.fdopen(descriptor, "rb", closefd=False) as output:
            body = output.read(MAX_OUTPUT_BYTES + 1)
        after = os.fstat(descriptor)
        identity = lambda value: (value.st_dev, value.st_ino, value.st_mode, value.st_nlink, value.st_uid, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
        if len(body) != before.st_size or len(body) > MAX_OUTPUT_BYTES or identity(before) != identity(after):
            raise PDFPageInspectionError("page_inspection_output_changed_or_oversized")
        return body
    finally:
        os.close(descriptor)


def inspect_selected_pdf_pages(
    data: bytes, *, artifact_id: str, pages: tuple[int, ...], timeout_seconds: float = 45,
) -> dict:
    """Inspect at most 64 explicit original page numbers, without native quotes.

    ``page_count`` refers to the original document. Only ``selected_pages`` are
    loaded; a successful report makes no completeness claim about other pages.
    ``width`` and ``height`` are the displayed dimensions after PDF rotation.
    Resource limits contain ordinary processing costs, not a security sandbox.
    """
    _validate_input(data, artifact_id, pages)
    if type(timeout_seconds) not in (int, float) or not 0 < timeout_seconds <= WORKER_TIMEOUT_SECONDS or not math.isfinite(timeout_seconds):
        raise PDFPageInspectionError("invalid_inspection_timeout")
    if os.name != "posix":
        raise PDFPageInspectionError("page_inspection_requires_posix_resource_limits")
    try:
        engine_version = metadata.version("PyMuPDF")
        if not _VERSION.fullmatch(engine_version):
            raise PDFPageInspectionError("unsupported_page_inspection_engine")
        module = Path(__file__).resolve()
        parser_sha256 = _sha(module.read_bytes())
        with tempfile.TemporaryDirectory(prefix="ett-pdf-page-inspection-") as directory:
            root = Path(directory)
            source, output = root / "original.pdf", root / "metadata.json"
            source.write_bytes(data)
            source.chmod(0o600)
            env = {"PATH": os.defpath, "PYTHONPATH": os.pathsep.join(str(Path(p).resolve()) for p in sys.path if p),
                   "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8", "LC_ALL": "C.UTF-8"}
            try:
                completed = subprocess.run(
                    [sys.executable, str(module), "--worker", str(source), str(output), artifact_id, ",".join(map(str, sorted(pages)))],
                    cwd=root, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, timeout=timeout_seconds, check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise PDFPageInspectionError("page_inspection_time_limit") from exc
            if completed.returncode != 0:
                raise PDFPageInspectionError("page_inspection_failed_or_resource_limit")
            report = _parse_json(_read_output(output))
            _validate_report(report, data=data, artifact_id=artifact_id, pages=pages,
                             parser_sha256=parser_sha256, engine_version=engine_version)
            return report
    except PDFPageInspectionError:
        raise
    except (ValueError, OSError, UnicodeError, RecursionError, OverflowError, metadata.PackageNotFoundError) as exc:
        raise PDFPageInspectionError("page_inspection_unavailable_or_invalid") from exc


def _inspect_worker(data: bytes, artifact_id: str, selection: tuple[int, ...]) -> dict:
    # Import the PDF engine only after _worker_main applies process limits.
    import pymupdf

    _validate_input(data, artifact_id, selection)
    pymupdf.TOOLS.mupdf_display_errors(False)
    pymupdf.TOOLS.mupdf_display_warnings(False)
    with pymupdf.open(stream=data, filetype="pdf") as document:
        # Empty-password encryption may authenticate automatically and clear
        # is_encrypted; the original trailer still identifies encryption.
        if document.needs_pass or document.is_encrypted or document.is_repaired or document.xref_get_key(-1, "Encrypt")[0] != "null":
            raise PDFPageInspectionError("encrypted_or_repaired_pdf_unsupported")
        count = document.page_count
        if not 1 <= count <= MAX_PAGE_NUMBER or any(number > count for number in selection):
            raise PDFPageInspectionError("page_outside_source_pdf")
        pages = []
        for number in sorted(selection):
            page = document.load_page(number - 1)
            dimensions = [round(float(page.rect.width), 6), round(float(page.rect.height), 6)]
            if page.rotation not in (0, 90, 180, 270) or any(not math.isfinite(value) or not 1 <= value <= 20000 for value in dimensions):
                raise PDFPageInspectionError("unsupported_selected_page_geometry")
            # Images are explicitly omitted. The string exists only in this
            # bounded worker and is discarded; no quote/hash/row is emitted.
            text = page.get_text("text", flags=pymupdf.TEXTFLAGS_TEXT & ~pymupdf.TEXT_PRESERVE_IMAGES, sort=False)
            if len(text) > MAX_PAGE_TEXT_BYTES or len(text.encode("utf-8")) > MAX_PAGE_TEXT_BYTES:
                raise PDFPageInspectionError("selected_page_native_text_limit")
            pages.append({"page": number, "width": dimensions[0], "height": dimensions[1],
                          "rotation": page.rotation, "native_text_present": bool(text.strip())})
            del text, page
    return {"schema_version": 1, "kind": PARSER_NAME, "artifact_id": artifact_id,
            "artifact_sha256": _sha(data), "size_bytes": len(data), "page_count": count,
            "selected_pages": sorted(selection), "pages": pages,
            "parser": {"name": PARSER_NAME, "version": PARSER_VERSION, "sha256": _sha(Path(__file__).read_bytes()),
                       "engine": "pymupdf", "engine_version": pymupdf.VersionBind, "mupdf_version": pymupdf.VersionFitz},
            **{key: False for key in _FALSE_FLAGS}}


if __name__ == "__main__":
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (1024 * 1024 * 1024,) * 2)
        resource.setrlimit(resource.RLIMIT_CPU, (30, 30))
        resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_OUTPUT_BYTES,) * 2)
        resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        if len(sys.argv) != 6 or sys.argv[1] != "--worker":
            raise PDFPageInspectionError("invalid_worker_invocation")
        source, output, artifact_id, raw_selection = sys.argv[2:6]
        if len(raw_selection) > MAX_SELECTED_PAGES * 11 or not re.fullmatch(r"[0-9]+(?:,[0-9]+)*", raw_selection):
            raise PDFPageInspectionError("invalid_worker_page_selection")
        selection = tuple(int(value) for value in raw_selection.split(","))
        with Path(source).open("rb") as stream:
            data = stream.read(MAX_PDF_BYTES + 1)
        body = _canonical(_inspect_worker(data, artifact_id, selection))
        if len(body) > MAX_OUTPUT_BYTES:
            raise PDFPageInspectionError("page_inspection_output_limit")
        Path(output).write_bytes(body)
    except Exception:
        sys.exit(2)
