"""Stateful checksum monitor must detect drift without losing a good baseline."""

from __future__ import annotations

import hashlib
from unittest.mock import patch

import pytest

from scripts import monitor_official_ntm_sources as monitor


class _Response:
    def __init__(
        self,
        body: bytes,
        status_code: int = 200,
        *,
        content_type: str = "application/pdf",
        final_url: str = "https://example.test/final",
    ) -> None:
        self.content = body
        self.status_code = status_code
        self.url = final_url
        self.headers = {"content-type": content_type, "etag": '"v2"'}


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


def test_pending_legal_digest_is_sticky_and_forces_full_revalidation() -> None:
    body = b"%PDF-1.7\n" + b"pending legal content" * 20
    previous = {
        "sources": {
            "only": {
                "sha256": "approved-digest",
                "pending_sha256": hashlib.sha256(body).hexdigest(),
                "etag": '"approved-etag"',
                "last_modified": "Mon, 31 Aug 2026 00:00:00 GMT",
                "url": "https://example.test/source.pdf",
            }
        }
    }
    client = _Client(
        _Response(
            body,
            content_type="application/pdf",
            final_url="https://example.test/source.pdf",
        )
    )
    with (
        patch.object(monitor, "SOURCES", {"only": "https://example.test/source.pdf"}),
        patch.object(monitor, "SOURCE_MODES", {"only": "legal_drift"}),
        patch.object(monitor.httpx, "Client", return_value=client),
    ):
        report = monitor.monitor_sources(previous_state=previous)

    assert client.request_headers == {}
    assert report["review_required"] is True
    assert report["pending_review_source_ids"] == ["only"]
    assert report["sources"][0]["requires_approval"] is True
    assert report["next_state"]["sources"]["only"]["pending_sha256"] == hashlib.sha256(body).hexdigest()


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
    client = _Client(_Response(b"%PDF-1.7\n" + b"x" * 101))
    with (
        patch.object(monitor, "SOURCES", {"only": "https://example.test/source.pdf"}),
        patch.object(monitor, "SOURCE_MODES", {"only": "legal_drift"}),
        patch.object(monitor.httpx, "Client", return_value=client),
    ):
        report = monitor.monitor_sources(previous_state=previous)
    assert report["review_required"] is True
    assert report["changed_source_ids"] == ["only"]
    assert client.request_headers["If-None-Match"] == '"v1"'
    assert report["sources"][0]["baseline_advanced"] is False
    assert report["next_state"]["sources"]["only"]["sha256"] == "old"
    assert report["next_state"]["sources"]["only"]["pending_sha256"] == report["sources"][0]["observed_sha256"]


def test_explicit_approval_advances_legal_baseline() -> None:
    body = b"%PDF-1.7\n" + b"approved" * 20
    previous = {
        "sources": {
            "only": {
                "sha256": "old",
                "pending_sha256": hashlib.sha256(body).hexdigest(),
                "etag": '"v1"',
                "url": "https://example.test/source.pdf",
            }
        }
    }
    client = _Client(_Response(body))
    with (
        patch.object(monitor, "SOURCES", {"only": "https://example.test/source.pdf"}),
        patch.object(monitor, "SOURCE_MODES", {"only": "legal_drift"}),
        patch.object(monitor.httpx, "Client", return_value=client),
    ):
        report = monitor.monitor_sources(
            previous_state=previous,
            accept_changes=True,
            approval_ref="PR-187/legal-review",
        )
    row = report["sources"][0]
    state = report["next_state"]["sources"]["only"]
    assert report["review_required"] is False
    assert report["accepted_source_ids"] == ["only"]
    assert row["baseline_advanced"] is True
    assert state["sha256"] == row["observed_sha256"]
    assert state["approval_ref"] == "PR-187/legal-review"


