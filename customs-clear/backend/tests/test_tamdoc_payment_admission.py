"""Commercial extraction remains review material, never an active legal grant."""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.core import SourceStatus, SyncLog, TrTsAct
from app.models.tnved import Commodity, NonTariffMeasure, SpecialDuty, TamdocSyncCandidate, VatPreference
from app.services import normative_store, tamdoc_sync as service
from app.services.official_payment_admission import LEGAL_REVIEW_BLOCKER


@pytest.fixture
def database(monkeypatch):
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine, tables=[model.__table__ for model in (
        Commodity, TamdocSyncCandidate, VatPreference, SpecialDuty,
        NonTariffMeasure, SourceStatus, SyncLog, TrTsAct,
    )])
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(service, "SessionLocal", factory)
    monkeypatch.setattr(normative_store, "SessionLocal", factory)
    with factory() as db:
        db.add(VatPreference(hs_code_prefix="1234567890", vat_rate=10,
                             decree_info="existing fixture", comment="unchanged"))
        db.add(SpecialDuty(hs_code_prefix="1234567890", origin_country="CN",
                           rate_percent=7.5, regulatory_act="existing fixture"))
        db.commit()
    yield factory
    engine.dispose()


def snapshot(factory, *models):
    with factory() as db:
        return {model.__tablename__: [tuple(row) for row in db.execute(select(model.__table__)).all()]
                for model in models}


def candidate(factory, **changes):
    data = dict(doc_url="https://www.alta.ru/tamdoc/test/", doc_title="Fixture only",
                doc_type="vat", hs_prefix="1234567890", country_codes="CN",
                vat_rates="10", percent_rates="", status="pending", excerpt="Unreviewed text")
    data.update(changes)
    with factory() as db:
        row = TamdocSyncCandidate(**data)
        db.add(row)
        db.commit()
        return row.id


@pytest.mark.parametrize("doc_type,vat_rates,percent_rates", [
    ("vat", "10", ""), ("vat", "0", ""), ("vat", "", ""),
    ("special", "", "7.5"), ("mixed", "10", "7.5"), (" VaT ", "", ""),
    ("other", "10", ""), ("other", "", "0"), ("license", "bad json", ""),
])
@pytest.mark.parametrize("historical_status", ["pending", "approved", "rejected"])
def test_payment_approval_never_changes_candidate_or_active_rows(
        database, doc_type, vat_rates, percent_rates, historical_status):
    cid = candidate(database, doc_type=doc_type, vat_rates=vat_rates,
                    percent_rates=percent_rates, status=historical_status,
                    excerpt='{"legal_review_verified":true,"approved":true,"manifest_sha256":"forged"}')
    models = (TamdocSyncCandidate, VatPreference, SpecialDuty, NonTariffMeasure, TrTsAct, SourceStatus, SyncLog)
    before = snapshot(database, *models)
    result = service.approve_tamdoc_candidate(cid, include_non_tariff=True)
    assert result["status"] == "manual_review_required"
    assert result["candidate_status"] == historical_status
    assert result["db_mutated"] is False
    assert result["active_rates_written"] is False and result["active_ntm_written"] is False
    assert result["legal_review_verified"] is False
    assert result["blockers"] == [LEGAL_REVIEW_BLOCKER]
    assert snapshot(database, *models) == before


@pytest.mark.parametrize("writer,args", [
    (service._upsert_vat_preferences, (["1234567890"], [0], "forged", "approved")),
    (service._upsert_special_duties, (["1234567890"], ["CN"], [7.5], "forged")),
])
def test_legacy_payment_writer_rejects_before_opening_a_session(monkeypatch, writer, args):
    monkeypatch.setattr(service, "SessionLocal", lambda: pytest.fail("Payment writer opened DB"))
    with pytest.raises(PermissionError, match="manifest_bound_legal_review_required"):
        writer(*args)


def test_batch_cannot_label_commercial_normative_candidates_approved(database):
    payment = candidate(database)
    other = candidate(database, doc_type="other", vat_rates="", doc_url="fixture:other")
    no_code = candidate(database, doc_type="other", vat_rates="", hs_prefix="", doc_url="fixture:missing")
    models = (TamdocSyncCandidate, VatPreference, SpecialDuty, NonTariffMeasure, TrTsAct, SourceStatus, SyncLog)
    before = snapshot(database, *models)
    result = service.approve_tamdoc_candidates_batch(include_non_tariff=False)
    assert result == {
        "status": "manual_review_required", "blocked": 3, "db_mutated": False,
        "active_rates_written": False, "legal_review_verified": False,
        "blockers": sorted([LEGAL_REVIEW_BLOCKER, service.NTM_REVIEW_BLOCKER]),
        "active_ntm_written": False, "processed": 3, "approved": 0, "rejected": 0, "errors": 0,
    }
    rows = {row["id"]: row for row in service.list_tamdoc_candidates()}
    assert all(rows[cid]["status"] == "pending" for cid in (payment, other, no_code))
    assert snapshot(database, *models) == before
    second = service.approve_tamdoc_candidates_batch()
    assert second["db_mutated"] is False and second["blocked"] == 3


