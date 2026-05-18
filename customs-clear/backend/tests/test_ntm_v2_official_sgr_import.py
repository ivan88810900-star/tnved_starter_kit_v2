"""Official SGR contour: import, applicability, diagnostics."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.core import NonTariffRule
from app.models.ntm_v2 import NtmApplicabilityRuleV2, NtmMeasureV2
from app.services.ntm_v2_legacy_rules_import import (
    get_advisory_legacy_rule_requirements_v2,
    import_legacy_non_tariff_rules_to_ntm_v2,
)
from app.services.ntm_v2_official_sgr_diagnostics import compare_official_sgr_rules_vs_legacy_sgr
from app.services.ntm_v2_official_sgr_import import (
    OFFICIAL_SGR_SOURCE_KIND,
    evaluate_official_sgr_for_position,
    import_official_sgr_rules_to_ntm_v2,
    load_official_sgr_payload,
    official_sgr_rule_matches_position,
)


@pytest.fixture
def memory_sessionmaker(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            NonTariffRule.__table__,
            NtmMeasureV2.__table__,
            NtmApplicabilityRuleV2.__table__,
        ],
    )
    sm = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr("app.db.SessionLocal", sm)
    monkeypatch.setattr("app.services.normative_store.SessionLocal", sm)
    return sm


@pytest.fixture
def official_sgr_imported(memory_sessionmaker: sessionmaker) -> dict:
    payload = load_official_sgr_payload()
    return import_official_sgr_rules_to_ntm_v2(payload)


def test_import_creates_measure_and_rules(official_sgr_imported: dict) -> None:
    assert official_sgr_imported["rules_created"] >= 30
    assert official_sgr_imported["measures_created"] == 1
    assert official_sgr_imported["source_kind"] == OFFICIAL_SGR_SOURCE_KIND


def test_import_idempotent(official_sgr_imported: dict, memory_sessionmaker: sessionmaker) -> None:
    r2 = import_official_sgr_rules_to_ntm_v2()
    assert r2["rules_created"] == 0
    assert r2["rules_updated"] >= official_sgr_imported["rules_created"]
    with memory_sessionmaker() as s:
        assert s.query(NtmMeasureV2).filter_by(source_kind=OFFICIAL_SGR_SOURCE_KIND).count() == 1


def test_applicability_preserved(memory_sessionmaker: sessionmaker, official_sgr_imported: dict) -> None:
    with memory_sessionmaker() as s:
        definite = (
            s.query(NtmApplicabilityRuleV2)
            .filter_by(source_kind=OFFICIAL_SGR_SOURCE_KIND, applicability="definite")
            .count()
        )
        possible = (
            s.query(NtmApplicabilityRuleV2)
            .filter_by(source_kind=OFFICIAL_SGR_SOURCE_KIND, applicability="possible")
            .count()
        )
        clarify = (
            s.query(NtmApplicabilityRuleV2)
            .filter_by(source_kind=OFFICIAL_SGR_SOURCE_KIND, applicability="needs_clarification")
            .count()
        )
    assert definite >= 2
    assert possible >= 12
    assert clarify >= 6


def test_toy_9503007500_no_definite_sgr(official_sgr_imported: dict) -> None:
    ev = evaluate_official_sgr_for_position("9503007500", "Кукла пластиковая")
    assert ev["has_definite_sgr"] is False
    assert not any(r["applicability"] == "definite" for r in ev["matched_rules"])


def test_adult_cosmetics_3304990000_not_definite_without_child_keywords(
    official_sgr_imported: dict,
) -> None:
    ev = evaluate_official_sgr_for_position("3304990000", "Косметика для взрослых")
    assert ev["has_definite_sgr"] is False


def test_child_cosmetics_3304_definite_with_keywords(official_sgr_imported: dict) -> None:
    ev = evaluate_official_sgr_for_position("3304990000", "Детский крем для лица")
    assert ev["has_definite_sgr"] is True


def test_definite_disinfectant_3808(official_sgr_imported: dict) -> None:
    ev = evaluate_official_sgr_for_position("3808990000", "Дезинфицирующее средство")
    assert ev["has_definite_sgr"] is True
    assert ev["definite_rules"][0]["hs_prefix"] == "3808"


def test_plain_drinking_water_no_sgr(official_sgr_imported: dict) -> None:
    ev = evaluate_official_sgr_for_position("2201900000", "Питьевая вода")
    assert ev["has_definite_sgr"] is False
    assert ev["has_advisory_sgr"] is False


def test_needs_clarification_mineral_water(official_sgr_imported: dict) -> None:
    ev = evaluate_official_sgr_for_position("2201900000", "минеральная вода лечебная")
    assert ev["has_definite_sgr"] is False
    assert any(r["applicability"] == "needs_clarification" for r in ev["matched_rules"])


def test_needs_clarification_bad_description(official_sgr_imported: dict) -> None:
    ev = evaluate_official_sgr_for_position("9999999999", "БАД витаминный комплекс")
    assert any(r["applicability"] == "needs_clarification" for r in ev["matched_rules"])


def test_diagnostics_toy_shows_legacy_extra_sgr(
    memory_sessionmaker: sessionmaker,
    official_sgr_imported: dict,
) -> None:
    from app.services.normative_store import SEED_NON_TARIFF_RULES

    with memory_sessionmaker() as s:
        for row in SEED_NON_TARIFF_RULES:
            s.add(NonTariffRule(**row))
        s.commit()
    import_legacy_non_tariff_rules_to_ntm_v2()

    cmp = compare_official_sgr_rules_vs_legacy_sgr("9503007500", "Кукла пластиковая")
    assert cmp["official_v2"]["has_definite_sgr"] is False
    assert cmp["legacy"]["rules"]["has_advisory_sgr"] is True
    assert len(cmp["legacy_extra_sgr"]["rules_advisory_sgr"]) >= 1


def test_diagnostics_adult_cosmetics_legacy_advisory_not_official_definite(
    memory_sessionmaker: sessionmaker,
    official_sgr_imported: dict,
) -> None:
    from app.services.normative_store import SEED_NON_TARIFF_RULES

    with memory_sessionmaker() as s:
        for row in SEED_NON_TARIFF_RULES:
            s.add(NonTariffRule(**row))
        s.commit()
    import_legacy_non_tariff_rules_to_ntm_v2()

    cmp = compare_official_sgr_rules_vs_legacy_sgr("3304990000", "Косметика для взрослых")
    assert cmp["official_v2"]["has_definite_sgr"] is False
    legacy_sgr = get_advisory_legacy_rule_requirements_v2("3304990000", "Косметика для взрослых")
    assert any(r.get("permit_type") == "СГР" for r in legacy_sgr)


def test_official_not_in_production_broker(
    memory_sessionmaker: sessionmaker,
    official_sgr_imported: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.services.non_tariff_service.get_full_ntm_requirements", lambda _h, _d="": [])
    monkeypatch.setattr("app.services.non_tariff_service.find_rules_for_code", lambda _h: [])
    monkeypatch.setattr("app.services.non_tariff_service.find_measures_for_code", lambda _h, **_: [])
    monkeypatch.setattr("app.services.non_tariff_service.find_measures_by_description", lambda _d, _h: [])
    monkeypatch.setattr("app.services.non_tariff_service.get_sensitive_override", lambda _h: None)
    monkeypatch.setattr("app.services.non_tariff_service.find_normative_notes_for_hs", lambda _h: [])
    monkeypatch.setattr("app.services.non_tariff_service.get_regulatory_documents_for_hs", lambda _h, **_: [])
    monkeypatch.setattr("app.services.non_tariff_service.lookup_tr_ts_acts_by_codes", lambda _c: [])

    from app.services.non_tariff_service import check_position_non_tariff

    res = asyncio.run(
        check_position_non_tariff(
            "3808990000",
            "Дезинфектант",
            "DE",
            [],
            skip_registry_verify=True,
            rules_enforcement_enabled=True,
        )
    )
    assert "СГР" not in res["required_permit_types"]
    assert "СГР" not in res["missing_permit_types"]
