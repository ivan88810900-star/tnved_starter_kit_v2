"""Selected-page OCR preflight inspects geometry, never supplies native quotes."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import subprocess
from types import SimpleNamespace

import pymupdf
import pytest

from app.services import ett_ocr_page_inspection as inspection


def _pdf(*, native_text=False, rotation=0):
    with pymupdf.open() as document:
        page = document.new_page(width=100, height=200)
        if native_text:
            page.insert_text((10, 30), "Native text")
        page.set_rotation(rotation)
        return document.tobytes()


@pytest.fixture(scope="module")
def inspected_pdf():
    body = _pdf(native_text=True)
    report = inspection.inspect_selected_pdf_pages(body, artifact_id="inspection-fixture", pages=(1,))
    return body, report


def test_actual_rotation_and_native_text_are_metadata_only():
    body = _pdf(native_text=True, rotation=90)
    report = inspection.inspect_selected_pdf_pages(body, artifact_id="rotated-scan", pages=(1,))
    assert set(report) == {
        "schema_version", "kind", "artifact_id", "artifact_sha256", "size_bytes",
        "page_count", "selected_pages", "pages", "parser", "native_text_quotes_included",
        "native_text_rows_included", "legal_identity_verified", "legal_effective_dates_verified",
        "can_promote", "production_ready",
    }
    assert report["schema_version"] == 1
    assert report["kind"] == "ett_selected_pdf_page_inspection"
    assert report["artifact_id"] == "rotated-scan"
    assert report["artifact_sha256"] == hashlib.sha256(body).hexdigest()
    assert report["size_bytes"] == len(body)
    assert report["page_count"] == 1
    assert report["selected_pages"] == [1]
    assert report["pages"] == [{
        "page": 1, "width": 200.0, "height": 100.0, "rotation": 90,
        "native_text_present": True,
    }]
    parser = report["parser"]
    assert set(parser) == {"name", "version", "sha256", "engine", "engine_version", "mupdf_version"}
    assert parser["name"] == "ett_selected_pdf_page_inspection"
    assert parser["version"] == "1"
    assert parser["sha256"] == hashlib.sha256(Path(inspection.__file__).read_bytes()).hexdigest()
    assert parser["engine"] == "pymupdf"
    assert parser["engine_version"] == pymupdf.VersionBind
    assert parser["mupdf_version"] == pymupdf.VersionFitz
    for key in ("native_text_quotes_included", "native_text_rows_included", "legal_identity_verified",
                "legal_effective_dates_verified", "can_promote", "production_ready"):
        assert report[key] is False
    assert "Native text" not in json.dumps(report)


def test_large_document_returns_only_selected_pages_in_sorted_order():
    with pymupdf.open() as document:
        for index in range(1470):
            document.new_page(width=100 + index % 2, height=200 + index % 2)
        body = document.tobytes()
    report = inspection.inspect_selected_pdf_pages(body, artifact_id="large-legal-scan", pages=(2, 1))
    assert report["page_count"] == 1470
    assert report["selected_pages"] == [1, 2]
    assert report["pages"] == [
        {"page": 1, "width": 100.0, "height": 200.0, "rotation": 0, "native_text_present": False},
        {"page": 2, "width": 101.0, "height": 201.0, "rotation": 0, "native_text_present": False},
    ]


def test_pdf_is_opened_only_in_resource_limited_child(monkeypatch):
    body = _pdf(native_text=True)
    monkeypatch.setattr(pymupdf, "open", lambda *a, **k: pytest.fail("parent must not open the PDF"))
    report = inspection.inspect_selected_pdf_pages(body, artifact_id="child-only", pages=(1,))
    assert report["pages"][0]["native_text_present"] is True


@pytest.mark.parametrize("pages", [(), (1, 1), (True,), (False,), (0,), (-1,), (1.0,), ("1",),
                                    [1], {1}, "1", None, tuple(range(1, 66))])
def test_invalid_page_selection_fails_before_worker(monkeypatch, pages):
    body = _pdf()
    monkeypatch.setattr(inspection.subprocess, "run", lambda *a, **k: pytest.fail("worker must not run"))
    with pytest.raises(inspection.PDFPageInspectionError):
        inspection.inspect_selected_pdf_pages(body, artifact_id="fixture", pages=pages)


def test_page_outside_document_is_rejected():
    with pytest.raises(inspection.PDFPageInspectionError):
        inspection.inspect_selected_pdf_pages(_pdf(), artifact_id="fixture", pages=(2,))


@pytest.mark.parametrize("timeout", [0, -1, 45.01, 10 ** 1000, float("nan"), float("inf"), -float("inf"),
                                      True, "1", None])
def test_invalid_time_budget_fails_before_worker(monkeypatch, timeout):
    body = _pdf()
    monkeypatch.setattr(inspection.subprocess, "run", lambda *a, **k: pytest.fail("worker must not run"))
    with pytest.raises(inspection.PDFPageInspectionError):
        inspection.inspect_selected_pdf_pages(body, artifact_id="fixture", pages=(1,), timeout_seconds=timeout)


@pytest.mark.parametrize("body", [b"", b"<html>not PDF</html>", b"%PDF-1.4\ntruncated",
                                  "%PDF-1.4\n%%EOF", bytearray(b"%PDF-1.4\n%%EOF"), None])
def test_invalid_source_shape_fails_before_worker(monkeypatch, body):
    monkeypatch.setattr(inspection.subprocess, "run", lambda *a, **k: pytest.fail("worker must not run"))
    with pytest.raises(inspection.PDFPageInspectionError):
        inspection.inspect_selected_pdf_pages(body, artifact_id="fixture", pages=(1,))


def test_source_larger_than_64_mib_fails_before_worker(monkeypatch):
    body = b"%PDF-1.4\n" + b" " * (64 * 1024 * 1024) + b"\n%%EOF"
    monkeypatch.setattr(inspection.subprocess, "run", lambda *a, **k: pytest.fail("worker must not run"))
    with pytest.raises(inspection.PDFPageInspectionError):
        inspection.inspect_selected_pdf_pages(body, artifact_id="oversized", pages=(1,))


@pytest.mark.parametrize("artifact_id", ["", "../private", "a/b", "x" * 129, None, True])
def test_invalid_artifact_identifier_fails_before_worker(monkeypatch, artifact_id):
    body = _pdf()
    monkeypatch.setattr(inspection.subprocess, "run", lambda *a, **k: pytest.fail("worker must not run"))
    with pytest.raises(inspection.PDFPageInspectionError):
        inspection.inspect_selected_pdf_pages(body, artifact_id=artifact_id, pages=(1,))


def test_worker_timeout_is_sanitized(monkeypatch):
    def timeout(*args, **kwargs):
        assert kwargs["timeout"] == 2.5
        raise subprocess.TimeoutExpired("/private/source/document.pdf", 2.5,
                                        output=b"secret-output", stderr=b"secret-stderr")
    monkeypatch.setattr(inspection.subprocess, "run", timeout)
    with pytest.raises(inspection.PDFPageInspectionError) as caught:
        inspection.inspect_selected_pdf_pages(_pdf(), artifact_id="fixture", pages=(1,), timeout_seconds=2.5)
    assert "private" not in str(caught.value)
    assert "secret" not in str(caught.value)


def test_worker_receives_no_application_secrets(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "private-database")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "private-key")
    def worker(*args, **kwargs):
        assert "DATABASE_URL" not in kwargs["env"]
        assert "AWS_SECRET_ACCESS_KEY" not in kwargs["env"]
        assert kwargs["stdin"] == subprocess.DEVNULL
        assert kwargs["timeout"] <= 45
        assert not kwargs.get("shell", False)
        return SimpleNamespace(returncode=2, stdout=b"secret-output", stderr=b"secret-stderr")
    monkeypatch.setattr(inspection.subprocess, "run", worker)
    with pytest.raises(inspection.PDFPageInspectionError) as caught:
        inspection.inspect_selected_pdf_pages(_pdf(), artifact_id="fixture", pages=(1,))
    assert "secret" not in str(caught.value)


def _worker_bytes(body):
    def worker(command, **kwargs):
        output_path = Path(command[command.index("--worker") + 2])
        output_path.write_bytes(body)
        output_path.chmod(0o600)
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
    return worker


def _worker_returning(report):
    return _worker_bytes(json.dumps(report).encode("utf-8"))


def test_unchanged_worker_report_passes_parent_validation(inspected_pdf, monkeypatch):
    body, report = inspected_pdf
    monkeypatch.setattr(inspection.subprocess, "run", _worker_returning(report))
    assert inspection.inspect_selected_pdf_pages(body, artifact_id="inspection-fixture", pages=(1,)) == report


@pytest.mark.parametrize("mutation", [
    "source_sha256", "source_size", "parser_sha256", "parser_engine_version", "selection",
    "extra_native_quotes", "extra_page_quotes", "native_rows_flag", "legal_identity_flag",
    "legal_dates_flag", "can_promote_flag", "production_ready_flag", "page_rotation",
    "page_width", "huge_page_width", "native_text_type", "page_count_type",
])
def test_forged_worker_metadata_cannot_cross_parent_validation(inspected_pdf, monkeypatch, mutation):
    body, original = inspected_pdf
    report = deepcopy(original)
    if mutation == "source_sha256":
        report["artifact_sha256"] = "0" * 64
    elif mutation == "source_size":
        report["size_bytes"] += 1
    elif mutation == "parser_sha256":
        report["parser"]["sha256"] = "0" * 64
    elif mutation == "parser_engine_version":
        report["parser"]["engine_version"] = "unverified-engine"
    elif mutation == "selection":
        report["selected_pages"] = [2]
    elif mutation == "extra_native_quotes":
        report["native_text_quotes"] = ["Fabricated legal quotation"]
    elif mutation == "extra_page_quotes":
        report["pages"][0]["rows"] = [{"raw_text": "Fabricated rate"}]
    elif mutation == "native_rows_flag":
        report["native_text_rows_included"] = True
    elif mutation == "legal_identity_flag":
        report["legal_identity_verified"] = True
    elif mutation == "legal_dates_flag":
        report["legal_effective_dates_verified"] = True
    elif mutation == "can_promote_flag":
        report["can_promote"] = True
    elif mutation == "production_ready_flag":
        report["production_ready"] = True
    elif mutation == "page_rotation":
        report["pages"][0]["rotation"] = 45
    elif mutation == "page_width":
        report["pages"][0]["width"] = float("nan")
    elif mutation == "huge_page_width":
        report["pages"][0]["width"] = 10 ** 1000
    elif mutation == "native_text_type":
        report["pages"][0]["native_text_present"] = "false"
    else:
        report["page_count"] = True

    monkeypatch.setattr(inspection.subprocess, "run", _worker_returning(report))
    with pytest.raises(inspection.PDFPageInspectionError):
        inspection.inspect_selected_pdf_pages(body, artifact_id="inspection-fixture", pages=(1,))


def test_encrypted_source_cannot_provide_geometry():
    with pymupdf.open() as document:
        document.new_page()
        body = document.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256,
                               owner_pw="owner", user_pw="reader")
    with pytest.raises(inspection.PDFPageInspectionError):
        inspection.inspect_selected_pdf_pages(body, artifact_id="encrypted", pages=(1,))


def test_encrypted_source_with_empty_reader_password_is_still_rejected():
    with pymupdf.open() as document:
        document.new_page()
        body = document.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256,
                               owner_pw="owner", user_pw="")
    with pymupdf.open(stream=body, filetype="pdf") as reopened:
        assert not reopened.needs_pass
        assert not reopened.is_encrypted
        assert reopened.xref_get_key(-1, "Encrypt")[0] == "dict"
    with pytest.raises(inspection.PDFPageInspectionError):
        inspection.inspect_selected_pdf_pages(body, artifact_id="auto-authenticated-encryption", pages=(1,))


def test_repaired_pdf_cannot_provide_original_page_metadata():
    body, replacements = re.subn(rb"startxref\s+\d+\s+%%EOF", b"startxref\n0\n%%EOF", _pdf())
    assert replacements == 1
    with pymupdf.open(stream=body, filetype="pdf") as reopened:
        assert reopened.is_repaired
    with pytest.raises(inspection.PDFPageInspectionError):
        inspection.inspect_selected_pdf_pages(body, artifact_id="repaired", pages=(1,))


@pytest.mark.parametrize("malformation", ["oversized", "duplicate_keys", "deep_nesting", "invalid_utf8"])
def test_worker_output_limits_and_json_ambiguity_fail_closed(inspected_pdf, monkeypatch, malformation):
    body, report = inspected_pdf
    if malformation == "oversized":
        output = b" " * (inspection.MAX_OUTPUT_BYTES + 1)
    elif malformation == "duplicate_keys":
        output = ('{"artifact_id":"inspection-fixture",' + json.dumps(report)[1:]).encode("utf-8")
    elif malformation == "deep_nesting":
        output = b"[" * 2000 + b"]" * 2000
    else:
        output = b"\xff"
    monkeypatch.setattr(inspection.subprocess, "run", _worker_bytes(output))
    with pytest.raises(inspection.PDFPageInspectionError):
        inspection.inspect_selected_pdf_pages(body, artifact_id="inspection-fixture", pages=(1,))
