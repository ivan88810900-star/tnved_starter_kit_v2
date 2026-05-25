"""Тесты продуктового блока sanctions/risk (MVP)."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.core import (
    CountryRisk,
    EuSanctionsList,
    GeoSpecialDuty,
    OfacSdnList,
    SanctionImportRisk,
)
from app.services.sanctions_risk_block import (
    build_sanctions_risk_block,
    load_sanctions_risk_fixture,
)


@pytest.fixture
def memory_sessionmaker(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine("sqlite:///:memory:")
    tables = [
        SanctionImportRisk.__table__,
        OfacSdnList.__table__,
        EuSanctionsList.__table__,
        CountryRisk.__table__,
        GeoSpecialDuty.__table__,
    ]
    Base.metadata.create_all(engine, tables=tables)
    sm = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr("app.db.SessionLocal", sm)
    monkeypatch.setattr("app.services.sanctions_risk_block.SessionLocal", sm)
    return sm


def test_missing_sources_yield_manual_review(memory_sessionmaker: sessionmaker) -> None:
    with memory_sessionmaker() as db:
        block = build_sanctions_risk_block(
            hs_code="8509400000",
            description="Пылесос",
            country="CN",
            db=db,
        )
    assert block.overall_severity == "manual_review_required"
    assert block.status == "MANUAL_REVIEW"
    assert block.coverage_complete is False
    assert not block.signals
    assert block.empty_message
    assert any("не настроены" in w.lower() or "ручная" in w.lower() for w in block.warnings)


def test_clear_no_match_with_fixture_coverage(memory_sessionmaker: sessionmaker) -> None:
    with memory_sessionmaker() as db:
        load_sanctions_risk_fixture(db)
        block = build_sanctions_risk_block(
            hs_code="8509400000",
            description="Пылесос бытовой",
            country="CN",
            db=db,
        )
    assert block.coverage_complete is True
    assert block.overall_severity in {"clear", "low"}
    assert block.status in {"OK", "WARNING"}
    assert not block.signals


def test_positive_hs_sanction_match(memory_sessionmaker: sessionmaker) -> None:
    with memory_sessionmaker() as db:
        load_sanctions_risk_fixture(db)
        block = build_sanctions_risk_block(
            hs_code="8517120000",
            description="Смартфон",
            country="CN",
            db=db,
        )
    assert block.signals
    assert block.overall_severity in {"medium", "high"}
    assert any(s.category == "hs_sanctions" for s in block.signals)
    assert any(s.source == "sanction_import_risks" for s in block.signals)
    assert all(s.source_label for s in block.signals)


def test_positive_embargo_match(memory_sessionmaker: sessionmaker) -> None:
    with memory_sessionmaker() as db:
        load_sanctions_risk_fixture(db)
        block = build_sanctions_risk_block(
            hs_code="0406100000",
            description="Сыр",
            country="IT",
            db=db,
        )
    assert any(s.category == "embargo" for s in block.signals)
    assert block.overall_severity == "high"
    assert block.status == "CRITICAL"


def test_positive_counterparty_ofac_match(memory_sessionmaker: sessionmaker) -> None:
    with memory_sessionmaker() as db:
        load_sanctions_risk_fixture(db)
        block = build_sanctions_risk_block(
            hs_code="8509400000",
            description="Пылесос",
            country="CN",
            counterparty_name="FIXTURE SANCTIONED ENTITY LLC",
            db=db,
        )
    assert any(s.category == "counterparty_ofac" for s in block.signals)
    assert block.overall_severity == "high"


def test_stale_partial_source_not_presented_as_clear(memory_sessionmaker: sessionmaker) -> None:
    """Только один источник без полного покрытия — не «clear»."""
    with memory_sessionmaker() as db:
        db.add(
            SanctionImportRisk(
                hs_code_prefix="8517",
                jurisdiction="EU",
                risk_level="risk",
                description="partial only",
            )
        )
        db.commit()
        block = build_sanctions_risk_block(
            hs_code="9999999999",
            description="Тест",
            country="CN",
            db=db,
        )
    assert block.overall_severity == "manual_review_required"
    assert block.coverage_complete is False


def test_risk_api_endpoint(memory_sessionmaker: sessionmaker) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from app.main import app
    from app.security import require_authenticated_user

    app.dependency_overrides[require_authenticated_user] = lambda: {"sub": "test"}
    client = TestClient(app)
    with memory_sessionmaker() as db:
        load_sanctions_risk_fixture(db)
        r = client.post(
            "/api/risk/check",
            json={
                "hs_code": "8517120000",
                "description": "Смартфон",
                "country": "CN",
            },
        )
    app.dependency_overrides.clear()
    assert r.status_code == 200
    body = r.json()
    assert body["overall_severity"] in {"medium", "high", "manual_review_required", "low", "clear"}
    assert "signals" in body
    assert "source_coverage" in body
    assert body.get("disclaimer")
