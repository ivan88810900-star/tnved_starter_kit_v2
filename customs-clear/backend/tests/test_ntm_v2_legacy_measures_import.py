"""Импорт legacy non_tariff_measures → NTM v2 и shadow compare."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.ntm_v2 import NtmApplicabilityRuleV2, NtmMeasureV2
from app.models.tnved import Chapter, Commodity, NonTariffMeasure, Section
from app.services.ntm_v2_legacy_measures_import import (
    MEASURES_SOURCE_KIND,
    compare_legacy_non_tariff_measures_vs_ntm_v2,
    import_legacy_non_tariff_measures_to_ntm_v2,
    measure_type_to_measure_kind,
)


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


def _add_measure(
    sm: sessionmaker,
    *,
    commodity_code: str = "8517620000",
    measure_type: str = "certificate",
    description: str = "Декларация соответствия ТР ТС 004/2011",
    regulatory_act: str = "ТР ТС 004/2011",
    document_required: str = "",
    quality: str = "normal",
) -> NonTariffMeasure:
    with sm() as s:
        if s.query(Commodity).filter_by(code=commodity_code).first() is None:
            from app.models.tnved import Chapter

            if s.query(Chapter).first() is None:
                from app.models.tnved import Section

                sec = Section(roman_number="XVI", title="")
                s.add(sec)
                s.flush()
                ch = Chapter(section_id=sec.id, code="85", title="")
                s.add(ch)
                s.flush()
            else:
                ch = s.query(Chapter).first()
            s.add(Commodity(chapter_id=ch.id, code=commodity_code, description="test"))
            s.flush()
        row = NonTariffMeasure(
            commodity_code=commodity_code,
            measure_type=measure_type,
            description=description,
            document_required=document_required,
            regulatory_act=regulatory_act,
            quality=quality,
        )
        s.add(row)
        s.commit()
        s.refresh(row)
        return row


def test_measure_type_to_measure_kind_mapping() -> None:
    assert measure_type_to_measure_kind("certificate") == "technical_regulation"
    assert measure_type_to_measure_kind("license") == "license"
    assert measure_type_to_measure_kind("vet_control") == "vet"
    assert measure_type_to_measure_kind("marking") == "marking"
    assert measure_type_to_measure_kind("unknown_x") == "other"


def test_import_one_measure_creates_measure_and_rule(memory_sessionmaker: sessionmaker) -> None:
    _add_measure(memory_sessionmaker)
    r = import_legacy_non_tariff_measures_to_ntm_v2()
    assert r["legacy_measures_processed"] == 1
    assert r["measures_created"] == 1
    assert r["applicability_rules_created"] == 1
    with memory_sessionmaker() as s:
        m = s.query(NtmMeasureV2).filter_by(source_kind=MEASURES_SOURCE_KIND).one()
        rule = s.query(NtmApplicabilityRuleV2).filter_by(source_kind=MEASURES_SOURCE_KIND).one()
        assert rule.hs_code == "8517620000"
        assert rule.hs_scope_mode == "prefix"
        payload = rule.description_match_json["legacy_payload"]
        assert payload["commodity_code"] == "8517620000"
        assert payload["legal_ref"] == "ТР ТС 004/2011"
        assert m.measure_kind == "technical_regulation"


def test_import_idempotent(memory_sessionmaker: sessionmaker) -> None:
    _add_measure(memory_sessionmaker)
    r1 = import_legacy_non_tariff_measures_to_ntm_v2()
    r2 = import_legacy_non_tariff_measures_to_ntm_v2()
    assert r2["measures_created"] == 0
    assert r2["applicability_rules_created"] == 0
    assert r2["duplicates_skipped"] == r1["applicability_rules_created"]
    with memory_sessionmaker() as s:
        assert s.query(NtmMeasureV2).count() == 1


def test_import_skips_noise(memory_sessionmaker: sessionmaker) -> None:
    _add_measure(memory_sessionmaker, quality="noise")
    r = import_legacy_non_tariff_measures_to_ntm_v2()
    assert r["skipped_noise"] == 1
    assert r["measures_created"] == 0


def test_import_different_measure_types(memory_sessionmaker: sessionmaker) -> None:
    _add_measure(memory_sessionmaker, measure_type="license", description="Лицензия Минпромторга")
    _add_measure(
        memory_sessionmaker,
        commodity_code="0101210000",
        measure_type="vet_control",
        description="Ветеринарный сертификат",
        regulatory_act="",
    )
    r = import_legacy_non_tariff_measures_to_ntm_v2()
    assert r["measures_created"] == 2
    with memory_sessionmaker() as s:
        kinds = {m.measure_kind for m in s.query(NtmMeasureV2).all()}
        assert "license" in kinds
        assert "vet" in kinds


def test_compare_full_overlap(memory_sessionmaker: sessionmaker) -> None:
    _add_measure(memory_sessionmaker)
    import_legacy_non_tariff_measures_to_ntm_v2()
    cmp = compare_legacy_non_tariff_measures_vs_ntm_v2("8517620000")
    assert cmp["is_full_match"] is True
    assert cmp["legacy_only"] == []
    assert cmp["v2_only"] == []


def test_compare_legacy_only_before_import(memory_sessionmaker: sessionmaker) -> None:
    _add_measure(memory_sessionmaker)
    cmp = compare_legacy_non_tariff_measures_vs_ntm_v2("8517620000")
    assert cmp["legacy_only"]
    assert cmp["v2_only"] == []
    assert cmp["is_full_match"] is False


def test_compare_multiple_measures_same_hs(memory_sessionmaker: sessionmaker) -> None:
    _add_measure(
        memory_sessionmaker,
        measure_type="license",
        description="Лицензия на импорт",
        regulatory_act="Постановление 1",
    )
    _add_measure(
        memory_sessionmaker,
        measure_type="certificate",
        description="Сертификат соответствия",
        regulatory_act="Постановление 2",
    )
    import_legacy_non_tariff_measures_to_ntm_v2()
    cmp = compare_legacy_non_tariff_measures_vs_ntm_v2("8517620000")
    assert cmp["is_full_match"] is True
    assert len(cmp["overlap"]) >= 2


def test_compare_prefix_commodity_code(memory_sessionmaker: sessionmaker) -> None:
    """Мера на 4-значном commodity_code матчится на 10-значный HS (как LIKE pref%)."""
    _add_measure(
        memory_sessionmaker,
        commodity_code="8517",
        description="Декларация соответствия ТР ТС 004/2011",
        regulatory_act="ТР ТС 004/2011",
    )
    import_legacy_non_tariff_measures_to_ntm_v2()
    cmp = compare_legacy_non_tariff_measures_vs_ntm_v2("8517620000")
    assert cmp["is_full_match"] is True


def test_smoke_real_db_sample() -> None:
    """Smoke на dev-БД: несколько HS, где legacy measures не пусты."""
    from sqlalchemy import inspect

    from app.db import SessionLocal, engine
    from app.models.tnved import NonTariffMeasure
    from app.services.non_tariff_rules import find_measures_for_code

    insp = inspect(engine)
    if not insp.has_table("non_tariff_measures") or not insp.has_table("ntm_measures_v2"):
        pytest.skip("requires non_tariff_measures and ntm_measures_v2 tables")

    with SessionLocal() as s:
        if s.query(NonTariffMeasure).limit(1).count() == 0:
            pytest.skip("no non_tariff_measures in DB")

    samples: list[str] = []
    for code in ("3004909200", "8517620000", "8471300000", "6403990000"):
        if find_measures_for_code(code):
            samples.append(code)
        if len(samples) >= 3:
            break
    if not samples:
        pytest.skip("no HS with legacy measures in sample set")

    report = import_legacy_non_tariff_measures_to_ntm_v2()
    assert report["measures_created"] >= 0

    mismatches: list[tuple[str, dict]] = []
    for hs in samples:
        cmp = compare_legacy_non_tariff_measures_vs_ntm_v2(hs)
        if not cmp["is_full_match"]:
            mismatches.append((hs, cmp))
    assert mismatches == [], f"shadow mismatches: {mismatches[:3]}"
