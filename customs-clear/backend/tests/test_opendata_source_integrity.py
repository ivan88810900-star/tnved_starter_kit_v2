"""Fail-closed provenance checks for scheduled FTS/FSA open-data adapters."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import httpx
from contextlib import contextmanager
import pytest

from app.services import opendata_client, opendata_customs, opendata_fsa, opendata_trois
from scripts import monitor_official_ntm_sources as monitor
from scripts import opendata_sync


def _response(url: str, status: int, body: bytes = b"", **headers: str) -> httpx.Response:
    request = httpx.Request("GET", url)
    return httpx.Response(status, content=body, headers=headers, request=request)


class _SequenceClient:
    def __init__(self, responses: list[httpx.Response]) -> None:
        self.responses = list(responses)
        self.requested: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def get(self, url: str, **_kwargs) -> httpx.Response:
        self.requested.append(url)
        return self.responses.pop(0)

    @contextmanager
    def stream(self, method: str, url: str, **kwargs):
        response = self.get(url, **kwargs)
        try:
            yield response
        finally:
            response.close()


@pytest.mark.parametrize(
    "url",
    (
        "http://customs.gov.ru/7730176610-trois/meta.csv",
        "file:///etc/passwd",
        "https://attacker-customs.gov.ru/7730176610-trois/meta.csv",
        "https://child.customs.gov.ru/7730176610-trois/meta.csv",
        "https://customs.gov.ru.attacker.example/7730176610-trois/meta.csv",
        "https://user@customs.gov.ru/7730176610-trois/meta.csv",
        "https://customs.gov.ru:444/7730176610-trois/meta.csv",
        "https://customs.gov.ru/7730176610-mask44/meta.csv",
        "https://customs.gov.ru/other/7730176610-trois/meta.csv",
        "https://customs.gov.ru/7730176610-trois/%2e%2e/meta.csv",
    ),
)
def test_opendata_rejects_untrusted_or_cross_dataset_url(url: str) -> None:
    with pytest.raises(RuntimeError):
        opendata_client._validate_official_url(
            url,
            agency="fts",
            dataset_id="7730176610-trois",
            expected_suffix=".csv",
        )


def test_opendata_accepts_only_observed_canonical_dataset_paths() -> None:
    assert opendata_client._validate_official_url(
        "https://customs.gov.ru/storage/opendata/7730176610-trois/data-20260901.csv",
        agency="fts",
        dataset_id="7730176610-trois",
        expected_suffix=".csv",
    )
    assert opendata_client._validate_official_url(
        "https://fsa.gov.ru/opendata/7736638268-rss/data-20260901.7z",
        agency="fsa",
        dataset_id="7736638268-rss",
        expected_suffix=".7z",
    )
    with pytest.raises(RuntimeError, match="unsupported FTS opendata dataset"):
        opendata_client._validate_official_url(
            "https://customs.gov.ru/attacker-dataset/data-20260901.csv",
            agency="fts",
            dataset_id="attacker-dataset",
            expected_suffix=".csv",
        )


def test_opendata_rejects_untrusted_url_before_creating_client() -> None:
    with (
        patch.object(opendata_client, "_http_client") as client_factory,
        pytest.raises(RuntimeError, match="untrusted official opendata host"),
    ):
        opendata_client.download_bytes(
            "https://attacker.example/7730176610-trois/data-20260901.csv",
            expected_kind="csv",
            dataset_id="7730176610-trois",
            expected_suffix=".csv",
        )
    client_factory.assert_not_called()


def test_opendata_rejects_off_host_redirect_before_following(tmp_path: Path) -> None:
    url = "https://customs.gov.ru/7730176610-trois/meta.csv"
    client = _SequenceClient(
        [_response(url, 302, location="https://attacker.example/stolen.csv")]
    )
    destination = tmp_path / "meta.csv"
    with (
        patch.object(opendata_client, "_http_client", return_value=client),
        pytest.raises(RuntimeError, match="untrusted FTS opendata URL"),
    ):
        opendata_client.download_bytes(
            url,
            dest=destination,
            expected_kind="csv",
            dataset_id="7730176610-trois",
            expected_suffix=".csv",
        )
    assert client.requested == [url]
    assert not destination.exists()


def test_opendata_rejects_same_dataset_redirect_to_wrong_artifact() -> None:
    url = (
        "https://customs.gov.ru/storage/opendata/7730176610-trois/"
        "data-20260901.csv"
    )
    client = _SequenceClient(
        [
            _response(
                url,
                302,
                location=(
                    "https://customs.gov.ru/storage/opendata/7730176610-trois/"
                    "data-20260902.csv"
                ),
            )
        ]
    )
    with (
        patch.object(opendata_client, "_http_client", return_value=client),
        pytest.raises(RuntimeError, match="unexpected path"),
    ):
        opendata_client.download_bytes(
            url,
            expected_kind="csv",
            dataset_id="7730176610-trois",
            expected_suffix=".csv",
        )
    assert client.requested == [url]


def test_opendata_rejects_200_error_content_without_writing(tmp_path: Path) -> None:
    url = (
        "https://customs.gov.ru/storage/opendata/7730176610-trois/"
        "data-20260901.csv"
    )
    client = _SequenceClient(
        [_response(url, 200, b"<html>upstream error</html>", **{"content-type": "text/html"})]
    )
    destination = tmp_path / "data-20260901.csv"
    with (
        patch.object(opendata_client, "_http_client", return_value=client),
        pytest.raises(RuntimeError, match="Content-Type: text/html"),
    ):
        opendata_client.download_bytes(
            url,
            dest=destination,
            expected_kind="csv",
            dataset_id="7730176610-trois",
            expected_suffix=".csv",
        )
    assert not destination.exists()


@pytest.mark.parametrize(
    ("kind", "body", "content_type"),
    (
        ("csv", b"<html><body>gateway error</body></html>", "application/octet-stream"),
        ("csv", b'{"status":"error","message":"denied"}', "text/plain"),
        ("xml", b"<html><body>not metadata</body></html>", "application/xml"),
        ("7z", b"PK-not-a-seven-zip", "application/octet-stream"),
    ),
)
def test_opendata_rejects_error_or_wrong_content(
    kind: str,
    body: bytes,
    content_type: str,
) -> None:
    with pytest.raises(RuntimeError):
        opendata_client._validate_download_body(
            body,
            expected_kind=kind,
            content_type=content_type,
        )


def test_scheduled_adapter_forces_tls_verification() -> None:
    backend_root = Path(__file__).resolve().parent.parent
    env = dict(os.environ)
    existing_pythonpath = str(env.get("PYTHONPATH") or "").strip()
    env.update(
        {
            "PYTHONPATH": os.pathsep.join(
                value for value in (str(backend_root), existing_pythonpath) if value
            ),
            "CUSTOMSCLEAR_REGULATORY_ADAPTER_MODE": "1",
            "OPENDATA_VERIFY_SSL": "false",
        }
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "from app.services import opendata_client; "
            "print(opendata_client.VERIFY_SSL)",
        ],
        cwd=backend_root,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert completed.stdout.strip() == "True"


def _fts_meta(
    *,
    identifier: str = "7730176610-trois",
    artifact_url: str = (
        "https://customs.gov.ru/storage/opendata/7730176610-trois/"
        "data-20260901.csv"
    ),
    snapshot_id: str = "data-20260901.csv",
) -> bytes:
    return (
        "property,value\n"
        f"identifier,{identifier}\n"
        "format,CSV\n"
        f"{snapshot_id},{artifact_url}\n"
    ).encode()


@pytest.mark.parametrize(
    "payload",
    (
        _fts_meta(identifier=""),
        _fts_meta(identifier="7730176610-mask44"),
        _fts_meta(
            artifact_url=(
                "https://customs.gov.ru/storage/opendata/7730176610-mask44/"
                "data-20260901.csv"
            )
        ),
        _fts_meta(snapshot_id="data-x..csv"),
        _fts_meta(snapshot_id="data-x%2fescape.csv"),
    ),
)
def test_fts_meta_requires_exact_identity_and_safe_artifacts(payload: bytes) -> None:
    with (
        patch.object(opendata_client, "download_bytes", return_value=payload),
        pytest.raises(RuntimeError),
    ):
        opendata_client.fetch_fts_meta("7730176610-trois")


def test_fts_meta_marks_only_validated_dataset_provenance() -> None:
    with patch.object(opendata_client, "download_bytes", return_value=_fts_meta()):
        meta = opendata_client.fetch_fts_meta("7730176610-trois")
    assert meta.identifier == "7730176610-trois"
    assert meta.provenance_verified is True


def _fsa_meta(
    *,
    identifier: str = "7736638268-rss",
    source: str = (
        "https://fsa.gov.ru/opendata/7736638268-rss/data-20260901.7z"
    ),
    structure: str = (
        "https://fsa.gov.ru/opendata/7736638268-rss/structure-20190917.csv"
    ),
) -> bytes:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<meta>
  <identifier>{identifier}</identifier>
  <modified>01.09.2026</modified>
  <format>7Z</format>
  <data><dataversion><source>{source}</source><structure>{structure}</structure></dataversion></data>
</meta>
""".encode()


