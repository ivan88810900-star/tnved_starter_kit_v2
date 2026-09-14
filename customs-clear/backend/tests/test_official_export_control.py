from __future__ import annotations

from app.services.official_export_control import (
    evaluate_export_control_requirement,
    export_control_dataset_summary,
    match_export_control_candidate,
)
from scripts.build_official_export_control_dataset import _TnvedLinkParser


def test_all_six_lists_dataset_is_loaded_and_normalized() -> None:
    summary = export_control_dataset_summary()
    assert summary["candidate_count"] == 1087
    assert summary["raw_candidate_count"] == 1087
    assert summary["effective_candidate_count"] == 1085
    assert summary["retired_exact_code_count"] == 2
    assert summary["retired_exact_codes"] == ["3910000002", "3910000008"]
    assert summary["retired_exact_codes_catalog_revision"] == "ett:2026-06-18"
    assert summary["source_list_count"] == 6
    assert summary["source_list_candidate_counts"] == {
        "1284": 112,
        "1285": 132,
        "1286": 331,
        "1287": 51,
        "1288": 162,
        "1299": 616,
    }
    assert sum(summary["source_list_candidate_counts"].values()) > summary["candidate_count"]
    assert summary["applicability"] == "needs_clarification"
    assert summary["enforcement_enabled"] is False


def test_candidate_match_prefers_reference_prefix() -> None:
    matched = match_export_control_candidate("8517620009")
    assert matched is not None
    assert "8517620009".startswith(matched)


def test_non_candidate_has_no_export_control_row() -> None:
    assert evaluate_export_control_requirement("0101210000", "лошадь") is None


def test_obsolete_revision_codes_do_not_match() -> None:
    assert evaluate_export_control_requirement("2710198200", "масло смазочное") is None
    assert evaluate_export_control_requirement("3910000002", "силикон в первичной форме") is None
    assert evaluate_export_control_requirement("3910000008", "силикон в первичной форме") is None


def test_current_silicone_replacement_codes_remain_candidates() -> None:
    assert evaluate_export_control_requirement("3910000006", "силикон в первичной форме") is not None
    assert evaluate_export_control_requirement("3910000009", "силикон в первичной форме") is not None


def test_export_control_row_cannot_affect_missing_check() -> None:
    row = evaluate_export_control_requirement("8517620009", "маршрутизатор")
    assert row is not None
    assert row["applicability"] == "needs_clarification"
    assert row["used_for_missing_check"] is False
    assert row["requires_manual_review"] is True
    assert row["source_documents"]


def test_builder_ignores_tnved_links_from_previous_revision_blocks() -> None:
    parser = _TnvedLinkParser()
    parser.feed("""
        <div class="content-new">
          <a class="ordw-tnved" href="/tnved/code/3910000006/">3910 00 000 6</a>
        </div>
        <div class="content-old">
          <div><a class="ordw-tnved" href="/tnved/code/3910000002/">3910 00 000 2</a></div>
        </div>
        <a class="ordw-tnved" href="/tnved/?tnved=8543"><span>8543</span></a>
    """)
    assert parser.codes == {"3910000006", "8543"}
