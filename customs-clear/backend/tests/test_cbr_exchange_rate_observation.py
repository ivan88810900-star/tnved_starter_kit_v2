from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.core import ExchangeRate, SourceStatus
from app.services.exchange_rates import (
    CBRF_SOURCE_CODE,
    CBRRateObservation,
    _cbr_stored_rate_row_observation,
    get_cbr_rate_observation,
)


def _memory_sessionmaker():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        bind=engine,
        tables=[ExchangeRate.__table__, SourceStatus.__table__],
    )
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


def test_observation_preserves_row_identity_and_separates_global_evidence() -> None:
    sessions = _memory_sessionmaker()
    observed_at = datetime(2026, 9, 14, 10, 30, 0)
    digest = "a" * 64
    with sessions() as db:
        eur = ExchangeRate(
            currency_code="EUR", rate=101.25, nominal=1.0, updated_at=observed_at
        )
        usd = ExchangeRate(
            currency_code="USD", rate=92.5, nominal=1.0, updated_at=observed_at
        )
        db.add_all([usd, eur])
        db.flush()
        eur_id, usd_id = eur.id, usd.id
        db.add(
            SourceStatus(
                source_code=CBRF_SOURCE_CODE,
                source_name="CBR daily XML",
                source_url="https://www.cbr.ru/scripts/XML_daily.asp",
                revision=f"cbrf:2026-09-14:sha256:{digest}",
                synced_at=observed_at,
                is_stale=False,
                note="global snapshot evidence",
            )
        )
        db.commit()

    with patch("app.services.exchange_rates.SessionLocal", sessions):
        observation = get_cbr_rate_observation()

    assert isinstance(observation, CBRRateObservation)
    assert [(row.row_id, row.currency_code) for row in observation.rows] == [
        (eur_id, "EUR"),
        (usd_id, "USD"),
    ]
    assert observation.rows[0].rub_per_unit == 101.25
    assert observation.rows[0].nominal == 1.0
    assert observation.rows[0].updated_at == observed_at
    assert observation.rows[0].stored_value_status == "candidate"
    assert observation.rows[0].invalid_reasons == ()

    evidence = observation.global_source_evidence
    assert len(evidence) == 1
    assert evidence[0].source_revision == f"cbrf:2026-09-14:sha256:{digest}"
    assert evidence[0].source_date.isoformat() == "2026-09-14"
    assert evidence[0].artifact_sha256 == digest
    assert evidence[0].evidence_scope == "global_source_status"
    assert evidence[0].canonical_source_identity is True

    # Even an equal storage/sync timestamp and a digest-bearing global revision
    # are not an exact foreign key from either rate row to the artifact.
    assert evidence[0].exact_row_binding_verified is False
    assert observation.binding_status == "unverified_no_exact_row_artifact_binding"
    assert observation.exact_row_artifact_binding_verified is False
    assert observation.payment_admission_granted is False


@pytest.mark.parametrize(
    ("rate", "nominal", "expected_reason"),
    [
        (-1.0, 1.0, "rate_not_positive"),
        (0.0, 1.0, "rate_not_positive"),
        (float("inf"), 1.0, "rate_not_finite"),
        (float("nan"), 1.0, "rate_not_finite"),
        (92.5, -1.0, "nominal_not_positive"),
        (92.5, 0.0, "nominal_not_positive"),
        (92.5, float("inf"), "nominal_not_finite"),
        (92.5, float("nan"), "nominal_not_finite"),
    ],
)
def test_invalid_stored_numbers_are_explicit_and_not_emitted_as_candidates(
    rate: float,
    nominal: float,
    expected_reason: str,
) -> None:
    row = SimpleNamespace(
        id=17,
        currency_code="USD",
        rate=rate,
        nominal=nominal,
        updated_at=datetime(2026, 9, 14, 10, 30, 0),
    )

    observation = _cbr_stored_rate_row_observation(row)

    assert observation.row_id == 17
    assert observation.currency_code == "USD"
    assert observation.stored_value_status == "invalid"
    assert expected_reason in observation.invalid_reasons
    assert observation.rub_per_unit is None
    assert observation.nominal is None