@pytest.mark.parametrize(
    "payload",
    (
        _fsa_meta(identifier="7736638268-rds"),
        _fsa_meta(
            source="https://fsa.gov.ru/opendata/7736638268-rds/data-20260901.7z"
        ),
        _fsa_meta(
            structure="https://fsa.gov.ru/opendata/7736638268-rds/structure-20190917.csv"
        ),
        _fsa_meta(structure=""),
        _fsa_meta(
            structure="https://fsa.gov.ru/opendata/7736638268-rss/not-a-structure.csv"
        ),
    ),
)
def test_fsa_meta_rejects_cross_wiring_and_missing_schema(payload: bytes) -> None:
    with (
        patch.object(opendata_client, "download_bytes", return_value=payload),
        pytest.raises(RuntimeError),
    ):
        opendata_client.fetch_fsa_meta("7736638268-rss")


def test_fsa_meta_marks_only_validated_dataset_provenance() -> None:
    with patch.object(opendata_client, "download_bytes", return_value=_fsa_meta()):
        meta = opendata_client.fetch_fsa_meta("7736638268-rss")
    assert meta.identifier == "7736638268-rss"
    assert meta.provenance_verified is True


def _catalog_rows() -> list[dict[str, str]]:
    return [
        {
            "id": "7730176610-trois",
            "title": "ТРОИС",
            "meta_url": "https://customs.gov.ru/7730176610-trois/meta.csv",
            "format": "CSV",
        },
        {
            "id": "7730176610-mask44",
            "title": "Маски графы 44",
            "meta_url": "https://customs.gov.ru/7730176610-mask44/meta.csv",
            "format": "CSV",
        },
    ]


