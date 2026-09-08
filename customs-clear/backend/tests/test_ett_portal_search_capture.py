"""Bounded observed-link capture with synthetic DOM and original-byte replay."""
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
from html import escape
import json
from pathlib import Path

import pytest

from app.services.ett_artifacts import LocalArtifactStore
from app.services.ett_legal_search import parse_legal_search
from app.services.ett_transport import OfficialResponse, OfficialTransportError
from scripts import capture_ett_portal_search as capture
from scripts import probe_ett_portal_search as probe
from tests.test_ett_legal_search import page, row


INSTANT = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)
LEGAL_FLAGS = (
    "source_identity_verified", "adoption_dates_verified", "effective_dates_verified",
    "amendment_inventory_complete", "document_absence_verified",
    "cross_page_snapshot_consistency_verified", "production_ready", "active_rates_written",
    "durable_legal_retention_attested",
)


def url(number):
    return capture.INITIAL_URL + (f"&PAGEN_1={number}" if number > 1 else "")


def body(document="1", *, links=(), rows=None, extra="", query=capture.QUERY, empty=False):
    anchors = "".join(
        f'<a href="{escape(url(number).removeprefix("https://docs.eaeunion.org"))}">{escape(label)}</a>'
        for number, label in links
    )
    return page(row(document=document) if rows is None else rows, pagination=False, query=query, empty=empty, extra=anchors + extra)


def source(raw, requested):
    return OfficialResponse(
        url=requested, requested_url=requested, content=raw, media_type="text/html",
        retrieved_at=INSTANT, redirect_chain=(),
    )


def run(tmp_path, pages, *, on_request=None):
    store = LocalArtifactStore(tmp_path / "objects")
    seen = []

    def fetch(requested):
        seen.append(requested)
        if on_request:
            on_request(requested)
        value = pages[requested]
        if isinstance(value, Exception):
            raise value
        return source(value, requested)

    report = capture.capture_portal_search(store, fetch=fetch)
    return report, store, seen


def assert_unverified(report):
    assert all(report[key] is False for key in LEGAL_FLAGS)
    assert report["storage_kind"] == "local_development"


def assert_saved(store, record, raw):
    assert record["sha256"] == hashlib.sha256(raw).hexdigest()
    assert record["size_bytes"] == len(raw)
    assert record["retrieved_at"] == INSTANT.isoformat()
    assert store.read(record["sha256"]) == raw


def test_three_pages_follow_only_observed_next_link_and_retain_exact_parent_evidence(tmp_path):
    pages = {
        url(1): body("1", links=[(2, "2"), (2, "След."), (3, "3")]),
        url(2): body("2", links=[(1, "1"), (3, "След.")]),
        url(3): body("3", links=[(1, "1"), (2, "Пред.")]),
    }
    report, store, seen = run(tmp_path, pages)
    assert seen == [url(1), url(2), url(3)]
    assert report["status"] == "observed_chain_captured"
    assert report["stop_reason"] == "observed_chain_exhausted"
    assert report["observed_chain_exhausted"] is True
    assert report["pending_next_url"] is None
    assert report["attempted_pages"] == report["captured_pages"] == report["accepted_pages"] == 3
    assert report["accepted_raw_rows"] == 3
    assert report["captured_bytes"] == sum(map(len, pages.values()))
    assert report["highest_observed_page_number"] == 3
    assert report["results"][0]["followed_from"] is None
    for number, record in enumerate(report["results"], 1):
        assert_saved(store, record, pages[url(number)])
        assert record["page_number"] == number
        assert record["requested_url"] == record["response_url"] == url(number)
        assert record["row_payloads_retained_in"] == "source_html"
        if number > 1:
            previous = pages[url(number - 1)]
            parsed = parse_legal_search(previous, url(number - 1))
            link = next(item for item in parsed.pagination_links if item.url == url(number))
            assert record["followed_from"] == {
                "page_sha256": hashlib.sha256(previous).hexdigest(),
                "page_url": url(number - 1), "link": asdict(link),
            }
    assert_unverified(report)


def test_later_page_does_not_authorize_constructing_missing_immediate_next_url(tmp_path):
    raw = body(links=[(3, "3")])
    report, store, seen = run(tmp_path, {url(1): raw})
    assert seen == [url(1)]
    assert report["highest_observed_page_number"] == 3
    assert report["stop_reason"] == "observed_next_page_link_missing"
    assert report["status"] == "incomplete"
    assert report["observed_chain_exhausted"] is False
    assert_saved(store, report["results"][0], raw)


