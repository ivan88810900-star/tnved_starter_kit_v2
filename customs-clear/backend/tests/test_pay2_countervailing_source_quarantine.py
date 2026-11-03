"""PAY-2: fail closed for the disproven countervailing snapshot."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.tnved import SpecialDuty
from app.services.countervailing_ingestion import (
    _load_bundle_payload,
    run_countervailing_apply,
    run_countervailing_dry_run,
)
from app.services.payment_engine import _resolve_special_duties
from app.services.payment_revision_utils import (
    is_official_countervailing_ingestion_revision,
    is_rejected_countervailing_revision,
)


BACKEND_ROOT = Path(__file__).resolve().parents[1]
BUNDLE_REL = "data/raw_normative/eec_countervailing.json"
BUNDLE_PATH = BACKEND_ROOT / BUNDLE_REL
REJECTED_REVISION = "countervailing:2026-06-18"


@pytest.fixture()
def isolated_session(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine, tables=[SpecialDuty.__table__])
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    monkeypatch.setattr("app.services.payment_engine.SessionLocal", factory)
    monkeypatch.setattr("app.services.countervailing_ingestion.SessionLocal", factory)
    monkeypatch.setattr("app.services.countervailing_ingestion._BACKEND_ROOT", BACKEND_ROOT)
    try:
        yield factory
    finally:
        engine.dispose()


def test_tracked_bundle_is_quarantined_before_any_apply(isolated_session) -> None:
    payload, parser = _load_bundle_payload(BUNDLE_REL)
    assert payload is not None
    assert parser["status"] == "manual_review_required"
    assert parser["reason"] == "source_verification_rejected_source_mismatch"

    dry_run = run_countervailing_dry_run(rel_path=BUNDLE_REL)
    apply = run_countervailing_apply(rel_path=BUNDLE_REL)
    assert dry_run["status"] == "manual_review_required"
    assert apply["status"] == "manual_review_required"
    assert apply["db_mutated"] is False
    with isolated_session() as db:
        assert db.query(SpecialDuty).count() == 0


def test_bundle_keeps_primary_source_mismatch_evidence() -> None:
    payload = json.loads(BUNDLE_PATH.read_text(encoding="utf-8"))
    evidence = payload["verification_evidence"]
    assert payload["verification_status"] == "rejected_source_mismatch"
    assert len(evidence) == 2
    assert {item["claimed_act"] for item in evidence} == {
        "Решение Совета ЕЭК № 95 от 10.07.2018",
        "Решение Коллегии ЕЭК № 164 от 17.12.2019",
    }
    assert all(item["official_url"] == "https://docs.eaeunion.org/documents/search/" for item in evidence)
    assert all(row["needs_verification"] is True for row in payload["measures"])


def test_rejected_revision_is_not_official_provenance() -> None:
    assert is_rejected_countervailing_revision(REJECTED_REVISION)
    assert not is_official_countervailing_ingestion_revision(REJECTED_REVISION)
    assert is_official_countervailing_ingestion_revision("countervailing:2026-10-15")


def test_persisted_rejected_row_is_visible_but_withheld(isolated_session) -> None:
    with isolated_session() as db:
        db.add(
            SpecialDuty(
                hs_code_prefix="4810",
                origin_country="CN",
                rate_percent=12.8,
                rate_specific=0.0,
                currency_code="USD",
                regulatory_act="Решение Совета ЕЭК № 95 от 10.07.2018",
                measure_type="countervailing",
                effective_from="2018-08-01",
                countervailing_source_code="EEC_COUNTERVAILING",
                countervailing_source_revision=REJECTED_REVISION,
                countervailing_source_url="https://eec.eaeunion.org/comission/department/catr/trade-protect/",
                needs_verification=False,
            )
        )
        db.commit()

    total, details = _resolve_special_duties(
        "4810000000", "CN", 100_000.0, 1.0, {"USD": 92.0}
    )
    assert total == 0.0
    assert len(details) == 1
    assert details[0]["amount"] is None
    assert details[0]["manual_review_required"] is True
    assert "отозван" in details[0]["warning"]

    no_country_total, no_country_details = _resolve_special_duties(
        "4810000000", None, 100_000.0, 1.0, {"USD": 92.0}
    )
    assert no_country_total == 0.0
    assert no_country_details[0]["manual_review_required"] is True
    assert no_country_details[0]["needs_verification"] is True
    assert "отозван" in no_country_details[0]["warning"]

    other_country_total, other_country_details = _resolve_special_duties(
        "4810000000", "TR", 100_000.0, 1.0, {"USD": 92.0}
    )
    assert other_country_total == 0.0
    assert other_country_details == []
