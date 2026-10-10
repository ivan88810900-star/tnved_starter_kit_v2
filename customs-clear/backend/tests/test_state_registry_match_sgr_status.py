from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.core import SgrCertificate
from app.services.state_registry_match import (
    SGR_RECOMMENDATION_FUZZY,
    classify_sgr_registry_status,
    lookup_sgr_registry,
)


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    SgrCertificate.__table__.create(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("Действует", "active"),
        ("ACTIVE", "active"),
        ("Зарегистрировано", "active"),
        ("Аннулировано", "inactive"),
        ("Недействительно", "inactive"),
        ("Не действует", "inactive"),
        ("Не зарегистрировано", "inactive"),
        ("Приостановлено", "inactive"),
        ("revoked", "inactive"),
        ("not active", "inactive"),
        ("not valid", "inactive"),
        ("not registered", "inactive"),
        ("invalid", "unverified"),
        ("unregistered", "unverified"),
        ("", "unverified"),
        ("сведения требуют уточнения", "unverified"),
    ],
)
def test_sgr_status_classifier_is_fail_closed(status: str, expected: str) -> None:
    assert classify_sgr_registry_status(status) == expected


def _lookup(session: Session) -> dict[str, str]:
    return lookup_sgr_registry(
        session,
        {"name_ru": "cream moisturizer", "manufacturer": "Maker"},
        {"manufacturer": "Maker"},
        hs_code="3304990000",
    )


def test_revoked_fuzzy_match_is_not_described_as_current(session: Session) -> None:
    session.add(
        SgrCertificate(
            sgr_number="REV-1",
            product_name="cream moisturizer",
            manufacturer="Maker",
            brand="Other",
            status="Аннулировано",
        )
    )
    session.commit()

    result = _lookup(session)

    assert result["document_number"] == "REV-1"
    assert result["status"] == "Найдено совпадение, статус требует проверки"
    assert "не подтверждает действие документа" in result["recommendation"]
    assert "действующее СГР" not in result["recommendation"]


def test_unknown_status_match_requires_review(session: Session) -> None:
    session.add(
        SgrCertificate(
            sgr_number="UNKNOWN-1",
            product_name="cream moisturizer",
            manufacturer="Maker",
            brand="Other",
            status="",
        )
    )
    session.commit()

    result = _lookup(session)

    assert result["status"] == "Найдено совпадение, статус требует проверки"
    assert "статус «не указан»" in result["recommendation"]


def test_active_fuzzy_match_keeps_existing_advisory(session: Session) -> None:
    session.add(
        SgrCertificate(
            sgr_number="ACTIVE-1",
            product_name="cream moisturizer",
            manufacturer="Maker",
            brand="Other",
            status="Действует",
        )
    )
    session.commit()

    result = _lookup(session)

    assert result["status"] == "Найдено по бренду/составу"
    assert result["recommendation"] == SGR_RECOMMENDATION_FUZZY