def test_earlier_highest_page_is_remembered_when_next_page_drops_pagination(tmp_path):
    report, _, seen = run(tmp_path, {
        url(1): body("1", links=[(2, "2"), (3, "3")]),
        url(2): body("2"),
    })
    assert seen == [url(1), url(2)]
    assert report["highest_observed_page_number"] == 3
    assert report["accepted_pages"] == 2
    assert report["stop_reason"] == "observed_next_page_link_missing"
    assert report["observed_chain_exhausted"] is False


def test_query_echo_mismatch_retains_raw_body_but_accepts_no_rows(tmp_path):
    raw = body(query="different query")
    report, store, seen = run(tmp_path, {url(1): raw})
    assert seen == [url(1)]
    assert report["stop_reason"] == "search_parse_failed"
    assert report["captured_pages"] == 1
    assert report["accepted_pages"] == report["accepted_raw_rows"] == 0
    assert report["results"][0]["parse_status"] == "unresolved"
    assert_saved(store, report["results"][0], raw)
    assert_unverified(report)


def test_exhausted_chain_keeps_unsupported_rows_and_never_proves_legal_completeness(tmp_path):
    raw = body(rows=row(document="1") + row(document="2", category="Международные договоры – Архив", label="Протокол"))
    report, store, _ = run(tmp_path, {url(1): raw})
    assert report["observed_chain_exhausted"] is True
    assert report["accepted_raw_rows"] == 2
    assert report["results"][0]["row_identity_counts"] == {
        "observed_decision_identity": 1, "outside_supported_decision_category": 1,
    }
    assert_saved(store, report["results"][0], raw)
    assert_unverified(report)


def test_explicit_empty_notice_is_retained_without_document_absence_claim(tmp_path):
    raw = body(rows="", empty=True)
    report, store, _ = run(tmp_path, {url(1): raw})
    assert report["observed_chain_exhausted"] is True
    assert report["accepted_pages"] == 1
    assert report["accepted_raw_rows"] == 0
    assert report["results"][0]["empty_result_notice"] is True
    assert_saved(store, report["results"][0], raw)
    assert_unverified(report)


def test_page_limit_stops_before_fetching_next_observed_link(tmp_path, monkeypatch):
    assert capture.MAX_PAGES == 20
    monkeypatch.setattr(capture, "MAX_PAGES", 1)
    report, _, seen = run(tmp_path, {url(1): body(links=[(2, "2")])})
    assert seen == [url(1)]
    assert report["stop_reason"] == "page_budget_exceeded"
    assert report["pending_next_url"] == url(2)
    assert report["accepted_pages"] == 1


def test_byte_limit_reserves_maximum_response_before_next_request(tmp_path, monkeypatch):
    assert capture.MAX_TOTAL_BYTES == 80 * 1024 * 1024
    raw = body(links=[(2, "2")])
    maximum = len(raw) + 1
    monkeypatch.setattr(capture, "MAX_HTML_BYTES", maximum)
    monkeypatch.setattr(capture, "MAX_TOTAL_BYTES", maximum)
    report, store, seen = run(tmp_path, {url(1): raw})
    assert seen == [url(1)]
    assert report["stop_reason"] == "byte_budget_exceeded"
    assert report["captured_bytes"] == len(raw) < maximum
    assert_saved(store, report["results"][0], raw)


def test_row_limit_stops_before_request_once_allowance_is_used(tmp_path, monkeypatch):
    assert capture.MAX_RAW_ROWS == 1000
    monkeypatch.setattr(capture, "MAX_RAW_ROWS", 1)
    report, _, seen = run(tmp_path, {url(1): body(links=[(2, "2")])})
    assert seen == [url(1)]
    assert report["stop_reason"] == "row_budget_exceeded"
    assert report["accepted_raw_rows"] == 1
    assert report["pending_next_url"] == url(2)


def test_page_exceeding_remaining_row_allowance_is_saved_but_rows_not_accepted(tmp_path, monkeypatch):
    monkeypatch.setattr(capture, "MAX_RAW_ROWS", 2)
    pages = {url(1): body("1", links=[(2, "2")]), url(2): body(rows=row(document="2") + row(document="3"))}
    report, store, seen = run(tmp_path, pages)
    assert seen == [url(1), url(2)]
    assert report["stop_reason"] == "row_budget_exceeded"
    assert report["captured_pages"] == 2
    assert report["accepted_pages"] == report["accepted_raw_rows"] == 1
    last = report["results"][1]
    assert last["observed_raw_rows"] == 2
    assert last["parse_status"] == "unresolved"
    assert "accepted_raw_rows" not in last
    assert_saved(store, last, pages[url(2)])


