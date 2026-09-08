"""Review-only OCR preserves source evidence and fails closed under bounded work."""
from copy import deepcopy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
from types import SimpleNamespace
import zlib

import pymupdf
import pytest

from app.services import ett_ocr_candidates as ocr
from app.services import ett_pdf_evidence as native_pdf
from app.services.ett_artifacts import LocalArtifactStore
from scripts import download_ett_ocr_model as downloader
from scripts import ocr_ett_pdf as cli


MODEL = b"offline synthetic model fixture: never executed"


def png(width=300, height=300):
    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress((b"\x00" + b"\xff" * (width * 3)) * height)) + chunk(b"IEND", b""))


def tsv(text="1079", confidence="98.123456"):
    return ("\t".join(ocr._TSV_FIELDS) + "\n" + f"5\t1\t1\t1\t1\t1\t10\t20\t40\t10\t{confidence}\t{text}\n").encode()


def pdf(native_pages=(), count=2):
    with pymupdf.open() as document:
        for page in range(1, count + 1):
            target = document.new_page(width=72, height=72)
            if page in native_pages:
                target.insert_text((10, 20), "Native", fontsize=8)
        return document.tobytes()


class Worker:
    def __init__(self, *, fail_page=None, fail_render=False, raw_tsv=None, omit_text=False, width=300, height=300):
        self.calls = []
        self.work_dirs = []
        self.fail_page, self.fail_render = fail_page, fail_render
        self.raw_tsv, self.omit_text = raw_tsv, omit_text
        self.width, self.height = width, height

    def __call__(self, command, *, cwd, timeout, output_limit, prlimit):
        self.calls.append(command)
        self.work_dirs.append(cwd)
        assert 0 < timeout <= 60
        assert prlimit == "/usr/bin/prlimit"
        assert cwd.stat().st_mode & 0o777 == 0o700
        tool = Path(command[0]).name
        if command[1:] == ["--version"]:
            return b"tesseract 5.3.4\n leptonica-fixture\n", b""
        if command[1:] == ["-v"]:
            return b"", b"pdftoppm version 22.12.0\nCopyright fixture\n"
        if tool == "pdftoppm":
            page = int(command[command.index("-f") + 1])
            assert command[command.index("-l") + 1] == str(page)
            assert command[command.index("-r") + 1] == "300"
            assert output_limit == ocr.MAX_PNG_BYTES
            # Prior page scratch output has already been cleaned up.
            assert not list(cwd.glob("page-*.png"))
            if self.fail_render:
                raise ocr.OCRExecutionError("worker_timeout")
            Path(command[-1]).with_suffix(".png").write_bytes(png(self.width, self.height))
        else:
            assert tool == "tesseract"
            prefix = Path(command[2])
            page = int(prefix.name.split("-")[1])
            private_model = Path(command[command.index("--tessdata-dir") + 1])
            assert private_model.parent == cwd
            assert (private_model / "rus.traineddata").read_bytes() == MODEL
            assert command[command.index("-l") + 1] == "rus"
            assert command[command.index("--psm") + 1] == "3"
            assert "tessedit_create_tsv=1" in command and "tessedit_create_txt=1" in command
            if page == self.fail_page:
                raise ocr.OCRExecutionError("worker_timeout")
            prefix.with_suffix(".tsv").write_bytes(self.raw_tsv if self.raw_tsv is not None else tsv())
            if not self.omit_text:
                prefix.with_suffix(".txt").write_bytes(b"1079\n")
        return b"", b""


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr, "MODEL_SIZE", len(MODEL))
    monkeypatch.setattr(ocr, "MODEL_SHA256", hashlib.sha256(MODEL).hexdigest())
    monkeypatch.setattr(ocr, "MODEL_GIT_BLOB", hashlib.sha1(f"blob {len(MODEL)}\0".encode() + MODEL).hexdigest())
    monkeypatch.setattr(ocr, "_tools", lambda: {tool: f"/usr/bin/{tool}" for tool in ("prlimit", "pdftoppm", "tesseract")})
    model = tmp_path / "model"
    model.mkdir(mode=0o700)
    receipt = {
        "schema_version": 1, "kind": "pinned_ocr_model_download", "source_url": ocr.MODEL_URL,
        "upstream_repository": "tesseract-ocr/tessdata_fast", "upstream_commit": ocr.MODEL_COMMIT,
        "language": "rus", "model_filename": "rus.traineddata", "size_bytes": len(MODEL),
        "git_blob_sha1": ocr.MODEL_GIT_BLOB, "sha256": ocr.MODEL_SHA256, "git_blob_pin_verified": True,
        "upstream_license": "Apache-2.0", "installed_globally": False, "model_executed": False,
        "legal_approval": False, "usage": "ocr_candidate_generation_only",
        "license": {"filename": "LICENSE", "source_url": ocr.LICENSE_URL, "size_bytes": ocr.LICENSE_SIZE,
                    "git_blob_sha1": ocr.LICENSE_GIT_BLOB, "sha256": ocr.LICENSE_SHA256},
    }
    for name, body in (("rus.traineddata", MODEL), ("LICENSE", downloader.BUNDLED_LICENSE.read_bytes()), ("receipt.json", json.dumps(receipt).encode())):
        path = model / name
        path.write_bytes(body)
        path.chmod(0o600)
    source = LocalArtifactStore(tmp_path / "source")
    source_body = pdf()
    digest = source.put(source_body)
    output = LocalArtifactStore(tmp_path / "output")
    return SimpleNamespace(model=model, receipt=receipt, source=source, body=source_body, digest=digest, output=output)


