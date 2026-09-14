"""AI extraction is evidence, never authority to mutate active normative data."""
from __future__ import annotations

import asyncio
import hashlib
import json
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import BulkImportFileCheckpoint, BulkImportJob, HistoricalCrawlCheckpoint, HsRate
from app.models.tnved import NonTariffMeasure, SpecialDuty
from app.services import bulk_normative_ai as bulk
from app.services import historical_crawler_engine as historical
from app.services.ett_artifacts import LocalArtifactStore


CLAIMS = [
    {"measure_category": "duty", "hs_codes": ["8517130000"], "rate_or_requirement": "7.5%",
     "vat_rate": 10, "regulatory_act": "Unverified model claim"},
    {"measure_category": "special_duty", "hs_codes": ["8517130000"], "rate_or_requirement": "31%",
     "origin_country": "CN", "regulatory_act": "Unverified model claim"},
    {"measure_category": "excise", "hs_codes": ["240220"], "rate_or_requirement": "300 руб."},
    {"measure_category": "non_tariff", "hs_codes": ["8517"], "rate_or_requirement": "Лицензия ФСБ"},
    {"measure_category": "import_ban", "hs_codes": ["8517"], "rate_or_requirement": "Запрет"},
]
SOURCE = b"<html><body>Unreviewed source evidence with product exceptions.</body></html>"
RAW = json.dumps(CLAIMS, ensure_ascii=False)


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[model.__table__ for model in (
        HsRate, SpecialDuty, NonTariffMeasure, BulkImportJob,
        BulkImportFileCheckpoint, HistoricalCrawlCheckpoint,
    )])
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(bulk, "SessionLocal", sessions)
    monkeypatch.setattr(historical, "SessionLocal", sessions)
    monkeypatch.setattr(bulk, "RAW_NORMATIVE_DIR", tmp_path / "raw")
    monkeypatch.setattr(bulk, "AI_REVIEW_DIR", tmp_path / "runtime" / "review")
    monkeypatch.setattr(bulk, "_job_running", False)
    llm = AsyncMock(return_value=RAW)
    monkeypatch.setattr(bulk, "call_gemini_with_throttle", llm)
    monkeypatch.setattr(historical, "call_gemini_with_throttle", llm)
    with sessions() as db:
        db.add(HsRate(hs_code="8517130000", hs_prefix="8517130000", duty_rate="5%", vat_import_rate=22,
                      source_url="retained-existing-fixture", source_revision="before"))
        db.add(SpecialDuty(hs_code_prefix="8517130000", origin_country="CN", rate_percent=8,
                           regulatory_act="existing fixture"))
        db.add(NonTariffMeasure(commodity_code="8517130000", measure_type="license",
                               document_required="Existing conditional fixture", regulatory_act="existing fixture"))
        db.commit()

    @event.listens_for(engine, "before_cursor_execute")
    def no_active_write(conn, cursor, statement, parameters, context, executemany):
        sql = statement.lower().lstrip()
        if sql.startswith(("insert", "update", "delete", "replace")):
            assert all(table not in sql for table in ("hs_rates", "special_duties", "non_tariff_measures")), statement

    yield sessions, llm
    engine.dispose()


def assert_active_unchanged(sessions):
    with sessions() as db:
        rate = db.query(HsRate).one()
        assert (rate.duty_rate, rate.vat_import_rate, rate.source_revision) == ("5%", 22, "before")
        assert db.query(SpecialDuty).one().rate_percent == 8
        assert db.query(NonTariffMeasure).one().document_required == "Existing conditional fixture"


def assert_review_evidence(checkpoint, source=SOURCE):
    assert checkpoint.status == bulk.AI_REVIEW_CHECKPOINT_STATUS
    assert len(checkpoint.status) <= 16
    assert checkpoint.measures_applied == 0
    result = json.loads(checkpoint.error_note)
    assert result["status"] == "manual_review_required"
    assert result["measures_applied"] == 0
    store = LocalArtifactStore(bulk.AI_REVIEW_DIR, create=False)
    evidence = json.loads(store.read(result["evidence_sha256"]))
    assert store.read(evidence["source_sha256"]) == source
    assert evidence["source_sha256"] == hashlib.sha256(source).hexdigest()
    assert store.read(evidence["raw_model_output_sha256"]).decode() == RAW
    assert store.read(evidence["extracted_text_sha256"]).decode() == bulk.extract_text_from_bytes(source)
    assert store.read(evidence["system_prompt_sha256"]).decode() == bulk.BULK_SYSTEM_PROMPT
    assert evidence["rows"] == CLAIMS
    for name in ("source_evidence_verified", "legal_review_verified", "retention_verified",
                 "active_rates_written", "active_measures_written"):
        assert result[name] is False
        assert evidence[name] is False
    assert evidence["source_kind"] == "ai_extraction_unreviewed"
    return evidence


