"""Integration of retained bytes, table cells, typography and note references."""
from copy import deepcopy
import json
from pathlib import Path
import time

import pytest

from app.services import ett_analysis as analysis
from app.services.ett_acquisition import AcquisitionError
from app.services.ett_acquisition import canonical_bytes
from app.services.ett_artifacts import LocalArtifactStore
from tests.test_ett_acquisition import capture


@pytest.fixture(scope="module")
def chapter01():
    corpus = Path(__file__).resolve().parents[3] / "backend/app/services/source_sync/data"
    return next(corpus.glob("ru.01_*.pdf")).read_bytes()


def test_original_bytes_produce_complete_base_cells_with_unverified_footnotes(chapter01):
    report = analysis.analyze_chapter(chapter01, artifact_id="chapter-01", chapter="01", known_note_ids=("63C",))
    rows = {row["code"]: row for row in report["records"]}
    assert rows["0101210000"]["duty_cell_analysis"]["duty"]["ad_valorem_percent"] == "0"
    bee = rows["0106410001"]
    assert bee["duty_raw"] == "563С)"
    assert bee["duty_cell_analysis"]["duty"]["ad_valorem_percent"] == "5"
    assert bee["duty_cell_analysis"]["footnote_ids"] == ["63C"]
    assert bee["unbound_footnote_ids"] == []
    assert bee["rate_applicability_verified"] is False
    assert report["current_rates_verified"] is report["can_promote"] is False
    assert report["legal_rates_resolved"] == 0
    assert "0101000000" not in rows


def test_note_ids_are_not_silently_assumed_present(chapter01):
    report = analysis.analyze_chapter(chapter01, artifact_id="chapter-01", chapter="01")
    row = next(row for row in report["records"] if row["code"] == "0106410001")
    assert row["unbound_footnote_ids"] == ["63C"]
    assert report["duty_cell_summary"]["unbound_footnote_references"]["63C"] > 0


@pytest.fixture
def technical_set(tmp_path, monkeypatch):
    store = LocalArtifactStore(tmp_path / "objects")
    result, _ = capture(store)
    notes = {"observed_note_ids": ["63C", "63C"], "duplicate_note_ids": ["63C"],
             "note_count": 2, "legal_dates_verified": False, "issues": ["duplicate_note_ids"],
             "unassigned_rows": [], "all_source_rows_accounted": True}
    monkeypatch.setattr(analysis, "extract_tariff_notes", lambda *a, **k: deepcopy(notes))
    calls = []
    def assemble(data, *, artifact_id, chapter, known_note_ids):
        assert data.startswith(b"%PDF-")
        assert not known_note_ids  # Duplicate note IDs never count as bound.
        calls.append((artifact_id, chapter))
        return {"records": [{"code": chapter + "12345678", "issues": []}], "record_count": 1, "issues": [],
                "source_pages_without_text": [], "source_pages_without_headers": [],
                "resolved_description_count": 1, "excluded_candidates": [],
                "duty_cell_summary": {"parsed": 1, "unresolved": 0, "unbound_footnote_references": {"63C": 1}}}
    monkeypatch.setattr(analysis, "analyze_chapter", assemble)
    return store, result["receipt_sha256"], calls


def test_full_analysis_index_binds_every_chapter_report_without_legal_promotion(technical_set):
    store, digest, calls = technical_set
    result = analysis.analyze_acquisition(store, digest)
    assert result["chapter_count"] == result["table_records"] == result["parsed_duty_cells"] == len(calls) == 96
    assert result["unbound_footnote_references"] == {"63C": 96}
    assert result["complete_rate_catalog_verified"] is result["production_ready"] is result["active_rates_written"] is False
    assert result["legal_rates_resolved"] == 0
    assert result["linked_legal_pdf_capture"] is True
    assert result["note_inventory_diagnostics"] == ["duplicate_note_ids"]
    assert result["assembly_diagnostics"] == result["row_diagnostics"] == {}
    assert result["all_note_source_rows_accounted"] is True
    summary = json.loads(store.read(result["report_sha256"]))
    assert summary["receipt_sha256"] == digest
    assert len(summary["chapters"]) == 96
    for chapter in summary["chapters"]:
        assert json.loads(store.read(chapter["report_sha256"]))["record_count"] == 1


def test_partial_analysis_cannot_return_a_complete_report(technical_set, monkeypatch):
    store, digest, _ = technical_set
    original = analysis.analyze_chapter
    def fail(data, **kwargs):
        if kwargs["chapter"] == "03": raise ValueError("unreadable third chapter")
        return original(data, **kwargs)
    monkeypatch.setattr(analysis, "analyze_chapter", fail)
    with pytest.raises(ValueError, match="unreadable third"):
        analysis.analyze_acquisition(store, digest)


def test_analysis_output_budget_is_enforced(technical_set, monkeypatch):
    store, digest, _ = technical_set
    monkeypatch.setattr(analysis, "MAX_REPORT_BYTES", 10)
    with pytest.raises(AcquisitionError, match="resource budget"):
        analysis.analyze_acquisition(store, digest)


def test_analysis_cannot_skip_integrity_checks(technical_set, monkeypatch):
    store, _, _ = technical_set
    with pytest.raises(ValueError):
        analysis.analyze_acquisition(store, "a" * 64)


def test_bounded_encoding_preserves_canonical_hash_and_rejects_overflow():
    value = {"я": ["ставка", 1], "a": False}
    raw = canonical_bytes(value)
    assert analysis._bounded_json(value, maximum=len(raw), started=time.monotonic()) == raw
    with pytest.raises(AcquisitionError, match="resource budget"):
        analysis._bounded_json(value, maximum=len(raw)-1, started=time.monotonic())


def test_empty_chapter_is_explicitly_incomplete(technical_set, monkeypatch):
    store, digest, _ = technical_set
    original = analysis.analyze_chapter
    def empty(data, **kwargs):
        report = original(data, **kwargs)
        if kwargs["chapter"] == "03":
            report.update(records=[], record_count=0, resolved_description_count=0)
            report["duty_cell_summary"].update(parsed=0)
        return report
    monkeypatch.setattr(analysis, "analyze_chapter", empty)
    result = analysis.analyze_acquisition(store, digest)
    assert result["empty_table_chapters"] == ["03"]
    assert "empty_table_chapters" in result["blockers"]
    assert result["complete_rate_catalog_verified"] is False


@pytest.mark.parametrize("ids", ["63C", ["063C"], ["63С"], [True], range(10_001)])
def test_note_identifier_input_is_bounded_and_exact(ids):
    with pytest.raises(ValueError, match="known note IDs"):
        analysis.analyze_chapter(b"unused", artifact_id="chapter-01", chapter="01", known_note_ids=ids)
