"""NTM v2 measures enforcement (vet/phyto only, ``NTM_V2_MEASURES_ENFORCEMENT_ENABLED``)."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.tnved import Chapter, Commodity, NonTariffMeasure, Section
from app.models.ntm_v2 import NtmApplicabilityRuleV2, NtmMeasureV2
from app.services.ntm_v2_legacy_measures_enforcement import (
    classify_v2_measure_for_enforcement,
    compare_non_tariff_check_measures_enforcement,
    is_ntm_v2_measures_enforcement_enabled,
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
        "app.services.non_tariff_service.get_full_ntm_requirements",
        lambda _hs, _d="": [],
    )
    monkeypatch.setattr("app.services.non_tariff_service.find_rules_for_code", lambda _hs: [])
    monkeypatch.setattr("app.services.non_tariff_service.find_measures_for_code", lambda _hs, **_: [])
    monkeypatch.setattr("app.services.non_tariff_service.find_measures_by_description", lambda _d, _hs: [])
    monkeypatch.setattr("app.services.non_tariff_service.get_sensitive_override", lambda _hs: None)
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
    commodity_code: str,
    measure_type: str,
    description: str,
    regulatory_act: str = "",
) -> None:
    with sm() as s:
        if s.query(Chapter).first() is None:
            sec = Section(roman_number="II", title="")
            s.add(sec)
            s.flush()
            s.add(Chapter(section_id=sec.id, code=commodity_code[:2], title=""))
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


async def _check(hs: str, desc: str, *, enforcement: bool | None, monkeypatch: pytest.MonkeyPatch) -> dict:
    from app.services.non_tariff_service import check_position_non_tariff

    monkeypatch.delenv("NTM_V2_MEASURES_ENFORCEMENT_ENABLED", raising=False)
    if enforcement:
        monkeypatch.setenv("NTM_V2_MEASURES_ENFORCEMENT_ENABLED", "true")
    return await check_position_non_tariff(
        hs_code=hs,
        description=desc,
        country="CN",
        permits=[],
        skip_registry_verify=True,
        measures_enforcement_enabled=enforcement,
    )


def test_flag_default_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NTM_V2_MEASURES_ENFORCEMENT_ENABLED", raising=False)
    assert is_ntm_v2_measures_enforcement_enabled() is False


def test_gate_allow_vet_vs(memory_sessionmaker: sessionmaker) -> None:
    row = {
        "source_kind": "legacy_non_tariff_measures",
        "measure_kind": "vet",
        "permit_type": "ВС",
        "tr_ts": None,
        "measure_key": "vet|ВС||",
    }
    assert classify_v2_measure_for_enforcement(row, []) == "allow"


def test_gate_skip_sgr(memory_sessionmaker: sessionmaker) -> None:
    row = {
        "source_kind": "legacy_non_tariff_measures",
        "measure_kind": "sgr",
        "permit_type": "СГР",
        "measure_key": "sgr|СГР||",
    }
    assert classify_v2_measure_for_enforcement(row, []) == "skip"


def test_gate_skip_baseline_has_vs() -> None:
    row = {
        "source_kind": "legacy_non_tariff_measures",
        "measure_kind": "vet",
        "permit_type": "ВС",
        "measure_key": "k",
    }
    baseline = [{"permit_type": "ВС", "tr_ts": None}]
    assert classify_v2_measure_for_enforcement(row, baseline) == "skip"


def test_enforcement_adds_vs(
    memory_sessionmaker: sessionmaker,
    minimal_ntm_patches: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_measure(
        memory_sessionmaker,
        commodity_code="0201",
        measure_type="vet_control",
        description="Ветеринарный сертификат на ввоз",
    )
    off = asyncio.run(_check("0201100000", "Говядина", enforcement=False, monkeypatch=monkeypatch))
    on = asyncio.run(_check("0201100000", "Говядина", enforcement=True, monkeypatch=monkeypatch))
    assert "ВС" not in off["required_permit_types"]
    assert "ВС" in on["required_permit_types"]
    assert "ВС" in on["missing_permit_types"]


def test_enforcement_adds_fss_when_layers_missing(
    memory_sessionmaker: sessionmaker,
    minimal_ntm_patches: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_measure(
        memory_sessionmaker,
        commodity_code="0808",
        measure_type="phyto_control",
        description="Фитосанитарный сертификат",
    )
    off = asyncio.run(_check("0808108000", "Яблоки", enforcement=False, monkeypatch=monkeypatch))
    on = asyncio.run(_check("0808108000", "Яблоки", enforcement=True, monkeypatch=monkeypatch))
    assert "ФСС" not in off["required_permit_types"]
    assert "ФСС" in on["required_permit_types"]


def test_skip_when_baseline_has_vs_from_layers(
    memory_sessionmaker: sessionmaker,
    minimal_ntm_patches: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_measure(
        memory_sessionmaker,
        commodity_code="0201",
        measure_type="vet_control",
        description="Ветеринарный сертификат",
    )

    def _catalog(_hs: str, _d: str = "") -> list[dict]:
        return [
            {
                "permit_type": "ВС",
                "tr_ts": None,
                "tr_ts_full_name": "",
                "description": "vet layer",
                "legal_ref": "layer",
                "matched_prefix": "0201",
                "priority": 1,
            }
        ]

    monkeypatch.setattr("app.services.non_tariff_service.get_full_ntm_requirements", _catalog)
    off = asyncio.run(_check("0201100000", "Говядина", enforcement=False, monkeypatch=monkeypatch))
    on = asyncio.run(_check("0201100000", "Говядина", enforcement=True, monkeypatch=monkeypatch))
    assert "ВС" in off["required_permit_types"]
    assert on["required_permit_types"] == off["required_permit_types"]


def test_sgr_not_added_with_flag_on(
    memory_sessionmaker: sessionmaker,
    minimal_ntm_patches: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_measure(
        memory_sessionmaker,
        commodity_code="8508",
        measure_type="sgr",
        description="Свидетельство о государственной регистрации",
    )
    on = asyncio.run(_check("8508110000", "Пылесос", enforcement=True, monkeypatch=monkeypatch))
    assert "СГР" not in on["required_permit_types"]


def test_status_ok_to_error_when_new_vs(
    memory_sessionmaker: sessionmaker,
    minimal_ntm_patches: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_measure(
        memory_sessionmaker,
        commodity_code="1301",
        measure_type="vet_control",
        description="Ветеринарный сертификат",
    )
    off = asyncio.run(_check("1301900000", "", enforcement=False, monkeypatch=monkeypatch))
    on = asyncio.run(_check("1301900000", "", enforcement=True, monkeypatch=monkeypatch))
    assert off["status"] in ("OK", "WARNING")
    assert on["status"] == "ERROR"
    assert "ВС" in on["missing_permit_types"]


def test_compare_diagnostic(
    memory_sessionmaker: sessionmaker,
    minimal_ntm_patches: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_measure(
        memory_sessionmaker,
        commodity_code="0201",
        measure_type="vet_control",
        description="Ветеринарный сертификат",
    )
    cmp = asyncio.run(
        compare_non_tariff_check_measures_enforcement("0201100000", description="Говядина")
    )
    assert cmp["changed"] is True
    assert "ВС" in cmp["added_permit_types"]


def test_regression_matrix_only_vs_fss(
    memory_sessionmaker: sessionmaker,
    minimal_ntm_patches: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.test_ntm_pipeline import REGRESSION_MATRIX

    with memory_sessionmaker() as s:
        for row in s.query(NonTariffMeasure).limit(1).all():
            pass
    # seed representative measures from file DB not needed — matrix uses real catalog paths

    seen: set[str] = set()
    forbidden_added: list[tuple[str, list[str]]] = []
    changed = 0
    added_freq: dict[str, int] = {}

    for hs, desc, _exp in REGRESSION_MATRIX:
        if hs in seen:
            continue
        seen.add(hs)
        cmp = asyncio.run(
            compare_non_tariff_check_measures_enforcement(hs, desc, skip_registry_verify=True)
        )
        if cmp["changed"]:
            changed += 1
        for pt in cmp.get("added_permit_types") or []:
            added_freq[pt] = added_freq.get(pt, 0) + 1
            if pt not in ("ВС", "ФСС"):
                forbidden_added.append((hs, cmp["added_permit_types"]))

    assert forbidden_added == [], f"unexpected permit types added: {forbidden_added[:5]}"
    assert all(pt in ("ВС", "ФСС") for pt in added_freq), added_freq
