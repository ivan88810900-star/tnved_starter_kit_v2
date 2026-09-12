"""Input, resource and publication boundaries of the offline corpus audit."""
import json
import os
from pathlib import Path

import pytest

from scripts import audit_ett_pdf_cells as audit


@pytest.fixture
def corpus(tmp_path):
    root = tmp_path / "corpus"
    root.mkdir()
    for chapter in audit.CHAPTERS:
        (root / f"ru.{chapter}_retained.pdf").write_bytes(b"%PDF-1.7\n%%EOF")
    return root


def test_exact_corpus_census_ignores_nonchapter_ancillary_files(corpus):
    (corpus / "README.md").write_text("Explicitly selected historical files")
    found = audit.discover_corpus(corpus)
    assert tuple(found) == audit.CHAPTERS
    assert len(found) == 96 and "77" not in found


@pytest.mark.parametrize("problem", ["missing", "duplicate", "reserved", "malformed", "symlink", "fifo"])
def test_ambiguous_or_nonregular_sources_are_rejected_before_parsing(corpus, problem, monkeypatch):
    monkeypatch.setattr(audit, "analyze_chapter", lambda *a, **kw: pytest.fail("Parser must not run"))
    first = corpus / "ru.01_retained.pdf"
    if problem == "missing":
        first.unlink()
    elif problem == "duplicate":
        (corpus / "ru.01_another.pdf").write_bytes(first.read_bytes())
    elif problem == "reserved":
        (corpus / "ru.77_invalid.pdf").write_bytes(first.read_bytes())
    elif problem == "malformed":
        (corpus / "ru.1_invalid.pdf").write_bytes(first.read_bytes())
    elif problem == "symlink":
        first.unlink()
        first.symlink_to(corpus / "ru.02_retained.pdf")
    else:
        first.unlink()
        os.mkfifo(first)
    with pytest.raises(audit.AuditError):
        audit.audit_corpus(corpus)


def test_symlink_corpus_root_is_not_accepted(corpus, tmp_path):
    alias = tmp_path / "alias"
    alias.symlink_to(corpus, target_is_directory=True)
    with pytest.raises(audit.AuditError, match="directory"):
        audit.discover_corpus(alias)


@pytest.mark.parametrize("limit", ["MAX_SOURCE_BYTES", "MAX_TOTAL_SOURCE_BYTES", "MAX_DIRECTORY_ENTRIES", "MAX_SECONDS"])
def test_input_and_time_budgets_fail_before_worker(corpus, monkeypatch, limit):
    monkeypatch.setattr(audit, limit, 0)
    monkeypatch.setattr(audit, "analyze_chapter", lambda *a, **kw: pytest.fail("Parser must not run"))
    with pytest.raises(audit.AuditError):
        audit.audit_corpus(corpus)


def test_tariff_notes_cannot_alias_a_chapter(corpus):
    with pytest.raises(audit.AuditError, match="separately"):
        audit.audit_corpus(corpus, tariff_notes=corpus / "ru.01_retained.pdf")


def test_malformed_pdf_is_rejected_before_analysis(corpus, monkeypatch):
    (corpus / "ru.01_retained.pdf").write_bytes(b"Not an actual PDF source")
    monkeypatch.setattr(audit, "analyze_chapter", lambda *a, **kw: pytest.fail("Parser must not run"))
    with pytest.raises(audit.AuditError, match="framing"):
        audit.audit_corpus(corpus)


@pytest.mark.parametrize("limit", ["MAX_SINGLE_REPORT_BYTES", "MAX_TOTAL_REPORT_BYTES", "MAX_RECORDS"])
def test_analysis_output_and_record_budgets_are_enforced(corpus, monkeypatch, limit):
    monkeypatch.setattr(audit, limit, 0)
    monkeypatch.setattr(audit, "_canonical", lambda value: pytest.fail("Whole-report JSON allocation is forbidden before budget enforcement"))
    # Only the fields consulted before the budget are needed. No fabricated
    # fixture can exercise the successful audit or source-verification path.
    monkeypatch.setattr(audit, "analyze_chapter", lambda *a, **kw: {
        "extraction_parser": {}, "assembler": {}, "analysis_component_sha256": {},
        "records": [{"code": "0101210000"}],
    })
    with pytest.raises(audit.AuditError, match="budget"):
        audit.audit_corpus(corpus)


def test_source_state_change_during_read_is_not_accepted(corpus, monkeypatch):
    original = audit._file_state
    calls = 0
    def changed(path):
        nonlocal calls
        state = original(path)
        calls += 1
        return state if calls == 1 else (*state[:-1], state[-1] + 1)
    monkeypatch.setattr(audit, "_file_state", changed)
    with pytest.raises(audit.AuditError, match="changed"):
        audit._read_pdf(corpus / "ru.01_retained.pdf")


def test_failure_after_first_real_chapter_never_publishes_success(corpus, tmp_path, capsys):
    pinned = Path(__file__).resolve().parents[3] / "backend/app/services/source_sync/data"
    first = next(pinned.glob("ru.01_*.pdf"))
    (corpus / "ru.01_retained.pdf").write_bytes(first.read_bytes())
    # Chapter 02 has framing only, not a parseable PDF. Chapter 01 is analyzed
    # normally; the aggregate report must still remain unpublished.
    output = tmp_path / "evidence.json"
    previous = b'{"prior":"completed audit remains untouched"}'
    output.write_bytes(previous)
    status = audit.main(["--corpus", str(corpus), "--output", str(output)])
    assert status == 2
    assert output.read_bytes() == previous
    assert json.loads(capsys.readouterr().out)["status"] == "ERROR"
    assert not list(tmp_path.glob(".ett-audit-*"))


@pytest.mark.parametrize("target", ["source_alias", "symlink", "non_json"])
def test_output_cannot_replace_source_or_follow_alias(corpus, tmp_path, target):
    source = corpus / "ru.01_retained.pdf"
    original = source.read_bytes()
    output = tmp_path / ("evidence.pdf" if target == "non_json" else "evidence.json")
    if target == "source_alias":
        os.link(source, output)
    elif target == "symlink":
        output.symlink_to(source)
    with pytest.raises(audit.AuditError):
        audit._write_output(output, b"{}", [source])
    assert source.read_bytes() == original


def test_atomic_output_digest_is_the_hash_of_the_actual_report_file(tmp_path):
    output = tmp_path / "evidence.json"
    raw = audit._canonical({"production_ready": False, "current_rates_verified": False})
    audit._write_output(output, raw, [])
    assert output.read_bytes() == raw
    assert audit._sha(output.read_bytes()) == audit._sha(raw)
    assert not list(tmp_path.glob(".ett-audit-*"))
