"""Изоляция source_kind: TR TS / layers adapters не читают rules/measures."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.ntm_v2 import NtmApplicabilityRuleV2, NtmMeasureV2
from app.models.tnved import Chapter, Commodity, NonTariffMeasure, Section
from app.services.ntm_engine_v2 import (
    get_layer_requirements_v2_legacy_shape,
    get_tr_ts_requirements_v2_legacy_shape,
)
from app.services.ntm_v2_import import import_ntm_layers_to_ntm_v2, import_tr_ts_catalog_to_ntm_v2
from app.services.ntm_v2_legacy_measures_import import import_legacy_non_tariff_measures_to_ntm_v2

from app.services.ntm_v2_legacy_rules_import import RULES_SOURCE_KIND
from app.services.ntm_v2_combined_runtime_diagnostics import compare_non_tariff_check_legacy_vs_safe_v2


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


def _ensure_chapter(sm: sessionmaker, code: str) -> None:
    with sm() as s:
        if s.query(Chapter).first() is not None:
            return
        from app.models.tnved import Section

        sec = Section(roman_number="XVI", title="")
        s.add(sec)
        s.flush()
        s.add(Chapter(section_id=sec.id, code=code[:2], title=""))
        s.commit()


def test_tr_ts_adapter_ignores_legacy_measures(memory_sessionmaker: sessionmaker) -> None:
    import_tr_ts_catalog_to_ntm_v2()
    _ensure_chapter(memory_sessionmaker, "85")
    with memory_sessionmaker() as s:
        s.add(Commodity(chapter_id=s.query(Chapter).first().id, code="8517620000", description="t"))
        s.add(
            NonTariffMeasure(
                commodity_code="8517620000",
                measure_type="certificate",
                description="Сертификат соответствия ТР ТС 020/2011",
                regulatory_act="ТР ТС 020/2011",
                quality="normal",
            )
        )
        s.commit()
    import_legacy_non_tariff_measures_to_ntm_v2()

    rows = get_tr_ts_requirements_v2_legacy_shape("8517620000", "")
    permits = {r["permit_type"] for r in rows}
    assert "СС" not in permits
    assert "СГР" not in permits
    assert "ДС" in permits or "СС" in permits  # из каталога ТР ТС


def test_layers_adapter_ignores_legacy_measures(memory_sessionmaker: sessionmaker) -> None:
    import_ntm_layers_to_ntm_v2()
    _ensure_chapter(memory_sessionmaker, "02")
    with memory_sessionmaker() as s:
        ch = s.query(Chapter).first()
        s.add(Commodity(chapter_id=ch.id, code="0201100000", description="t"))
        s.add(
            NonTariffMeasure(
                commodity_code="0201100000",
                measure_type="sgr",
                description="Свидетельство о государственной регистрации",
                regulatory_act="",
                quality="normal",
            )
        )
        s.commit()
    import_legacy_non_tariff_measures_to_ntm_v2()

    rows = get_layer_requirements_v2_legacy_shape("0201100000", "Говядина")
    assert "СГР" not in {r["permit_type"] for r in rows}


def test_tr_ts_adapter_ignores_legacy_rules_v2_rows(memory_sessionmaker: sessionmaker) -> None:
    import_tr_ts_catalog_to_ntm_v2()
    with memory_sessionmaker() as s:
        m = NtmMeasureV2(
            measure_kind="technical_regulation",
            permit_type="СГР",
            title="leaked rule measure",
            short_description="",
            tr_ts_act_code="009/2011",
            status="active",
            source_kind=RULES_SOURCE_KIND,
            source_ref="test",
            import_key=f"{RULES_SOURCE_KIND}|technical_regulation|СГР|009/2011",
        )
        s.add(m)
        s.flush()
        s.add(
            NtmApplicabilityRuleV2(
                measure_id=m.id,
                direction="import",
                hs_scope_mode="prefix",
                hs_code="8517",
                applicability="definite",
                priority=1,
                source_kind=RULES_SOURCE_KIND,
                source_ref="test",
                rule_import_key=f"{RULES_SOURCE_KIND}|rule:1|СГР|009/2011|8517",
            )
        )
        s.commit()

    rows = get_tr_ts_requirements_v2_legacy_shape("8517620000", "")
    assert "СГР" not in {r["permit_type"] for r in rows}


def test_replacement_catalog_no_extra_after_full_import(
    memory_sessionmaker: sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """После импорта rules+measures replacement (v2 TR+layers) не добавляет типов на 8517."""
    monkeypatch.setattr(
        "app.services.non_tariff_service.get_full_ntm_requirements",
        lambda hs, d="": [],
    )
    monkeypatch.setattr("app.services.non_tariff_service.find_rules_for_code", lambda _h: [])
    monkeypatch.setattr("app.services.non_tariff_service.find_measures_for_code", lambda _h, **_: [])
    monkeypatch.setattr("app.services.non_tariff_service.find_measures_by_description", lambda _d, _h: [])
    monkeypatch.setattr("app.services.non_tariff_service.get_sensitive_override", lambda _h: None)
    monkeypatch.setattr("app.services.non_tariff_service.find_normative_notes_for_hs", lambda _h: [])
    monkeypatch.setattr("app.services.non_tariff_service.get_regulatory_documents_for_hs", lambda _h, **_: [])
    monkeypatch.setattr("app.services.non_tariff_service.lookup_tr_ts_acts_by_codes", lambda _c: [])

    import_tr_ts_catalog_to_ntm_v2()
    import_ntm_layers_to_ntm_v2()
    import_legacy_non_tariff_measures_to_ntm_v2()

    row = asyncio.run(compare_non_tariff_check_legacy_vs_safe_v2("8517620000", ""))
    repl_added = row["contribution"].get("replacement_catalog_added") or []
    assert repl_added == [], f"unexpected replacement leak: {repl_added}"
