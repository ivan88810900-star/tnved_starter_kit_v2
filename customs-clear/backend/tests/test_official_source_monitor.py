"""Stateful checksum monitor must detect drift without losing a good baseline."""

from __future__ import annotations

from unittest.mock import patch

from scripts import monitor_official_ntm_sources as monitor


class _Response:
    def __init__(self, body: bytes, status_code: int = 200) -> None:
        self.content = body
        self.status_code = status_code
        self.url = "https://example.test/final"
        self.headers = {"content-type": "application/pdf", "etag": '"v2"'}


class _Client:
    def __init__(self, response: _Response) -> None:
        self.response = response
        self.request_headers = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def get(self, url, headers=None):
        self.request_headers = headers
        return self.response


def test_changed_digest_requires_review() -> None:
    previous = {
        "sources": {
            "only": {
                "sha256": "old",
                "etag": '"v1"',
                "url": "https://example.test/source",
            }
        }
    }
    client = _Client(_Response(b"x" * 101))
    with (
        patch.object(monitor, "SOURCES", {"only": "https://example.test/source"}),
        patch.object(monitor.httpx, "Client", return_value=client),
    ):
        report = monitor.monitor_sources(previous_state=previous)
    assert report["review_required"] is True
    assert report["changed_source_ids"] == ["only"]
    assert client.request_headers["If-None-Match"] == '"v1"'


def test_failed_fetch_preserves_previous_state() -> None:
    previous = {"sources": {"only": {"sha256": "known-good", "url": "https://example.test/source"}}}
    client = _Client(_Response(b"failure", status_code=503))
    with (
        patch.object(monitor, "SOURCES", {"only": "https://example.test/source"}),
        patch.object(monitor.httpx, "Client", return_value=client),
    ):
        report = monitor.monitor_sources(previous_state=previous)
    assert report["all_available"] is False
    assert report["next_state"]["sources"]["only"]["sha256"] == "known-good"
