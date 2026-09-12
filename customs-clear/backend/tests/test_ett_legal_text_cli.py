"""Native extraction CLI reports real retained evidence without replacing files."""
import hashlib
import json
from pathlib import Path

import pymupdf
import pytest

from app.services.ett_discovery_audit import canonical_json_bytes
from app.services.ett_legal_capture import capture_legal_documents
from scripts import extract_ett_legal_documents as cli
from tests.test_ett_legal_capture import mocked_fetch
from tests.test_ett_discovery_audit import audit_fixture
from tests.test_ett_legal_capture_cli import PORTAL_HTML
from app.services.ett_legal_attachments import parse_legal_attachments


def setup(tmp_path):
    audit, store = audit_fixture(tmp_path)
    page_url = audit["capture_plan"][0]["page_url"]
    with pymupdf.open() as doc:
        page = doc.new_page()
        page.insert_text((72, 72), "Synthetic native evidence")
        doc.new_page()
        pdf = doc.tobytes()
    responses = {page_url: PORTAL_HTML}
    responses.update({ref.url: pdf for ref in parse_legal_attachments(PORTAL_HTML, page_url).documents})
    captured = capture_legal_documents(store, canonical_json_bytes(audit), fetch=mocked_fetch(responses, []))
    assert captured["supported_capture_plan_completed"]
    path = tmp_path / "capture.json"
    path.write_bytes(canonical_json_bytes(captured))
    output = tmp_path / "native.json"
    argv = ["--capture-report", str(path), "--store-root", str(tmp_path / "objects"), "--output", str(output)]
    return captured, store, path, output, argv


def test_cli_real_worker_publishes_native_and_original_bound_metadata_reports(tmp_path, capsys):
    capture, store, path, output, argv = setup(tmp_path)
    original_capture = path.read_bytes()
    assert cli.main(argv) == 0
    report = json.loads(output.read_bytes())
    assert report["all_declared_successful_pdfs_extracted"]
    assert report["page_count"] == 2 * len(capture["pdfs"])
    assert report["no_native_text_page_count"] == len(capture["pdfs"])
    assert report["parent_metadata_failures"] == 0
    assert len(report["parent_metadata"]) == 1
    parent = report["parent_metadata"][0]
    metadata = json.loads(store.read(parent["metadata_report_sha256"]))
    assert metadata["source_sha256"] == hashlib.sha256(PORTAL_HTML).hexdigest()
    assert metadata["fields"]["adoption_date"]["observed_iso_date"] == "2022-04-19"
    assert metadata["effective_dates_verified"] is False
    for row in report["pdfs"]:
        assert row["parent_metadata_report_sha256s"] == [parent["metadata_report_sha256"]]
        assert row["ocr_candidate_pages"] == [2]
    assert output.stat().st_mode & 0o777 == 0o600
    assert not list(tmp_path.glob(".ett-legal-text-*"))
    assert path.read_bytes() == original_capture
    assert json.loads(capsys.readouterr().out)["production_ready"] is False


def test_cli_extraction_failure_still_publishes_safe_partial_report(tmp_path, capsys):
    _, _, _, output, argv = setup(tmp_path)
    def fail(*args, **kwargs):
        raise RuntimeError("SECRET worker payload")
    assert cli.main(argv, extract=fail) == 2
    report = json.loads(output.read_bytes())
    assert report["status"] == "incomplete"
    assert report["failed_pdfs"] > 0
    assert report["parent_metadata"][0]["status"] == "extracted"
    assert "SECRET" not in output.read_text() + capsys.readouterr().out


@pytest.mark.parametrize("symlink", [False, True])
def test_cli_existing_destination_is_refused_before_extraction(tmp_path, capsys, symlink):
    _, _, _, output, argv = setup(tmp_path)
    if symlink:
        output.symlink_to(tmp_path / "absent")
    else:
        output.write_bytes(b"previous")
    assert cli.main(argv, extract=lambda *a, **kw: pytest.fail("extraction must not run")) == 2
    assert output.is_symlink() if symlink else output.read_bytes() == b"previous"
    assert json.loads(capsys.readouterr().out)["reason"] == "legal_text_input_or_report_failed"


def test_cli_tampered_capture_report_cannot_publish_a_result(tmp_path, capsys):
    _, _, path, output, argv = setup(tmp_path)
    path.write_bytes(b'{"SECRET":"not capture evidence"}')
    assert cli.main(argv, extract=lambda *a, **kw: pytest.fail("extraction must not run")) == 2
    assert not output.exists()
    assert "SECRET" not in capsys.readouterr().out