def run(setup, worker=None, **kwargs):
    return ocr.ocr_pdf_candidate(setup.source, setup.digest, artifact_id="scanned-act", model_directory=setup.model,
                                 output_store=setup.output, runner=worker or Worker(), **kwargs)


def page_reports(setup, report):
    return [json.loads(setup.output.read(page["report_sha256"])) for page in report["pages"]]


def test_pins_match_downloaded_model_and_license():
    assert ocr.MODEL_COMMIT == downloader.UPSTREAM_COMMIT
    assert ocr.MODEL_SIZE == downloader.EXPECTED_SIZE
    assert ocr.MODEL_GIT_BLOB == downloader.EXPECTED_GIT_BLOB_SHA1
    assert ocr.MODEL_SHA256 == "e16e5e036cce1d9ec2b00063cf8b54472625b9e14d893a169e2b0dedeb4df225"
    assert ocr.LICENSE_SHA256 == downloader.LICENSE_SHA256
    assert ocr.LICENSE_GIT_BLOB == downloader.LICENSE_GIT_BLOB_SHA1


def test_review_outputs_retain_exact_source_model_raw_text_and_confidence(setup):
    worker = Worker()
    report = run(setup, worker)
    stored = json.loads(setup.output.read(report["report_sha256"]))
    assert stored == {key: value for key, value in report.items() if key != "report_sha256"}
    assert report["status"] == "review_required" and report["ocr_complete"]
    assert report["pages_succeeded"] == 2 and report["word_count"] == 2
    assert setup.output.read(report["source_pdf_sha256"]) == setup.body
    for name, digest in report["model_artifacts"].items():
        assert setup.output.read(digest) == (setup.model / name).read_bytes()
    native = json.loads(setup.output.read(report["native_extraction_report_sha256"]))
    assert not any(page["rows"] for page in native["pages"])
    assert report["engine"]["version"] == "tesseract 5.3.4"
    assert report["renderer"]["version"] == "pdftoppm version 22.12.0"
    for record in page_reports(setup, report):
        assert setup.output.read(record["ocr_tsv_sha256"]) == tsv()
        assert setup.output.read(record["ocr_text_sha256"]) == b"1079\n"
        assert setup.output.read(record["image_sha256"]) == png()
        assert record["words"] == [{"text": "1079", "bbox_pixels": [10, 20, 40, 10], "confidence_raw": "98.123456",
                                    "block": 1, "paragraph": 1, "line": 1, "word": 1}]
        # Actual scans merge rates with superscripts; even confident OCR is not a duty/date.
        assert record["status"] == "unreviewed_ocr"
        assert not record["superscript_and_table_interpretation_verified"]
        assert not record["embedded_pdf_text"] and not record["legal_approval"]
        assert not {"rate", "duty", "effective_from", "raw_text"}.intersection(record)
    for key in ("production_ready", "can_promote", "legal_identity_verified", "legal_effective_dates_verified",
                "active_rates_written", "global_model_installation", "current_legal_inventory_verified"):
        assert report[key] is False
    assert report["pipeline_sha256"] == hashlib.sha256(Path(ocr.__file__).read_bytes()).hexdigest()
    assert not any(path.exists() for path in worker.work_dirs)