def test_customs_catalog_requires_each_managed_dataset_once() -> None:
    rows = _catalog_rows()
    with (
        patch.object(opendata_customs, "fetch_customs_catalog", return_value=rows[:1]),
        pytest.raises(RuntimeError, match="missing managed datasets"),
    ):
        opendata_customs.sync_customs_catalog()
    with (
        patch.object(
            opendata_customs,
            "fetch_customs_catalog",
            return_value=[*rows, dict(rows[0])],
        ),
        pytest.raises(RuntimeError, match="duplicate managed dataset"),
    ):
        opendata_customs.sync_customs_catalog()


@pytest.mark.parametrize(
    "meta_url",
    (
        "https://attacker.example/7730176610-trois/meta.csv",
        "https://customs.gov.ru/7730176610-mask44/meta.csv",
        "https://customs.gov.ru/storage/opendata/7730176610-trois/meta.csv",
    ),
)
def test_customs_catalog_rejects_untrusted_or_wrong_metadata_url(meta_url: str) -> None:
    rows = _catalog_rows()
    rows[0]["meta_url"] = meta_url
    with (
        patch.object(opendata_customs, "fetch_customs_catalog", return_value=rows),
        pytest.raises(RuntimeError),
    ):
        opendata_customs.sync_customs_catalog()


