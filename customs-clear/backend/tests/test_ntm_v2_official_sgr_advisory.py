"""Official SGR → advisory_requirements (флаг ``NTM_V2_OFFICIAL_SGR_ADVISORY_ENABLED``)."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.core import NonTariffRule
from app.models.ntm_v2 import NtmApplicabilityRuleV2, NtmMeasureV2
from app.services.ntm_v2_legacy_rules_import import import_legacy_non_tariff_rules_to_ntm_v2
from app.services.ntm_v2_official_sgr_import import (
    OFFICIAL_SGR_SOURCE_KIND,
    OFFICIAL_SGR_SOURCE_LABEL,
    get_advisory_official_sgr_requirements_v2,
    import_official_sgr_rules_to_ntm_v2,
    load_official_sgr_payload,
    merge_advisory_legacy_and_official,
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
def minimal_ntm_patches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.non_tariff_service.get_full_ntm_requirements",
        lambda _hs, _d="": [],
    )
    monkeypatch.setattr("app.services.non_tariff_service.find_rules_for_code", lambda _hs: [])
    monkeypatch.setattr("app.services.non_tariff_service.find_measures_for_code", lambda _hs, **_: [])
    monkeypatch.setattr(
        "app.services.non_tariff_service.find_measures_by_description",
        lambda _d, _hs: [],
    )
    monkeypatch.setattr("app.services.non_tariff_service.get_sensitive_override", lambda _hs: None)
    monkeypatch.setattr("app.services.non_tariff_service.find_normative_notes_for_hs", lambda _hs: [])
    monkeypatch.setattr(
        "app.services.non_tariff_service.get_regulatory_documents_for_hs",
        lambda _hs, **_: [],
    )
    monkeypatch.setattr(
        "app.services.non_tariff_service.lookup_tr_ts_acts_by_codes",
        lambda _codes: [],
    )


@pytest.fixture
def official_and_legacy_imported(memory_sessionmaker: sessionmaker) -> None:
    from app.services.normative_store import SEED_NON_TARIFF_RULES

    with memory_sessionmaker() as s:
        for row in SEED_NON_TARIFF_RULES:
            s.add(NonTariffRule(**row))
        s.commit()
    import_legacy_non_tariff_rules_to_ntm_v2()
    import_official_sgr_rules_to_ntm_v2(load_official_sgr_payload())


async def _check(
    hs: str,
    desc: str,
    *,
    official_advisory: bool | None,
) -> dict:
    from app.services.non_tariff_service import check_position_non_tariff

    return await check_position_non_tariff(
        hs_code=hs,
        description=desc,
        country="DE",
        permits=[],
        skip_registry_verify=True,
        official_sgr_advisory_enabled=official_advisory,
    )


def test_official_advisory_flag_off_no_official_source(
    official_and_legacy_imported: None,
    minimal_ntm_patches: None,
) -> None:
    res = asyncio.run(_check("3808990000", "Дезинфектант", official_advisory=False))
    sources = {a.get("source") for a in res.get("advisory_requirements") or []}
    assert OFFICIAL_SGR_SOURCE_KIND not in sources


def test_official_advisory_flag_on_3808_definite_in_advisory(
    official_and_legacy_imported: None,
    minimal_ntm_patches: None,
) -> None:
    res = asyncio.run(_check("3808990000", "Дезинфицирующее средство", official_advisory=True))
    official = [a for a in res.get("advisory_requirements") or [] if a.get("source") == OFFICIAL_SGR_SOURCE_KIND]
    assert len(official) >= 1
    assert any(a.get("applicability") == "definite" and a.get("permit_type") == "СГР" for a in official)
    assert official[0].get("source_label") == OFFICIAL_SGR_SOURCE_LABEL
    assert all(a.get("used_for_missing_check") is False for a in official)
    assert "не активировано" in (official[0].get("reason") or "").lower()


def test_mineral_water_needs_clarification_in_advisory(
    official_and_legacy_imported: None,
    minimal_ntm_patches: None,
) -> None:
    res = asyncio.run(_check("2201900000", "минеральная вода лечебная", official_advisory=True))
    official = [a for a in res.get("advisory_requirements") or [] if a.get("source") == OFFICIAL_SGR_SOURCE_KIND]
    assert any(a.get("applicability") == "needs_clarification" for a in official)


def test_toy_no_official_advisory_legacy_may_remain(
    official_and_legacy_imported: None,
    minimal_ntm_patches: None,
) -> None:
    res = asyncio.run(_check("9503007500", "Кукла пластиковая", official_advisory=True))
    official = [a for a in res.get("advisory_requirements") or [] if a.get("source") == OFFICIAL_SGR_SOURCE_KIND]
    assert official == []
    legacy_sgr = [
        a
        for a in res.get("advisory_requirements") or []
        if a.get("permit_type") == "СГР" and a.get("source") != OFFICIAL_SGR_SOURCE_KIND
    ]
    assert len(legacy_sgr) >= 1


def test_adult_cosmetics_no_official_definite_legacy_sgr(
    official_and_legacy_imported: None,
    minimal_ntm_patches: None,
) -> None:
    res = asyncio.run(_check("3304990000", "Косметика для взрослых", official_advisory=True))
    official = [a for a in res.get("advisory_requirements") or [] if a.get("source") == OFFICIAL_SGR_SOURCE_KIND]
    assert not any(a.get("applicability") == "definite" for a in official)
    assert any(
        a.get("permit_type") == "СГР" and a.get("source") != OFFICIAL_SGR_SOURCE_KIND
        for a in res.get("advisory_requirements") or []
    )


def test_broker_and_status_unchanged_with_official_advisory(
    official_and_legacy_imported: None,
    minimal_ntm_patches: None,
) -> None:
    off = asyncio.run(_check("3808990000", "Дезинфектант", official_advisory=False))
    on = asyncio.run(_check("3808990000", "Дезинфектант", official_advisory=True))
    assert off["required_permit_types"] == on["required_permit_types"]
    assert off["missing_permit_types"] == on["missing_permit_types"]
    assert off["status"] == on["status"]
    assert "СГР" not in on["required_permit_types"]
    assert "СГР" not in on["missing_permit_types"]


def test_merge_official_first_suppresses_legacy_same_soft_key() -> None:
    legacy = [
        {
            "permit_type": "СГР",
            "tr_ts": None,
            "applicability": "possible",
            "source": "legacy_non_tariff_rules",
        }
    ]
    official = [
        {
            "permit_type": "СГР",
            "tr_ts": None,
            "applicability": "possible",
            "source": OFFICIAL_SGR_SOURCE_KIND,
        }
    ]
    merged = merge_advisory_legacy_and_official(legacy, official)
    assert len(merged) == 1
    assert merged[0]["source"] == OFFICIAL_SGR_SOURCE_KIND


def test_merge_keeps_legacy_when_applicability_differs() -> None:
    legacy = [{"permit_type": "СГР", "tr_ts": None, "applicability": "possible", "source": "legacy_non_tariff_rules"}]
    official = [{"permit_type": "СГР", "tr_ts": None, "applicability": "definite", "source": OFFICIAL_SGR_SOURCE_KIND}]
    merged = merge_advisory_legacy_and_official(legacy, official)
    assert len(merged) == 2
    assert merged[0]["source"] == OFFICIAL_SGR_SOURCE_KIND


def test_get_advisory_official_helper_returns_definite(
    official_and_legacy_imported: None,
) -> None:
    rows = get_advisory_official_sgr_requirements_v2("3808990000", "Дезинфицирующее средство")
    assert any(r.get("applicability") == "definite" for r in rows)
    assert all(r.get("used_for_missing_check") is False for r in rows)


CHILD_DIAPERS_TITLE = "Детские подгузники/пеленки (по описанию)"


@pytest.mark.parametrize(
    ("description", "expect_child_advisory"),
    [
        ("детские подгузники", True),
        ("пеленки для младенцев", True),
        ("подгузники для взрослых", False),
        ("подгузники", False),
    ],
)
def test_child_diapers_9619_official_advisory_gates(
    official_and_legacy_imported: None,
    description: str,
    expect_child_advisory: bool,
) -> None:
    rows = get_advisory_official_sgr_requirements_v2("9619000000", description)
    child_rows = [r for r in rows if r.get("rule_name") == CHILD_DIAPERS_TITLE]
    assert bool(child_rows) is expect_child_advisory
    if expect_child_advisory:
        assert child_rows[0]["applicability"] == "needs_clarification"
        assert child_rows[0]["used_for_missing_check"] is False
