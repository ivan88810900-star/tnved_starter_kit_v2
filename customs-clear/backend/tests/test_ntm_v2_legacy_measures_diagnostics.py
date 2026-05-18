"""Диагностика imported legacy non_tariff_measures (distribution + enforcement impact)."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.ntm_v2 import NtmApplicabilityRuleV2, NtmMeasureV2
from app.models.tnved import Chapter, Commodity, NonTariffMeasure, Section
from app.services.ntm_v2_legacy_measures_diagnostics import (
    analyze_legacy_measures_v2_distribution,
    compare_legacy_measures_enforcement_impact,
    merge_v2_legacy_measures_into_broker,
    run_legacy_measures_impact_matrix,
)
from app.services.ntm_v2_legacy_measures_import import import_legacy_non_tariff_measures_to_ntm_v2


@pytest.fixture
def memory_sessionmaker(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            Section.__table__,
            Chapter.__table__,
            Commodity.__table__,
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
    monkeypatch.setattr(
        "app.services.ntm_v2_legacy_measures_diagnostics.get_full_ntm_requirements",
        lambda _hs, _d="": [],
    )
    monkeypatch.setattr(
        "app.services.non_tariff_service.get_full_ntm_requirements",
        lambda _hs, _d="": [],
    )
    monkeypatch.setattr("app.services.non_tariff_service.find_rules_for_code", lambda _hs: [])
    monkeypatch.setattr("app.services.non_tariff_service.find_measures_for_code", lambda _hs, **_: [])
    monkeypatch.setattr("app.services.ntm_triggers.find_measures_by_description", lambda _d, _hs: [])
    monkeypatch.setattr(
        "app.services.non_tariff_service.find_measures_by_description",
        lambda _d, _hs: [],
    )
    monkeypatch.setattr(
        "app.services.ntm_v2_legacy_measures_diagnostics.get_sensitive_override",
        lambda hs: "РУ" if (hs or "").startswith("30") else None,
    )
    monkeypatch.setattr(
        "app.services.non_tariff_service.get_sensitive_override",
        lambda hs: "РУ" if (hs or "").startswith("30") else None,
    )
    monkeypatch.setattr(
        "app.services.non_tariff_service.find_normative_notes_for_hs",
        lambda _hs: [],
    )
    monkeypatch.setattr(
        "app.services.non_tariff_service.get_regulatory_documents_for_hs",
        lambda _hs, **_: [],
    )
    monkeypatch.setattr(
        "app.services.non_tariff_service.lookup_tr_ts_acts_by_codes",
        lambda _codes: [],
    )


def _seed_measure(
    sm: sessionmaker,
    *,
    commodity_code: str = "3004",
    measure_type: str = "certificate",
    description: str = "Декларация соответствия ТР ТС 061/2012",
    regulatory_act: str = "ТР ТС 061/2012",
) -> None:
    with sm() as s:
        if s.query(Chapter).first() is None:
            sec = Section(roman_number="VI", title="")
            s.add(sec)
            s.flush()
            s.add(Chapter(section_id=sec.id, code="30", title=""))
            s.flush()
        ch = s.query(Chapter).first()
        if s.query(Commodity).filter_by(code=commodity_code).first() is None:
            s.add(Commodity(chapter_id=ch.id, code=commodity_code, description="t"))
            s.flush()
        s.add(
            NonTariffMeasure(
                commodity_code=commodity_code,
                measure_type=measure_type,
                description=description,
                regulatory_act=regulatory_act,
                quality="normal",
            )
        )
        s.commit()
    import_legacy_non_tariff_measures_to_ntm_v2()


def test_distribution_counts(memory_sessionmaker: sessionmaker) -> None:
    _seed_measure(memory_sessionmaker)
    dist = analyze_legacy_measures_v2_distribution(session=memory_sessionmaker())
    assert dist["measures"]["total_imported"] == 1
    assert dist["measures"]["nonempty_permit_type"] >= 1
    assert dist["rules"]["total_imported"] == 1
    assert "enforcement_candidate" in dist["measures"]["suitability"]


def test_merge_skips_empty_permit() -> None:
    broker = [{"permit_type": "РУ", "tr_ts": None}]
    rows = [
        {"permit_type": "", "tr_ts": None},
        {"permit_type": "ДС", "tr_ts": "004/2011"},
    ]
    merged = merge_v2_legacy_measures_into_broker(broker, rows)
    assert len(merged) == 2
    assert ("ДС", "004/2011") in {(r["permit_type"], r.get("tr_ts")) for r in merged}


def test_impact_baseline_unchanged_without_enforcement_match(
    memory_sessionmaker: sessionmaker,
    minimal_ntm_patches: None,
) -> None:
    _seed_measure(memory_sessionmaker, commodity_code="9999", measure_type="marking", description="маркировка")
    cmp = asyncio.run(
        compare_legacy_measures_enforcement_impact("9999000000", description="товар")
    )
    assert cmp["changed"] is False or not cmp["added_permit_types"]


def test_impact_adds_new_permit_type(
    memory_sessionmaker: sessionmaker,
    minimal_ntm_patches: None,
) -> None:
    _seed_measure(memory_sessionmaker)
    cmp = asyncio.run(
        compare_legacy_measures_enforcement_impact("3004909200", description="Лекарство")
    )
    assert "ДС" in cmp["added_permit_types"] or "ДС" in cmp["added_missing_permit_types"]
    assert cmp["changed"] is True
    assert cmp["baseline_required_permit_types"] == ["РУ"]


def test_impact_already_covered_no_new_type(
    memory_sessionmaker: sessionmaker,
    minimal_ntm_patches: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_measure(
        memory_sessionmaker,
        commodity_code="8517",
        description="Декларация соответствия ТР ТС 004/2011",
        regulatory_act="ТР ТС 004/2011",
    )

    def _catalog(_hs: str, _d: str = "") -> list[dict]:
        return [
            {
                "permit_type": "ДС",
                "tr_ts": "004/2011",
                "tr_ts_full_name": "",
                "description": "catalog",
                "legal_ref": "TR",
                "matched_prefix": "8517",
                "priority": 1,
            }
        ]

    monkeypatch.setattr(
        "app.services.ntm_v2_legacy_measures_diagnostics.get_full_ntm_requirements",
        _catalog,
    )
    monkeypatch.setattr("app.services.non_tariff_service.get_full_ntm_requirements", _catalog)

    cmp = asyncio.run(
        compare_legacy_measures_enforcement_impact("8517620000", description="")
    )
    assert "ДС" not in cmp["added_permit_types"]
    covered = [x for x in cmp["impact_by_measure"] if x["classification"] == "exactly_already_covered"]
    assert covered


def test_impact_same_permit_different_tr_ts_no_new_type(
    memory_sessionmaker: sessionmaker,
    minimal_ntm_patches: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_measure(
        memory_sessionmaker,
        commodity_code="8517",
        description="Декларация соответствия ТР ТС 061/2012",
        regulatory_act="ТР ТС 061/2012",
    )

    def _catalog(_hs: str, _d: str = "") -> list[dict]:
        return [
            {
                "permit_type": "ДС",
                "tr_ts": "004/2011",
                "tr_ts_full_name": "",
                "description": "catalog",
                "legal_ref": "TR",
                "matched_prefix": "8517",
                "priority": 1,
            }
        ]

    monkeypatch.setattr(
        "app.services.ntm_v2_legacy_measures_diagnostics.get_full_ntm_requirements",
        _catalog,
    )
    monkeypatch.setattr("app.services.non_tariff_service.get_full_ntm_requirements", _catalog)

    cmp = asyncio.run(compare_legacy_measures_enforcement_impact("8517620000", description=""))
    assert "ДС" not in cmp["added_permit_types"]
    diff_tr = [
        x
        for x in cmp["impact_by_measure"]
        if x["classification"] == "permit_type_already_covered_different_tr_ts"
    ]
    assert diff_tr


def test_matrix_changed_unchanged(
    memory_sessionmaker: sessionmaker,
    minimal_ntm_patches: None,
) -> None:
    _seed_measure(memory_sessionmaker)
    matrix = asyncio.run(
        run_legacy_measures_impact_matrix(
            [
                ("3004909200", "Лекарство"),
                ("0101210000", "Коровы"),
            ]
        )
    )
    assert matrix["total_cases"] == 2
    assert matrix["changed_cases"] >= 1
    assert matrix["unchanged_cases"] >= 0