def test_dataset_csv_parsers_require_identity_columns(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="unexpected schema"):
        opendata_trois._parse_trois_csv("foo;bar\n1;2\n")
    with pytest.raises(RuntimeError, match="unexpected schema"):
        opendata_customs._parse_mask44_csv("foo;bar\n1;2\n")
    fsa_csv = tmp_path / "wrong.csv"
    fsa_csv.write_text("foo;bar\n1;2\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="unexpected CSV schema"):
        opendata_fsa._validate_fsa_csv_schema(fsa_csv, doc_type="СС")


def test_opendata_summary_requires_explicit_provenance_identity_and_revision() -> None:
    valid = {
        "status": "ok",
        "official_source_verified": True,
        "dataset_id": opendata_sync.TROIS_DATASET_ID,
        "parsed_rows": 10,
        "snapshot_id": "data-20260901.csv",
    }
    assert opendata_sync._single_summary(
        valid,
        count_keys=("parsed_rows", "rows"),
        expected_dataset_id=opendata_sync.TROIS_DATASET_ID,
    )[0] is True
    for key in ("official_source_verified", "dataset_id", "snapshot_id"):
        invalid = dict(valid)
        invalid.pop(key)
        assert opendata_sync._single_summary(
            invalid,
            count_keys=("parsed_rows", "rows"),
            expected_dataset_id=opendata_sync.TROIS_DATASET_ID,
        )[0] is False


def test_fsa_summary_requires_both_exact_verified_dataset_revisions() -> None:
    valid = {
        "aggregate_status": "ok",
        "official_source_verified": True,
        "rss": [
            {
                "status": "ok",
                "official_source_verified": True,
                "dataset_id": opendata_sync.FSA_RSS_ID,
                "parsed": 100,
                "snapshot_id": "data-20260901.7z",
            }
        ],
        "rds": [
            {
                "status": "skipped",
                "official_source_verified": True,
                "dataset_id": opendata_sync.FSA_RDS_ID,
                "rows": 200,
                "snapshot_id": "data-20260902.7z",
            }
        ],
    }
    assert opendata_sync._fsa_summary(valid) == (
        True,
        300,
        "data-20260901.7z,data-20260902.7z",
    )

    no_provenance = {**valid, "official_source_verified": False}
    assert opendata_sync._fsa_summary(no_provenance)[0] is False

    swapped = {**valid, "rss": [{**valid["rss"][0], "dataset_id": opendata_sync.FSA_RDS_ID}]}
    assert opendata_sync._fsa_summary(swapped)[0] is False

    no_revision = {**valid, "rds": [{**valid["rds"][0], "snapshot_id": ""}]}
    assert opendata_sync._fsa_summary(no_revision)[0] is False


def test_customs_strict_contract_rejects_unverified_and_invalid_catalog_total(
    capsys,
) -> None:
    mask = {
        "status": "ok",
        "official_source_verified": True,
        "dataset_id": opendata_sync.MASK44_DATASET_ID,
        "rows": 10,
        "snapshot_id": "data-20260901.csv",
    }
    catalog = {
        "status": "ok",
        "official_source_verified": False,
        "managed_dataset_ids": [
            opendata_sync.MASK44_DATASET_ID,
            opendata_sync.TROIS_DATASET_ID,
        ],
        "total": "not-an-integer",
    }
    with (
        patch.object(sys, "argv", ["opendata_sync.py", "--source", "customs", "--strict"]),
        patch.object(opendata_sync, "sync_mask44", return_value=mask),
        patch.object(opendata_sync, "sync_customs_catalog", return_value=catalog),
        patch.object(opendata_sync, "_record_status"),
    ):
        assert opendata_sync.main() == 1
    contract_line = next(
        line
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("REGULATORY_SYNC_RESULT=")
    )
    contract = json.loads(contract_line.split("=", 1)[1])
    assert contract["status"] == "error"
    assert contract["official_source"] is False


@pytest.mark.parametrize(
    ("original", "candidate"),
    (
        ("https://publication.pravo.gov.ru/doc", "https://ru/doc"),
        ("https://eec.eaeunion.org/doc", "https://org/doc"),
        ("https://eec.eaeunion.org/doc", "https://child.eec.eaeunion.org/doc"),
        ("https://eec.eaeunion.org/doc", "http://eec.eaeunion.org/doc"),
        ("https://eec.eaeunion.org/doc", "https://eec.eaeunion.org:444/doc"),
    ),
)
def test_monitor_rejects_parent_child_and_insecure_redirects(
    original: str,
    candidate: str,
) -> None:
    assert monitor._redirect_host_allowed(original, candidate) is False


def test_monitor_rejects_off_host_redirect_before_request() -> None:
    source = "https://eec.eaeunion.org/source.pdf"
    client = _SequenceClient(
        [_response(source, 302, location="https://attacker.example/source.pdf")]
    )
    with (
        patch.object(monitor, "SOURCES", {"only": source}),
        patch.object(monitor, "SOURCE_MODES", {"only": "legal_drift"}),
        patch.object(monitor.httpx, "Client", return_value=client) as client_factory,
    ):
        result = monitor.monitor_sources(previous_state={"sources": {}})
    client_options = client_factory.call_args.kwargs
    assert client_options["follow_redirects"] is False
    assert client_options["trust_env"] is False
    assert client_options["verify"] is True
    assert client.requested == [source]
    assert result["all_available"] is False
    assert result["sources"][0]["validation_error"] == "unexpected_redirect_target"
    assert result["monitored_url_count"] == 1
    assert result["revision_candidate_source_count"] == 1
    assert result["revision_covered_source_count"] == 0
    assert result["revision_gap_source_count"] == 0
    assert result["revision_unavailable_source_count"] == 1
    assert result["explicit_availability_source_count"] == 0
    assert result["availability_only_source_count"] == 0
    assert result["revision_monitor_gate_ok"] is False


def test_every_monitor_source_uses_tls() -> None:
    assert monitor.SOURCES
    assert all(monitor._redirect_host_allowed(url, url) for url in monitor.SOURCES.values())


def test_monitor_configuration_has_explicit_current_coverage_counts() -> None:
    configured = [
        (
            monitor.SOURCE_MODES.get(source_id, "legal_drift"),
            monitor._expected_content_kind(url),
        )
        for source_id, url in monitor.SOURCES.items()
    ]
    # Nine relief/GSP PDFs and three distinct parent pages join the monitor.
    assert len(configured) == 62
    assert sum(mode == "availability" for mode, _kind in configured) == 8
    assert sum(
        mode != "availability" and kind != "html_or_document"
        for mode, kind in configured
    ) == 24
    assert sum(
        mode == "legal_drift" and kind == "html_or_document"
        for mode, kind in configured
    ) == 30


def _html_response(url: str, body: bytes) -> httpx.Response:
    return _response(url, 200, body, **{"content-type": "text/html; charset=utf-8"})


def test_monitor_canonical_html_identity_ignores_template_nonce_but_is_not_revision() -> None:
    url = "https://publication.pravo.gov.ru/Document/View/0001202207190026"
    first = (
        b'<html><head><title>Official act</title><link rel="canonical" '
        b'href="https://publication.pravo.gov.ru/Document/View/0001202207190026">'
        b"<script>nonce='first'</script></head>"
        b"<body><h1>Government resolution</h1></body></html>" + b" " * 101
    )
    second = first.replace(b"nonce='first'", b"nonce='other'")
    revision, identity_verified, revision_covered, _ = monitor._revision_material(
        url=url,
        final_url=url,
        monitor_mode="legal_drift",
        content_type="text/html",
        body=first,
    )
    assert identity_verified is True
    assert revision_covered is False
    previous = {
        "sources": {
            "only": {
                "url": url,
                "sha256": hashlib.sha256(revision).hexdigest(),
                "artifact_identity_verified": True,
                "revision_covered": False,
            }
        }
    }
    client = _SequenceClient([_html_response(url, second)])
    with (
        patch.object(monitor, "SOURCES", {"only": url}),
        patch.object(monitor, "SOURCE_MODES", {"only": "legal_drift"}),
        patch.object(monitor.httpx, "Client", return_value=client),
    ):
        result = monitor.monitor_sources(previous_state=previous)
    assert result["sources"][0]["changed"] is False
    assert result["sources"][0]["artifact_identity_verified"] is True
    assert result["sources"][0]["revision_covered"] is False
    assert result["sources"][0]["approval_allowed"] is False
    assert result["sources"][0]["ok"] is True
    assert result["sources"][0]["revision_gap"] is True
    assert result["sources"][0]["effective_monitor_mode"] == "availability_only"
    assert result["all_available"] is True
    assert result["revision_coverage_complete"] is False
    assert result["revision_monitor_gate_ok"] is True


def test_loss_of_previously_covered_revision_is_a_hard_failure() -> None:
    url = "https://publication.pravo.gov.ru/Document/View/0001202207190026"
    body = (
        b'<html><head><link rel="canonical" '
        b'href="https://publication.pravo.gov.ru/Document/View/0001202207190026">'
        b"</head><body>0001202207190026</body></html>" + b" " * 101
    )
    previous = {
        "sources": {
            "only": {
                "url": url,
                "sha256": "previous-direct-artifact",
                "revision_covered": True,
                "artifact_identity_verified": True,
            }
        }
    }
    client = _SequenceClient([_html_response(url, body)])
    with (
        patch.object(monitor, "SOURCES", {"only": url}),
        patch.object(monitor, "SOURCE_MODES", {"only": "legal_drift"}),
        patch.object(monitor.httpx, "Client", return_value=client),
    ):
        result = monitor.monitor_sources(previous_state=previous)
    row = result["sources"][0]
    assert row["ok"] is False
    assert row["validation_error"] == "legal_revision_coverage_regressed"
    assert result["all_available"] is False


def test_monitor_detects_canonical_legal_attachment_change() -> None:
    url = "https://eec.eaeunion.org/comission/department/example.php"
    old_body = (
        b'<html><body><h1>Technical regulation</h1><a href="/upload/act-v1.pdf">Act</a>'
        b"</body></html>" + b" " * 101
    )
    new_body = old_body.replace(b"act-v1.pdf", b"act-v2.pdf")
    old_revision, identity_verified, revision_covered, _ = monitor._revision_material(
        url=url,
        final_url=url,
        monitor_mode="legal_drift",
        content_type="text/html",
        body=old_body,
    )
    assert identity_verified is True
    assert revision_covered is False
    previous = {
        "sources": {
            "only": {
                "url": url,
                "sha256": hashlib.sha256(old_revision).hexdigest(),
                "artifact_identity_verified": True,
                "revision_covered": False,
            }
        }
    }
    client = _SequenceClient([_html_response(url, new_body)])
    with (
        patch.object(monitor, "SOURCES", {"only": url}),
        patch.object(monitor, "SOURCE_MODES", {"only": "legal_drift"}),
        patch.object(monitor.httpx, "Client", return_value=client),
    ):
        result = monitor.monitor_sources(previous_state=previous)
    assert result["changed_source_ids"] == []
    assert result["sources"][0]["identity_changed"] is True
    assert result["review_required"] is False
    assert result["revision_gap_source_ids"] == ["only"]


def test_monitor_rejects_soft_404_document_page() -> None:
    url = "https://publication.pravo.gov.ru/Document/View/0001202207190026"
    body = (
        b"<html><head><title>404 page not found</title></head>"
        b"<body>Document not found</body></html>" + b" " * 101
    )
    ok, error = monitor._validate_observation(
        url=url,
        final_url=url,
        status_code=200,
        content_type="text/html",
        body=body,
    )
    assert ok is False
    assert error == "soft_not_found_page_detected"


def test_unidentified_legal_html_is_explicit_availability_only_gap() -> None:
    url = "https://eec.eaeunion.org/generic-portal"
    body = (
        b"<html><head><title>Official portal</title></head>"
        b"<body><h1>Information</h1></body></html>" + b" " * 101
    )
    client = _SequenceClient([_html_response(url, body)])
    with (
        patch.object(monitor, "SOURCES", {"only": url}),
        patch.object(monitor, "SOURCE_MODES", {"only": "legal_drift"}),
        patch.object(monitor.httpx, "Client", return_value=client),
    ):
        result = monitor.monitor_sources(previous_state={"sources": {}})
    row = result["sources"][0]
    assert row["ok"] is True
    assert row["artifact_identity_verified"] is False
    assert row["revision_covered"] is False
    assert row["requires_approval"] is False
    assert row["approval_allowed"] is False
    assert row["effective_monitor_mode"] == "availability_only"
    assert result["unapprovable_source_ids"] == []
    assert result["unverified_revision_source_ids"] == ["only"]
    assert result["monitored_url_count"] == 1
    assert result["revision_candidate_source_count"] == 1
    assert result["revision_covered_source_count"] == 0
    assert result["revision_gap_source_count"] == 1
    assert result["revision_unavailable_source_count"] == 0
    assert result["explicit_availability_source_count"] == 0
    assert result["availability_only_source_count"] == 1
    assert result["revision_coverage_complete"] is False


def test_monitor_rejects_same_host_redirect_to_wrong_resource() -> None:
    requested = "https://publication.pravo.gov.ru/Document/View/0001202207190026"
    final = "https://publication.pravo.gov.ru/"
    client = _SequenceClient([_response(requested, 302, location=final)])
    with (
        patch.object(monitor, "SOURCES", {"only": requested}),
        patch.object(monitor, "SOURCE_MODES", {"only": "legal_drift"}),
        patch.object(monitor.httpx, "Client", return_value=client),
    ):
        result = monitor.monitor_sources(previous_state={"sources": {}})
    row = result["sources"][0]
    assert row["ok"] is False
    assert row["artifact_identity_verified"] is False
    assert row["approval_allowed"] is False
    assert row["validation_error"] == "unexpected_redirect_target"
    assert client.requested == [requested]


def test_monitor_rejects_same_host_pdf_redirect_before_contacting_wrong_artifact() -> None:
    requested = "https://eec.eaeunion.org/upload/legal-list-v1.pdf"
    target = "https://eec.eaeunion.org/upload/unrelated-list.pdf"
    client = _SequenceClient([_response(requested, 302, location=target)])
    with (
        patch.object(monitor, "SOURCES", {"only": requested}),
        patch.object(monitor, "SOURCE_MODES", {"only": "legal_drift"}),
        patch.object(monitor.httpx, "Client", return_value=client),
    ):
        result = monitor.monitor_sources(previous_state={"sources": {}})
    assert client.requested == [requested]
    assert result["all_available"] is False
    assert result["sources"][0]["validation_error"] == "unexpected_redirect_target"


def test_monitor_rejects_same_path_redirect_that_changes_query_identity() -> None:
    requested = "https://eec.eaeunion.org/upload/legal-list.pdf"
    target = requested + "?artifact=other"
    client = _SequenceClient([_response(requested, 302, location=target)])
    with (
        patch.object(monitor, "SOURCES", {"only": requested}),
        patch.object(monitor, "SOURCE_MODES", {"only": "legal_drift"}),
        patch.object(monitor.httpx, "Client", return_value=client),
    ):
        result = monitor.monitor_sources(previous_state={"sources": {}})
    assert client.requested == [requested]
    assert result["sources"][0]["validation_error"] == "unexpected_redirect_target"

    pravo = "https://publication.pravo.gov.ru/Document/View/0001202207190026"
    assert monitor._redirect_target_allowed(
        pravo,
        "https://publication.pravo.gov.ru/document/0001202207190026?download=other",
    ) is False


def test_monitor_rejects_wrong_html_card_at_expected_document_path() -> None:
    url = "https://publication.pravo.gov.ru/Document/View/0001202207190026"
    body = (
        b"<html><head><title>Official portal</title></head>"
        b"<body><h1>Generic search page</h1></body></html>" + b" " * 101
    )
    client = _SequenceClient([_html_response(url, body)])
    with (
        patch.object(monitor, "SOURCES", {"only": url}),
        patch.object(monitor, "SOURCE_MODES", {"only": "legal_drift"}),
        patch.object(monitor.httpx, "Client", return_value=client),
    ):
        result = monitor.monitor_sources(previous_state={"sources": {}})
    row = result["sources"][0]
    assert row["ok"] is False
    assert row["artifact_identity_verified"] is False
    assert row["approval_allowed"] is False
    assert row["validation_error"] == "publication_document_identity_unconfirmed"


def test_html_identity_cannot_be_approved_as_legal_revision() -> None:
    url = "https://publication.pravo.gov.ru/Document/View/0001202207190026"
    body = (
        b'<html><head><link rel="canonical" '
        b'href="https://publication.pravo.gov.ru/Document/View/0001202207190026">'
        b"</head><body>0001202207190026</body></html>" + b" " * 101
    )
    revision, identity_verified, revision_covered, _ = monitor._revision_material(
        url=url,
        final_url=url,
        monitor_mode="legal_drift",
        content_type="text/html",
        body=body,
    )
    digest = hashlib.sha256(revision).hexdigest()
    assert identity_verified is True
    assert revision_covered is False
    previous = {
        "sources": {
            "only": {
                "url": url,
                "sha256": "approved-direct-artifact-digest",
                "pending_sha256": digest,
            }
        }
    }
    client = _SequenceClient([_html_response(url, body)])
    with (
        patch.object(monitor, "SOURCES", {"only": url}),
        patch.object(monitor, "SOURCE_MODES", {"only": "legal_drift"}),
        patch.object(monitor.httpx, "Client", return_value=client),
    ):
        result = monitor.monitor_sources(
            previous_state=previous,
            accept_changes=True,
            approval_ref="PR-187/legal-review",
        )
    row = result["sources"][0]
    assert row["ok"] is True
    assert row["revision_gap"] is True
    assert row["approval_allowed"] is False
    assert row["baseline_advanced"] is False
    assert result["accepted_source_ids"] == []
    assert result["next_state"]["sources"]["only"]["sha256"] == (
        "approved-direct-artifact-digest"
    )


def test_availability_only_cannot_satisfy_revision_gate() -> None:
    url = "https://eec.eaeunion.org/portal"
    body = b"<html><body>Official portal is online</body></html>" + b" " * 101
    client = _SequenceClient([_html_response(url, body)])
    with (
        patch.object(monitor, "SOURCES", {"only": url}),
        patch.object(monitor, "SOURCE_MODES", {"only": "availability"}),
        patch.object(monitor.httpx, "Client", return_value=client),
    ):
        result = monitor.monitor_sources(previous_state={"sources": {}})
    assert result["all_available"] is True
    assert result["review_required"] is False
    assert result["revision_coverage_complete"] is False