def test_new_legal_source_requires_review_before_first_baseline() -> None:
    client = _Client(_Response(b"%PDF-1.7\n" + b"new legal source" * 20))
    with (
        patch.object(monitor, "SOURCES", {"only": "https://example.test/source.pdf"}),
        patch.object(monitor, "SOURCE_MODES", {"only": "legal_drift"}),
        patch.object(monitor.httpx, "Client", return_value=client),
    ):
        report = monitor.monitor_sources(previous_state={"sources": {}})
    row = report["sources"][0]
    state = report["next_state"]["sources"]["only"]
    assert row["new_source"] is True
    assert row["requires_approval"] is True
    assert row["baseline_advanced"] is False
    assert "sha256" not in state
    assert state["pending_sha256"] == row["observed_sha256"]


def test_structured_source_advances_automatically() -> None:
    previous = {"sources": {"only": {"sha256": "old", "url": "https://example.test/source.xml"}}}
    client = _Client(
        _Response(
            b"<root>" + b"structured" * 20 + b"</root>",
            content_type="application/xml",
        )
    )
    with (
        patch.object(monitor, "SOURCES", {"only": "https://example.test/source.xml"}),
        patch.object(monitor, "SOURCE_MODES", {"only": "structured_freshness"}),
        patch.object(monitor.httpx, "Client", return_value=client),
    ):
        report = monitor.monitor_sources(previous_state=previous)
    row = report["sources"][0]
    assert report["review_required"] is False
    assert row["changed"] is True
    assert row["baseline_advanced"] is True
    assert report["next_state"]["sources"]["only"]["sha256"] == row["observed_sha256"]


def test_availability_page_html_change_is_not_treated_as_source_revision() -> None:
    previous = {"sources": {"only": {"sha256": "old", "url": "https://example.test/portal"}}}
    client = _Client(
        _Response(
            b"<html><body>new portal template</body></html>" + b"x" * 101,
            content_type="text/html",
        )
    )
    with (
        patch.object(monitor, "SOURCES", {"only": "https://example.test/portal"}),
        patch.object(monitor, "SOURCE_MODES", {"only": "availability"}),
        patch.object(monitor.httpx, "Client", return_value=client),
    ):
        report = monitor.monitor_sources(previous_state=previous)
    row = report["sources"][0]
    assert row["ok"] is True
    assert row["changed"] is False
    assert row["new_source"] is False
    assert row["baseline_advanced"] is True
    assert report["review_required"] is False


def test_approval_does_not_accept_a_digest_that_changed_after_review() -> None:
    previous = {
        "sources": {
            "only": {
                "sha256": "old",
                "pending_sha256": "reviewed-digest",
                "url": "https://example.test/source.pdf",
            }
        }
    }
    client = _Client(_Response(b"%PDF-1.7\n" + b"changed-again" * 20))
    with (
        patch.object(monitor, "SOURCES", {"only": "https://example.test/source.pdf"}),
        patch.object(monitor, "SOURCE_MODES", {"only": "legal_drift"}),
        patch.object(monitor.httpx, "Client", return_value=client),
    ):
        report = monitor.monitor_sources(
            previous_state=previous,
            accept_changes=True,
            approval_ref="PR-187/legal-review",
        )
    row = report["sources"][0]
    assert row["approval_digest_mismatch"] is True
    assert row["baseline_advanced"] is False
    assert row["requires_approval"] is True
    assert report["accepted_source_ids"] == []
    assert report["next_state"]["sources"]["only"]["sha256"] == "old"


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


def test_invalid_pdf_is_rejected_and_preserves_baseline() -> None:
    previous = {
        "sources": {
            "only": {"sha256": "known-good", "url": "https://example.test/source.pdf"}
        }
    }
    client = _Client(
        _Response(
            b"<html><body>ordinary response, but not a PDF</body></html>" + b"x" * 101,
            content_type="text/html",
        )
    )
    with (
        patch.object(monitor, "SOURCES", {"only": "https://example.test/source.pdf"}),
        patch.object(monitor, "SOURCE_MODES", {"only": "legal_drift"}),
        patch.object(monitor.httpx, "Client", return_value=client),
    ):
        report = monitor.monitor_sources(previous_state=previous)
    assert report["all_available"] is False
    assert report["sources"][0]["validation_error"] == "invalid_pdf_content"
    assert report["next_state"]["sources"]["only"]["sha256"] == "known-good"


