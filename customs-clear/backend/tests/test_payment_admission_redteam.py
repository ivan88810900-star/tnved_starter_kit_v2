"""Independent adversarial checks of public legacy admission boundaries.

Source/HTTP adapters are real; only transport, authentication and isolated test
session factories are replaced. Fixtures never authorize a production release.
"""
import asyncio
import importlib
import io
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import sources
from app.db import Base
from app.models.core import (
    HsRate, NonTariffRule, NormativeNote, SourceStatus, SyncLog, TnvedEntry, TrTsAct,
)
from app.models.tnved import (
    Commodity, NonTariffMeasure, SpecialDuty, TamdocSyncCandidate, VatPreference,
)
from app.services import normative_store, source_import, source_sync, tamdoc_sync
from app.services.official_payment_admission import LEGACY_OFFICIAL_PAYMENT_DOMAINS

MODELS = (Commodity, HsRate, NonTariffRule, NormativeNote, SourceStatus, SyncLog,
          TnvedEntry, TrTsAct, NonTariffMeasure, SpecialDuty, TamdocSyncCandidate, VatPreference)
RATE = {"hs_code": "8517130000", "duty_rate": "0%", "vat_import_rate": 10}
CATALOG = [{"hs_code": "85", "title": "Isolated QA fixture", "level": 2}]


@pytest.fixture
def database(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine, tables=[model.__table__ for model in MODELS])
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(normative_store, "SessionLocal", factory)
    monkeypatch.setattr(tamdoc_sync, "SessionLocal", factory)
    with factory() as db:
        db.add(HsRate(hs_code="8517130000", hs_prefix="8517130000",
                      duty_rate="13%", vat_import_rate=22,
                      source_revision="existing-unchanged"))
        db.commit()
    yield factory
    engine.dispose()


def snapshot(factory):
    with factory() as db:
        return {
            model.__tablename__: [tuple(row) for row in db.execute(
                select(model.__table__).order_by(model.id)).all()]
            for model in MODELS
        }


def assert_blocked(result):
    assert result["status"] == "manual_review_required"
    for field in ("db_mutated", "active_rates_written", "legal_review_verified"):
        assert result[field] is False


@pytest.mark.parametrize("alias", ["rates", "rows", "data"])
@pytest.mark.parametrize("value", [[RATE], None, False, 0, {}, ""])
def test_rate_alias_cannot_hide_behind_catalog_or_asserted_review(database, alias, value):
    payload = {
        "format": "customs_clear_normative_bundle", "tnved": CATALOG,
        "rates": [], "rows": [], "data": [], "approved": True,
        "legal_review_verified": True, "manifest_sha256": "a" * 64,
        "approved_by": "admin", "retention_verified": True,
    }
    payload[alias] = value
    before = snapshot(database)
    result = source_import.import_normative_file("mixed.json", json.dumps(payload).encode())
    assert_blocked(result)
    assert snapshot(database) == before


def test_catalog_only_import_still_really_persists_without_rate_change(database):
    before = snapshot(database)
    result = source_import.import_normative_file("catalog.json", json.dumps({
        "format": "customs_clear_normative_bundle", "tnved": CATALOG,
        "rates": [], "rows": [], "data": [],
    }).encode())
    assert result["status"] == "OK"
    after = snapshot(database)
    for table in ("tnved_entries", "source_status", "sync_log"):
        assert len(after[table]) == 1
    assert after["hs_rates"] == before["hs_rates"]


