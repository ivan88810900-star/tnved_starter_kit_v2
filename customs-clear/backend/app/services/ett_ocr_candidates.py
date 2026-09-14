"""Opt-in OCR evidence for PDFs without native text; never legal source rows.

Original PDF bytes, the pinned Russian model, rendered images and unmodified
Tesseract TSV/TXT are retained separately in a local content-addressed store.
OCR words and confidence scores are candidates for review, not legal findings.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import subprocess
import tempfile
import time
import zlib

from app.services.ett_artifacts import ArtifactIntegrityError, LocalArtifactStore
from app.services.ett_pdf_evidence import MAX_PDF_BYTES, PDFEvidenceError, extract_pdf_evidence
from app.services.ett_ocr_page_inspection import inspect_selected_pdf_pages


MODEL_COMMIT = "87416418657359cb625c412a48b6e1d6d41c29bd"
MODEL_URL = "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/87416418657359cb625c412a48b6e1d6d41c29bd/rus.traineddata"
MODEL_SIZE = 3_861_738
MODEL_GIT_BLOB = "b146cb2263acbc6383f8e92ea0ce759537687bb8"
MODEL_SHA256 = "e16e5e036cce1d9ec2b00063cf8b54472625b9e14d893a169e2b0dedeb4df225"
LICENSE_SIZE = 11_358
LICENSE_SHA256 = "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30"
LICENSE_GIT_BLOB = "d645695673349e3947e8e5ae42332d0ac3164cd7"
LICENSE_URL = "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/87416418657359cb625c412a48b6e1d6d41c29bd/LICENSE"
MAX_OCR_PAGES = 64
MAX_PAGE_PIXELS = 25_000_000
MAX_TOTAL_PIXELS = 512_000_000
MAX_PNG_BYTES = 32 * 1024 * 1024
MAX_TSV_BYTES = 8 * 1024 * 1024
MAX_TEXT_BYTES = 2 * 1024 * 1024
MAX_WORDS_PER_PAGE = 20_000
MAX_PAGE_REPORT_BYTES = 16 * 1024 * 1024
MAX_TOTAL_OUTPUT_BYTES = 512 * 1024 * 1024
DIAGNOSTIC_RESERVE_BYTES = 1024 * 1024
AGGREGATE_SECONDS = 900
DPI = 300
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_TSV_FIELDS = ("level", "page_num", "block_num", "par_num", "line_num", "word_num", "left", "top", "width", "height", "conf", "text")


class OCRInputError(ValueError):
    """Invalid source/model/request; no OCR should run."""


class OCRExecutionError(ValueError):
    """A sanitized, reportable incomplete OCR operation."""


def _sha(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _json(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _unique_json(body: bytes):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise OCRInputError("duplicate_model_receipt_key")
            result[key] = value
        return result
    return json.loads(body, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(OCRInputError("invalid_model_receipt_number")))


def _private_named_file(directory: int, name: str, maximum: int) -> bytes:
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=directory)
    try:
        before = os.fstat(descriptor)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid()
                or before.st_nlink != 1 or stat.S_IMODE(before.st_mode) not in (0o400, 0o600)
                or not 0 < before.st_size <= maximum):
            raise OCRInputError("unsafe_model_file")
        chunks = []
        size = 0
        while size <= maximum:
            chunk = os.read(descriptor, min(65536, maximum + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        after = os.fstat(descriptor)
        identity = lambda value: (value.st_dev, value.st_ino, value.st_mode, value.st_nlink, value.st_uid, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
        if size != before.st_size or size > maximum or identity(before) != identity(after):
            raise OCRInputError("model_file_changed")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _read_model(directory: Path) -> dict[str, bytes]:
    """Reuse the store's no-follow private-directory boundary for named model files."""
    try:
        import fcntl
        guard = LocalArtifactStore(directory, create=False)
        with guard._directory() as descriptor:
            fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
            files = {name: _private_named_file(descriptor, name, limit) for name, limit in
                     (("rus.traineddata", MODEL_SIZE), ("LICENSE", LICENSE_SIZE), ("receipt.json", 16 * 1024))}
        model, license_body = files["rus.traineddata"], files["LICENSE"]
        if (len(model) != MODEL_SIZE or _sha(model) != MODEL_SHA256
                or hashlib.sha1(f"blob {len(model)}\0".encode("ascii") + model).hexdigest() != MODEL_GIT_BLOB):
            raise OCRInputError("model_pin_mismatch")
        if (len(license_body) != LICENSE_SIZE or _sha(license_body) != LICENSE_SHA256
                or hashlib.sha1(f"blob {len(license_body)}\0".encode("ascii") + license_body).hexdigest() != LICENSE_GIT_BLOB):
            raise OCRInputError("model_license_pin_mismatch")
        receipt = _unique_json(files["receipt.json"])
        expected = {"schema_version": 1, "kind": "pinned_ocr_model_download", "source_url": MODEL_URL,
                    "upstream_repository": "tesseract-ocr/tessdata_fast", "upstream_commit": MODEL_COMMIT,
                    "language": "rus", "model_filename": "rus.traineddata", "size_bytes": MODEL_SIZE,
                    "git_blob_sha1": MODEL_GIT_BLOB, "sha256": MODEL_SHA256,
                    "upstream_license": "Apache-2.0", "installed_globally": False,
                    "model_executed": False, "legal_approval": False, "usage": "ocr_candidate_generation_only"}
        if (type(receipt) is not dict or any(type(receipt.get(k)) is not type(v) or receipt.get(k) != v for k, v in expected.items())
                or receipt.get("git_blob_pin_verified") is not True
                or receipt.get("license") != {"filename": "LICENSE", "source_url": LICENSE_URL,
                                              "size_bytes": LICENSE_SIZE, "git_blob_sha1": LICENSE_GIT_BLOB,
                                              "sha256": LICENSE_SHA256}):
            raise OCRInputError("model_receipt_pin_mismatch")
        return files
    except OCRInputError:
        raise
    except (ValueError, OSError, ArtifactIntegrityError, ImportError) as exc:
        raise OCRInputError("model_unavailable_or_invalid") from exc