def test_rejection_and_listing_remain_available(database):
    cid = candidate(database)
    result = service.reject_tamdoc_candidate(cid, "Needs retained official source")
    assert result["new_status"] == "rejected"
    rows = service.list_tamdoc_candidates(status="rejected")
    assert len(rows) == 1 and rows[0]["error_message"] == "Needs retained official source"
    assert service.approve_tamdoc_candidate(999999)["error"] == "candidate_not_found"


@pytest.fixture
def mirror(monkeypatch):
    monkeypatch.setattr(service, "TAMDOC_SYNC_ENABLED", True)
    monkeypatch.setattr(service, "TAMDOC_MAX_DELAY_SEC", 0)
    monkeypatch.setattr(service, "TAMDOC_PROXY", "")
    monkeypatch.setattr(service, "TAMDOC_ARCHIVE_USE_AI", False)

    class OfflineClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(service.httpx, "AsyncClient", OfflineClient)

    async def fetch(client, url):
        if url == service.TAMDOC_INDEX_URL:
            return '<a href="/tamdoc/test/">Unreviewed fixture</a>'
        return "<article>1234567890 товар. НДС 10%. Антидемпинговая пошлина 7,5%, Китай.</article>"

    monkeypatch.setattr(service, "_fetch_html", fetch)


@pytest.mark.parametrize("staging_only", [False, True])
def test_targeted_sync_only_stages_payment_extraction(database, mirror, staging_only):
    before = snapshot(database, VatPreference, SpecialDuty, NonTariffMeasure, TrTsAct)
    result = asyncio.run(service.sync_tamdoc_targeted(staging_only=staging_only))
    assert result["status"] == "OK", result
    assert result["staging_only"] is True
    assert result["payment_application_status"] == "manual_review_required"
    assert result["vat_created"] == result["special_created"] == 0 and result["staged_ok"] == 1
    row = service.list_tamdoc_candidates()[0]
    assert row["doc_type"] == "mixed" and row["status"] == "pending"
    assert row["vat_rates"] == "10" and "7.5" in row["percent_rates"]
    assert "manifest_bound_legal_review_required" in row["error_message"]
    assert snapshot(database, VatPreference, SpecialDuty, NonTariffMeasure, TrTsAct) == before
    with database() as db:
        source = db.query(SourceStatus).one()
        assert source.is_stale is True and "'legal_review_verified': False" in source.note


def test_document_sync_stages_both_payment_families(database, mirror):
    before = snapshot(database, VatPreference, SpecialDuty, NonTariffMeasure, TrTsAct)
    result = asyncio.run(service.sync_tamdoc_documents())
    assert result["status"] == "OK" and result["docs_processed"] == 1, result
    assert result["active_rates_written"] is False and result["staged_ok"] == 2
    rows = service.list_tamdoc_candidates()
    assert {row["doc_type"] for row in rows} == {"vat", "special"}
    assert all(row["status"] == "pending" for row in rows)
    assert snapshot(database, VatPreference, SpecialDuty, NonTariffMeasure, TrTsAct) == before
    with database() as db:
        assert all(row.is_stale for row in db.query(SourceStatus).all())


@pytest.mark.parametrize("staging_only", [False, True])
@pytest.mark.parametrize("auto_approve", [False, True])
def test_archive_apply_and_auto_approval_cannot_promote_payments(database, mirror, tmp_path,
                                                               staging_only, auto_approve):
    (tmp_path / "fixture.txt").write_text(
        "1234567890 товар. НДС 10%. Антидемпинговая пошлина 7,5%, Китай.", encoding="utf-8")
    before = snapshot(database, VatPreference, SpecialDuty, NonTariffMeasure, TrTsAct)
    result = service.sync_tamdoc_archive(str(tmp_path), staging_only=staging_only,
                                        include_non_tariff=False, auto_approve_pending=auto_approve)
    assert result["status"] == "OK" and result["docs_errors"] == 0
    assert result["staging_only"] is True and result["active_rates_written"] is False
    assert result["vat_candidates"] == result["special_candidates"] == 1
    assert result["vat_created"] == result["special_created"] == 0
    rows = service.list_tamdoc_candidates()
    assert len(rows) == 1 and rows[0]["status"] == "pending"
    assert "7.5" in rows[0]["percent_rates"] and rows[0]["vat_rates"] == "10"
    if auto_approve:
        assert result["batch_approve"]["blocked"] == 1 and result["batch_approve"]["approved"] == 0
    assert snapshot(database, VatPreference, SpecialDuty, NonTariffMeasure, TrTsAct) == before
    with database() as db:
        assert all(row.is_stale for row in db.query(SourceStatus).all())


