"""Compatibility checks for the read-only compact Canonical Gate-2 database."""

from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.models import HsRate
from app.models.tnved import Chapter, Commodity, Section
from app.services import normative_store
from app.services.tree_engine import CanonicalModel
from app.services.tree_engine.provider import CanonicalTreeProvider


def test_leaf_detection_accepts_hs_rates_without_hs_prefix(
    monkeypatch,
) -> None:
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text("CREATE TABLE hs_rates (id INTEGER PRIMARY KEY, hs_code VARCHAR(10))")
        )
        connection.execute(
            text(
                "CREATE TABLE tnved_commodities ("
                "id INTEGER PRIMARY KEY, code VARCHAR(32), description TEXT)"
            )
        )
        connection.execute(
            text("INSERT INTO hs_rates (hs_code) VALUES ('8517')")
        )
        connection.execute(
            text(
                "INSERT INTO tnved_commodities (code, description) "
                "VALUES ('8517110000', 'Телефонные аппараты')"
            )
        )

    monkeypatch.setattr(
        normative_store,
        "SessionLocal",
        sessionmaker(autocommit=False, autoflush=False, bind=engine),
    )

    assert normative_store.is_leaf_hs_code("8517110000") is True


def test_canonical_provider_builds_from_compact_hs_rates_schema() -> None:
    engine = create_engine("sqlite:///:memory:")
    Section.__table__.create(engine)
    Chapter.__table__.create(engine)
    Commodity.__table__.create(engine)
    HsRate.__table__.create(engine)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE hs_rates"))
        connection.execute(
            text("CREATE TABLE hs_rates (id INTEGER PRIMARY KEY, hs_code VARCHAR(10))")
        )
        connection.execute(text("INSERT INTO hs_rates (hs_code) VALUES ('8517')"))

    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    with factory() as db:
        section = Section(roman_number="XVI", title="Машины", notes="")
        db.add(section)
        db.flush()
        chapter = Chapter(
            section_id=section.id,
            code="85",
            title="Электрооборудование",
            notes="",
        )
        db.add(chapter)
        db.flush()
        db.add_all(
            [
                Commodity(
                    chapter_id=chapter.id,
                    code="8517",
                    description="Телефонные аппараты",
                ),
                Commodity(
                    chapter_id=chapter.id,
                    code="8517130000",
                    description="Смартфоны",
                ),
            ]
        )
        db.commit()

    model = CanonicalTreeProvider().get_model(session_factory=factory)

    assert isinstance(model, CanonicalModel)
    assert model.get_by_code("8517") is not None