@pytest.mark.parametrize("rows", [[row] for row in CLAIMS] + [CLAIMS, [], [None], [{"measure_category": "other"}]])
@pytest.mark.parametrize("forged_approval", [False, True])
def test_direct_writer_rejects_before_any_session_access(rows, forged_approval):
    db = Mock()
    claims = [dict(row, legal_review_verified=True, approved=True, confidence=1.0) if forged_approval and isinstance(row, dict)
              else row for row in rows]
    with pytest.raises(bulk.AINormativeAdmissionError, match="ai_normative_review_required"):
        bulk.apply_structured_rows(db, claims, source_tag="official://forged-manifest")
    assert db.mock_calls == []


def test_direct_writer_cannot_update_existing_or_partially_apply_mixed_rows(isolated):
    sessions, _ = isolated
    with sessions() as db:
        with pytest.raises(PermissionError):
            bulk.apply_structured_rows(db, CLAIMS, source_tag="fixture")
        assert not db.new and not db.dirty and not db.deleted
        db.commit()
    assert_active_unchanged(sessions)


def test_bulk_extracts_to_review_and_repeat_skips_model_without_claiming_application(isolated):
    sessions, llm = isolated
    root = bulk.raw_normative_dir()
    (root / "document.html").write_bytes(SOURCE)
    job = bulk.create_import_job()
    progress = []
    asyncio.run(bulk.run_bulk_import(job, delay_sec=0, progress_cb=progress.append))
    with sessions() as db:
        checkpoint = db.query(BulkImportFileCheckpoint).one()
        assert_review_evidence(checkpoint)
        assert db.query(BulkImportJob).one().status == "manual_review_required"
    assert progress[-1]["active_rates_written"] is False
    assert progress[-1]["active_measures_written"] is False
    assert progress[-1]["status"] == "manual_review_required"
    asyncio.run(bulk.run_bulk_import(job, delay_sec=0, progress_cb=progress.append))
    assert llm.await_count == 1
    assert progress[-1]["skipped"] is True
    assert progress[-1]["status"] == "manual_review_required"
    assert bulk.get_job_status(job)["job"]["measures_applied"] == 0
    assert bulk.get_job_status(job)["active_write_path_enabled"] is False
    assert_active_unchanged(sessions)


def test_crawler_extracts_exact_body_and_retains_full_url_as_untrusted_tag(isolated):
    sessions, llm = isolated
    crawler = historical.HistoricalCrawler(historical.CrawlerSettings(llm_delay_sec=0))
    fetch = AsyncMock(return_value=(200, SOURCE))
    crawler.fetch_document = fetch
    url = "https://official.example.invalid/document/" + "x" * 240
    result = asyncio.run(crawler.process_url_pipeline(url))
    assert result["status"] == "manual_review_required" and result["measures"] == 0
    with sessions() as db:
        evidence = assert_review_evidence(db.query(HistoricalCrawlCheckpoint).one())
        assert evidence["source_tag"] == "crawler:" + url
    again = asyncio.run(crawler.process_url_pipeline(url))
    assert again["skipped"] is True and again["status"] == "manual_review_required"
    assert fetch.await_count == 1 and llm.await_count == 1
    assert_active_unchanged(sessions)