def test_native_text_pages_are_not_replaced_with_ocr(setup):
    setup.body = pdf(native_pages=(1,))
    setup.digest = setup.source.put(setup.body)
    worker = Worker()
    report = run(setup, worker)
    assert report["selected_pages"] == [2] and report["native_text_pages_skipped"] == [1]
    assert report["pages_succeeded"] == 1
    assert [command[command.index("-f") + 1] for command in worker.calls if "-f" in command] == ["2"]


def test_entirely_native_selection_runs_no_ocr(setup):
    setup.digest = setup.source.put(pdf(native_pages=(1, 2)))
    worker = Worker()
    report = run(setup, worker, pages=(2,))
    assert report["status"] == "native_text_available"
    assert not report["ocr_complete"] and not worker.calls
    assert not report["legal_identity_verified"]


@pytest.mark.parametrize("selection", [(), [1], (True,), (0,), (1, 1), tuple(range(1, 66)), (3,)])
def test_invalid_or_outside_page_selection_rejected(setup, selection):
    worker = Worker()
    with pytest.raises(ocr.OCRInputError):
        run(setup, worker, pages=selection)
    assert not worker.calls


def test_wrong_source_bytes_rejected_before_worker(setup):
    source = SimpleNamespace(read=lambda _: b"not the selected PDF")
    worker = Worker()
    with pytest.raises(ocr.OCRInputError, match="source_digest_or_size_mismatch"):
        ocr.ocr_pdf_candidate(source, setup.digest, artifact_id="act", model_directory=setup.model,
                              output_store=setup.output, runner=worker)
    assert not worker.calls


@pytest.mark.parametrize("filename", ["rus.traineddata", "LICENSE"])
def test_same_size_corrupted_model_or_license_rejected(setup, filename):
    target = setup.model / filename
    target.write_bytes(b"X" * target.stat().st_size)
    with pytest.raises(ocr.OCRInputError, match="pin_mismatch"):
        run(setup)
    assert list(setup.output._root.iterdir()) == []


@pytest.mark.parametrize("key,value", [("sha256", "0" * 64), ("upstream_commit", "0" * 40), ("language", "eng"),
                                      ("size_bytes", True), ("schema_version", True), ("git_blob_pin_verified", 1),
                                      ("legal_approval", True), ("usage", "official_legal_text")])
def test_forged_model_receipt_rejected(setup, key, value):
    receipt = deepcopy(setup.receipt)
    receipt[key] = value
    (setup.model / "receipt.json").write_text(json.dumps(receipt))
    with pytest.raises(ocr.OCRInputError, match="model_receipt_pin_mismatch"):
        run(setup)


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "world_readable", "fifo"])
def test_model_file_security_boundary(setup, tmp_path, kind):
    target = setup.model / "rus.traineddata"
    if kind == "world_readable":
        target.chmod(0o644)
    elif kind == "hardlink":
        os.link(target, tmp_path / "alias")
    else:
        target.unlink()
        if kind == "symlink":
            other = tmp_path / "outside"
            other.write_bytes(MODEL)
            target.symlink_to(other)
        else:
            os.mkfifo(target, 0o600)
    with pytest.raises(ocr.OCRInputError):
        run(setup)


