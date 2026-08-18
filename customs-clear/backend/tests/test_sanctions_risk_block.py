"""Тесты продуктового блока sanctions/risk (MVP)."""

from __future__ import annotations

from pathlib import Path

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
    monkeypatch.setattr(
        "app.services.sanctions_risk_block.canonical_anchor_for_hs",
        lambda _hs: None,
    )
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
    scope = {item.code: item for item in block.screening_scope}
    assert scope["hs_code"].status == "checked"
    assert scope["country"].status == "checked"
    assert scope["counterparty"].status == "not_checked"


def test_no_match_with_fixture_coverage_stays_manual_review(memory_sessionmaker: sessionmaker) -> None:
    with memory_sessionmaker() as db:
        load_sanctions_risk_fixture(db)
        block = build_sanctions_risk_block(
            hs_code="8509400000",
            description="Пылесос бытовой",
            country="CN",
            db=db,
        )
    assert block.coverage_complete is True
    assert block.overall_severity == "manual_review_required"
    assert block.status == "MANUAL_REVIEW"
    assert not block.signals
    assert block.empty_message
    assert any("manual-review" in w.lower() or "seed" in w.lower() for w in block.warnings)


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
    ofac = next(s for s in block.signals if s.category == "counterparty_ofac")
    assert ofac.matched_entity == "FIXTURE SANCTIONED ENTITY LLC"
    assert ofac.match_method == "name_substring"
    assert ofac.source_url == "https://ofac.treasury.gov/specially-designated-nationals-list-sdn-list"
    assert len([s for s in block.signals if s.category == "counterparty_ofac"]) == 1


def test_export_scope_screens_end_user_but_never_reuses_import_country_or_hs_rules(
    memory_sessionmaker: sessionmaker,
) -> None:
    with memory_sessionmaker() as db:
        load_sanctions_risk_fixture(db)
        block = build_sanctions_risk_block(
            hs_code="0406100000",
            description="Сыр на вывоз",
            country="RU",
            destination_country="IT",
            counterparty_name="FIXTURE SANCTIONED ENTITY LLC",
            movement_direction="export",
            db=db,
        )

    assert any(signal.category == "counterparty_ofac" for signal in block.signals)
    assert not any(signal.category in {"embargo", "hs_sanctions"} for signal in block.signals)
    assert block.movement_direction == "export"
    assert block.coverage_complete is False
    scope = {item.code: item for item in block.screening_scope}
    assert scope["hs_code"].status == "not_checked"
    assert scope["country"].label == "Страна назначения"
    assert scope["country"].value == "IT"
    assert scope["country"].status == "not_checked"
    assert scope["counterparty"].status == "checked"


def test_risk_block_carries_canonical_anchor_and_typed_evidence(
    memory_sessionmaker: sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    anchor = {
        "stable_id": "node-0123456789abcdef01234567",
        "snapshot_id": "snap-v2-0123456789abcdef0123456789abcdef",
        "code": "0406100000",
        "node_type": "commodity",
    }
    monkeypatch.setattr(
        "app.services.sanctions_risk_block.canonical_anchor_for_hs",
        lambda _hs: anchor,
    )
    with memory_sessionmaker() as db:
        load_sanctions_risk_fixture(db)
        block = build_sanctions_risk_block(
            hs_code="0406100000",
            description="Сыр",
            country="IT",
            db=db,
        )

    embargo = next(s for s in block.signals if s.category == "embargo")
    assert embargo.matched_hs_prefix == "0406"
    assert embargo.matched_country == "IT"
    assert embargo.match_method == "country_hs_prefix"
    assert block.canonical_anchor is not None
    assert block.canonical_anchor.model_dump() == anchor
    assert all(row.known_gaps for row in block.source_coverage)


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


def test_product_details_uses_interactive_risk_checker_without_hardcoded_country() -> None:
    product_details = (
        Path(__file__).resolve().parents[2]
        / "frontend/src/components/tnved/ProductDetails.tsx"
    )
    risk_checker = (
        Path(__file__).resolve().parents[2]
        / "frontend/src/components/nonTariff/SmartRiskCheckBlock.tsx"
    )
    details_source = product_details.read_text(encoding="utf-8")
    checker_source = risk_checker.read_text(encoding="utf-8")
    assert "<SmartRiskCheckBlock" in details_source
    assert "['risks', 'Риски']" in details_source
    assert "country: 'CN'" not in checker_source
    assert 'country: "CN"' not in checker_source


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
    assert "screening_scope" in body
    assert "canonical_anchor" in body
    assert body.get("disclaimer")


def test_public_risk_endpoints_forward_typed_export_direction(
    memory_sessionmaker: sessionmaker,
) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from app.main import app
    from app.security import require_authenticated_user

    payload = {
        "hs_code": "0406100000",
        "description": "Сыр на вывоз",
        "country": "IT",
        "destination_country": "IT",
        "counterparty_name": "FOREIGN CUSTOMER",
        "movement_direction": "export",
    }
    app.dependency_overrides[require_authenticated_user] = lambda: {"sub": "test"}
    client = TestClient(app)
    try:
        with memory_sessionmaker() as db:
            load_sanctions_risk_fixture(db)
        single = client.post("/api/risk/check", json=payload)
        batch = client.post(
            "/api/risk/check-batch",
            json={"items": [payload]},
        )
        alias = client.post(
            "/api/risk/block",
            json={"items": [payload]},
        )
        product = client.post(
            "/api/non_tariff/risk-block",
            json={"items": [payload]},
        )
        invalid = client.post(
            "/api/risk/check",
            json={**payload, "movement_direction": "sideways"},
        )
    finally:
        app.dependency_overrides.clear()

    assert single.status_code == 200
    assert batch.status_code == 200
    assert alias.status_code == 200
    assert product.status_code == 200
    assert invalid.status_code == 422
    blocks = [
        single.json(),
        batch.json()["items"][0],
        alias.json()["items"][0],
        product.json()["items"][0]["risk_block"],
    ]
    for block in blocks:
        assert block["movement_direction"] == "export"
        assert not any(
            signal["category"] in {"embargo", "hs_sanctions"}
            for signal in block["signals"]
        )
        scope = {item["code"]: item for item in block["screening_scope"]}
        assert scope["hs_code"]["status"] == "not_checked"
        assert scope["country"]["label"] == "Страна назначения"