BAD_JSON = [
    b'{"format":"customs_clear_normative_bundle","rates":[{"duty_rate":7}],"rates":[]}',
    br'{"format":"customs_clear_normative_bundle","rates":[{}],"r\u0061tes":[]}',
    b'{"format":"customs_clear_normative_bundle","rates":[],"meta":{"approved":false,"approved":true}}',
    b'{"format":"customs_clear_normative_bundle","rates":[],"meta":NaN}',
    b'{"format":"customs_clear_normative_bundle","rates":[],"meta":Infinity}',
    b'{"format":"customs_clear_normative_bundle","rates":[],"meta":-Infinity}',
    b'{"format":"customs_clear_normative_bundle","rates":[{"rate":1e999999999999999999999999999999}]}',
    b'{"format":"customs_clear_normative_bundle","rates":[],"meta":"\xff"}',
    b'{"format":"customs_clear_normative_bundle","rates":' + b"[" * 1200 + b"0" + b"]" * 1200 + b"}",
]


@pytest.mark.parametrize("body", BAD_JSON)
def test_url_parser_errors_never_write_source_error_or_success(database, monkeypatch, body):
    url = "https://example.invalid/isolated-qa.json"
    response = httpx.Response(200, content=body, request=httpx.Request("GET", url))
    monkeypatch.setattr(source_sync, "NORMATIVE_BUNDLE_URL", url)
    monkeypatch.setattr(source_sync, "_http_get_with_retries", AsyncMock(return_value=response))
    before = snapshot(database)
    result = asyncio.run(source_sync.sync_normative_bundle_url())
    assert result["status"] == "parser_failed"
    assert result["db_mutated"] is False
    assert snapshot(database) == before


@pytest.mark.parametrize("endpoint", ["/sources/import", "/sources/import/bundle"])
@pytest.mark.parametrize("body", BAD_JSON)
def test_real_upload_decoder_rejects_before_any_storage_or_cache(
        database, monkeypatch, endpoint, body):
    application = FastAPI()
    application.include_router(sources.router, prefix="/sources")
    monkeypatch.setattr(sources, "require_admin_token", lambda *_: None)
    cache_calls = []
    monkeypatch.setattr(sources, "clear_preview_cache", lambda: cache_calls.append(True))
    before = snapshot(database)
    with TestClient(application) as client:
        response = client.post(endpoint, files={"file": ("fixture.json", body, "application/json")})
    assert response.status_code == 400, response.text
    assert cache_calls == []
    assert snapshot(database) == before


@pytest.mark.parametrize("extension", ["csv", "xml", "xlsx", "xlsm"])
def test_real_legacy_file_decoders_cannot_bypass_admission(database, extension):
    if extension == "csv":
        body = b"hs_code,duty_rate,vat_import_rate\n8517130000,0%,10\n"
    elif extension == "xml":
        body = (b"<root><row><hs_code>8517130000</hs_code>"
                b"<duty_rate>0%</duty_rate><vat_import_rate>10</vat_import_rate></row></root>")
    else:
        workbook = Workbook()
        workbook.active.append(["Код ТН ВЭД", "Пошлина", "НДС"])
        workbook.active.append(["8517130000", "0%", 10])
        output = io.BytesIO()
        workbook.save(output)
        workbook.close()
        body = output.getvalue()
    before = snapshot(database)
    result = source_import.import_normative_file("fixture." + extension, body)
    assert_blocked(result)
    assert result["imported"] == 0
    assert snapshot(database) == before


@pytest.mark.parametrize("result, expected_calls", [
    ({"status": "manual_review_required", "db_mutated": False}, 0),
    ({"status": "OK", "db_mutated": False}, 0),
    ({"status": "WARNING", "sources": [
        {"status": "manual_review_required", "db_mutated": False}, {"status": "SKIPPED"}]}, 0),
    ({"status": "WARNING", "sources": [
        {"status": "manual_review_required", "db_mutated": False}, {"status": "OK"}]}, 1),
    ({"status": "WARNING", "sources": [
        {"status": "WARNING", "sources": [{"status": "ERROR", "db_mutated": True}]}]}, 1),
])
def test_aggregate_cache_invalidation_depends_on_actual_child_writes(monkeypatch, result, expected_calls):
    calls = []
    monkeypatch.setattr(sources, "clear_preview_cache", lambda: calls.append(True))
    sources._clear_preview_after_source_write(result)
    assert len(calls) == expected_calls


