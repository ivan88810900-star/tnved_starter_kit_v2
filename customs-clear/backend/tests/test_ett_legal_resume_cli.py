"""Resumed reports are new files; cached retrievals are never relabelled as fresh."""
import hashlib
import json

import pytest

from app.services.ett_discovery_audit import canonical_json_bytes
from scripts import resume_ett_legal_documents as cli
from tests.test_ett_legal_capture import originals, execute, portal, PAGE1, PDF, PDF_BYTES


def setup(tmp_path):
    audit, store = originals(tmp_path)
    source, _ = execute(audit, store, {PAGE1: portal(), PDF: PDF_BYTES})
    source_path = tmp_path / "old-capture.json"
    source_path.write_bytes(canonical_json_bytes(source))
    discovery_path = tmp_path / "discovery.json"
    discovery_path.write_bytes(canonical_json_bytes(audit))
    output = tmp_path / "resumed.json"
    args = ["--source-capture-report", str(source_path), "--discovery-report", str(discovery_path),
            "--store-root", str(tmp_path / "objects"), "--output", str(output)]
    return source, source_path, discovery_path, output, args


def test_cli_reuses_originals_with_no_network_and_preserves_prior_report(tmp_path, capsys):
    source, old_path, _, output, args = setup(tmp_path)
    original = old_path.read_bytes()
    assert cli.main(args, fetch=lambda *a, **kw: pytest.fail("all originals were already captured")) == 0
    report = json.loads(output.read_bytes())
    assert report["resume_evidence"]["source_capture_report_sha256"] == hashlib.sha256(original).hexdigest()
    assert report["resume_evidence"]["new_requests"] == []
    assert report["resume_evidence"]["reused_html_responses"] == 1
    assert report["resume_evidence"]["reused_pdf_responses"] == 1
    assert report["documents"][0]["retrieved_at"] == source["documents"][0]["retrieved_at"]
    assert old_path.read_bytes() == original
    assert output.stat().st_mode & 0o777 == 0o600
    assert json.loads(capsys.readouterr().out)["production_ready"] is False


@pytest.mark.parametrize("symlink", [False, True])
def test_cli_refuses_existing_output_without_touching_it(tmp_path, capsys, symlink):
    _, _, _, output, args = setup(tmp_path)
    if symlink:
        output.symlink_to(tmp_path / "missing")
    else:
        output.write_bytes(b"prior")
    assert cli.main(args, fetch=lambda *a, **kw: pytest.fail("network must not run")) == 2
    assert output.is_symlink() if symlink else output.read_bytes() == b"prior"
    assert json.loads(capsys.readouterr().out)["reason"] == "legal_resume_input_or_report_failed"


def test_cli_invalid_old_report_does_not_write_new_report_or_leak_input(tmp_path, capsys):
    _, old_path, _, output, args = setup(tmp_path)
    old_path.write_bytes(b'{"SECRET":"invalid"}')
    assert cli.main(args, fetch=lambda *a, **kw: pytest.fail("network must not run")) == 2
    assert not output.exists()
    assert "SECRET" not in capsys.readouterr().out


def test_cli_refuses_symlinked_source_report(tmp_path, capsys):
    _, old_path, _, output, args = setup(tmp_path)
    original = tmp_path / "actual-original.json"
    old_path.rename(original)
    old_path.symlink_to(original)
    assert cli.main(args, fetch=lambda *a, **kw: pytest.fail("network must not run")) == 2
    assert not output.exists()
    assert json.loads(capsys.readouterr().out)["reason"] == "legal_resume_input_or_report_failed"
