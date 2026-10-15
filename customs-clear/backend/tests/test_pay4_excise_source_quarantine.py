"""PAY-4: quarantine the 2025 excise schedule from 2026 calculations."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.core import HsRate
from app.models.tnved import Commodity, HsDutyRule, SpecialDuty, VatPreference
from app.services.excise_ingestion import (
    _load_bundle_payload,
    run_excise_apply,
    run_excise_dry_run,
)
from app.services.payment_engine import compute_payments
from app.services.payment_revision_utils import (
    is_official_excise_ingestion_revision,
    is_rejected_excise_revision,
)


BACKEND_ROOT = Path(__file__).resolve().parents[1]
BUNDLE_REL = "data/raw_normative/eec_excise.json"
BUNDLE_PATH = BACKEND_ROOT / BUNDLE_REL
REJECTED_REVISION = "excise:2026-06-18"


@pytest.fixture()
def isolated_session(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        bind=engine,
        tables=[
            Commodity.__table__,
            HsDutyRule.__table__,
            HsRate.__table__,
            SpecialDuty.__table__,
            VatPreference.__table__,
        ],
    )
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    for target in (
        "app.services.excise_ingestion.SessionLocal",
        "app.services.payment_engine.SessionLocal",
        "app.services.normative_store.SessionLocal",
        "app.services.rate_display.SessionLocal",
    ):
        monkeypatch.setattr(target, factory)
    monkeypatch.setattr("app.services.excise_ingestion._BACKEND_ROOT", BACKEND_ROOT)
    monkeypatch.setattr("app.services.payment_engine.get_country_risk_by_iso", lambda _country: None)
    monkeypatch.setattr("app.services.payment_engine.find_geo_embargo_match", lambda *a, **k: None)
    monkeypatch.setattr("app.services.payment_engine.find_geo_duty_override_row", lambda *a, **k: None)
    monkeypatch.setattr("app.services.payment_engine.get_tariff_preference", lambda _country: None)
    monkeypatch.setattr("app.services.payment_engine.get_recycling_fee", lambda *a, **k: [])
    monkeypatch.setattr(
        "app.services.payment_engine.get_integrated_data_stats",
        lambda: {"hs_rates_count": 1},
    )
    monkeypatch.setattr("app.services.payment_engine.get_tnved_context_for_hs", lambda _code: {})
    try:
        yield factory
    finally:
        engine.dispose()


def _seed_excise(factory, *, revision: str = REJECTED_REVISION, value: float = 643.0) -> None:
    with factory() as db:
        db.add(
            HsRate(
                hs_code="2207100000",
                hs_prefix="2207100000",
                duty_rate="0%",
                vat_import_rate=22.0,
                excise_type="fixed",
                excise_value=value,
                excise_basis="НК РФ Ст. 193 — этиловый спирт",
                source_revision="ett:2026-06-18",
                source_url="https://eec.eaeunion.org/",
                excise_source_code="EEC_EXCISE",
                excise_source_revision=revision,
                excise_source_url="https://www.nalog.gov.ru/rn77/taxation/taxes/excise/",
            )
        )
        db.commit()


def test_tracked_bundle_is_quarantined_before_any_apply(isolated_session) -> None:
    payload, parser = _load_bundle_payload(BUNDLE_REL)
    assert payload is not None
    assert parser["status"] == "manual_review_required"
    assert parser["reason"] == "source_verification_rejected_obsolete_effective_period"

    dry_run = run_excise_dry_run(rel_path=BUNDLE_REL)
    apply = run_excise_apply(rel_path=BUNDLE_REL)
    assert dry_run["status"] == "manual_review_required"
    assert apply["status"] == "manual_review_required"
    assert apply["db_mutated"] is False
    with isolated_session() as db:
        assert db.query(HsRate).count() == 0


def test_bundle_retains_primary_source_mismatch_evidence() -> None:
    payload = json.loads(BUNDLE_PATH.read_text(encoding="utf-8"))
    assert payload["effective_to"] == "2025-12-31"
    assert payload["verification_status"] == "rejected_obsolete_effective_period"
    evidence = payload["verification_evidence"]
    assert len(evidence) == 1
    assert "643" in evidence[0]["bundle_example"]
    assert "824" in evidence[0]["current_rule"]
    assert evidence[0]["official_act"] == "Federal Law No. 425-FZ of 2025-11-28"
    assert evidence[0]["official_url"].startswith("https://www.nalog.gov.ru/")


def test_rejection_is_bounded_to_the_disproven_revision() -> None:
    assert is_rejected_excise_revision(REJECTED_REVISION)
    assert not is_official_excise_ingestion_revision(REJECTED_REVISION)
    assert is_official_excise_ingestion_revision("excise:2026-10-15")


def test_persisted_rejected_excise_withholds_affected_amounts(isolated_session) -> None:
    _seed_excise(isolated_session)
    result = compute_payments(
        {"hs_code": "2207100000", "customs_value": 100_000.0, "quantity": 2.0}
    )

    assert result["status"] == "MANUAL_REVIEW_REQUIRED"
    assert result["breakdown"]["excise"] is None
    assert result["breakdown"]["vat_base"] is None
    assert result["breakdown"]["vat"] is None
    assert result["breakdown"]["total_payable"] is None
    assert result["breakdown"]["total_partial"] is not None
    assert result["data_quality"]["excise_source_rejected"] is True
    assert result["data_quality"]["manual_review_required"] is True
    assert "отозванной revision" in result["breakdown"]["excise_reason"]


def test_manual_amount_and_later_verified_revision_are_not_blocked(isolated_session) -> None:
    _seed_excise(isolated_session)
    manual = compute_payments(
        {
            "hs_code": "2207100000",
            "customs_value": 100_000.0,
            "quantity": 2.0,
            "excise": 1_648.0,
        }
    )
    assert manual["status"] == "OK"
    assert manual["breakdown"]["excise"] == 1_648.0
    assert manual["breakdown"]["total_payable"] is not None

    with isolated_session() as db:
        row = db.query(HsRate).filter(HsRate.hs_code == "2207100000").one()
        row.excise_source_revision = "excise:2026-10-15"
        row.excise_value = 824.0
        db.commit()
    verified = compute_payments(
        {"hs_code": "2207100000", "customs_value": 100_000.0, "quantity": 2.0}
    )
    assert verified["status"] == "OK"
    assert verified["breakdown"]["excise"] == 1_648.0
    assert verified["breakdown"]["vat"] is not None
    assert verified["breakdown"]["total_payable"] is not None
