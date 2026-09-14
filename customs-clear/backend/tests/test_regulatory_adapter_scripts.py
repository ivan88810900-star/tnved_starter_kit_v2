"""Strict-mode contracts for source adapter entry points."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import os
import sys
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.services import exchange_rates
from app.services.source_document import SourceDocument
from scripts import opendata_sync, sync_eu_sanctions, sync_ofac_sanctions, update_rates


def _result_contract(stdout: str) -> dict:
    line = next(
        row
        for row in reversed(stdout.splitlines())
        if row.startswith("REGULATORY_SYNC_RESULT=")
    )
    return json.loads(line.split("=", 1)[1])


def test_cbr_strict_mode_rejects_fallback_result(capsys) -> None:
    fallback = {
        "status": "OK",
        "source": "FALLBACK",
        "provenance_recorded": True,
        "date": "2026-09-01",
        "updated": 2,
    }
    with (
        patch.object(sys, "argv", ["update_rates.py", "--strict", "--json"]),
        patch.object(
            update_rates,
            "update_exchange_rates_from_cbrf",
            new_callable=AsyncMock,
            return_value=fallback,
        ) as update,
    ):
        exit_code = asyncio.run(update_rates._main())
    payload = _result_contract(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["status"] == "error"
    assert payload["official_source"] is False
    update.assert_awaited_once_with(allow_fallback=False)


@pytest.mark.parametrize(
    "date_attribute",
    ("", "2026-09-01", "32.09.2026"),
)
def test_cbr_parser_rejects_missing_or_invalid_official_date(date_attribute: str) -> None:
    date_part = f' Date="{date_attribute}"' if date_attribute else ""
    xml = (
        f"<ValCurs{date_part}><Valute><CharCode>USD</CharCode>"
        "<Value>90,0</Value><Nominal>1</Nominal></Valute></ValCurs>"
    )
    with pytest.raises(ValueError):
        exchange_rates._parse_cbr_xml(xml)


def test_cbr_validator_rejects_stale_or_future_payload_dates() -> None:
    now = datetime(2026, 9, 1, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="stale"):
        exchange_rates._validate_cbr_rate_date("2020-01-01", now=now)
    with pytest.raises(ValueError, match="future"):
        exchange_rates._validate_cbr_rate_date("2026-09-03", now=now)
    exchange_rates._validate_cbr_rate_date("2026-08-20", now=now)


def test_opendata_fsa_summary_rejects_nested_error() -> None:
    ok, rows, revision = opendata_sync._fsa_summary(
        {
            "aggregate_status": "ok",
            "official_source_verified": True,
            "rss": [{
                "status": "ok",
                "official_source_verified": True,
                "dataset_id": opendata_sync.FSA_RSS_ID,
                "parsed": 120,
                "snapshot_id": "rss-1",
            }],
            "rds": [{
                "status": "error",
                "official_source_verified": True,
                "dataset_id": opendata_sync.FSA_RDS_ID,
                "parsed": 0,
                "snapshot_id": "rds-1",
            }],
        }
    )
    assert ok is False
    assert rows == 120
    assert revision == "rss-1"


def test_opendata_fsa_summary_rejects_unverified_empty_skip() -> None:
    ok, rows, revision = opendata_sync._fsa_summary(
        {
            "aggregate_status": "ok",
            "official_source_verified": True,
            "rss": [{
                "status": "skipped",
                "official_source_verified": True,
                "dataset_id": opendata_sync.FSA_RSS_ID,
                "rows": 0,
                "snapshot_id": "rss-1",
            }],
            "rds": [{
                "status": "skipped",
                "official_source_verified": True,
                "dataset_id": opendata_sync.FSA_RDS_ID,
                "rows": 80,
                "snapshot_id": "rds-1",
            }],
        }
    )
    assert ok is False
    assert rows == 80
    assert revision == "rds-1,rss-1"


def test_opendata_single_summary_rejects_empty_success() -> None:
    ok, rows, revision = opendata_sync._single_summary(
        {
            "status": "ok",
            "official_source_verified": True,
            "dataset_id": opendata_sync.TROIS_DATASET_ID,
            "parsed_rows": 0,
            "snapshot_id": "empty-1",
        },
        count_keys=("parsed_rows", "rows"),
        expected_dataset_id=opendata_sync.TROIS_DATASET_ID,
    )
    assert (ok, rows, revision) == (False, 0, "empty-1")


def test_opendata_entrypoint_records_failed_source_instead_of_crashing(capsys) -> None:
    with (
        patch.object(sys, "argv", ["opendata_sync.py", "--source", "trois", "--strict"]),
        patch.object(
            opendata_sync,
            "sync_trois_opendata",
            side_effect=RuntimeError("official snapshot unavailable"),
        ),
        patch.object(opendata_sync, "_record_status") as record_status,
    ):
        exit_code = opendata_sync.main()

    payload = _result_contract(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["status"] == "error"
    assert payload["source_ids"] == ["fts_trois_registry"]
    record_status.assert_called_once()
    assert record_status.call_args.kwargs["ok"] is False


def test_ofac_strict_mode_rejects_empty_official_snapshot(capsys) -> None:
    with (
        patch.object(
            sys,
            "argv",
            ["sync_ofac_sanctions.py", "--official-only", "--strict", "--json"],
        ),
        patch.object(
            sync_ofac_sanctions,
            "_http_get",
            return_value=(SourceDocument("<?xml version='1.0'?><sdnList></sdnList>".encode()), "application/xml"),
        ),
        patch.object(sync_ofac_sanctions, "_extract_rows_from_xml", return_value=[]),
        patch.object(sync_ofac_sanctions, "_validate_rows", return_value=0),
        patch.object(sync_ofac_sanctions, "_replace_rows", return_value=0),
        patch.object(sync_ofac_sanctions, "upsert_source_status") as status,
        patch.object(sync_ofac_sanctions, "append_sync_log") as sync_log,
    ):
        exit_code = sync_ofac_sanctions.main()
    payload = _result_contract(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["status"] == "error"
    assert payload["official_source"] is True
    assert payload["rows_parsed"] == 0
    assert payload["rows_applied"] == 0


def test_eu_strict_mode_does_not_treat_goods_workbook_as_full_snapshot(capsys) -> None:
    goods_rows = [{"hs_code": "8517620000", "description": "radio equipment", "entity_name": ""}]
    with (
        patch.object(
            sys,
            "argv",
            ["sync_eu_sanctions.py", "--official-only", "--strict", "--json"],
        ),
        patch.object(
            sync_eu_sanctions,
            "_http_get_with_fallback",
            side_effect=RuntimeError("primary list unavailable"),
        ),
        patch.object(
            sync_eu_sanctions,
            "_http_get_bytes",
            return_value=(
                b"PK" + b"x" * 200,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
        ),
        patch.object(sync_eu_sanctions, "_rows_from_eu_correlation_xlsx", return_value=goods_rows),
        patch.object(sync_eu_sanctions, "_upsert_rows_partial") as partial_upsert,
        patch.object(sync_eu_sanctions, "upsert_source_status"),
        patch.object(sync_eu_sanctions, "append_sync_log"),
    ):
        exit_code = sync_eu_sanctions.main()
    payload = _result_contract(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["status"] == "error"
    assert payload["official_source"] is True
    assert payload["snapshot_kind"] == "partial"
    assert payload["rows_parsed"] == 1
    assert payload["rows_applied"] == 0
    partial_upsert.assert_not_called()


def test_ofac_scheduled_validation_never_applies_enforcement_rows(capsys) -> None:
    rows = [{"name": "ENTITY", "type": "entity", "origin_country": "US", "aliases": "[]"}]
    with (
        patch.object(
            sys,
            "argv",
            [
                "sync_ofac_sanctions.py",
                "--official-only",
                "--validate-only",
                "--strict",
                "--json",
            ],
        ),
        patch.object(
            sync_ofac_sanctions,
            "_http_get",
            return_value=(SourceDocument("<official/>".encode()), "application/xml"),
        ) as download,
        patch.object(sync_ofac_sanctions, "_extract_rows_from_xml", return_value=rows),
        patch.object(sync_ofac_sanctions, "_validate_rows", return_value=1200) as validate,
        patch.object(sync_ofac_sanctions, "_replace_rows") as replace,
        patch.object(sync_ofac_sanctions, "upsert_source_status") as status,
        patch.object(sync_ofac_sanctions, "append_sync_log") as sync_log,
        patch.object(sync_ofac_sanctions, "bump_preview_cache_revision") as bump,
    ):
        exit_code = sync_ofac_sanctions.main()
    payload = _result_contract(capsys.readouterr().out)
    assert exit_code == 0
    download.assert_called_once_with(
        sync_ofac_sanctions.OFAC_DEFAULT_URL,
        timeout_sec=45.0,
        retries=4,
    )
    validate.assert_called_once()
    replace.assert_not_called()
    bump.assert_not_called()
    assert status.call_args.kwargs["source_code"] == "OFAC_SDN_VALIDATION"
    assert sync_log.call_args.args[0] == "OFAC_SDN_VALIDATION"
    assert payload["operation"] == "validation_only"
    assert payload["official_source"] is True
    assert payload["enforcement_changed"] is False
    assert payload["rows_validated"] == 1200
    assert payload["rows_applied"] == 0


def test_ofac_manual_apply_remains_explicit_and_reports_enforcement_change(capsys) -> None:
    custom_url = "https://fixture.invalid/ofac.xml"
    rows = [{"name": "ENTITY", "type": "entity", "origin_country": "US", "aliases": "[]"}]
    with (
        patch.object(
            sys,
            "argv",
            [
                "sync_ofac_sanctions.py",
                "--url",
                custom_url,
                "--apply",
                "--strict",
                "--json",
            ],
        ),
        patch.object(
            sync_ofac_sanctions,
            "_http_get",
            return_value=(SourceDocument("<fixture/>".encode()), "application/xml"),
        ) as download,
        patch.object(sync_ofac_sanctions, "_extract_rows_from_xml", return_value=rows),
        patch.object(sync_ofac_sanctions, "_replace_rows", return_value=1) as replace,
        patch.object(sync_ofac_sanctions, "upsert_source_status") as status,
        patch.object(sync_ofac_sanctions, "append_sync_log") as sync_log,
        patch.object(sync_ofac_sanctions, "bump_preview_cache_revision"),
    ):
        exit_code = sync_ofac_sanctions.main()
    payload = _result_contract(capsys.readouterr().out)
    assert exit_code == 0
    download.assert_called_once_with(custom_url, timeout_sec=45.0, retries=4)
    replace.assert_called_once()
    assert replace.call_args.kwargs["source_url"] == custom_url
    assert replace.call_args.kwargs["revision"].startswith("sha256:")
    status.assert_not_called()
    sync_log.assert_not_called()
    assert payload["operation"] == "apply"
    assert payload["official_source"] is False
    assert payload["enforcement_changed"] is True
    assert payload["rows_applied"] == 1


def test_eu_scheduled_validation_ignores_env_fallbacks_and_never_applies(capsys) -> None:
    rows = [{"hs_code": "", "description": "entity", "entity_name": "ENTITY"}]
    with (
        patch.object(
            sys,
            "argv",
            [
                "sync_eu_sanctions.py",
                "--official-only",
                "--validate-only",
                "--strict",
                "--json",
            ],
        ),
        patch.dict(os.environ, {"EU_SANCTIONS_FALLBACK_URLS": "https://fixture.invalid/feed"}),
        patch.object(
            sync_eu_sanctions,
            "_http_get_with_fallback",
            return_value=(SourceDocument("<official/>".encode()), "application/xml", sync_eu_sanctions.EU_DEFAULT_URL),
        ) as download,
        patch.object(sync_eu_sanctions, "_rows_from_xml", return_value=rows),
        patch.object(sync_eu_sanctions, "_validate_rows", return_value=600) as validate,
        patch.object(sync_eu_sanctions, "_replace_rows") as replace,
        patch.object(sync_eu_sanctions, "_upsert_rows_partial") as partial,
        patch.object(sync_eu_sanctions, "upsert_source_status") as status,
        patch.object(sync_eu_sanctions, "append_sync_log") as sync_log,
        patch.object(sync_eu_sanctions, "bump_preview_cache_revision") as bump,
    ):
        exit_code = sync_eu_sanctions.main()
    payload = _result_contract(capsys.readouterr().out)
    assert exit_code == 0
    download.assert_called_once_with(
        [sync_eu_sanctions.EU_DEFAULT_URL],
        timeout_sec=45.0,
        retries=4,
    )
    validate.assert_called_once()
    replace.assert_not_called()
    partial.assert_not_called()
    bump.assert_not_called()
    assert status.call_args.kwargs["source_code"] == "EU_SANCTIONS_VALIDATION"
    assert sync_log.call_args.args[0] == "EU_SANCTIONS_VALIDATION"
    assert payload["operation"] == "validation_only"
    assert payload["official_source"] is True
    assert payload["enforcement_changed"] is False
    assert payload["rows_validated"] == 600
    assert payload["rows_applied"] == 0


def test_eu_manual_apply_remains_explicit(capsys) -> None:
    custom_url = "https://fixture.invalid/eu.xml"
    rows = [{"hs_code": "", "description": "entity", "entity_name": "ENTITY"}]
    with (
        patch.object(
            sys,
            "argv",
            [
                "sync_eu_sanctions.py",
                "--url",
                custom_url,
                "--apply",
                "--strict",
                "--json",
            ],
        ),
        patch.object(
            sync_eu_sanctions,
            "_http_get_with_fallback",
            return_value=(SourceDocument("<fixture/>".encode()), "application/xml", custom_url),
        ),
        patch.object(sync_eu_sanctions, "_rows_from_xml", return_value=rows),
        patch.object(sync_eu_sanctions, "_replace_rows", return_value=1) as replace,
        patch.object(sync_eu_sanctions, "upsert_source_status") as status,
        patch.object(sync_eu_sanctions, "append_sync_log") as sync_log,
        patch.object(sync_eu_sanctions, "bump_preview_cache_revision"),
    ):
        exit_code = sync_eu_sanctions.main()
    payload = _result_contract(capsys.readouterr().out)
    assert exit_code == 0
    replace.assert_called_once()
    assert replace.call_args.kwargs["source_url"] == custom_url
    assert replace.call_args.kwargs["revision"].startswith("sha256:")
    status.assert_not_called()
    sync_log.assert_not_called()
    assert payload["operation"] == "apply"
    assert payload["official_source"] is False
    assert payload["enforcement_changed"] is True
    assert payload["rows_applied"] == 1


def test_ofac_default_mode_validates_without_replacing(capsys) -> None:
    custom_url = "https://fixture.invalid/ofac.xml"
    rows = [{"name": "ENTITY", "type": "entity", "origin_country": "US", "aliases": "[]"}]
    with (
        patch.object(sys, "argv", ["sync_ofac_sanctions.py", "--url", custom_url, "--json"]),
        patch.object(
            sync_ofac_sanctions,
            "_http_get",
            return_value=(SourceDocument("<fixture/>".encode()), "application/xml"),
        ),
        patch.object(sync_ofac_sanctions, "_extract_rows_from_xml", return_value=rows),
        patch.object(sync_ofac_sanctions, "_validate_rows", return_value=1),
        patch.object(sync_ofac_sanctions, "_replace_rows") as replace,
        patch.object(sync_ofac_sanctions, "upsert_source_status"),
        patch.object(sync_ofac_sanctions, "append_sync_log"),
        patch.object(sync_ofac_sanctions, "bump_preview_cache_revision") as bump,
    ):
        exit_code = sync_ofac_sanctions.main()

    payload = _result_contract(capsys.readouterr().out)
    assert exit_code == 0
    replace.assert_not_called()
    bump.assert_not_called()
    assert payload["operation"] == "validation_only"
    assert payload["enforcement_changed"] is False
    assert payload["rows_applied"] == 0


def test_eu_default_mode_validates_without_replacing(capsys) -> None:
    custom_url = "https://fixture.invalid/eu.xml"
    rows = [{"hs_code": "", "description": "entity", "entity_name": "ENTITY"}]
    with (
        patch.object(sys, "argv", ["sync_eu_sanctions.py", "--url", custom_url, "--json"]),
        patch.object(
            sync_eu_sanctions,
            "_http_get_with_fallback",
            return_value=(SourceDocument("<fixture/>".encode()), "application/xml", custom_url),
        ),
        patch.object(sync_eu_sanctions, "_rows_from_xml", return_value=rows),
        patch.object(sync_eu_sanctions, "_validate_rows", return_value=1),
        patch.object(sync_eu_sanctions, "_replace_rows") as replace,
        patch.object(sync_eu_sanctions, "upsert_source_status"),
        patch.object(sync_eu_sanctions, "append_sync_log"),
        patch.object(sync_eu_sanctions, "bump_preview_cache_revision") as bump,
    ):
        exit_code = sync_eu_sanctions.main()

    payload = _result_contract(capsys.readouterr().out)
    assert exit_code == 0
    replace.assert_not_called()
    bump.assert_not_called()
    assert payload["operation"] == "validation_only"
    assert payload["enforcement_changed"] is False
    assert payload["rows_applied"] == 0


def test_ofac_official_parser_requires_current_schema_identity() -> None:
    namespace = sync_ofac_sanctions.OFAC_CURRENT_XML_NAMESPACE
    valid_xml = f"""
        <sdnList xmlns="{namespace}">
          <publshInformation>
            <Record_Count>1</Record_Count><Publish_Date>09/01/2026</Publish_Date>
          </publshInformation>
          <sdnEntry><uid>1</uid><lastName>EXAMPLE ENTITY</lastName><sdnType>Entity</sdnType></sdnEntry>
        </sdnList>
    """
    rows = sync_ofac_sanctions._extract_rows_from_xml(
        valid_xml,
        require_official_schema=True,
    )
    assert [row["name"] for row in rows] == ["EXAMPLE ENTITY"]

    arbitrary_xml = valid_xml.replace(
        f'<sdnList xmlns="{namespace}">',
        f'<payload xmlns="{namespace}">',
    ).replace("</sdnList>", "</payload>")
    with pytest.raises(ValueError, match="root"):
        sync_ofac_sanctions._extract_rows_from_xml(
            arbitrary_xml,
            require_official_schema=True,
        )

    outdated_xml = valid_xml.replace(namespace, "http://tempuri.org/sdnList.xsd")
    with pytest.raises(ValueError, match="namespace"):
        sync_ofac_sanctions._extract_rows_from_xml(
            outdated_xml,
            require_official_schema=True,
        )

    invalid_date_xml = valid_xml.replace("09/01/2026", "bogus")
    with pytest.raises(ValueError, match="Publish_Date"):
        sync_ofac_sanctions._extract_rows_from_xml(
            invalid_date_xml,
            require_official_schema=True,
        )


def test_eu_official_parser_requires_export_metadata_and_named_entities() -> None:
    namespace = sync_eu_sanctions.EU_XML_NAMESPACE
    entities = "".join(
        f'<sanctionEntity euReferenceNumber="EU.{index}" logicalId="{index}">'
        f'<nameAlias wholeName="EXAMPLE ENTITY {index}" />'
        "</sanctionEntity>"
        for index in range(sync_eu_sanctions.EU_OFFICIAL_MIN_ENTITIES)
    )
    valid_xml = f"""
        <export xmlns="{namespace}" generationDate="2026-09-01" globalFileId="42">
          {entities}
        </export>
    """
    rows = sync_eu_sanctions._rows_from_xml(valid_xml, require_official_schema=True)
    assert len(rows) == sync_eu_sanctions.EU_OFFICIAL_MIN_ENTITIES
    assert rows[0]["entity_name"] == "EXAMPLE ENTITY 0"

    arbitrary_xml = valid_xml.replace(namespace, "urn:arbitrary:export")
    with pytest.raises(ValueError, match="namespace"):
        sync_eu_sanctions._rows_from_xml(
            arbitrary_xml,
            require_official_schema=True,
        )

    correlation_only_xml = f"""
        <export xmlns="{namespace}" generationDate="2026-09-01" globalFileId="42">
          <sanctionEntity euReferenceNumber="EU.1.1" logicalId="1" />
        </export>
    """
    with pytest.raises(ValueError, match="nameAlias"):
        sync_eu_sanctions._rows_from_xml(
            correlation_only_xml,
            require_official_schema=True,
        )

    invalid_date_xml = valid_xml.replace("2026-09-01", "bogus")
    with pytest.raises(ValueError, match="generationDate"):
        sync_eu_sanctions._rows_from_xml(
            invalid_date_xml,
            require_official_schema=True,
        )

    hs_like_tokens = " ".join(str(1000 + index) for index in range(20))
    expanding_entities = "".join(
        f'<sanctionEntity euReferenceNumber="EU.SMALL.{index}">'
        f'<nameAlias wholeName="SMALL ENTITY {index}" /><remark>{hs_like_tokens}</remark>'
        "</sanctionEntity>"
        for index in range(25)
    )
    expanded_but_partial_xml = f"""
        <export xmlns="{namespace}" generationDate="2026-09-01" globalFileId="42">
          {expanding_entities}
        </export>
    """
    with pytest.raises(ValueError, match="too few sanctionEntity"):
        sync_eu_sanctions._rows_from_xml(
            expanded_but_partial_xml,
            require_official_schema=True,
        )


def test_official_modes_do_not_body_sniff_arbitrary_json(capsys) -> None:
    with (
        patch.object(
            sys,
            "argv",
            ["sync_ofac_sanctions.py", "--official-only", "--json"],
        ),
        patch.object(
            sync_ofac_sanctions,
            "_http_get",
            return_value=('{"items":[{"name":"NOT OFAC"}]}', "application/json"),
        ),
        patch.object(sync_ofac_sanctions, "_validate_rows") as ofac_validate,
        patch.object(sync_ofac_sanctions, "_replace_rows") as ofac_replace,
        patch.object(sync_ofac_sanctions, "upsert_source_status"),
        patch.object(sync_ofac_sanctions, "append_sync_log"),
    ):
        assert sync_ofac_sanctions.main() == 1
    ofac_payload = _result_contract(capsys.readouterr().out)
    assert ofac_payload["status"] == "error"
    ofac_validate.assert_not_called()
    ofac_replace.assert_not_called()

    with (
        patch.object(
            sys,
            "argv",
            ["sync_eu_sanctions.py", "--official-only", "--json"],
        ),
        patch.object(
            sync_eu_sanctions,
            "_http_get_with_fallback",
            return_value=(
                '{"items":[{"entity_name":"NOT EU"}]}',
                "application/json",
                sync_eu_sanctions.EU_DEFAULT_URL,
            ),
        ),
        patch.object(sync_eu_sanctions, "_rows_from_json") as json_parser,
        patch.object(sync_eu_sanctions, "_validate_rows") as eu_validate,
        patch.object(sync_eu_sanctions, "_replace_rows") as eu_replace,
        patch.object(sync_eu_sanctions, "upsert_source_status"),
        patch.object(sync_eu_sanctions, "append_sync_log"),
    ):
        assert sync_eu_sanctions.main() == 1
    eu_payload = _result_contract(capsys.readouterr().out)
    assert eu_payload["status"] == "error"
    json_parser.assert_not_called()
    eu_validate.assert_not_called()
    eu_replace.assert_not_called()


def _valid_ofac_govcloud_url() -> str:
    return (
        "https://"
        + sync_ofac_sanctions.OFAC_GOVCLOUD_REDIRECT_HOST
        + "/Published/1e995403-6e53-4855-809c-7e3e8556a9cb/2026-09-03/"
        "662b270b-fd55-4d88-b532-9b871b9af1b8/SDN.XML"
        "?X-Amz-Algorithm=AWS4-HMAC-SHA256"
        "&X-Amz-Credential=ASIA1234567890ABCDEF%2F20260903%2Fus-gov-west-1%2Fs3%2Faws4_request"
        "&X-Amz-Date=20260903T091224Z"
        "&X-Amz-Expires=3600"
        "&X-Amz-Security-Token=temporary-token"
        "&X-Amz-Signature="
        + ("a" * 64)
        + "&X-Amz-SignedHeaders=host"
        "&response-content-disposition=attachment%3B%20filename%3D%22sdn.xml%22"
        "&response-content-type=text%2Fxml"
    )


def _install_mock_http_client(monkeypatch, module, handler):
    real_client = httpx.Client
    requests: list[str] = []
    client_kwargs: dict[str, object] = {}

    def recording_handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return handler(request)

    transport = httpx.MockTransport(recording_handler)

    def client_factory(**kwargs):
        client_kwargs.update(kwargs)
        return real_client(transport=transport, **kwargs)

    monkeypatch.setattr(module.httpx, "Client", client_factory)
    return requests, client_kwargs


def _assert_hardened_client_kwargs(kwargs: dict[str, object]) -> None:
    assert kwargs["follow_redirects"] is False
    assert kwargs["trust_env"] is False
    assert kwargs["verify"] is True


def test_sanctions_redirect_policies_allow_only_exact_official_artifacts() -> None:
    ofac_s3_url = _valid_ofac_govcloud_url()
    assert sync_ofac_sanctions._redirect_url_allowed(
        sync_ofac_sanctions.OFAC_DEFAULT_URL,
        ofac_s3_url,
    )
    assert not sync_ofac_sanctions._redirect_url_allowed(
        sync_ofac_sanctions.OFAC_DEFAULT_URL,
        "https://attacker.example/sdn.xml",
    )
    assert not sync_ofac_sanctions._redirect_url_allowed(
        sync_ofac_sanctions.OFAC_DEFAULT_URL,
        "https://www.treasury.gov/ofac/downloads/not-sdn.xml",
    )
    assert sync_eu_sanctions._redirect_url_allowed(
        sync_eu_sanctions.EU_DEFAULT_URL,
        sync_eu_sanctions.EU_DEFAULT_URL,
    )
    assert not sync_eu_sanctions._redirect_url_allowed(
        sync_eu_sanctions.EU_DEFAULT_URL,
        "https://attacker.example/content",
    )
    assert sync_eu_sanctions._redirect_url_allowed(
        sync_eu_sanctions.EU_CORRELATION_XLSX_URL,
        sync_eu_sanctions.EU_CORRELATION_XLSX_URL,
    )
    assert not sync_eu_sanctions._redirect_url_allowed(
        sync_eu_sanctions.EU_CORRELATION_XLSX_URL,
        sync_eu_sanctions.EU_CORRELATION_XLSX_URL + "&extra=1",
    )


def test_ofac_follows_only_the_exact_signed_govcloud_artifact(monkeypatch) -> None:
    govcloud_url = _valid_ofac_govcloud_url()

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == sync_ofac_sanctions.OFAC_DEFAULT_URL:
            return httpx.Response(302, headers={"location": govcloud_url})
        return httpx.Response(
            200,
            text="<sdnList/>",
            headers={"content-type": "text/xml"},
        )

    requests, kwargs = _install_mock_http_client(
        monkeypatch,
        sync_ofac_sanctions,
        handler,
    )
    body, content_type = sync_ofac_sanctions._http_get(
        sync_ofac_sanctions.OFAC_DEFAULT_URL,
        retries=1,
    )

    assert body == "<sdnList/>"
    assert content_type == "text/xml"
    assert requests == [sync_ofac_sanctions.OFAC_DEFAULT_URL, govcloud_url]
    _assert_hardened_client_kwargs(kwargs)


@pytest.mark.parametrize(
    "location",
    (
        "https://attacker.example/SDN.XML",
        "http://www.treasury.gov/ofac/downloads/sdn.xml",
        "https://www.treasury.gov/ofac/downloads/not-sdn.xml",
        "https://wc2h-sls-prod-public-published.s3.us-gov-west-1.amazonaws.com/"
        "Published/not-the-approved-object/SDN.XML",
    ),
)
def test_ofac_rejects_redirect_before_contacting_unapproved_target(
    monkeypatch,
    location: str,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": location})

    requests, kwargs = _install_mock_http_client(
        monkeypatch,
        sync_ofac_sanctions,
        handler,
    )
    with pytest.raises(RuntimeError, match="unexpected OFAC redirect target"):
        sync_ofac_sanctions._http_get(
            sync_ofac_sanctions.OFAC_DEFAULT_URL,
            retries=1,
        )

    assert requests == [sync_ofac_sanctions.OFAC_DEFAULT_URL]
    _assert_hardened_client_kwargs(kwargs)


@pytest.mark.parametrize(
    "location",
    (
        "https://attacker.example/content",
        "http://webgate.ec.europa.eu/fsd/fsf/public/files/"
        "xmlFullSanctionsList_1_1/content",
        "https://webgate.ec.europa.eu/fsd/fsf/public/files/"
        "xmlFullSanctionsList_1_1/not-content",
    ),
)
def test_eu_feed_rejects_redirect_before_contacting_unapproved_target(
    monkeypatch,
    location: str,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": location})

    requests, kwargs = _install_mock_http_client(
        monkeypatch,
        sync_eu_sanctions,
        handler,
    )
    with pytest.raises(RuntimeError, match="unexpected EU sanctions redirect target"):
        sync_eu_sanctions._http_get(
            sync_eu_sanctions.EU_DEFAULT_URL,
            retries=1,
        )

    assert requests == [sync_eu_sanctions.EU_DEFAULT_URL]
    _assert_hardened_client_kwargs(kwargs)


@pytest.mark.parametrize(
    "location",
    (
        "https://attacker.example/eu.xlsx",
        "http://finance.ec.europa.eu/document/download/"
        "e5a807d3-6ca0-4bfb-8c6c-2f56f55e0b2e_en"
        "?filename=faqs-sanctions-russia-correlation-table-goods-regulation-833_en.xlsx",
        "https://finance.ec.europa.eu/document/download/wrong-document"
        "?filename=faqs-sanctions-russia-correlation-table-goods-regulation-833_en.xlsx",
        "https://finance.ec.europa.eu/document/download/"
        "e5a807d3-6ca0-4bfb-8c6c-2f56f55e0b2e_en?filename=wrong.xlsx",
    ),
)
def test_eu_binary_fallback_rejects_redirect_before_contacting_unapproved_target(
    monkeypatch,
    location: str,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": location})

    requests, kwargs = _install_mock_http_client(
        monkeypatch,
        sync_eu_sanctions,
        handler,
    )
    with pytest.raises(RuntimeError, match="unexpected EU sanctions redirect target"):
        sync_eu_sanctions._http_get_bytes(
            sync_eu_sanctions.EU_CORRELATION_XLSX_URL,
            retries=1,
        )

    assert requests == [sync_eu_sanctions.EU_CORRELATION_XLSX_URL]
    _assert_hardened_client_kwargs(kwargs)
