"""Каскадный поиск non_tariff_measures по префиксам кода."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.tnved import NonTariffMeasure
from app.services.non_tariff_measures_lookup import build_measure_code_candidates, get_measures_for_code


def test_build_measure_code_candidates_includes_chapter_and_position_pad() -> None:
    candidates = set(build_measure_code_candidates("0601100000"))
    assert "0601100000" in candidates
    assert "0601000000" in candidates
    assert "06" in candidates


def test_get_measures_for_code_0601100000_phyto_and_certificate() -> None:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    NonTariffMeasure.__table__.create(engine)
    TestSession = sessionmaker(bind=engine)
    with TestSession() as db:
        db.add_all([
            NonTariffMeasure(
                commodity_code="0601000000",
                measure_type="phyto_control",
                description="Фитосанитарный контроль",
                regulatory_act="Тестовый нормативный источник",
            ),
            NonTariffMeasure(
                commodity_code="06",
                measure_type="certificate",
                description="Подтверждение соответствия",
                regulatory_act="Тестовый нормативный источник",
            ),
        ])
        db.commit()
        rows = get_measures_for_code("0601100000", db)
    types = {(m.measure_type or "").strip().lower() for m in rows}
    assert "phyto_control" in types
    assert "certificate" in types
