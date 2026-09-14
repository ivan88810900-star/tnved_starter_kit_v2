"""Source-row reproduction is necessary evidence, never legal interpretation."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pymupdf
import pytest

from app.services import ett_evidence_binding as binding
from app.services.ett_artifacts import ArtifactIntegrityError, LocalArtifactStore
from app.services.ett_manifest import manifest_sha256, validate_manifest
from app.services.ett_pdf_evidence import PDFEvidenceError, extract_pdf_evidence
from tests.ett_fixtures import synthetic_manifest_data


@pytest.mark.parametrize("fabricated", [False, True])
def test_cli_row_verification_exit_status_and_no_database_or_store_writes(candidate, tmp_path, fabricated):
    import os
    import subprocess
    import sys

    data, _ = candidate
    if fabricated:
        ref = data["rate_rules"][0]["evidence"][0]
        ref["raw_text"] = "fabricated row"
        ref["raw_text_sha256"] = hashlib.sha256(ref["raw_text"].encode()).hexdigest()
    manifest_file = tmp_path / "candidate.json"
    manifest_file.write_text(json.dumps(data), encoding="utf-8")
    root = tmp_path / "objects"
    before = {p.name: p.read_bytes() for p in root.iterdir()}
    database = tmp_path / "must-not-be-created.db"
    result = subprocess.run(
        [sys.executable, "scripts/ett_candidates.py", "verify-rows", str(manifest_file), "--store-root", str(root)],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "DATABASE_URL": "sqlite:///" + str(database),
             "PYTHONPATH": os.pathsep.join(str(Path(p).resolve()) for p in sys.path if p)},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == (2 if fabricated else 0), result.stderr
    report = json.loads(result.stdout)
    assert report["rows_verified"] is (not fabricated)
    assert report["production_ready"] is report["effective_dates_verified"] is False
    assert not database.exists()
    assert {p.name: p.read_bytes() for p in root.iterdir()} == before


@pytest.fixture(scope="module")
def source_fixture():
    """Real chapter quote plus a deliberately contradictory synthetic date quote."""
    corpus = Path(__file__).resolve().parents[3] / "backend/app/services/source_sync/data"
    chapter_body = next(corpus.glob("ru.01_*.pdf")).read_bytes()
    with pymupdf.open() as document:
        document.new_page().insert_text((90, 90), "Synthetic fixture: validity starts 2030-01-01")
        notes_body = document.tobytes()
    data = synthetic_manifest_data()
    bodies = {"chapter-01": chapter_body, "tariff_notes": notes_body}
    evidence = {}
    for artifact in data["artifacts"]:
        if artifact["artifact_id"] not in bodies:
            continue
        body = bodies[artifact["artifact_id"]]
        artifact.update(sha256=hashlib.sha256(body).hexdigest(), size_bytes=len(body), media_type="application/pdf")
        report = extract_pdf_evidence(body, artifact_id=artifact["artifact_id"], chapter=artifact.get("chapter"))
        if artifact["artifact_id"] == "chapter-01":
            candidate = next(row for page in report["pages"] for row in page["candidates"] if row["code"] == "0101210000")
            page = report["pages"][candidate["page"] - 1]
            row = next(row for row in page["rows"] if row["row"] == candidate["row"])
        else:
            page = report["pages"][0]
            row = page["rows"][0]
        evidence[artifact["artifact_id"]] = {"artifact_id": artifact["artifact_id"], "artifact_sha256": artifact["sha256"], "page": page["page"], "row": row["row"], "raw_text": row["raw_text"], "raw_text_sha256": row["raw_text_sha256"]}
    for item in (*data["codes"], *data["rate_rules"]):
        item["evidence"] = [deepcopy(evidence["chapter-01"])]
        item["effective_evidence"] = [deepcopy(evidence["tariff_notes"])]
    data["footnotes"] = [{"footnote_id": "synthetic-note", "text": "Synthetic informational text", "evidence": [deepcopy(evidence["tariff_notes"])], "resolution": "informational", "rule_ids": [], "rationale": "Synthetic test; no legal interpretation"}]
    validate_manifest(data)
    return data, bodies


@pytest.fixture
def candidate(source_fixture, tmp_path):
    data, bodies = source_fixture
    root = tmp_path / "objects"
    writable = LocalArtifactStore(root)
    for body in bodies.values():
        writable.put(body)
    return deepcopy(data), LocalArtifactStore(root, create=False)


def _all_references(data):
    for item in (*data["codes"], *data["rate_rules"]):
        yield from item["evidence"]
        yield from item["effective_evidence"]
    for footnote in data["footnotes"]:
        yield from footnote["evidence"]


def test_exact_quotes_bind_to_real_pdf_but_never_approve_dates_or_duties(candidate):
    data, store = candidate
    report = binding.verify_manifest_source_rows(data, store)
    assert report["rows_verified"] is True
    assert report["manifest_sha256"] == manifest_sha256(data)
    assert report["references_total"] == report["references_verified"] == 5
    assert report["references_failed"] == 0
    assert report["issues"] == []
    assert report["scope"] == "referenced_pdf_rows_only"
    assert report["pdf_artifacts_extracted"] == 2
    assert report["unreferenced_artifact_count"] == 98
    # The quoted chapter prints 0 while the synthetic manifest says 5; the note
    # quotes 2030 while the manifest interval starts in 2026. Existence of source
    # text alone must not approve either legal interpretation.
    assert "2030-01-01" in data["codes"][0]["effective_evidence"][0]["raw_text"]
    assert data["codes"][0]["valid_from"] == "2026-01-01"
    assert data["rate_rules"][0]["duty"]["ad_valorem_percent"] == "5"
    for flag in ("complete_artifact_inventory_verified", "current_legal_inventory_verified", "effective_dates_verified", "duty_interpretation_verified", "footnote_interpretation_verified", "legal_approval_verified", "production_ready", "can_promote", "active_rates_written"):
        assert report[flag] is False
    assert len(report["parser_identities"]) == 1
    assert report["parser_identities"][0]["engine_version"] == pymupdf.VersionBind
    assert report["manifest_parser"]["name"] == "synthetic-test-parser"


def test_each_unique_pdf_is_extracted_once_for_all_reference_types(candidate, monkeypatch):
    data, store = candidate
    actual = binding.extract_pdf_evidence
    calls = []
    def counted(body, **kwargs):
        calls.append(kwargs["artifact_id"])
        return actual(body, **kwargs)
    monkeypatch.setattr(binding, "extract_pdf_evidence", counted)
    report = binding.verify_manifest_source_rows(data, store)
    assert report["rows_verified"]
    assert calls == ["chapter-01", "tariff_notes"]


@pytest.mark.parametrize("where", ["code", "code_date", "rate", "rate_date", "footnote"])
def test_fabricated_and_rehashed_quotes_fail_at_every_reference_location(candidate, where):
    data, store = candidate
    reference = {
        "code": data["codes"][0]["evidence"][0],
        "code_date": data["codes"][0]["effective_evidence"][0],
        "rate": data["rate_rules"][0]["evidence"][0],
        "rate_date": data["rate_rules"][0]["effective_evidence"][0],
        "footnote": data["footnotes"][0]["evidence"][0],
    }[where]
    reference["raw_text"] = "Confidential fabricated quotation not in the PDF"
    reference["raw_text_sha256"] = hashlib.sha256(reference["raw_text"].encode()).hexdigest()
    validate_manifest(data)  # The old hash-only contract cannot reject this.
    report = binding.verify_manifest_source_rows(data, store)
    assert report["rows_verified"] is False
    assert report["references_verified"] == 4
    assert report["references_failed"] == 1
    assert report["issues"][0]["reason"] == "source_row_text_mismatch"
    assert "Confidential" not in json.dumps(report)


@pytest.mark.parametrize("page,row,reason", [
    (1, "p0001:r99999", "source_row_not_found"),
    (2, "p0001:r00001", "invalid_or_inconsistent_row_locator"),
    (99, "p0099:r00001", "source_row_not_found"),
    (1, "table:1:row:1", "invalid_or_inconsistent_row_locator"),
    (1, "p0001:r00000", "invalid_or_inconsistent_row_locator"),
    (1, "private/secret/path", "invalid_or_inconsistent_row_locator"),
])
def test_wrong_page_row_and_unrecognized_locator_fail_closed(candidate, page, row, reason):
    data, store = candidate
    data["codes"][0]["evidence"][0].update(page=page, row=row)
    report = binding.verify_manifest_source_rows(data, store)
    assert report["rows_verified"] is False
    assert report["issues"][0]["reason"] == reason
    assert "secret" not in json.dumps(report)


def test_wrong_existing_row_is_not_accepted_by_quote_search(candidate):
    data, store = candidate
    data["codes"][0]["evidence"][0]["row"] = "p0001:r00001"
    report = binding.verify_manifest_source_rows(data, store)
    assert report["rows_verified"] is False
    assert report["issues"][0]["reason"] == "source_row_text_mismatch"


@pytest.mark.parametrize("media_type", ["text/html", "application/json", "application/xml", "text/xml"])
def test_non_pdf_references_are_explicitly_unsupported(candidate, media_type):
    data, store = candidate
    next(a for a in data["artifacts"] if a["artifact_id"] == "tariff_notes")["media_type"] = media_type
    report = binding.verify_manifest_source_rows(data, store)
    assert report["rows_verified"] is False
    assert report["references_verified"] == 2
    assert report["references_failed"] == 3
    assert {issue["reason"] for issue in report["issues"]} == {"non_pdf_evidence_unsupported"}


@pytest.mark.parametrize("failure", [ArtifactIntegrityError("private storage details"), OSError("private path details")])
def test_unavailable_store_is_sanitized(candidate, monkeypatch, failure):
    data, store = candidate
    def unavailable(self, digest):
        raise failure
    monkeypatch.setattr(LocalArtifactStore, "read", unavailable)
    report = binding.verify_manifest_source_rows(data, store)
    assert report["references_failed"] == 5
    assert report["rows_verified"] is False
    assert "private" not in json.dumps(report)


def test_store_body_is_independently_checked_against_manifest(candidate, monkeypatch):
    data, store = candidate
    monkeypatch.setattr(LocalArtifactStore, "read", lambda *a: b"wrong body")
    report = binding.verify_manifest_source_rows(data, store)
    assert report["references_failed"] == 5
    assert {issue["reason"] for issue in report["issues"]} == {"artifact_integrity_mismatch"}


def test_pdf_parser_failure_never_becomes_verified(candidate, monkeypatch):
    data, store = candidate
    def failed(*args, **kwargs):
        raise PDFEvidenceError("Untrusted PDF text and private details")
    monkeypatch.setattr(binding, "extract_pdf_evidence", failed)
    report = binding.verify_manifest_source_rows(data, store)
    assert report["rows_verified"] is False
    assert report["references_failed"] == 5
    assert {issue["reason"] for issue in report["issues"]} == {"pdf_extraction_failed"}
    assert "private" not in json.dumps(report)


def test_model_construct_cannot_bypass_manifest_revalidation(candidate):
    data, store = candidate
    validated = validate_manifest(data)
    invalid = validated.model_copy(update={"codes": (validated.codes[0].model_copy(update={"valid_from": True}),)})
    with pytest.raises(binding.EvidenceBindingError, match="validation failed"):
        binding.verify_manifest_source_rows(invalid, store)


def test_invalid_manifest_error_does_not_echo_raw_evidence(candidate):
    data, store = candidate
    data["codes"][0]["evidence"][0]["raw_text"] = "Secret source text"
    with pytest.raises(binding.EvidenceBindingError) as caught:
        binding.verify_manifest_source_rows(data, store)
    assert "Secret" not in str(caught.value)


def test_aggregate_reference_limit(candidate, monkeypatch):
    data, store = candidate
    monkeypatch.setattr(binding, "MAX_REFERENCES", 4)
    with pytest.raises(binding.EvidenceBindingError, match="reference count"):
        binding.verify_manifest_source_rows(data, store)


@pytest.mark.parametrize("limit,reason", [("MAX_REFERENCED_PDFS", "pdf_artifact_count_limit"), ("MAX_SOURCE_BYTES", "aggregate_source_size_limit")])
def test_aggregate_extraction_limits_fail_closed(candidate, monkeypatch, limit, reason):
    data, store = candidate
    monkeypatch.setattr(binding, limit, 0)
    report = binding.verify_manifest_source_rows(data, store)
    assert report["references_failed"] == 5
    assert report["rows_verified"] is False
    assert {issue["reason"] for issue in report["issues"]} == {reason}


def test_aggregate_time_budget_stops_new_extractions(candidate, monkeypatch):
    data, store = candidate
    ticks = iter([0, 301, 302])
    monkeypatch.setattr(binding.time, "monotonic", lambda: next(ticks))
    report = binding.verify_manifest_source_rows(data, store)
    assert report["references_failed"] == 5
    assert {issue["reason"] for issue in report["issues"]} == {"binding_time_limit"}


def test_issue_output_is_bounded_and_counts_remain_complete(candidate, monkeypatch):
    data, store = candidate
    monkeypatch.setattr(binding, "MAX_REFERENCED_PDFS", 0)
    monkeypatch.setattr(binding, "MAX_ISSUES", 2)
    report = binding.verify_manifest_source_rows(data, store)
    assert report["references_failed"] == 5
    assert len(report["issues"]) == 2
    assert report["issues_truncated"] is True


def test_supplied_manifest_bytes_are_bound_to_normalized_digest(candidate):
    data, store = candidate
    report = binding.verify_manifest_source_rows(json.dumps(data).encode(), store)
    assert report["rows_verified"] is True
    assert report["manifest_sha256"] == manifest_sha256(data)