def test_elapsed_limit_after_fetch_preserves_late_raw_bytes_without_accepting_rows(tmp_path, monkeypatch):
    assert capture.MAX_ELAPSED_SECONDS == 20 * 60
    now = [0.0]
    monkeypatch.setattr(capture.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(capture, "MAX_ELAPSED_SECONDS", 2)
    monkeypatch.setattr(capture, "MAX_REQUEST_SECONDS", 1)
    raw = body()
    report, store, seen = run(tmp_path, {url(1): raw}, on_request=lambda _: now.__setitem__(0, 3.0))
    assert seen == [url(1)]
    assert report["stop_reason"] == "elapsed_time_budget"
    assert report["captured_pages"] == 1
    assert report["accepted_pages"] == report["accepted_raw_rows"] == 0
    assert_saved(store, report["results"][0], raw)


def test_elapsed_limit_before_first_request_returns_incomplete_without_network(tmp_path, monkeypatch):
    moments = iter([0.0, 3.0])
    monkeypatch.setattr(capture.time, "monotonic", lambda: next(moments))
    monkeypatch.setattr(capture, "MAX_ELAPSED_SECONDS", 2)
    report, _, seen = run(tmp_path, {})
    assert seen == []
    assert report["results"] == []
    assert report["stop_reason"] == "elapsed_time_budget"
    assert report["observed_chain_exhausted"] is False


def test_elapsed_budget_reserves_full_bounded_request_before_network(tmp_path, monkeypatch):
    monkeypatch.setattr(capture.time, "monotonic", lambda: 0.0)
    monkeypatch.setattr(capture, "MAX_ELAPSED_SECONDS", 2)
    monkeypatch.setattr(capture, "MAX_REQUEST_SECONDS", 3)
    report, _, seen = run(tmp_path, {})
    assert seen == []
    assert report["stop_reason"] == "elapsed_time_budget"
    assert report["attempted_pages"] == 0


def test_transport_failure_preserves_prior_page_and_exact_next_link_without_retry(tmp_path):
    first = body(links=[(2, "2")])
    report, store, seen = run(tmp_path, {url(1): first, url(2): OfficialTransportError("SECRET upstream error")})
    assert seen == [url(1), url(2)]
    assert report["stop_reason"] == "transport_failure"
    assert report["captured_pages"] == report["accepted_pages"] == 1
    assert report["results"][1]["status"] == "failed"
    assert report["results"][1]["followed_from"]["page_sha256"] == hashlib.sha256(first).hexdigest()
    assert_saved(store, report["results"][0], first)
    assert "SECRET" not in json.dumps(report)


def test_parser_failure_after_first_page_retains_both_original_bodies(tmp_path):
    pages = {url(1): body("1", links=[(2, "2")]), url(2): body("2").replace(b'class="SearchForm _documents"', b'class="unrecognized"')}
    report, store, seen = run(tmp_path, pages)
    assert seen == [url(1), url(2)]
    assert report["stop_reason"] == "search_parse_failed"
    assert report["captured_pages"] == 2
    assert report["accepted_pages"] == 1
    for record in report["results"]:
        assert_saved(store, record, pages[record["requested_url"]])


def test_repeated_original_body_is_retained_but_not_accepted_as_next_page(tmp_path):
    raw = body(links=[(2, "2")])
    report, store, seen = run(tmp_path, {url(1): raw, url(2): raw})
    assert seen == [url(1), url(2)]
    assert report["stop_reason"] == "repeated_search_page_body"
    assert report["accepted_pages"] == 1
    assert report["captured_pages"] == 2
    assert_saved(store, report["results"][1], raw)


@pytest.mark.parametrize("reverse_rows", [False, True])
def test_repeated_result_set_cannot_be_accepted_when_html_or_row_order_changes(tmp_path, reverse_rows):
    rows = [row(document="1"), row(document="2")]
    first = body(rows="".join(rows), links=[(2, "2")])
    second = body(rows="".join(reversed(rows) if reverse_rows else rows), extra="<p>different incidental HTML</p>")
    assert hashlib.sha256(first).digest() != hashlib.sha256(second).digest()
    report, store, seen = run(tmp_path, {url(1): first, url(2): second})
    assert seen == [url(1), url(2)]
    assert report["stop_reason"] == "repeated_search_result_rows"
    assert report["observed_chain_exhausted"] is False
    assert report["accepted_pages"] == 1
    assert report["accepted_raw_rows"] == 2
    assert_saved(store, report["results"][1], second)


def test_cli_exhausted_chain_writes_complete_new_report_and_returns_zero(tmp_path, capsys):
    output = tmp_path / "capture.json"
    store_root = tmp_path / "objects"
    raw = body()
    code = capture.main(["--store-root", str(store_root), "--output", str(output)], fetch=lambda requested: source(raw, requested))
    assert code == 0
    report = json.loads(output.read_text())
    printed = json.loads(capsys.readouterr().out)
    assert report["status"] == printed["status"] == "observed_chain_captured"
    assert report["observed_chain_exhausted"] is True
    assert_unverified(report)
    assert LocalArtifactStore(store_root, create=False).read(report["results"][0]["sha256"]) == raw
    assert list(tmp_path.glob(".ett-search-probe-*")) == []


def test_cli_incomplete_capture_writes_progress_and_returns_two(tmp_path, capsys):
    output = tmp_path / "capture.json"
    first = body(links=[(2, "2")])
    seen = []

    def fetch(requested):
        seen.append(requested)
        if requested == url(1):
            return source(first, requested)
        raise OfficialTransportError("SECRET")

    assert capture.main(["--store-root", str(tmp_path / "objects"), "--output", str(output)], fetch=fetch) == 2
    assert seen == [url(1), url(2)]
    report = json.loads(output.read_text())
    assert report["status"] == "incomplete"
    assert report["accepted_pages"] == 1
    assert report["stop_reason"] == "transport_failure"
    assert "SECRET" not in output.read_text() + capsys.readouterr().out


@pytest.mark.parametrize("symlink", [False, True])
def test_cli_refuses_existing_output_or_dangling_symlink_before_capture(tmp_path, symlink, capsys):
    output = tmp_path / "capture.json"
    if symlink:
        output.symlink_to(tmp_path / "missing.json")
    else:
        output.write_text("existing report")
    assert capture.main(
        ["--store-root", str(tmp_path / "objects"), "--output", str(output)],
        fetch=lambda requested: pytest.fail("existing report must fail before fetch"),
    ) == 2
    assert json.loads(capsys.readouterr().out)["reason"] == "capture_setup_or_report_failed"
    assert not (tmp_path / "objects").exists()
    if symlink:
        assert output.is_symlink()
        assert not (tmp_path / "missing.json").exists()
    else:
        assert output.read_text() == "existing report"


def test_cli_report_publication_race_cannot_replace_another_writer(tmp_path, monkeypatch, capsys):
    output = tmp_path / "capture.json"
    writer = capture._write_report

    def competing_writer(path, report):
        path.write_text("winning concurrent report")
        writer(path, report)

    monkeypatch.setattr(capture, "_write_report", competing_writer)
    assert capture.main(["--store-root", str(tmp_path / "objects"), "--output", str(output)], fetch=lambda requested: source(body(), requested)) == 2
    assert output.read_text() == "winning concurrent report"
    assert json.loads(capsys.readouterr().out)["status"] == "ERROR"
    assert list(tmp_path.glob(".ett-search-probe-*")) == []


def test_cli_failed_atomic_publication_leaves_no_partial_report_and_keeps_source(tmp_path, monkeypatch, capsys):
    output = tmp_path / "capture.json"
    store_root = tmp_path / "objects"
    raw = body()
    real_link = probe.os.link

    def failed_publish(source_path, target, *args, **kwargs):
        if Path(target) == output:
            raise OSError("SECRET publication failure")
        return real_link(source_path, target, *args, **kwargs)

    monkeypatch.setattr(probe.os, "link", failed_publish)
    assert capture.main(["--store-root", str(store_root), "--output", str(output)], fetch=lambda requested: source(raw, requested)) == 2
    assert not output.exists()
    assert list(tmp_path.glob(".ett-search-probe-*")) == []
    assert LocalArtifactStore(store_root, create=False).read(hashlib.sha256(raw).hexdigest()) == raw
    assert "SECRET" not in capsys.readouterr().out