@pytest.mark.parametrize("include_non_tariff", [False, True])
@pytest.mark.parametrize("doc_type,hint", [
    ("other", "vet_control"), ("other", "phyto_control"), ("tr_ts", "tr_ts"),
    ("license", "license"), ("certificate", "certificate"), ("sgr", "sgr"),
    ("fsb", "fsb"), ("fsetc", "fsetc"), ("marking", "marking"), ("other", "other"),
])
def test_nonpayment_candidate_is_not_approved_by_administrator_status(
        database, include_non_tariff, doc_type, hint):
    cid = candidate(database, doc_type=doc_type, measure_type_hint=hint, vat_rates="",
                    excerpt="Only raw materials; processed products are excluded")
    models = (TamdocSyncCandidate, NonTariffMeasure, TrTsAct, VatPreference, SpecialDuty, SourceStatus, SyncLog)
    before = snapshot(database, *models)
    result = service.approve_tamdoc_candidate(cid, include_non_tariff=include_non_tariff)
    assert result["status"] == "manual_review_required" and result["candidate_status"] == "pending"
    assert result["active_ntm_written"] is False and result["db_mutated"] is False
    assert result["blockers"] == [service.NTM_REVIEW_BLOCKER]
    assert snapshot(database, *models) == before


@pytest.mark.parametrize("writer", ["ntm", "tr_catalog"])
def test_legacy_ntm_writers_reject_before_opening_database(monkeypatch, writer):
    monkeypatch.setattr(service, "SessionLocal", lambda: pytest.fail("Unreviewed NTM writer opened DB"))
    with pytest.raises(PermissionError, match="curated_ntm_review_required"):
        if writer == "ntm":
            service._upsert_non_tariff([("1234", "Conditional rule")], "vet_control", "Unreviewed", "ВС")
        else:
            service._upsert_tr_ts_acts(["004/2011"], title="Unreviewed", text="Condition",
                                       source_url="fixture:mirror", source_revision="forged")


@pytest.mark.parametrize("include_non_tariff", [False, True])
@pytest.mark.parametrize("staging_only", [False, True])
@pytest.mark.parametrize("auto_approve", [False, True])
def test_archive_cannot_expand_prefix_or_write_technical_regulation(
        database, mirror, tmp_path, include_non_tariff, staging_only, auto_approve):
    with database() as db:
        db.add(Commodity(chapter_id=1, code="1234567890", description="Excluded fixture product"))
        db.commit()
    (tmp_path / "tr_ts_fixture.txt").write_text(
        "1234 Технический регламент ТР ТС 004/2011, только специальные товары, кроме исключений.",
        encoding="utf-8")
    before = snapshot(database, NonTariffMeasure, TrTsAct, VatPreference, SpecialDuty)
    result = service.sync_tamdoc_archive(str(tmp_path), staging_only=staging_only,
                                        include_non_tariff=include_non_tariff, auto_approve_pending=auto_approve)
    assert result["status"] == "OK" and result["docs_processed"] == 1
    assert result["non_tariff_created"] == result["tr_ts_acts_created"] == result["tr_ts_acts_updated"] == 0
    assert result["tr_ts_docs"] == 1 and result["active_ntm_written"] is False
    assert result["ntm_application_status"] == "manual_review_required"
    rows = service.list_tamdoc_candidates()
    assert len(rows) == 1 and rows[0]["status"] == "pending" and rows[0]["doc_type"] == "tr_ts"
    assert "curated_ntm_review_required" in rows[0]["error_message"]
    if auto_approve:
        assert result["batch_approve"]["blocked"] == 1 and result["batch_approve"]["approved"] == 0
    assert snapshot(database, NonTariffMeasure, TrTsAct, VatPreference, SpecialDuty) == before


def test_document_sync_retains_nonpayment_extraction_without_active_requirements(database, mirror, monkeypatch):
    async def fetch(client, url):
        if url == service.TAMDOC_INDEX_URL:
            return '<a href="/tamdoc/conditional/">Conditional fixture</a>'
        return "<article>1234567890 ветеринарный контроль только сырья, кроме переработанных товаров.</article>"

    monkeypatch.setattr(service, "_fetch_html", fetch)
    before = snapshot(database, NonTariffMeasure, TrTsAct)
    result = asyncio.run(service.sync_tamdoc_documents())
    assert result["status"] == "OK" and result["non_tariff_created"] == 0 and result["staged_ok"] == 1
    assert result["active_ntm_written"] is False
    row = service.list_tamdoc_candidates()[0]
    assert row["status"] == "pending" and row["measure_type_hint"] == "vet_control"
    assert "кроме переработанных" in row["excerpt"]
    assert snapshot(database, NonTariffMeasure, TrTsAct) == before
