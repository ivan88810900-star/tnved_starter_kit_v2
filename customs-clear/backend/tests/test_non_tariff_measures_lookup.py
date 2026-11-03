"""Каскадный поиск non_tariff_measures по префиксам кода."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.tnved import Chapter, Commodity, NonTariffMeasure, Section
from app.services.non_tariff_measures_lookup import build_measure_code_candidates, get_measures_for_code


def test_build_measure_code_candidates_includes_chapter_and_position_pad() -> None:
    candidates = set(build_measure_code_candidates("0601100000"))
    assert "0601100000" in candidates
    assert "0601000000" in candidates
    assert "06" in candidates


def test_get_measures_for_code_0601100000_phyto_and_certificate() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            Section.__table__,
            Chapter.__table__,
            Commodity.__table__,
            NonTariffMeasure.__table__,
        ],
    )
    test_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    with test_session() as db:
        section = Section(roman_number="NTM", title="Lookup test")
        db.add(section)
        db.flush()
        chapter = Chapter(section_id=section.id, code="06", title="Live plants")
        db.add(chapter)
        db.flush()
        db.add_all([
            Commodity(chapter_id=chapter.id, code="0601000000", description="Plants"),
            Commodity(chapter_id=chapter.id, code="0601100000", description="Bulbs"),
            NonTariffMeasure(
                commodity_code="0601100000",
                measure_type="phyto_control",
                regulatory_act="test-phyto",
                quality="verified",
            ),
            NonTariffMeasure(
                commodity_code="0601000000",
                measure_type="certificate",
                regulatory_act="test-certificate",
                quality="verified",
            ),
        ])
        db.commit()
        rows = get_measures_for_code("0601100000", db)
    types = {(m.measure_type or "").strip().lower() for m in rows}
    assert "phyto_control" in types
    assert "certificate" in types
