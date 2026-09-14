"""Legacy lookup storage contract, not a current legal country inventory.

Old assertions that BR/IN/TR must receive GSP reductions from a live database
encoded the bug. Eligibility regressions are in test_payment_preference_eligibility.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.tnved import CountryTariffPreference
from app.services import normative_store


@pytest.fixture
def legacy_lookup(monkeypatch):
    engine = create_engine("sqlite://")
    CountryTariffPreference.__table__.create(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as db:
        db.add_all([
            CountryTariffPreference(country_code="BR", preference_type="gsp",
                duty_coefficient=0.75, legal_ref="Historical fixture, not eligibility",
                effective_from="2009-11-27"),
            CountryTariffPreference(country_code="BY", preference_type="eaeu",
                duty_coefficient=0, legal_ref="Historical fixture, not goods status",
                effective_from="2015-01-01"),
        ])
        db.commit()
    monkeypatch.setattr(normative_store, "SessionLocal", sessions)
    yield normative_store.get_tariff_preference
    engine.dispose()


def test_lookup_preserves_legacy_candidate_without_asserting_eligibility(legacy_lookup):
    candidate = legacy_lookup("BR")
    assert candidate is not None
    assert candidate.preference_type == "gsp"
    assert candidate.duty_coefficient == 0.75
    assert candidate.effective_from == "2009-11-27"
    assert candidate.legal_ref == "Historical fixture, not eligibility"


def test_lookup_is_case_insensitive(legacy_lookup):
    assert legacy_lookup(" br ").country_code == "BR"


@pytest.mark.parametrize("country", [None, "", "X", "XX", "12"])
def test_unknown_or_invalid_lookup_has_no_inferred_preference(legacy_lookup, country):
    assert legacy_lookup(country) is None


def test_zero_candidate_is_retained_as_data_not_proof(legacy_lookup):
    assert legacy_lookup("BY").duty_coefficient == 0
