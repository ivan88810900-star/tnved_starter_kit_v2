"""GET /api/v1/tnved/{code} — поле measures для фронта frontend/web."""

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models.core import HsRate
from app.services.normative_store import init_db

client = TestClient(app)

MEASURES_CASES: dict[str, list[str]] = {
    "5208211000": ["ДС"],
    "6101100000": ["ДС"],
    "6401100000": ["ДС"],
    "9503001000": ["СС"],
    "3304100000": ["ДС"],
    "8517130000": ["ДС"],
    "8401100000": [],
}


@pytest.fixture(scope="module", autouse=True)
def _exact_rate_evidence_for_measure_cases() -> None:
    """Give the endpoint exact persisted evidence that every fixture code exists.

    The production endpoint deliberately rejects an arbitrary 10-digit code
    when neither a commodity nor an exact tariff row exists.  This test owns
    only the tariff-existence fixtures it creates and leaves the measure
    expectations themselves unchanged.
    """
    init_db()
    revision = "test-tnved-measures-api"
    with SessionLocal() as db:
        existing = {
            row[0]
            for row in db.query(HsRate.hs_code)
            .filter(HsRate.hs_code.in_(MEASURES_CASES))
            .all()
        }
        inserted = [
            HsRate(
                hs_code=code,
                hs_prefix=code,
                duty_rate="0",
                source_revision=revision,
            )
            for code in MEASURES_CASES
            if code not in existing
        ]
        db.add_all(inserted)
        db.flush()
        inserted_ids = [row.id for row in inserted]
        db.commit()
    try:
        yield
    finally:
        if inserted_ids:
            with SessionLocal() as db:
                db.query(HsRate).filter(HsRate.id.in_(inserted_ids)).delete(
                    synchronize_session=False
                )
                db.commit()


def test_commodity_measures_regression() -> None:
    for code, expected in MEASURES_CASES.items():
        r = client.get(f"/api/v1/tnved/{code}")
        assert r.status_code == 200, f"{code}: {r.status_code}"
        measures = [m.get("type", "") for m in r.json().get("measures", [])]
        if expected == []:
            assert measures == [], f"{code}: expected empty, got {measures}"
        else:
            assert all(e in measures for e in expected), f"{code}: expected {expected}, got {measures}"
            assert len(measures) > 0