def test_block_page_is_rejected_even_with_success_http_status() -> None:
    previous = {"sources": {"only": {"sha256": "known-good", "url": "https://example.test/source"}}}
    client = _Client(
        _Response(
            b"<html><body>Access denied by upstream gateway</body></html>" + b"x" * 101,
            content_type="text/html",
        )
    )
    with (
        patch.object(monitor, "SOURCES", {"only": "https://example.test/source"}),
        patch.object(monitor, "SOURCE_MODES", {"only": "legal_drift"}),
        patch.object(monitor.httpx, "Client", return_value=client),
    ):
        report = monitor.monitor_sources(previous_state=previous)
    assert report["all_available"] is False
    assert report["sources"][0]["validation_error"] == "block_or_error_page_detected"
    assert report["next_state"]["sources"]["only"]["sha256"] == "known-good"


@pytest.mark.parametrize(
    ("body", "content_type"),
    (
        (b"<html><body>maintenance</body></html>" + b"x" * 101, "text/html"),
        (b"<root><broken></root>" + b"x" * 101, "application/xml"),
        (b"<root>" + b"x" * 101 + b"</root>", "text/html"),
    ),
)
def test_structured_xml_monitor_rejects_html_malformed_or_wrong_content_type(
    body: bytes,
    content_type: str,
) -> None:
    previous = {
        "sources": {
            "only": {"sha256": "known-good", "url": "https://example.test/source.xml"}
        }
    }
    client = _Client(_Response(body, content_type=content_type))
    with (
        patch.object(monitor, "SOURCES", {"only": "https://example.test/source.xml"}),
        patch.object(monitor, "SOURCE_MODES", {"only": "structured_freshness"}),
        patch.object(monitor.httpx, "Client", return_value=client),
    ):
        report = monitor.monitor_sources(previous_state=previous)
    assert report["all_available"] is False
    assert report["sources"][0]["validation_error"] == "invalid_xml_content"
    assert report["next_state"]["sources"]["only"]["sha256"] == "known-good"


def test_legal_baseline_acceptance_requires_reference() -> None:
    try:
        monitor.monitor_sources(previous_state={"sources": {}}, accept_changes=True)
    except ValueError as exc:
        assert "approval_ref" in str(exc)
    else:  # pragma: no cover - fail with a useful message
        raise AssertionError("legal baseline was accepted without approval reference")