def test_database_observation_marks_invalid_rows_and_withholds_their_values() -> None:
    sessions = _memory_sessionmaker()
    with sessions() as db:
        db.add_all(
            [
                ExchangeRate(currency_code="USD", rate=-1.0, nominal=1.0),
                ExchangeRate(currency_code="EUR", rate=float("inf"), nominal=1.0),
                ExchangeRate(currency_code="CNY", rate=12.5, nominal=0.0),
            ]
        )
        db.commit()

    with patch("app.services.exchange_rates.SessionLocal", sessions):
        observation = get_cbr_rate_observation()

    rows = {row.currency_code: row for row in observation.rows}
    assert rows["USD"].invalid_reasons == ("rate_not_positive",)
    assert rows["EUR"].invalid_reasons == ("rate_not_finite",)
    assert rows["CNY"].invalid_reasons == ("nominal_not_positive",)
    for row in rows.values():
        assert row.stored_value_status == "invalid"
        assert row.rub_per_unit is None
        assert row.nominal is None


def test_observation_is_read_only_and_never_adds_fallback_rows() -> None:
    sessions = _memory_sessionmaker()
    with patch("app.services.exchange_rates.SessionLocal", sessions):
        observation = get_cbr_rate_observation()

    assert observation.rows == ()
    assert observation.global_source_evidence == ()
    with sessions() as db:
        assert db.query(ExchangeRate).count() == 0
        assert db.query(SourceStatus).count() == 0


def test_unparseable_global_revision_is_preserved_but_not_promoted() -> None:
    sessions = _memory_sessionmaker()
    with sessions() as db:
        db.add(
            SourceStatus(
                source_code=CBRF_SOURCE_CODE,
                source_name="failed CBR refresh",
                source_url="https://www.cbr.ru/scripts/XML_daily.asp",
                revision="fallback",
                synced_at=datetime(2026, 9, 14, 11, 0, 0),
                is_stale=True,
                note="network unavailable",
            )
        )
        db.add(
            SourceStatus(
                source_code="UNRELATED",
                source_name="other source",
                source_url="https://example.invalid/",
                revision="other:2026-09-14",
                synced_at=datetime(2026, 9, 14, 11, 0, 0),
                is_stale=False,
                note="not CBR evidence",
            )
        )
        db.commit()

    with patch("app.services.exchange_rates.SessionLocal", sessions):
        observation = get_cbr_rate_observation()

    assert len(observation.global_source_evidence) == 1
    evidence = observation.global_source_evidence[0]
    assert evidence.source_revision == "fallback"
    assert evidence.source_date is None
    assert evidence.artifact_sha256 is None
    assert evidence.is_stale is True
    assert evidence.canonical_source_identity is True
    assert observation.payment_admission_granted is False


@pytest.mark.parametrize(
    ("source_code", "source_url"),
    [
        ("CBR", "https://www.cbr.ru/scripts/XML_daily.asp"),
        (CBRF_SOURCE_CODE, "https://www.cbr.ru/"),
        ("CBR", "https://mirror.invalid/XML_daily.asp"),
    ],
)
def test_noncanonical_source_identity_keeps_raw_revision_unparsed(
    source_code: str,
    source_url: str,
) -> None:
    sessions = _memory_sessionmaker()
    digest = "b" * 64
    revision = f"cbrf:2026-09-14:sha256:{digest}"
    with sessions() as db:
        db.add(
            SourceStatus(
                source_code=source_code,
                source_name="unverified CBR identity",
                source_url=source_url,
                revision=revision,
                synced_at=datetime(2026, 9, 14, 11, 0, 0),
                is_stale=False,
                note="raw metadata only",
            )
        )
        db.commit()

    with patch("app.services.exchange_rates.SessionLocal", sessions):
        observation = get_cbr_rate_observation()

    assert len(observation.global_source_evidence) == 1
    evidence = observation.global_source_evidence[0]
    assert evidence.source_code == source_code
    assert evidence.source_url == source_url
    assert evidence.source_revision == revision
    assert evidence.canonical_source_identity is False
    assert evidence.source_date is None
    assert evidence.artifact_sha256 is None
    assert evidence.exact_row_binding_verified is False


def test_observation_contract_is_immutable() -> None:
    observation = CBRRateObservation(rows=(), global_source_evidence=())

    with pytest.raises(FrozenInstanceError):
        observation.payment_admission_granted = True  # type: ignore[misc]
