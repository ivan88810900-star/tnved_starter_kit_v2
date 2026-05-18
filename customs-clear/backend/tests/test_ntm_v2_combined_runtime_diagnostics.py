"""Combined legacy vs safe v2 runtime diagnostics."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.core import NonTariffRule
from app.models.ntm_v2 import NtmApplicabilityRuleV2, NtmMeasureV2
from app.models.tnved import Chapter, Commodity, NonTariffMeasure, Section
from app.services.ntm_v2_combined_runtime_diagnostics import (
    compare_non_tariff_check_legacy_vs_safe_v2,
    run_safe_v2_combined_impact_matrix,
)
from app.services.ntm_v2_legacy_measures_import import import_legacy_non_tariff_measures_to_ntm_v2
from app.services.ntm_v2_legacy_rules_import import import_legacy_non_tariff_rules_to_ntm_v2


@pytest.fixture
def memory_sessionmaker(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            Section.__table__,
            Chapter.__table__,
            Commodity.__table__,
            NonTariffRule.__table__,
            NonTariffMeasure.__table__,
            NtmMeasureV2.__table__,
            NtmApplicabilityRuleV2.__table__,
        ],
    )
    sm = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr("app.db.SessionLocal", sm)
    monkeypatch.setattr("app.services.normative_store.SessionLocal", sm)
    monkeypatch.setattr("app.services.non_tariff_rules.SessionLocal", sm)
    return sm


@pytest.fixture
def minimal_ntm_patches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.non_tariff_service.get_full_ntm_requirements", lambda _h, _d="": [])
    monkeypatch.setattr("app.services.non_tariff_service.find_rules_for_code", lambda _h: [])
    monkeypatch.setattr("app.services.non_tariff_service.find_measures_for_code", lambda _h, **_: [])
    monkeypatch.setattr("app.services.non_tariff_service.find_measures_by_description", lambda _d, _h: [])
    monkeypatch.setattr("app.services.non_tariff_service.get_sensitive_override", lambda h: "РУ" if (h or "").startswith("30") else None)
    monkeypatch.setattr("app.services.non_tariff_service.find_normative_notes_for_hs", lambda _h: [])
    monkeypatch.setattr("app.services.non_tariff_service.get_regulatory_documents_for_hs", lambda _h, **_: [])
    monkeypatch.setattr("app.services.non_tariff_service.lookup_tr_ts_acts_by_codes", lambda _c: [])


def _seed_rule(sm: sessionmaker) -> None:
    with sm() as s:
        s.add(
            NonTariffRule(
                name="Лекарства",
                hs_prefix="3004",
                required_permits="ДС",
                tr_ts="061/2012",
                tr_ts_edition="",
                exception_note="",
                priority=5,
                valid_from="",
                valid_to="",
                source_url="https://test",
                source_revision="test",
            )
        )
        s.commit()
    import_legacy_non_tariff_rules_to_ntm_v2()


def _seed_vet_measure(sm: sessionmaker) -> None:
    with sm() as s:
        if s.query(Chapter).first() is None:
            sec = Section(roman_number="II", title="")
            s.add(sec)
            s.flush()
            s.add(Chapter(section_id=sec.id, code="02", title=""))
            s.flush()
        ch = s.query(Chapter).first()
        s.add(Commodity(chapter_id=ch.id, code="0201", description="t"))
        s.flush()
        s.add(
            NonTariffMeasure(
                commodity_code="0201",
                measure_type="vet_control",
                description="Ветеринарный сертификат",
                quality="normal",
            )
        )
        s.commit()
    import_legacy_non_tariff_measures_to_ntm_v2()


def test_rules_enforcement_possible_does_not_add_ds(
    memory_sessionmaker: sessionmaker,
    minimal_ntm_patches: None,
) -> None:
    _seed_rule(memory_sessionmaker)
    row = asyncio.run(compare_non_tariff_check_legacy_vs_safe_v2("3004909200", "Лекарство"))
    assert "ДС" not in row["diff"]["added_permit_types"]
    assert row["contribution"]["rules_enforcement_added"] == []


def test_measures_enforcement_adds_vs(
    memory_sessionmaker: sessionmaker,
    minimal_ntm_patches: None,
) -> None:
    _seed_vet_measure(memory_sessionmaker)
    row = asyncio.run(compare_non_tariff_check_legacy_vs_safe_v2("0201100000", "Говядина"))
    assert "ВС" in row["diff"]["added_permit_types"]
    assert "ВС" in row["contribution"]["measures_enforcement_added"]


def test_matrix_summary_counts(
    memory_sessionmaker: sessionmaker,
    minimal_ntm_patches: None,
) -> None:
    _seed_rule(memory_sessionmaker)
    _seed_vet_measure(memory_sessionmaker)
    m = asyncio.run(
        run_safe_v2_combined_impact_matrix([("3004909200", "Лекарство"), ("0201100000", "Говядина")])
    )
    assert m["total_cases"] == 2
    assert m.get("rules_enforcement_permit_frequency") == {}
    assert m["changed_cases"] >= 1
    assert "ВС" in m.get("measures_enforcement_permit_frequency", {})


def test_replacement_only_unchanged_when_catalog_empty(
    memory_sessionmaker: sessionmaker,
    minimal_ntm_patches: None,
) -> None:
    row = asyncio.run(compare_non_tariff_check_legacy_vs_safe_v2("0101210000", "Коровы"))
    assert row["diff"]["changed"] is False
    assert row["contribution"]["replacement_only_no_semantic_change"] is True