def test_persisted_state_requires_current_schema_version(tmp_path) -> None:
    missing = tmp_path / "missing.json"
    assert monitor._load_state(missing) == {
        "version": monitor.STATE_SCHEMA_VERSION,
        "sources": {},
    }

    legacy = tmp_path / "legacy.json"
    legacy.write_text('{"version":1,"sources":{}}', encoding="utf-8")
    with pytest.raises(RuntimeError, match="expected version=3"):
        monitor._load_state(legacy)

    v2 = tmp_path / "v2.json"
    v2.write_text(
        '{"version":2,"sources":{"ofac":{"sha256":"approved",'
        '"etag":"\\"old\\"","last_modified":"yesterday"}}}',
        encoding="utf-8",
    )
    migrated = monitor._load_state(v2)
    assert migrated["version"] == monitor.STATE_SCHEMA_VERSION
    assert migrated["sources"]["ofac"]["sha256"] == "approved"
    assert "etag" not in migrated["sources"]["ofac"]
    assert "last_modified" not in migrated["sources"]["ofac"]

    source_url = "https://example.test/source.xml"
    client = _Client(
        _Response(
            b"",
            status_code=304,
            content_type="application/xml",
            final_url=source_url,
        )
    )
    with (
        patch.object(monitor, "SOURCES", {"ofac": source_url}),
        patch.object(monitor, "SOURCE_MODES", {"ofac": "structured_freshness"}),
        patch.object(monitor.httpx, "Client", return_value=client),
    ):
        report = monitor.monitor_sources(previous_state=migrated)
    assert client.request_headers == {}
    assert report["all_available"] is False
    assert report["sources"][0]["validation_error"] == "unexpected_http_status:304"

    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{not-json", encoding="utf-8")
    with pytest.raises(RuntimeError, match="cannot read"):
        monitor._load_state(corrupt)


def test_extensionless_eu_feed_is_xml_and_rejects_html() -> None:
    eu_url = (
        "https://webgate.ec.europa.eu/fsd/fsf/public/files/"
        "xmlFullSanctionsList_1_1/content"
    )
    assert monitor._expected_content_kind(eu_url) == "xml"
    ok, error = monitor._validate_observation(
        url=eu_url,
        final_url=eu_url,
        status_code=200,
        content_type="text/html",
        body=b"<html><body>ordinary EC portal page</body></html>" + b"x" * 101,
    )
    assert ok is False
    assert error == "invalid_xml_content"


def test_monitor_accepts_exact_ofac_govcloud_redirect_and_rejects_others() -> None:
    ofac_url = "https://www.treasury.gov/ofac/downloads/sdn.xml"
    s3_url = (
        "https://wc2h-sls-prod-public-published.s3.us-gov-west-1.amazonaws.com/"
        "exports/SDN.XML?version=42"
    )
    assert monitor._redirect_host_allowed(ofac_url, s3_url)
    assert not monitor._redirect_host_allowed(
        ofac_url,
        "https://attacker.example/SDN.XML",
    )
    assert not monitor._redirect_host_allowed(
        ofac_url,
        "https://other-bucket.s3.us-gov-west-1.amazonaws.com/SDN.XML",
    )
    assert not monitor._redirect_host_allowed(
        ofac_url,
        "https://attacker.www.treasury.gov/SDN.XML",
    )
    eu_url = (
        "https://webgate.ec.europa.eu/fsd/fsf/public/files/"
        "xmlFullSanctionsList_1_1/content"
    )
    assert not monitor._redirect_host_allowed(
        eu_url,
        "https://attacker.webgate.ec.europa.eu/content",
    )

    namespace = monitor._OFAC_XML_NAMESPACE
    entries = "".join(
        f"<sdnEntry><uid>{index}</uid><lastName>EXAMPLE {index}</lastName>"
        "<sdnType>Entity</sdnType></sdnEntry>"
        for index in range(monitor._OFAC_MIN_ROWS)
    )
    body = f"""
        <sdnList xmlns="{namespace}">
          <publshInformation>
            <Record_Count>{monitor._OFAC_MIN_ROWS}</Record_Count><Publish_Date>09/01/2026</Publish_Date>
          </publshInformation>
          {entries}
        </sdnList>
    """.encode()
    assert monitor._validate_observation(
        url=ofac_url,
        final_url=s3_url,
        status_code=200,
        content_type="text/xml",
        body=body,
    ) == (True, None)

    ok, error = monitor._validate_observation(
        url=ofac_url,
        final_url="https://attacker.example/SDN.XML",
        status_code=200,
        content_type="text/xml",
        body=body,
    )
    assert ok is False
    assert error == "unexpected_redirect_host"


def test_conditional_304_still_enforces_final_redirect_host() -> None:
    ofac_url = "https://www.treasury.gov/ofac/downloads/sdn.xml"
    previous = {
        "sources": {
            "only": {
                "sha256": "known-good",
                "etag": '"known"',
                "url": ofac_url,
            }
        }
    }
    rejected_client = _Client(
        _Response(
            b"",
            status_code=304,
            content_type="text/xml",
            final_url="https://attacker.example/SDN.XML",
        )
    )
    with (
        patch.object(monitor, "SOURCES", {"only": ofac_url}),
        patch.object(monitor, "SOURCE_MODES", {"only": "structured_freshness"}),
        patch.object(monitor.httpx, "Client", return_value=rejected_client),
    ):
        report = monitor.monitor_sources(previous_state=previous)
    assert report["all_available"] is False
    assert report["sources"][0]["validation_error"] == "unexpected_redirect_host"
    assert report["next_state"]["sources"]["only"]["sha256"] == "known-good"

    govcloud_url = (
        "https://wc2h-sls-prod-public-published.s3.us-gov-west-1.amazonaws.com/"
        "exports/SDN.XML?version=42"
    )
    accepted_client = _Client(
        _Response(
            b"",
            status_code=304,
            content_type="text/xml",
            final_url=govcloud_url,
        )
    )
    with (
        patch.object(monitor, "SOURCES", {"only": ofac_url}),
        patch.object(monitor, "SOURCE_MODES", {"only": "structured_freshness"}),
        patch.object(monitor.httpx, "Client", return_value=accepted_client),
    ):
        report = monitor.monitor_sources(previous_state=previous)
    assert report["all_available"] is True
    assert report["sources"][0]["ok"] is True
    assert report["sources"][0]["final_url"] == govcloud_url


@pytest.mark.parametrize(
    "official_url",
    (
        "https://www.treasury.gov/ofac/downloads/sdn.xml",
        (
            "https://webgate.ec.europa.eu/fsd/fsf/public/files/"
            "xmlFullSanctionsList_1_1/content"
        ),
    ),
)
def test_official_sanctions_monitor_rejects_arbitrary_structured_xml(
    official_url: str,
) -> None:
    ok, error = monitor._validate_observation(
        url=official_url,
        final_url=official_url,
        status_code=200,
        content_type="application/xml",
        body=b"<arbitrary><item>structured but not an official feed</item></arbitrary>" + b" " * 101,
    )
    assert ok is False
    assert error == "invalid_xml_content"


def test_official_sanctions_monitor_rejects_tiny_or_invalidly_dated_snapshots() -> None:
    ofac_url = "https://www.treasury.gov/ofac/downloads/sdn.xml"
    ofac_namespace = monitor._OFAC_XML_NAMESPACE
    tiny_ofac = f"""
        <sdnList xmlns="{ofac_namespace}">
          <publshInformation><Record_Count>1</Record_Count><Publish_Date>09/01/2026</Publish_Date></publshInformation>
          <sdnEntry><uid>1</uid><lastName>EXAMPLE</lastName><sdnType>Entity</sdnType></sdnEntry>
        </sdnList>
    """.encode()
    assert monitor._validate_observation(
        url=ofac_url,
        final_url=ofac_url,
        status_code=200,
        content_type="text/xml",
        body=tiny_ofac,
    ) == (False, "invalid_xml_content")

    ofac_entries = "".join(
        f"<sdnEntry><uid>{index}</uid><lastName>EXAMPLE {index}</lastName>"
        "<sdnType>Entity</sdnType></sdnEntry>"
        for index in range(monitor._OFAC_MIN_ROWS)
    )
    invalid_date_ofac = f"""
        <sdnList xmlns="{ofac_namespace}">
          <publshInformation><Record_Count>{monitor._OFAC_MIN_ROWS}</Record_Count><Publish_Date>bogus</Publish_Date></publshInformation>
          {ofac_entries}
        </sdnList>
    """.encode()
    assert monitor._validate_observation(
        url=ofac_url,
        final_url=ofac_url,
        status_code=200,
        content_type="text/xml",
        body=invalid_date_ofac,
    ) == (False, "invalid_xml_content")

    eu_url = (
        "https://webgate.ec.europa.eu/fsd/fsf/public/files/"
        "xmlFullSanctionsList_1_1/content"
    )
    eu_namespace = monitor._EU_SANCTIONS_XML_NAMESPACE
    tiny_eu = f"""
        <export xmlns="{eu_namespace}" generationDate="2026-09-01" globalFileId="42">
          <sanctionEntity euReferenceNumber="EU.1.1"><nameAlias wholeName="EXAMPLE" /></sanctionEntity>
        </export>
    """.encode()
    assert monitor._validate_observation(
        url=eu_url,
        final_url=eu_url,
        status_code=200,
        content_type="application/xml",
        body=tiny_eu,
    ) == (False, "invalid_xml_content")

    eu_entities = "".join(
        f'<sanctionEntity euReferenceNumber="EU.{index}">'
        f'<nameAlias wholeName="EXAMPLE {index}" /></sanctionEntity>'
        for index in range(monitor._EU_SANCTIONS_MIN_ROWS)
    )
    invalid_date_eu = f"""
        <export xmlns="{eu_namespace}" generationDate="bogus" globalFileId="42">
          {eu_entities}
        </export>
    """.encode()
    assert monitor._validate_observation(
        url=eu_url,
        final_url=eu_url,
        status_code=200,
        content_type="application/xml",
        body=invalid_date_eu,
    ) == (False, "invalid_xml_content")
