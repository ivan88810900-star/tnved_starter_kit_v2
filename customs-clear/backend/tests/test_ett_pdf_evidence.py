"""PDF extraction provenance, ambiguity and bounded-worker regressions."""
from copy import deepcopy
import hashlib
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pymupdf
import pytest

from app.services import ett_pdf_evidence as pdf


CORPUS = Path(__file__).resolve().parents[3] / "backend/app/services/source_sync/data"


def _small_pdf(text="0101 21 000 0 Example power 735 kW"):
    with pymupdf.open() as document:
        document.new_page().insert_text((90, 90), text)
        return document.tobytes()


def _chapter(number):
    paths = list(CORPUS.glob(f"ru.{number}_*.pdf"))
    assert len(paths) == 1, "The pinned official-source corpus is required"
    return paths[0].read_bytes()


@pytest.fixture(scope="module")
def chapter01():
    body = _chapter("01")
    return body, pdf.extract_pdf_evidence(body, artifact_id="chapter-01", chapter="01")


def _candidates(report):
    return [candidate for page in report["pages"] for candidate in page["candidates"]]


def test_actual_pdf_rows_are_bound_to_original_bytes_and_engine(chapter01):
    body, report = chapter01
    assert report["artifact_sha256"] == hashlib.sha256(body).hexdigest()
    assert report["size_bytes"] == len(body)
    assert report["parser"]["engine_version"] == pymupdf.VersionBind
    assert report["parser"]["sha256"] == hashlib.sha256(Path(pdf.__file__).read_bytes()).hexdigest()
    assert report["page_count"] == 6
    assert report["candidate_count"] == 86
    assert report["legal_rates_resolved"] == 0
    assert report["can_promote"] is False
    for page in report["pages"]:
        for row in page["rows"]:
            assert row["raw_text"] == " ".join(word["text"] for word in row["words"])
            assert row["raw_text_sha256"] == hashlib.sha256(row["raw_text"].encode()).hexdigest()
            assert all(len(word["bbox"]) == 4 for word in row["words"])


def test_rate_is_only_a_located_fragment_and_description_continuation_is_explicit(chapter01):
    _, report = chapter01
    candidate = next(row for row in _candidates(report) if row["code"] == "0101210000")
    assert candidate["description_fragment"] == "– – чистопородные племенные"
    assert candidate["unit_fragment"] == "шт"
    assert candidate["rate_fragment"] == "0"
    assert candidate["status"] == "unreviewed"
    assert "continuation_binding_unresolved" in candidate["unresolved_reasons"]
    assert "effective_dates_unresolved" in candidate["unresolved_reasons"]
    assert not {"duty", "vat", "valid_from", "valid_to"}.intersection(candidate)
    assert any(row["raw_text"] == "животные" for row in report["pages"][0]["rows"])
    assert report["pages"][0]["hierarchy_row_count"] > 0
    assert "0101000000" not in {row["code"] for row in _candidates(report)}


def test_reproducible_extraction_verifies_the_full_report(chapter01):
    body, report = chapter01
    assert pdf.verify_pdf_evidence(body, report) is True
    assert pdf.extract_pdf_evidence(body, artifact_id="chapter-01", chapter="01") == report


@pytest.mark.parametrize("mutation", ["rate", "text_with_rehashed_digest", "coordinates", "engine", "page", "source_hash", "extra"])
def test_tampering_cannot_be_certified_by_rehashing_supplied_text(chapter01, mutation):
    body, original = chapter01
    report = deepcopy(original)
    if mutation == "rate":
        report["pages"][0]["candidates"][0]["rate_fragment"] = "99"
    elif mutation == "text_with_rehashed_digest":
        row = report["pages"][0]["rows"][0]
        row["raw_text"] = "Fabricated legal rate"
        row["raw_text_sha256"] = hashlib.sha256(row["raw_text"].encode()).hexdigest()
    elif mutation == "coordinates":
        report["pages"][0]["rows"][0]["words"][0]["bbox"][0] += 1
    elif mutation == "engine":
        report["parser"]["engine_version"] = "unreviewed-version"
    elif mutation == "page":
        report["pages"][0]["page"] = 9
    elif mutation == "source_hash":
        report["artifact_sha256"] = "0" * 64
    else:
        report["approved"] = True
    with pytest.raises(pdf.PDFEvidenceError, match="does not reproduce"):
        pdf.verify_pdf_evidence(body, report)


def test_pdf_footnote_glyphs_are_retained_without_concatenating_into_numeric_rate():
    report = pdf.extract_pdf_evidence(_chapter("30"), artifact_id="chapter-30", chapter="30")
    row = next(row for row in _candidates(report) if row["code"] == "3001902000")
    assert "63" in row["rate_fragment"]
    assert "С)" in row["rate_fragment"]
    assert "footnote_interpretation_unresolved" in row["unresolved_reasons"]
    assert report["legal_rates_resolved"] == 0


def test_without_confirmed_header_description_numbers_are_never_rates():
    report = pdf.extract_pdf_evidence(_small_pdf(), artifact_id="synthetic", chapter="01")
    row = _candidates(report)[0]
    assert row["code"] == "0101210000"
    assert row["rate_fragment"] is None
    assert "table_header_unconfirmed" in row["unresolved_reasons"]
    assert report["mode"] == "extraction_review"


def test_cross_chapter_candidate_and_duplicates_are_visible_not_deduplicated():
    with pymupdf.open() as document:
        for _ in range(2):
            document.new_page().insert_text((90, 90), "3001 20 100 0 Duplicate")
        body = document.tobytes()
    report = pdf.extract_pdf_evidence(body, artifact_id="synthetic", chapter="01")
    assert report["candidate_count"] == 2
    assert report["unique_candidate_count"] == 1
    assert report["duplicate_candidate_codes"] == ["3001201000"]
    assert all("chapter_mismatch" in row["unresolved_reasons"] for row in _candidates(report))