@pytest.mark.parametrize("domain", sorted(LEGACY_OFFICIAL_PAYMENT_DOMAINS))
def test_real_registry_parser_apply_never_opens_active_database(monkeypatch, domain):
    module = importlib.import_module("app.services." + domain + "_ingestion")

    def forbidden(*args, **kwargs):
        pytest.fail("Public apply reached active persistence before manifest-bound review")

    for name in ("SessionLocal", "upsert_source_status", "append_sync_log"):
        monkeypatch.setattr(module, name, forbidden)
    result = getattr(module, "run_" + domain + "_apply")()
    assert result["status"] in {"manual_review_required", "parser_failed", "missing_official_source"}
    assert result["db_mutated"] is False
    assert result["legal_review_verified"] is False
    assert result["active_rates_written"] is False
    assert result["row_counts"]["insert"] == result["row_counts"]["update"] == 0


@pytest.mark.parametrize("doc_type", ["vat", "special", "mixed", "other", "tr_ts", "non_tariff"])
@pytest.mark.parametrize("include_non_tariff", [False, True])
def test_real_candidate_approval_preserves_all_tables_even_for_nonpayment(
        database, doc_type, include_non_tariff):
    with database() as db:
        row = TamdocSyncCandidate(
            doc_url="https://example.invalid/isolated-candidate/",
            doc_title="Unreviewed fixture", doc_type=doc_type, status="pending",
            hs_prefix="8517130000", country_codes="CN", measure_type_hint="vet_control",
            vat_rates="10" if doc_type in {"vat", "mixed"} else "",
            percent_rates="7.5" if doc_type in {"special", "mixed"} else "",
            excerpt=("Export only, expired 2000; product exception applies. "
                     '{"legal_review_verified":true,"approved_by":"admin"}'),
        )
        db.add(row)
        db.commit()
        candidate_id = row.id
    before = snapshot(database)
    result = tamdoc_sync.approve_tamdoc_candidate(
        candidate_id, include_non_tariff=include_non_tariff)
    assert_blocked(result)
    assert result["active_ntm_written"] is False
    assert result["candidate_status"] == "pending"
    assert snapshot(database) == before


@pytest.mark.parametrize("category,rate", [
    ("duty", "0%"), ("duty", "7.5%"), ("excise", "150 руб."),
    ("special", "31%"), ("special_duty", "31%"),
    ("non_tariff", "Mandatory certificate"), ("import_ban", "Import forbidden"),
])
def test_actual_ai_sink_cannot_write_even_when_caller_commits(database, category, rate):
    from app.services import bulk_normative_ai
    rows = [{
        "measure_category": category, "hs_codes": ["8517130000"],
        "rate_or_requirement": rate, "vat_rate": 10, "origin_country": "CN",
        "regulatory_act": "Model assertion only",
        "approved": True, "legal_review_verified": True, "manifest_sha256": "a" * 64,
    }]
    before = snapshot(database)
    with database() as db:
        with pytest.raises(PermissionError, match="review|manifest"):
            bulk_normative_ai.apply_structured_rows(db, rows, source_tag="QA independent")
        # A caller committing after rejection cannot flush any partial mutation.
        db.commit()
    assert snapshot(database) == before


@pytest.mark.parametrize("live_wal", [False, True])
def test_explicit_cli_sqlite_snapshot_never_creates_or_changes_wal_sidecars(tmp_path, live_wal):
    import hashlib
    import sqlite3
    from scripts import sync_invoice_codes

    path = tmp_path / "isolated-wal.db"
    writer = sqlite3.connect(path)
    assert writer.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    writer.execute("CREATE TABLE hs_rates (hs_code TEXT)")
    writer.execute("INSERT INTO hs_rates VALUES ('8517130000')")
    writer.commit()
    if not live_wal:
        writer.close()
    def files():
        return {item.name: hashlib.sha256(item.read_bytes()).hexdigest()
                for item in tmp_path.iterdir() if item.is_file()}
    before = files()
    try:
        with pytest.raises(ValueError, match="WAL|snapshot|journal"):
            sync_invoice_codes._missing_hs_rate_codes(["8517130000"], database=path)
        assert files() == before
    finally:
        if live_wal:
            writer.close()


