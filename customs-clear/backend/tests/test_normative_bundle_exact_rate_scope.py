from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.core import HsRate, SourceStatus, SyncLog
from app.services import normative_store
from app.services.normative_bundle import _import_normative_bundle_dict


def test_isolated_fixture_rate_cannot_leak_to_missing_sibling(monkeypatch) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(
        bind=engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )
    Base.metadata.create_all(
        bind=engine,
        tables=[HsRate.__table__, SourceStatus.__table__, SyncLog.__table__],
    )
    monkeypatch.setattr(normative_store, "SessionLocal", testing_session)

    try:
        result = _import_normative_bundle_dict(
            {
                "format": "customs_clear_normative_bundle",
                "revision": "ett:scope-regression",
                "rates": [
                    {
                        "hs_code": "8471300000",
                        # A legacy producer may still send this unsafe broad
                        # value; an exact leaf must override it.
                        "hs_prefix": "8471",
                        "duty_rate": "5%",
                        "source_revision": "ett:scope-regression",
                        "source_url": "https://eec.eaeunion.org/comission/department/catr/ett/",
                    }
                ],
            },
            filename="exact-rate-scope.json",
        )

        assert result["status"] == "OK"
        with testing_session() as database:
            stored = (
                database.query(HsRate)
                .filter(HsRate.hs_code == "8471300000")
                .one()
            )
            assert stored.hs_prefix == "8471300000"

        exact, exact_match_length = normative_store.find_rate_for_hs("8471300000")
        assert exact is not None
        assert exact.duty_rate == "5%"
        assert exact_match_length == 10

        sibling, sibling_match_length = normative_store.find_rate_for_hs(
            "8471999999"
        )
        assert sibling is None
        assert sibling_match_length == 0
    finally:
        engine.dispose()