def test_model_lock_busy_fails_without_waiting(setup):
    descriptor = os.open(setup.model, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ocr.OCRInputError, match="model_unavailable"):
            run(setup)
    finally:
        os.close(descriptor)


def test_timeout_keeps_complete_first_page_and_incomplete_second_page(setup):
    report = run(setup, Worker(fail_page=2))
    assert report["status"] == "incomplete_ocr_review_required"
    assert report["pages_succeeded"] == report["pages_failed"] == 1
    first, second = page_reports(setup, report)
    assert first["status"] == "unreviewed_ocr" and setup.output.read(first["ocr_tsv_sha256"]) == tsv()
    assert second["status"] == "incomplete_ocr" and second["reason"] == "worker_timeout"
    assert setup.output.read(second["image_sha256"]) == png()
    assert not report["ocr_complete"] and not report["production_ready"]


def test_missing_text_preserves_valid_tsv_association(setup):
    report = run(setup, Worker(omit_text=True), pages=(1,))
    record = page_reports(setup, report)[0]
    assert record["status"] == "incomplete_ocr"
    assert setup.output.read(record["ocr_tsv_sha256"]) == tsv()
    assert "ocr_text_sha256" not in record


@pytest.mark.parametrize("raw", [b"bad header\n", tsv(confidence="nan"), tsv(confidence="101"),
                                tsv().replace(b"\t40\t10\t", b"\t9999\t10\t"), tsv().replace(b"5\t1", b"5\t2")])
def test_invalid_tsv_retained_without_success_or_legal_inference(setup, raw):
    report = run(setup, Worker(raw_tsv=raw), pages=(1,))
    record = page_reports(setup, report)[0]
    assert record["reason"] == "invalid_or_oversized_ocr_tsv"
    assert setup.output.read(record["ocr_tsv_sha256"]) == raw
    assert "words" not in record and not report["ocr_complete"]


@pytest.mark.parametrize("literal", ['"1079"', '"слово', '«67С)»'])
def test_literal_ocr_quotes_are_not_csv_syntax(literal):
    assert ocr._words(tsv(literal), 300, 300)[0]["text"] == literal


def test_empty_ocr_is_not_complete_review(setup):
    report = run(setup, Worker(raw_tsv=("\t".join(ocr._TSV_FIELDS) + "\n").encode()), pages=(1,))
    assert page_reports(setup, report)[0]["reason"] == "no_words_recognized"
    assert not report["ocr_complete"]


def test_wrong_render_geometry_fails_before_tesseract(setup):
    worker = Worker(width=301, height=310)
    report = run(setup, worker, pages=(1,))
    assert page_reports(setup, report)[0]["reason"] == "rendered_geometry_mismatch_or_pixel_limit"
    assert not any("--tessdata-dir" in command for command in worker.calls)


def test_failed_renders_still_consume_aggregate_pixel_budget(setup, monkeypatch):
    monkeypatch.setattr(ocr, "MAX_TOTAL_PIXELS", 90000)
    worker = Worker(fail_render=True)
    report = run(setup, worker)
    first, second = page_reports(setup, report)
    assert first["reason"] == "worker_timeout"
    assert second["reason"] == "aggregate_or_page_pixel_limit"
    assert len([command for command in worker.calls if "-f" in command]) == 1


def test_oversized_page_report_becomes_compact_incomplete_report(setup, monkeypatch):
    monkeypatch.setattr(ocr, "MAX_PAGE_REPORT_BYTES", 100)
    report = run(setup, pages=(1,))
    record = page_reports(setup, report)[0]
    assert record["reason"] == "page_report_size_limit" and record["word_count"] == 0
    assert "words" not in record and "ocr_text" not in record
    assert setup.output.read(record["ocr_tsv_sha256"]) == tsv()