@pytest.mark.parametrize("runner", ["bulk", "crawler"])
def test_evidence_failure_cannot_create_success_or_pending_checkpoint(isolated, monkeypatch, runner):
    sessions, _ = isolated
    fail = Mock(side_effect=OSError("evidence unavailable"))
    monkeypatch.setattr(bulk, "stage_structured_rows_for_review", fail)
    monkeypatch.setattr(historical, "stage_structured_rows_for_review", fail)
    if runner == "bulk":
        (bulk.raw_normative_dir() / "document.html").write_bytes(SOURCE)
        job = bulk.create_import_job()
        asyncio.run(bulk.run_bulk_import(job, delay_sec=0))
        with sessions() as db:
            checkpoint = db.query(BulkImportFileCheckpoint).one()
            assert db.query(BulkImportJob).one().status == "error"
    else:
        crawler = historical.HistoricalCrawler(historical.CrawlerSettings(llm_delay_sec=0))
        crawler.fetch_document = AsyncMock(return_value=(200, SOURCE))
        result = asyncio.run(crawler.process_url_pipeline("https://official.example.invalid/act"))
        assert result["status"] == "error"
        with sessions() as db:
            checkpoint = db.query(HistoricalCrawlCheckpoint).one()
    assert checkpoint.status == "error" and checkpoint.measures_applied == 0
    assert "evidence unavailable" in checkpoint.error_note
    assert_active_unchanged(sessions)


def test_changed_upload_cannot_bind_different_bytes_to_checkpoint_digest(isolated, monkeypatch):
    sessions, llm = isolated
    (bulk.raw_normative_dir() / "document.html").write_bytes(SOURCE)
    monkeypatch.setattr(bulk, "_sha256_file", lambda _: "0" * 64)
    job = bulk.create_import_job()
    asyncio.run(bulk.run_bulk_import(job, delay_sec=0))
    assert llm.await_count == 0
    with sessions() as db:
        assert db.query(BulkImportFileCheckpoint).one().status == "error"
        assert "changed" in db.query(BulkImportFileCheckpoint).one().error_note
    assert_active_unchanged(sessions)


def test_unexpected_bulk_failure_is_recorded_and_not_swallowed(isolated, monkeypatch):
    sessions, _ = isolated
    (bulk.raw_normative_dir() / "document.html").write_bytes(SOURCE)
    monkeypatch.setattr(bulk, "_sha256_file", Mock(side_effect=OSError("cannot read source")))
    job = bulk.create_import_job()
    with pytest.raises(OSError, match="cannot read source"):
        asyncio.run(bulk.run_bulk_import(job, delay_sec=0))
    assert bulk.is_import_running() is False
    with sessions() as db:
        assert db.query(BulkImportJob).one().status == "error"
    assert_active_unchanged(sessions)


def test_legacy_ok_checkpoint_does_not_become_fresh_legal_approval(isolated):
    sessions, llm = isolated
    path = bulk.raw_normative_dir() / "document.html"
    path.write_bytes(SOURCE)
    with sessions() as db:
        db.add(BulkImportFileCheckpoint(file_sha256=hashlib.sha256(SOURCE).hexdigest(), status="ok",
                                        measures_applied=19, relative_path="document.html"))
        db.commit()
    job = bulk.create_import_job()
    asyncio.run(bulk.run_bulk_import(job, delay_sec=0))
    assert llm.await_count == 0
    status = bulk.get_job_status(job)
    assert status["job"]["status"] == "manual_review_required"
    assert status["job"]["measures_applied"] == 0
    assert status["legal_review_verified"] is False
    assert_active_unchanged(sessions)


def test_authenticated_admin_background_path_is_review_only(isolated, monkeypatch):
    sessions, _ = isolated
    from app.api import admin_v1
    monkeypatch.setenv("ADMIN_API_TOKEN", "test-only-admin-token")
    app = FastAPI()
    app.include_router(admin_v1.router, prefix="/api/v1/admin")
    client = TestClient(app)
    assert client.post("/api/v1/admin/import/bulk/start").status_code == 401
    headers = {"X-Admin-Token": "test-only-admin-token"}
    upload = client.post("/api/v1/admin/import/bulk/upload", headers=headers,
                         files=[("files", ("document.html", SOURCE, "text/html"))])
    assert upload.status_code == 200
    started = client.post("/api/v1/admin/import/bulk/start?delay_sec=0", headers=headers)
    assert started.status_code == 200
    status = client.get("/api/v1/admin/import/bulk/status", params={"job_id": started.json()["job_id"]}, headers=headers)
    assert status.status_code == 200
    assert status.json()["job"]["status"] == "manual_review_required"
    assert status.json()["job"]["measures_applied"] == 0
    assert status.json()["application_status"] == "manual_review_required"
    assert_active_unchanged(sessions)
