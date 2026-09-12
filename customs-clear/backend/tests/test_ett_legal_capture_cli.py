"""Legal capture CLI keeps partial evidence and publishes reports without clobber."""
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from app.services.ett_transport import OfficialResponse, OfficialTransportError
from scripts import capture_ett_legal_documents as cli
from tests.test_ett_discovery_audit import audit_fixture, encoded


PDF = b"%PDF-1.7\nSynthetic capture fixture; no legal content or extraction.\n%%EOF\n"
PORTAL_HTML = (Path(__file__).parent / "fixtures/ett_legal_portal/collegium_66_run_34240219765.html").read_bytes()


def setup(tmp_path):
    audit, store = audit_fixture(tmp_path)
    discovery = tmp_path / "discovery.json"
    discovery.write_bytes(encoded(audit))
    output = tmp_path / "capture.json"
    argv = ["--discovery-report", str(discovery), "--store-root", str(tmp_path / "objects"), "--output", str(output)]
    return audit, store, discovery, output, argv


def source(url, *, expected_media):
    return OfficialResponse(url=url, requested_url=url,
        content=PORTAL_HTML if expected_media == "text/html" else PDF,
        media_type=expected_media, retrieved_at=datetime(2026, 9, 8, tzinfo=timezone.utc))


def test_cli_captures_replayed_plan_to_a_new_private_report(tmp_path, capsys):
    _, store, _, output, argv = setup(tmp_path)
    assert cli.main(argv, fetch=source) == 0
    report = json.loads(output.read_bytes())
    assert report["supported_capture_plan_completed"] is True
    assert report["captured_document_pages"] == 1
    assert report["captured_unique_pdfs"] >= 1
    assert report["unsupported_attachment_references"] > 0
    assert store.read(report["documents"][0]["sha256"]) == PORTAL_HTML
    for pdf in report["pdfs"]:
        assert store.read(pdf["sha256"]) == PDF
    assert report["production_ready"] is report["effective_dates_verified"] is False
    assert output.stat().st_mode & 0o777 == 0o600
    assert not list(tmp_path.glob(".ett-legal-capture-*"))
    stdout = json.loads(capsys.readouterr().out)
    assert stdout["status"] == "supported_discovery_plan_captured"
    assert stdout["production_ready"] is False


def test_cli_preserves_html_and_partial_report_when_pdf_capture_fails(tmp_path, capsys):
    _, store, _, output, argv = setup(tmp_path)
    def fetch(url, *, expected_media):
        if expected_media == "application/pdf":
            raise OfficialTransportError("SECRET upstream payload")
        return source(url, expected_media=expected_media)
    assert cli.main(argv, fetch=fetch) == 2
    report = json.loads(output.read_bytes())
    assert report["status"] == "incomplete"
    assert report["captured_document_pages"] == 1
    assert report["captured_unique_pdfs"] == 0
    assert report["failed_operations"] >= 1
    assert store.read(report["documents"][0]["sha256"]) == PORTAL_HTML
    assert "SECRET" not in output.read_text() + capsys.readouterr().out


@pytest.mark.parametrize("symlink", [False, True])
def test_cli_rejects_existing_output_before_network_without_replacing_it(tmp_path, capsys, symlink):
    _, _, _, output, argv = setup(tmp_path)
    if symlink:
        output.symlink_to(tmp_path / "absent-target")
    else:
        output.write_bytes(b"existing review")
    assert cli.main(argv, fetch=lambda *a, **kw: pytest.fail("network must not run")) == 2
    assert json.loads(capsys.readouterr().out)["reason"] == "legal_capture_input_or_report_failed"
    if symlink:
        assert output.is_symlink() and not (tmp_path / "absent-target").exists()
    else:
        assert output.read_bytes() == b"existing review"


def test_cli_rejects_invalid_plan_without_writing_success_or_leaking_input(tmp_path, capsys):
    _, _, discovery, output, argv = setup(tmp_path)
    discovery.write_bytes(b'{"SECRET":"invalid caller plan"}')
    assert cli.main(argv, fetch=lambda *a, **kw: pytest.fail("invalid plan reached network")) == 2
    assert not output.exists()
    assert "SECRET" not in capsys.readouterr().out


def test_cli_rejects_symlinked_discovery_report(tmp_path, capsys):
    _, _, discovery, output, argv = setup(tmp_path)
    original = tmp_path / "original.json"
    discovery.rename(original)
    discovery.symlink_to(original)
    assert cli.main(argv, fetch=lambda *a, **kw: pytest.fail("network must not run")) == 2
    assert not output.exists()
    assert json.loads(capsys.readouterr().out)["reason"] == "legal_capture_input_or_report_failed"


def test_cli_publication_race_keeps_the_other_writers_report(tmp_path, capsys):
    _, _, _, output, argv = setup(tmp_path)
    def fetch(url, *, expected_media):
        output.write_bytes(b"concurrent report")
        return source(url, expected_media=expected_media)
    assert cli.main(argv, fetch=fetch) == 2
    assert output.read_bytes() == b"concurrent report"
    assert not list(tmp_path.glob(".ett-legal-capture-*"))
    assert json.loads(capsys.readouterr().out)["reason"] == "legal_capture_input_or_report_failed"