def test_aggregate_limit_includes_successful_page_reports(setup, monkeypatch):
    original = run(setup, pages=(1,))
    record = page_reports(setup, original)[0]
    raw_total = len(setup.body) + sum((setup.model / name).stat().st_size for name in original["model_artifacts"])
    raw_total += len(setup.output.read(original["native_extraction_report_sha256"]))
    raw_total += sum(len(setup.output.read(original[tool]["version_output_sha256"])) for tool in ("engine", "renderer"))
    raw_total += sum(len(setup.output.read(record[key])) for key in ("image_sha256", "ocr_tsv_sha256", "ocr_text_sha256"))
    monkeypatch.setattr(ocr, "MAX_TOTAL_OUTPUT_BYTES", raw_total + 1 + ocr.DIAGNOSTIC_RESERVE_BYTES)
    limited = run(setup, pages=(1,))
    record = page_reports(setup, limited)[0]
    assert record["reason"] == "aggregate_output_size_limit" and not limited["ocr_complete"]
    assert limited["retained_data_bytes_before_summary"] + len(setup.output.read(limited["report_sha256"])) <= ocr.MAX_TOTAL_OUTPUT_BYTES


def test_tsv_stays_linked_when_text_exceeds_remaining_output_budget(setup, monkeypatch):
    original = run(setup, pages=(1,))
    record = page_reports(setup, original)[0]
    raw_total = original["retained_data_bytes_before_summary"] - len(setup.output.read(original["pages"][0]["report_sha256"]))
    monkeypatch.setattr(ocr, "MAX_TOTAL_OUTPUT_BYTES", raw_total - 1 + ocr.DIAGNOSTIC_RESERVE_BYTES)
    limited = run(setup, pages=(1,))
    partial = page_reports(setup, limited)[0]
    assert partial["reason"] == "aggregate_output_size_limit"
    assert partial["ocr_tsv_sha256"] == record["ocr_tsv_sha256"]
    assert "ocr_text_sha256" not in partial


def test_wall_timeout_is_sanitized_and_worker_is_resource_bounded(tmp_path, monkeypatch):
    def timeout(command, **kwargs):
        assert command[:2] == ["/usr/bin/prlimit", "--as=1073741824"]
        assert "--fsize=1024" in command and "--core=0" in command and "--nofile=64" in command
        assert kwargs["env"] == {"PATH": os.defpath, "OMP_THREAD_LIMIT": "1", "OMP_NUM_THREADS": "1", "LC_ALL": "C.UTF-8"}
        assert kwargs["stdin"] == subprocess.DEVNULL
        assert hasattr(kwargs["stdout"], "fileno") and hasattr(kwargs["stderr"], "fileno")
        assert kwargs["timeout"] == 3
        raise subprocess.TimeoutExpired("sensitive legal text", 3)
    monkeypatch.setattr(ocr.subprocess, "run", timeout)
    with pytest.raises(ocr.OCRExecutionError, match="^worker_timeout$"):
        ocr._run(["/usr/bin/tesseract", "--version"], cwd=tmp_path, timeout=3, output_limit=1024, prlimit="/usr/bin/prlimit")


def test_expired_aggregate_budget_creates_report_without_rendering(setup, monkeypatch):
    monkeypatch.setattr(ocr, "AGGREGATE_SECONDS", 0)
    def bounded_worker(*args, **kwargs):
        if kwargs["timeout"] <= 0:
            raise ocr.OCRExecutionError("aggregate_time_limit")
        pytest.fail("Expired aggregate deadline must not start a worker")
    report = run(setup, bounded_worker)
    assert report["pages_failed"] == 2
    assert all(record["reason"] == "aggregate_time_limit" for record in page_reports(setup, report))