@pytest.mark.parametrize("text", ["0101 Hierarchy", "0101 21 Hierarchy", "0101 21 000 Hierarchy", "7701 21 000 0 Invalid chapter", "9901 21 000 0 Invalid chapter", "Reference to 0101 21 000 0 in description", "01012100000 Too many digits"])
def test_hierarchy_references_and_invalid_codes_are_not_padded_to_leaf_candidates(text):
    report = pdf.extract_pdf_evidence(_small_pdf(text), artifact_id="synthetic")
    assert report["candidate_count"] == 0


def test_image_or_blank_page_is_explicitly_unresolved():
    with pymupdf.open() as document:
        document.new_page()
        body = document.tobytes()
    report = pdf.extract_pdf_evidence(body, artifact_id="synthetic")
    assert report["word_count"] == 0
    assert report["pages"][0]["unresolved_reasons"] == ["no_extractable_text"]


@pytest.mark.parametrize("body", [b"", b"<html>not a PDF</html>", b"%PDF-1.7\ntruncated", b"junk%PDF-1.7\n%%EOF", "%PDF-1.7\n%%EOF", bytearray(b"%PDF-1.7\n%%EOF")])
def test_invalid_or_incomplete_source_fails_before_worker(body, monkeypatch):
    monkeypatch.setattr(pdf.subprocess, "run", lambda *a, **k: pytest.fail("worker must not run"))
    with pytest.raises(pdf.PDFEvidenceError):
        pdf.extract_pdf_evidence(body, artifact_id="synthetic")


@pytest.mark.parametrize("artifact_id", ["", "../secret", "a/b", "https://eec.eaeunion.org", "x" * 129, None])
def test_invalid_artifact_identifier_is_rejected(artifact_id):
    with pytest.raises(pdf.PDFEvidenceError, match="identifier"):
        pdf.extract_pdf_evidence(_small_pdf(), artifact_id=artifact_id)


@pytest.mark.parametrize("chapter", ["1", "00", "77", "98", "ab", 1, True])
def test_invalid_chapter_is_rejected(chapter):
    with pytest.raises(pdf.PDFEvidenceError, match="Chapter"):
        pdf.extract_pdf_evidence(_small_pdf(), artifact_id="synthetic", chapter=chapter)


def test_oversized_input_is_rejected_before_worker(monkeypatch):
    monkeypatch.setattr(pdf, "MAX_PDF_BYTES", 10)
    with pytest.raises(pdf.PDFEvidenceError, match="size"):
        pdf.extract_pdf_evidence(_small_pdf(), artifact_id="synthetic")


def test_worker_timeout_is_sanitized(monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("private/secret/path", 1)
    monkeypatch.setattr(pdf.subprocess, "run", timeout)
    with pytest.raises(pdf.PDFEvidenceError, match="time limit") as caught:
        pdf.extract_pdf_evidence(_small_pdf(), artifact_id="synthetic")
    assert "private" not in str(caught.value)


def test_worker_receives_no_application_secrets(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "secret-db")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret-key")
    def worker(*args, **kwargs):
        assert "DATABASE_URL" not in kwargs["env"]
        assert "AWS_SECRET_ACCESS_KEY" not in kwargs["env"]
        assert kwargs["stdin"] == subprocess.DEVNULL
        assert kwargs["timeout"] == pdf.WORKER_TIMEOUT_SECONDS
        return SimpleNamespace(returncode=2)
    monkeypatch.setattr(pdf.subprocess, "run", worker)
    with pytest.raises(pdf.PDFEvidenceError, match="resource limit"):
        pdf.extract_pdf_evidence(_small_pdf(), artifact_id="synthetic")


def test_non_posix_environment_fails_explicitly(monkeypatch):
    monkeypatch.setattr(pdf, "os", SimpleNamespace(name="nt"))
    with pytest.raises(pdf.PDFEvidenceError, match="POSIX"):
        pdf.extract_pdf_evidence(_small_pdf(), artifact_id="synthetic")


def test_encrypted_pdf_is_rejected():
    with pymupdf.open() as document:
        document.new_page()
        body = document.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="reader")
    with pytest.raises(pdf.PDFEvidenceError, match="failed"):
        pdf.extract_pdf_evidence(body, artifact_id="synthetic")


def test_rotated_pdf_is_not_silently_reinterpreted():
    with pymupdf.open() as document:
        document.new_page().set_rotation(90)
        body = document.tobytes()
    with pytest.raises(pdf.PDFEvidenceError, match="failed"):
        pdf.extract_pdf_evidence(body, artifact_id="synthetic")


def test_page_count_limit_is_enforced_in_worker():
    with pymupdf.open() as document:
        for _ in range(pdf.MAX_PAGES + 1):
            document.new_page(width=10, height=10)
        body = document.tobytes()
    with pytest.raises(pdf.PDFEvidenceError, match="failed"):
        pdf.extract_pdf_evidence(body, artifact_id="synthetic")


def test_word_count_limit_is_enforced(monkeypatch):
    monkeypatch.setattr(pdf, "MAX_WORDS", 2)
    with pytest.raises(pdf.PDFEvidenceError, match="word count"):
        pdf._extract_worker(_small_pdf(), "synthetic", None)


@pytest.mark.parametrize("report", [None, [], {}, {"artifact_id": "fixture", "chapter": None, "value": float("nan")}])
def test_invalid_verification_report_is_rejected(report):
    with pytest.raises(pdf.PDFEvidenceError):
        pdf.verify_pdf_evidence(_small_pdf(), report)
