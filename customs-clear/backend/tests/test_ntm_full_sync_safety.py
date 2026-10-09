"""Synthetic full-sync rows must never become product NTM evidence."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.ntm_v2 import NtmApplicabilityRuleV2, NtmMeasureV2
from app.models.tnved import Chapter, Commodity, NonTariffMeasure, Section
from app.services.non_tariff_measures_lookup import get_measures_for_code
from app.services.ntm_v2_legacy_measures_import import import_legacy_non_tariff_measures_to_ntm_v2
from app.services.rag_retriever import build_rag_context
from app.services.regulatory_source_completeness import _count_db_probe
from app.services.state_registry_match import _nt_requires_sgr
from scripts import seed_ntm_full_sync


@pytest.fixture
def seeded_sessionmaker(monkeypatch: pytest.MonkeyPatch):
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
    monkeypatch.setattr(seed_ntm_full_sync, "SessionLocal", sm)
    monkeypatch.setattr("app.db.SessionLocal", sm)
    monkeypatch.setattr("app.services.normative_store.SessionLocal", sm)
    monkeypatch.setattr("app.services.non_tariff_rules.SessionLocal", sm)
    monkeypatch.setattr("app.services.regulatory_source_completeness.SessionLocal", sm)

    with sm() as db:
        section = Section(roman_number="II", title="")
        db.add(section)
        db.flush()
        chapter = Chapter(section_id=section.id, code="09", title="")
        db.add(chapter)
        db.flush()
        db.add(Commodity(chapter_id=chapter.id, code="0901000000", description="test"))
        db.commit()
    return sm


def test_seed_rows_are_reference_only_and_withheld(seeded_sessionmaker: sessionmaker) -> None:
    report = seed_ntm_full_sync.seed()
    assert report["inserted"] > 0

    with seeded_sessionmaker() as db:
        rows = db.query(NonTariffMeasure).all()
        assert rows
        assert {row.quality for row in rows} == {"synthetic_seed"}
        assert get_measures_for_code("0901000000", db) == []
        assert _nt_requires_sgr(db, "0901000000") is False
        context = build_rag_context(db, "090100", "кофе")
        assert "ТР ТС 021/2011" not in context
        assert "(нет выборки non_tariff_measures по префиксу кода)" in context

    assert _count_db_probe("non_tariff_measures") == 0

    imported = import_legacy_non_tariff_measures_to_ntm_v2()
    assert imported["skipped_synthetic"] == report["inserted"]
    assert imported["measures_created"] == 0


def test_rerun_repairs_old_generated_rows_but_preserves_verified(
    seeded_sessionmaker: sessionmaker,
) -> None:
    measure_type, regulatory_act, description = seed_ntm_full_sync.CHAPTER_NTMS["09"][0]
    with seeded_sessionmaker() as db:
        db.add(NonTariffMeasure(
            commodity_code="0901000000",
            measure_type=measure_type,
            regulatory_act=regulatory_act,
            description=description,
            document_required=regulatory_act,
            quality="normal",
        ))
        db.add(NonTariffMeasure(
            commodity_code="0901000000",
            measure_type="certificate",
            regulatory_act="CURATED-SOURCE",
            description="Проверенная курируемая строка",
            document_required="Документ",
            quality="verified",
        ))
        db.commit()

    report = seed_ntm_full_sync.seed()
    assert report["relabeled_synthetic"] == 1

    with seeded_sessionmaker() as db:
        admitted = get_measures_for_code("0901000000", db)
        assert len(admitted) == 1
        assert admitted[0].regulatory_act == "CURATED-SOURCE"
        repaired = db.query(NonTariffMeasure).filter_by(
            regulatory_act=regulatory_act,
            description=description,
        ).one()
        assert repaired.quality == "synthetic_seed"
