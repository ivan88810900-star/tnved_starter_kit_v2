"""Manifest review cannot be forged through a legacy importer or alias."""

import asyncio
import importlib
from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import sources
from app.services import normative_bundle, source_import, source_sync, tamdoc_sync
from app.services.official_payment_admission import LEGACY_OFFICIAL_PAYMENT_DOMAINS


@pytest.mark.parametrize("domain", sorted(LEGACY_OFFICIAL_PAYMENT_DOMAINS))
@pytest.mark.parametrize("forged", [False, True])
def test_valid_legacy_apply_stops_before_db_even_with_asserted_approval(domain, forged):
    module = importlib.import_module("app.services." + domain + "_ingestion")
    rows = [{"hs_code": "8517130000", "rate_percent": 0}]
    payload = {"official_ett_url": "https://eec.eaeunion.org/", "source_url": "https://www.nalog.gov.ru/"}
    if forged:
        payload.update(legal_review_verified=True, approved_by="admin", manifest_sha256="a" * 64)
    with ExitStack() as stack:
        stack.enter_context(patch.object(module, "discover_" + domain + "_bundle_path", return_value="test.json"))
        stack.enter_context(patch.object(module, "_validate_bundle_for_ingest", return_value=(payload, {"status": "parsed"}, "2026-09-12", rows, [])))
        for name in ["SessionLocal", "upsert_source_status", "append_sync_log", "run_payment_data_coverage_report"]:
            stack.enter_context(patch.object(module, name, side_effect=AssertionError("blocked apply reached " + name)))
        result = getattr(module, "run_" + domain + "_apply")()
    assert result["status"] == "manual_review_required"
    assert result["db_mutated"] is False
    assert result["row_counts"]["blocked"] == 1
    assert result["row_counts"]["insert"] == result["row_counts"]["update"] == 0
    assert any("manifest" in value for value in result["blockers"])


@pytest.mark.parametrize("container", [[{"hs_code": "8517130000", "duty_rate": 0}], None, False, 0, "", {}, "rates"])
@pytest.mark.parametrize("key", ["rates", "rows", "data"])
def test_mixed_bundle_is_blocked_before_catalog_or_provenance_write(container, key):
    payload = {"tnved": [{"hs_code": "85", "description": "test fixture"}], key: container,
               "approved": True, "reviewer": "admin"}
    with patch.object(normative_bundle, "_import_normative_bundle_dict", side_effect=AssertionError("storage reached")):
        result = normative_bundle.import_normative_bundle_dict(payload)
    assert result["status"] == "manual_review_required"
    assert result["db_mutated"] is False


def test_catalog_only_bundle_keeps_existing_storage_contract():
    payload = {"tnved": [{"hs_code": "85", "description": "fixture"}], "rates": [], "rows": [], "data": []}
    with patch.object(normative_bundle, "_import_normative_bundle_dict", return_value={"status": "OK"}) as store:
        assert normative_bundle.import_normative_bundle_dict(payload)["status"] == "OK"
    assert store.call_args.args[0] is payload


@pytest.mark.parametrize("content", [
    b'{"rates":[{}],"rates":[]}',
    b'{"rates":[],"metadata":{"x":1,"x":2}}',
    b'{"rates":[],"metadata":NaN}',
    b'{"rates":[{"rate":1e999999999999999999999999999999}]}',
    b'{"rates":' + b'[' * 1200 + b'0' + b']' * 1200 + b'}',
])
def test_ambiguous_bundle_json_cannot_hide_rates(content):
    with patch.object(normative_bundle, "_import_normative_bundle_dict", side_effect=AssertionError("storage reached")):
        with pytest.raises(ValueError):
            normative_bundle.import_normative_bundle_bytes(content)


@pytest.mark.parametrize("name,body", [
    ("fixture.csv", b'hs_code,duty_rate\n8517130000,0\n'),
    ("fixture.json", b'{"rows":[{"hs_code":"8517130000","duty_rate":0}]}'),
    ("fixture.xml", b'<root><row><hs_code>8517130000</hs_code><duty_rate>0</duty_rate></row></root>'),
])
def test_rate_file_aliases_do_not_write(name, body):
    with patch.object(source_import, "upsert_hs_rate", side_effect=AssertionError("rate write")), \
         patch.object(source_import, "upsert_source_status", side_effect=AssertionError("stamp write")):
        result = source_import.import_normative_file(name, body)
    assert result["db_mutated"] is False
    assert result["status"] == "manual_review_required"


@pytest.mark.parametrize("function,setting", [("sync_rates_feed", "NORMATIVE_FEED_URL"), ("sync_csv_feed", "NORMATIVE_CSV_URL")])
def test_legacy_rate_feed_cannot_write_or_download_before_review(function, setting):
    with patch.object(source_sync, setting, "https://example.invalid/fixture"), \
         patch.object(source_sync, "_http_get_with_retries", side_effect=AssertionError("network reached")), \
         patch.object(source_sync, "upsert_hs_rate", side_effect=AssertionError("rate write")):
        result = asyncio.run(getattr(source_sync, function)())
    assert result["status"] == "manual_review_required"
    assert result["db_mutated"] is False


def test_bundle_sync_propagates_block_without_stamping_success():
    response = httpx.Response(200, json={"format": "customs_clear_normative_bundle", "rates": [{"hs_code": "8517130000", "duty_rate": 0}]}, request=httpx.Request("GET", "https://example.invalid/fixture"))
    with patch.object(source_sync, "NORMATIVE_BUNDLE_URL", "https://example.invalid/fixture"), \
         patch.object(source_sync, "_http_get_with_retries", new=AsyncMock(return_value=response)), \
         patch.object(normative_bundle, "_import_normative_bundle_dict", side_effect=AssertionError("storage reached")):
        result = asyncio.run(source_sync.sync_normative_bundle_url())
    assert result["status"] == "manual_review_required"
    assert result["db_mutated"] is False


@pytest.mark.parametrize("function,args", [
    ("_upsert_vat_preferences", (["8517130000"], [0], "fixture", "fixture")),
    ("_upsert_special_duties", (["8517130000"], ["CN"], [0], "fixture")),
])
def test_mirror_payment_writers_have_no_positive_override(function, args):
    with patch.object(tamdoc_sync, "SessionLocal", side_effect=AssertionError("DB access")):
        with pytest.raises(PermissionError, match="manifest_bound"):
            getattr(tamdoc_sync, function)(*args)


@pytest.mark.parametrize("domain", sorted(LEGACY_OFFICIAL_PAYMENT_DOMAINS))
def test_blocked_apply_http_does_not_bump_application_cache(domain):
    application = FastAPI()
    application.include_router(sources.router, prefix="/sources")
    result = {"status": "manual_review_required", "db_mutated": False}
    with patch.object(sources, "require_admin_token"), \
         patch.object(sources, "run_" + domain + "_apply", return_value=result), \
         patch.object(sources, "clear_preview_cache") as cache:
        response = TestClient(application).post("/sources/payment-ingestion/" + domain.replace("_", "-") + "/apply")
    assert response.status_code == 200
    assert response.json() == result
    cache.assert_not_called()
