from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import os
from urllib.parse import urlencode

import pytest

from app.services.ett_artifacts import LocalArtifactStore
from app.services.ett_portal_search import PORTAL_SEARCH_URL
from app.services.ett_transport import OfficialResponse, OfficialTransportError
from scripts.probe_ett_portal_search import PROBE_QUERIES, main, probe_portal_search


def source(query):
    url = PORTAL_SEARCH_URL + "?" + urlencode({"q": query})
    content = ("<!doctype html><html><body>synthetic results: " + query + "</body></html>").encode()
    return OfficialResponse(url=url, requested_url=url, content=content,
                            media_type="text/html", retrieved_at=datetime(2026, 9, 8, tzinfo=timezone.utc))


def test_all_three_queries_retain_original_bytes_but_do_not_prove_legal_facts(tmp_path):
    store = LocalArtifactStore(tmp_path / "objects")
    calls = []
    def fetch(query):
        calls.append(query)
        return source(query)
    report = probe_portal_search(store, fetch=fetch)
    assert calls == ["Единого таможенного тарифа", "168", "09.07.2026"]
    assert report["attempted_queries"] == report["captured_queries"] == 3
    assert report["failed_queries"] == 0
    assert report["all_queries_captured"] is True
    for record, (_, query) in zip(report["results"], PROBE_QUERIES):
        response = source(query)
        assert record["sha256"] == hashlib.sha256(response.content).hexdigest()
        assert store.read(record["sha256"]) == response.content
        assert record["size_bytes"] == len(response.content)
        assert record["requested_url"] == record["response_url"] == response.requested_url
        assert record["redirect_chain"] == []
        assert record["retrieved_at"] == response.retrieved_at.isoformat()
    for key in ("source_identity_verified", "adoption_dates_verified", "effective_dates_verified",
                "amendment_inventory_complete", "search_results_interpreted", "document_absence_verified",
                "production_ready", "active_rates_written", "durable_legal_retention_attested"):
        assert report[key] is False
    assert report["storage_kind"] == "local_development"


def test_failure_does_not_prevent_later_queries_and_errors_are_static(tmp_path):
    calls = []
    def fetch(query):
        calls.append(query)
        if query == "168":
            raise OfficialTransportError("SECRET URL credential", diagnostics={"body": "SECRET", "kind": "rejected_url"})
        return source(query)
    report = probe_portal_search(LocalArtifactStore(tmp_path / "objects"), fetch=fetch)
    assert len(calls) == 3
    assert report["captured_queries"] == 2
    assert report["failed_queries"] == 1
    assert report["all_queries_captured"] is False
    assert report["results"][1]["reason"] == "transport_failure"
    assert "SECRET" not in json.dumps(report)


@pytest.mark.parametrize("change", [
    {"requested_url": PORTAL_SEARCH_URL + "?q=wrong"},
    {"url": "https://evil.example/documents/1/2/", "redirect_chain": ("https://evil.example/documents/1/2/",)},
    {"url": "https://docs.eaeunion.org/documents/search/?q=a&extra=b", "redirect_chain": ("https://docs.eaeunion.org/documents/search/?q=a&extra=b",)},
    {"url": "https://docs.eaeunion.org/documents/1/2/"},
    {"redirect_chain": ("https://docs.eaeunion.org/documents/1/2/",)},
    {"redirect_chain": ("https://docs.eaeunion.org/documents/1/2/",) * 4},
    {"content": b"not HTML"}, {"content": b""}, {"content": "not bytes"},
    {"media_type": "application/pdf"}, {"retrieved_at": datetime(2026, 9, 8)},
])
def test_forged_response_is_never_saved_as_a_captured_search(tmp_path, change):
    store = LocalArtifactStore(tmp_path / "objects")
    report = probe_portal_search(store, fetch=lambda query: replace(source(query), **change))
    assert report["captured_queries"] == 0
    assert report["failed_queries"] == 3
    assert list((tmp_path / "objects").iterdir()) == []


def test_verified_metadata_retains_canonical_document_redirect(tmp_path):
    url = "https://docs.eaeunion.org/documents/399/6620/"
    report = probe_portal_search(LocalArtifactStore(tmp_path / "objects"),
        fetch=lambda query: replace(source(query), url=url, redirect_chain=(url,)))
    assert report["captured_queries"] == 3
    assert all(record["redirect_chain"] == [url] and record["response_url"] == url for record in report["results"])


def test_storage_failure_is_static_and_later_queries_continue(tmp_path):
    store = LocalArtifactStore(tmp_path / "objects")
    readonly = LocalArtifactStore(tmp_path / "objects", create=False)
    report = probe_portal_search(readonly, fetch=source)
    assert report["failed_queries"] == 3
    assert all(record["reason"] == "source_storage_integrity_failure" for record in report["results"])
    assert store.storage_kind == "local_development"


@pytest.mark.parametrize("fail", [False, True])
def test_cli_writes_complete_new_private_report_and_exits_two_on_any_failure(tmp_path, capsys, fail):
    output = tmp_path / "report.json"
    def fetch(query):
        if fail and query == "168":
            raise OfficialTransportError("official source did not return HTTP 200")
        return source(query)
    status = main(["--store-root", str(tmp_path / "objects"), "--output", str(output)], fetch=fetch)
    assert status == (2 if fail else 0)
    report = json.loads(output.read_text())
    assert report["failed_queries"] == int(fail)
    assert report["production_ready"] is False
    assert os.stat(output).st_mode & 0o777 == 0o600
    assert not list(tmp_path.glob(".ett-search-probe-*"))
    stdout = json.loads(capsys.readouterr().out)
    assert stdout["status"] == ("incomplete" if fail else "captured")
    assert stdout["production_ready"] is False


@pytest.mark.parametrize("kind", ["existing", "symlink", "missing_parent"])
def test_cli_rejects_unavailable_output_before_fetch_or_overwrite(tmp_path, capsys, kind):
    output = tmp_path / "report.json"
    if kind == "existing":
        output.write_bytes(b"existing report")
    elif kind == "symlink":
        output.symlink_to(tmp_path / "missing-target")
    else:
        output = tmp_path / "absent" / "report.json"
    calls = []
    assert main(["--store-root", str(tmp_path / "objects"), "--output", str(output)],
                fetch=lambda query: calls.append(query)) == 2
    assert calls == []
    assert json.loads(capsys.readouterr().out)["reason"] == "probe_setup_or_report_failed"
    if kind == "existing":
        assert output.read_bytes() == b"existing report"


def test_cli_does_not_replace_report_created_during_acquisition(tmp_path, capsys):
    output = tmp_path / "report.json"
    def fetch(query):
        output.write_bytes(b"another writer")
        return source(query)
    assert main(["--store-root", str(tmp_path / "objects"), "--output", str(output)], fetch=fetch) == 2
    assert output.read_bytes() == b"another writer"
    assert not list(tmp_path.glob(".ett-search-probe-*"))
    assert json.loads(capsys.readouterr().out)["reason"] == "probe_setup_or_report_failed"