def _tools() -> dict[str, str]:
    if os.name != "posix":
        raise OCRInputError("ocr_requires_posix_resource_limits")
    result = {name: shutil.which(name, path=os.defpath) for name in ("prlimit", "pdftoppm", "tesseract")}
    if not all(result.values()):
        raise OCRInputError("ocr_system_tools_unavailable")
    return result


def _run(command: list[str], *, cwd: Path, timeout: float, output_limit: int, prlimit: str) -> tuple[bytes, bytes]:
    """No secrets, shell, network client or unbounded capture pipes in workers."""
    if timeout <= 0:
        raise OCRExecutionError("aggregate_time_limit")
    env = {"PATH": os.defpath, "OMP_THREAD_LIMIT": "1", "OMP_NUM_THREADS": "1", "LC_ALL": "C.UTF-8"}
    cpu = max(1, min(55, math.ceil(timeout)))
    arguments = [prlimit, "--as=1073741824", f"--cpu={cpu}", f"--fsize={output_limit}", "--nofile=64", "--core=0", "--", *command]
    with tempfile.TemporaryFile(dir=cwd) as stdout, tempfile.TemporaryFile(dir=cwd) as stderr:
        try:
            completed = subprocess.run(arguments, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                       stdout=stdout, stderr=stderr, timeout=timeout, check=False)
        except subprocess.TimeoutExpired as exc:
            raise OCRExecutionError("worker_timeout") from exc
        except OSError as exc:
            raise OCRExecutionError("worker_unavailable") from exc
        if completed.returncode != 0:
            raise OCRExecutionError("worker_failed_or_resource_limit")
        stdout.seek(0)
        stderr.seek(0)
        return stdout.read(65536), stderr.read(65536)