def test_cli_requires_explicit_source_model_and_output_and_reports_incomplete(setup, monkeypatch, capsys):
    result = run(setup, Worker(fail_page=2))
    def fake(source_store, digest, **kwargs):
        assert digest == setup.digest and kwargs["pages"] == (1, 2)
        assert kwargs["model_directory"] == setup.model
        return result
    monkeypatch.setattr(cli, "ocr_pdf_candidate", fake)
    assert cli.main(["--store-root", str(setup.source._root), "--source-sha256", setup.digest,
                     "--artifact-id", "scanned-act", "--model-directory", str(setup.model),
                     "--output-store-root", str(setup.output._root), "--pages", "1", "2"]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "incomplete_ocr_review_required"
    with pytest.raises(SystemExit) as missing:
        cli.main([])
    assert missing.value.code == 2


def test_rotated_original_uses_explicit_metadata_fallback_without_changing_source(setup):
    with pymupdf.open() as document:
        document.new_page(width=72, height=144).set_rotation(270)
        setup.body = document.tobytes()
    setup.digest = setup.source.put(setup.body)
    report = run(setup, Worker(width=600, height=300), pages=(1,))
    assert report["inspection_method"] == "selected_page_metadata_fallback"
    assert report["native_extraction_status"] == "failed_no_native_evidence"
    assert report["native_extraction_report_sha256"] is None
    assert report["source_page_count"] == 1 and report["requested_pages"] == [1]
    assert report["pages_not_inspected_ranges"] == []
    inspection = json.loads(setup.output.read(report["page_inspection_report_sha256"]))
    assert inspection["pages"] == [{"page": 1, "width": 144.0, "height": 72.0, "rotation": 270, "native_text_present": False}]
    page = page_reports(setup, report)[0]
    assert page["source_rotation_degrees"] == 270 and page["status"] == "unreviewed_ocr"
    assert setup.output.read(report["source_pdf_sha256"]) == setup.body
    assert not report["legal_identity_verified"] and not report["production_ready"]


def test_1470_page_pdf_only_inspects_and_ocrs_explicit_first_two_pages(setup):
    setup.body = pdf(count=1470)
    setup.digest = setup.source.put(setup.body)
    worker = Worker()
    report = run(setup, worker, pages=(2, 1))
    assert native_pdf.MAX_PAGES == 1000
    assert report["source_page_count"] == 1470
    assert report["inspection_method"] == "selected_page_metadata_fallback"
    assert report["native_extraction_report_sha256"] is None
    assert report["requested_pages"] == report["inspected_pages"] == report["selected_pages"] == [1, 2]
    assert report["pages_not_requested_ranges"] == report["pages_not_inspected_ranges"] == report["pages_not_ocr_completed_ranges"] == [[3, 1470]]
    assert report["ocr_complete"] and not report["entire_source_ocr_complete"]
    assert report["ocr_completion_scope"] == "selected_pages_without_native_text"
    assert [command[command.index("-f") + 1] for command in worker.calls if "-f" in command] == ["1", "2"]
    inspection = json.loads(setup.output.read(report["page_inspection_report_sha256"]))
    assert inspection["page_count"] == 1470 and len(inspection["pages"]) == 2
    assert all(not {"raw_text", "rows", "quotes"}.intersection(page) for page in inspection["pages"])


def test_native_failure_does_not_implicitly_fallback_to_whole_document(setup):
    with pymupdf.open() as document:
        document.new_page(width=72, height=72).set_rotation(90)
        setup.digest = setup.source.put(document.tobytes())
    worker = Worker()
    with pytest.raises(ocr.OCRInputError, match="explicit_page_selection_required"):
        run(setup, worker)
    assert not worker.calls


def test_rotated_native_text_presence_is_not_native_quote_evidence(setup):
    with pymupdf.open() as document:
        page = document.new_page(width=72, height=144)
        page.insert_text((10, 20), "Existing text", fontsize=8)
        page.set_rotation(270)
        setup.digest = setup.source.put(document.tobytes())
    worker = Worker()
    report = run(setup, worker, pages=(1,))
    assert report["inspection_method"] == "selected_page_metadata_fallback"
    assert report["native_extraction_report_sha256"] is None
    assert report["native_text_pages_skipped"] == [1] and report["selected_pages"] == []
    assert not worker.calls and not report["ocr_complete"]
    assert report["pages_not_ocr_completed_ranges"] == [[1, 1]]
    assert not report["legal_identity_verified"]