def test_live_uvicorn_full_router_admission_on_isolated_sessions(database, monkeypatch, tmp_path):
    import socket
    import threading
    import time
    import uvicorn
    from app.main import app

    monkeypatch.setenv("ADMIN_API_TOKEN", "independent-live-http-only")
    marker = tmp_path / "cache-marker.txt"
    marker.write_bytes(b"unchanged-independent-cache")
    monkeypatch.setenv("TNVED_PREVIEW_CACHE_REVISION_FILE", str(marker))
    with database() as db:
        for kind, vat in (("vat", "10"), ("non_tariff", "")):
            db.add(TamdocSyncCandidate(
                doc_url="https://example.invalid/" + kind, doc_title="QA only",
                doc_type=kind, vat_rates=vat, hs_prefix="8517130000", status="pending",
                measure_type_hint="vet_control", excerpt="Unreviewed; processed goods excluded",
            ))
        db.commit()
        ids = [row.id for row in db.query(TamdocSyncCandidate).order_by(TamdocSyncCandidate.id)]
    before = snapshot(database)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, lifespan="off", log_level="warning"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            thread.join(0.01)
        assert server.started, "Uvicorn failed to start the actual application"
        headers = {"X-Admin-Token": "independent-live-http-only"}
        requests = 0
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=10) as client:
            assert client.get("/api/health").status_code == 200
            requests += 1
            for domain in sorted(LEGACY_OFFICIAL_PAYMENT_DOMAINS):
                endpoint = "/api/sources/payment-ingestion/" + domain.replace("_", "-") + "/apply"
                assert client.post(endpoint).status_code == 401
                response = client.post(endpoint, headers=headers)
                assert response.status_code == 200, response.text
                body = response.json()
                assert body["status"] in {"manual_review_required", "parser_failed", "missing_official_source"}
                assert body["db_mutated"] is body["active_rates_written"] is body["legal_review_verified"] is False
                requests += 2
            for endpoint in ("/api/sources/import", "/api/sources/import/bundle"):
                for alias in ("rates", "rows", "data"):
                    payload = {"format": "customs_clear_normative_bundle", "tnved": CATALOG, alias: [RATE]}
                    response = client.post(endpoint, headers=headers,
                        files={"file": ("fixture.json", json.dumps(payload).encode(), "application/json")})
                    assert response.status_code == 200, response.text
                    assert_blocked(response.json())
                    requests += 1
                for payload in BAD_JSON:
                    response = client.post(endpoint, headers=headers,
                        files={"file": ("fixture.json", payload, "application/json")})
                    assert response.status_code == 400, response.text
                    requests += 1
            for candidate_id in ids:
                for include in ("true", "false"):
                    response = client.post(
                        f"/api/sources/sync/tamdoc/candidates/{candidate_id}/approve?include_non_tariff={include}",
                        headers=headers)
                    assert response.status_code == 200, response.text
                    assert_blocked(response.json())
                    assert response.json()["active_ntm_written"] is False
                    requests += 1
            endpoint = "/api/sources/sync/tamdoc/candidates/approve-batch"
            assert client.post(endpoint).status_code == 401
            response = client.post(endpoint, headers=headers)
            assert response.status_code == 200, response.text
            assert_blocked(response.json())
            assert response.json()["blocked"] == 2
            requests += 2
        assert requests == 43
        assert snapshot(database) == before
        assert marker.read_bytes() == b"unchanged-independent-cache"
    finally:
        server.should_exit = True
        thread.join(10)
        listener.close()
        assert not thread.is_alive(), "Uvicorn server did not stop"