def _read_output(path: Path, maximum: int) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_uid != os.geteuid() or before.st_size > maximum:
            raise OCRExecutionError("invalid_worker_output")
        with os.fdopen(descriptor, "rb", closefd=False) as source:
            body = source.read(maximum + 1)
        after = os.fstat(descriptor)
        if len(body) != before.st_size or len(body) > maximum or (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise OCRExecutionError("worker_output_changed_or_oversized")
        return body
    finally:
        os.close(descriptor)


def _png_geometry(body: bytes) -> tuple[int, int]:
    if len(body) > MAX_PNG_BYTES or not body.startswith(b"\x89PNG\r\n\x1a\n"):
        raise OCRExecutionError("invalid_rendered_png")
    offset, dimensions, image_data, ended = 8, None, False, False
    while offset + 12 <= len(body):
        length = struct.unpack(">I", body[offset:offset + 4])[0]
        kind = body[offset + 4:offset + 8]
        end = offset + length + 12
        if end > len(body) or zlib.crc32(body[offset + 4:end - 4]) & 0xffffffff != struct.unpack(">I", body[end - 4:end])[0]:
            raise OCRExecutionError("invalid_rendered_png")
        if offset == 8:
            if kind != b"IHDR" or length != 13:
                raise OCRExecutionError("invalid_rendered_png")
            dimensions = struct.unpack(">II", body[offset + 8:offset + 16])
            if not all(dimensions) or dimensions[0] * dimensions[1] > MAX_PAGE_PIXELS:
                raise OCRExecutionError("page_pixel_limit")
        elif kind == b"IHDR":
            raise OCRExecutionError("invalid_rendered_png")
        image_data = image_data or kind == b"IDAT" and length > 0
        offset = end
        if kind == b"IEND":
            ended = length == 0 and offset == len(body)
            break
    if dimensions is None or not image_data or not ended:
        raise OCRExecutionError("invalid_rendered_png")
    return dimensions


def _words(tsv: bytes, width: int, height: int) -> list[dict]:
    if len(tsv) > MAX_TSV_BYTES:
        raise OCRExecutionError("tsv_size_limit")
    try:
        reader = csv.DictReader(io.StringIO(tsv.decode("utf-8")), delimiter="\t", quoting=csv.QUOTE_NONE)
        if tuple(reader.fieldnames or ()) != _TSV_FIELDS:
            raise ValueError()
        words = []
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError()
            if row["level"] != "5" or not row["text"]:
                continue
            if len(row["text"]) > 4096 or "\x00" in row["text"] or row["page_num"] != "1":
                raise ValueError()
            if any(not re.fullmatch(r"[0-9]{1,8}", row[key]) for key in _TSV_FIELDS[2:10]):
                raise ValueError()
            left, top, w, h = (int(row[key]) for key in ("left", "top", "width", "height"))
            confidence = float(row["conf"])
            if not (left + w <= width and top + h <= height and math.isfinite(confidence) and -1 <= confidence <= 100):
                raise ValueError()
            words.append({"text": row["text"], "bbox_pixels": [left, top, w, h], "confidence_raw": row["conf"],
                          "block": int(row["block_num"]), "paragraph": int(row["par_num"]),
                          "line": int(row["line_num"]), "word": int(row["word_num"])})
            if len(words) > MAX_WORDS_PER_PAGE:
                raise ValueError()
        return words
    except (ValueError, UnicodeError, csv.Error) as exc:
        raise OCRExecutionError("invalid_or_oversized_ocr_tsv") from exc


def _remaining_ranges(total: int, processed: list[int]) -> list[list[int]]:
    """Express large unprocessed scope without expanding every source page."""
    cursor, ranges = 1, []
    for page in sorted(processed):
        if cursor < page:
            ranges.append([cursor, page - 1])
        cursor = page + 1
    if cursor <= total:
        ranges.append([cursor, total])
    return ranges


def ocr_pdf_candidate(
    source_store: LocalArtifactStore, source_sha256: str, *, artifact_id: str,
    model_directory: Path, output_store: LocalArtifactStore,
    pages: tuple[int, ...] | None = None, runner=_run,
) -> dict:
    """Persist a complete or incomplete review report; no API/runtime integration.

    A trusted test runner may be injected by tests. The CLI cannot replace tools,
    model pins, limits, language, source identities or the 300 dpi profile.
    """
    if type(source_sha256) is not str or not _SHA.fullmatch(source_sha256) or type(artifact_id) is not str or not _ID.fullmatch(artifact_id):
        raise OCRInputError("invalid_source_identity")
    if pages is not None and (type(pages) is not tuple or not pages or len(pages) > MAX_OCR_PAGES or any(type(page) is not int or page < 1 for page in pages) or len(set(pages)) != len(pages)):
        raise OCRInputError("invalid_page_selection")
    tools = _tools()
    try:
        source = source_store.read(source_sha256)
        if type(source) is not bytes or len(source) > MAX_PDF_BYTES or _sha(source) != source_sha256:
            raise OCRInputError("source_digest_or_size_mismatch")
        model_files = _read_model(Path(model_directory))
        started = time.monotonic()
        native, inspection = None, None
        try:
            native = extract_pdf_evidence(source, artifact_id=artifact_id)
        except PDFEvidenceError:
            if pages is None:
                raise OCRInputError("native_extraction_failed_explicit_page_selection_required") from None
            # An isolated, metadata-only fallback permits a few explicitly
            # selected pages of larger/rotated originals. It cannot supply
            # native text rows, legal quotes, or whole-document coverage.
            inspection = inspect_selected_pdf_pages(
                source, artifact_id=artifact_id, pages=pages,
                timeout_seconds=min(45, AGGREGATE_SECONDS - (time.monotonic() - started)),
            )
    except OCRInputError:
        raise
    except (ValueError, OSError) as exc:
        raise OCRInputError("source_unavailable_or_invalid_pdf") from exc
    source_pages = ({page["page"]: {**page, "rotation": 0, "native_text_present": bool(page["rows"])} for page in native["pages"]}
                    if native is not None else {page["page"]: page for page in inspection["pages"]})
    source_page_count = native["page_count"] if native is not None else inspection["page_count"]
    if pages is not None and any(page not in source_pages for page in pages):
        raise OCRInputError("page_outside_source_pdf")
    requested = sorted(pages) if pages is not None else sorted(source_pages)
    selected = [page for page in requested if not source_pages[page]["native_text_present"]]
    if len(selected) > MAX_OCR_PAGES:
        raise OCRInputError("ocr_page_count_limit")
    output_bytes, total_pixels = 0, 0

    def retain(body: bytes, *, diagnostic: bool = False) -> str:
        nonlocal output_bytes
        limit = MAX_TOTAL_OUTPUT_BYTES if diagnostic else MAX_TOTAL_OUTPUT_BYTES - DIAGNOSTIC_RESERVE_BYTES
        if output_bytes + len(body) > limit:
            raise OCRExecutionError("aggregate_output_size_limit")
        digest = output_store.put(body)
        if digest != _sha(body):
            raise ArtifactIntegrityError("OCR evidence store digest mismatch")
        output_bytes += len(body)
        return digest

    retain(source)
    model_artifacts = {name: retain(body) for name, body in model_files.items()}
    native_digest = retain(_json(native)) if native is not None else None
    inspection_digest = retain(_json(inspection)) if inspection is not None else None
    engine = renderer = None
    page_results = []
    with tempfile.TemporaryDirectory(prefix="ett-ocr-") as work_name:
        work = Path(work_name)
        source_path = work / "original.pdf"
        source_path.write_bytes(source)
        source_path.chmod(0o600)
        model_path = work / "model"
        model_path.mkdir(mode=0o700)
        for name, body in model_files.items():
            target = model_path / name
            target.write_bytes(body)
            target.chmod(0o600)
        startup_failure = None
        if selected:
            try:
                def identify(tool, argument, stream, expression):
                    outputs = runner([tools[tool], argument], cwd=work, timeout=min(5, AGGREGATE_SECONDS - (time.monotonic() - started)), output_limit=256 * 1024, prlimit=tools["prlimit"])
                    output = outputs[stream]
                    first = output.decode("utf-8").splitlines()[0]
                    if not re.fullmatch(expression, first):
                        raise OCRExecutionError("unsupported_tool_identity")
                    return {"version": first, "version_output_sha256": retain(output)}
                engine = identify("tesseract", "--version", 0, r"tesseract [0-9][A-Za-z0-9.+_-]{0,31}")
                renderer = identify("pdftoppm", "-v", 1, r"pdftoppm version [0-9][A-Za-z0-9.+_-]{0,31}")
            except (OCRExecutionError, UnicodeError, IndexError) as exc:
                startup_failure = str(exc) if isinstance(exc, OCRExecutionError) else "unsupported_tool_identity"
        for page_number in selected:
            prefix = work / f"page-{page_number:04d}"
            record = {"source_page": page_number, "status": "incomplete_ocr", "embedded_pdf_text": False,
                      "legal_approval": False, "legal_effective_dates_verified": False,
                      "source_pdf_sha256": source_sha256, "model_sha256": MODEL_SHA256,
                      "source_rotation_degrees": source_pages[page_number]["rotation"],
                      "word_count": 0, "engine": engine, "renderer": renderer}
            try:
                if startup_failure:
                    raise OCRExecutionError(startup_failure)
                source_page = source_pages[page_number]
                expected = (math.ceil(source_page["width"] * DPI / 72), math.ceil(source_page["height"] * DPI / 72))
                pixels = expected[0] * expected[1]
                if pixels > MAX_PAGE_PIXELS or total_pixels + pixels > MAX_TOTAL_PIXELS:
                    raise OCRExecutionError("aggregate_or_page_pixel_limit")
                remaining = AGGREGATE_SECONDS - (time.monotonic() - started)
                if remaining <= 0:
                    raise OCRExecutionError("aggregate_time_limit")
                # Failed renders also consume the aggregate work budget.
                total_pixels += pixels
                runner([tools["pdftoppm"], "-f", str(page_number), "-l", str(page_number), "-singlefile", "-r", str(DPI), "-png", str(source_path), str(prefix)],
                       cwd=work, timeout=min(45, remaining), output_limit=MAX_PNG_BYTES, prlimit=tools["prlimit"])
                png = _read_output(prefix.with_suffix(".png"), MAX_PNG_BYTES)
                width, height = _png_geometry(png)
                if abs(width - expected[0]) > 2 or abs(height - expected[1]) > 2 or total_pixels + max(0, width * height - pixels) > MAX_TOTAL_PIXELS:
                    raise OCRExecutionError("rendered_geometry_mismatch_or_pixel_limit")
                total_pixels += max(0, width * height - pixels)
                record.update(image_sha256=retain(png), image_width=width, image_height=height, dpi=DPI)
                remaining = AGGREGATE_SECONDS - (time.monotonic() - started)
                if remaining <= 0:
                    raise OCRExecutionError("aggregate_time_limit")
                runner([tools["tesseract"], str(prefix.with_suffix(".png")), str(prefix), "--tessdata-dir", str(model_path),
                        "-l", "rus", "--oem", "1", "--psm", "3", "--dpi", str(DPI),
                        "-c", "tessedit_create_tsv=1", "-c", "tessedit_create_txt=1"],
                       cwd=work, timeout=min(60, remaining), output_limit=16 * 1024 * 1024, prlimit=tools["prlimit"])
                # Retain complete raw engine outputs even if their schema/word
                # interpretation subsequently fails, always under an incomplete status.
                raw_outputs, output_failure = {}, None
                for suffix, maximum, key in ((".tsv", MAX_TSV_BYTES, "ocr_tsv_sha256"),
                                             (".txt", MAX_TEXT_BYTES, "ocr_text_sha256")):
                    try:
                        raw_outputs[suffix] = _read_output(prefix.with_suffix(suffix), maximum)
                        record[key] = retain(raw_outputs[suffix])
                    except (OCRExecutionError, OSError) as exc:
                        output_failure = str(exc) if isinstance(exc, OCRExecutionError) else "worker_output_unavailable_or_invalid"
                if output_failure:
                    raise OCRExecutionError(output_failure)
                tsv, text = raw_outputs[".tsv"], raw_outputs[".txt"]
                words = _words(tsv, width, height)
                decoded = text.decode("utf-8")
                if not words or not decoded.strip():
                    raise OCRExecutionError("no_words_recognized")
                record.update(status="unreviewed_ocr", ocr_text=decoded, words=words, word_count=len(words),
                              low_confidence_words_below_60=sum(float(word["confidence_raw"]) < 60 for word in words),
                              confidence_is_not_legal_accuracy=True, superscript_and_table_interpretation_verified=False)
            except (OCRExecutionError, OSError, UnicodeError) as exc:
                record["reason"] = str(exc) if isinstance(exc, OCRExecutionError) else "worker_output_unavailable_or_invalid"
            finally:
                # Keep only one page's worker files in scratch at a time.
                for suffix in (".png", ".tsv", ".txt"):
                    prefix.with_suffix(suffix).unlink(missing_ok=True)
            try:
                body = _json(record)
                if len(body) > MAX_PAGE_REPORT_BYTES:
                    raise OCRExecutionError("page_report_size_limit")
                page_digest = retain(body)
            except OCRExecutionError as exc:
                record.pop("words", None)
                record.pop("ocr_text", None)
                record.update(status="incomplete_ocr", word_count=0, reason=str(exc))
                body = _json(record)
                if len(body) > 4096:
                    raise OCRExecutionError("diagnostic_report_size_limit")
                page_digest = retain(body, diagnostic=True)
            page_results.append({"page": page_number, "status": record["status"], "report_sha256": page_digest,
                                 "word_count": record["word_count"], "reason": record.get("reason")})
    failed = sum(page["status"] != "unreviewed_ocr" for page in page_results)
    report = {
        "schema_version": 1, "kind": "ett_ocr_candidate_set", "artifact_id": artifact_id,
        "status": "native_text_available" if not selected else "incomplete_ocr_review_required" if failed else "review_required",
        "source_pdf_sha256": source_sha256, "source_size_bytes": len(source),
        "native_extraction_report_sha256": native_digest, "source_page_count": source_page_count,
        "native_extraction_status": "complete" if native is not None else "failed_no_native_evidence",
        "inspection_method": "full_native_extraction" if native is not None else "selected_page_metadata_fallback",
        "page_inspection_report_sha256": inspection_digest,
        "requested_pages": requested, "inspected_pages": sorted(source_pages),
        "pages_not_requested_ranges": _remaining_ranges(source_page_count, requested),
        "pages_not_inspected_ranges": _remaining_ranges(source_page_count, list(source_pages)),
        "selected_pages": selected, "native_text_pages_skipped": [page for page in requested if source_pages[page]["native_text_present"]],
        "model_artifacts": model_artifacts, "model_sha256": MODEL_SHA256,
        "model_commit": MODEL_COMMIT, "model_git_blob_sha1": MODEL_GIT_BLOB,
        "engine": engine, "renderer": renderer, "language": "rus", "dpi": DPI, "oem": 1, "psm": 3,
        "pages": page_results, "pages_succeeded": len(selected) - failed, "pages_failed": failed,
        "ocr_complete": bool(selected) and failed == 0, "word_count": sum(page["word_count"] for page in page_results),
        "ocr_completion_scope": "selected_pages_without_native_text",
        "entire_source_ocr_complete": bool(selected) and len(selected) == source_page_count and failed == 0,
        "pages_not_ocr_completed_ranges": _remaining_ranges(source_page_count, [page["page"] for page in page_results if page["status"] == "unreviewed_ocr"]),
        "total_rendered_pixels": total_pixels, "retained_data_bytes_before_summary": output_bytes,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "limits": {"pages": MAX_OCR_PAGES, "page_pixels": MAX_PAGE_PIXELS,
                   "aggregate_pixels": MAX_TOTAL_PIXELS, "aggregate_seconds": AGGREGATE_SECONDS,
                   "aggregate_output_bytes": MAX_TOTAL_OUTPUT_BYTES, "worker_address_space_bytes": 1073741824,
                   "render_wall_seconds": 45, "ocr_wall_seconds": 60, "worker_cpu_seconds": 55,
                   "png_bytes": MAX_PNG_BYTES, "tsv_bytes": MAX_TSV_BYTES, "text_bytes": MAX_TEXT_BYTES,
                   "page_report_bytes": MAX_PAGE_REPORT_BYTES, "words_per_page": MAX_WORDS_PER_PAGE},
        "pipeline_sha256": _sha(Path(__file__).read_bytes()), "generated_at": datetime.now(timezone.utc).isoformat(),
        "embedded_pdf_text": False, "confidence_is_not_legal_accuracy": True,
        "legal_identity_verified": False, "legal_effective_dates_verified": False,
        "superscript_and_table_interpretation_verified": False, "current_legal_inventory_verified": False,
        "production_ready": False, "can_promote": False, "active_rates_written": False, "global_model_installation": False,
    }
    summary = _json(report)
    if len(summary) > 65536:
        raise OCRExecutionError("summary_size_limit")
    digest = retain(summary, diagnostic=True)
    return {**report, "report_sha256": digest}
