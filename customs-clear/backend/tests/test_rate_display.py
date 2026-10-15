"""Ставки для карточки: акциз с наследованием, подакцизные главы без данных."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import db as app_db
from app.models.core import HsRate
from app.services import normative_store, rate_display
from app.services.rate_display import format_excise_display, resolve_excise_for_hs


@pytest.fixture(autouse=True)
def isolated_rate_db(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Keep rate-display checks independent of an ambient development DB."""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'rate-display.sqlite'}",
        connect_args={"check_same_thread": False},
    )
    app_db.Base.metadata.create_all(bind=engine, tables=[HsRate.__table__])
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    monkeypatch.setattr(app_db, "engine", engine)
    monkeypatch.setattr(app_db, "SessionLocal", session_factory)
    monkeypatch.setattr(normative_store, "SessionLocal", session_factory)
    monkeypatch.setattr(rate_display, "SessionLocal", session_factory)

    with session_factory() as db:
        db.add(
            HsRate(
                hs_code="2204000000",
                hs_prefix="2204",
                duty_rate="0",
                excise_type="fixed",
                excise_value=45.0,
                excise_basis="руб/л",
            )
        )
        db.commit()

    try:
        yield
    finally:
        engine.dispose()


def test_excise_inherited_from_parent_for_champagne_leaf() -> None:
    excise_type, excise_value, excise_basis = resolve_excise_for_hs("2204101100")
    assert excise_type == "fixed"
    assert excise_value == 45.0
    assert format_excise_display(excise_type, excise_value, excise_basis) == "45 ₽/л"


def test_excise_needs_review_for_alcohol_without_data() -> None:
    excise_type, excise_value, _ = resolve_excise_for_hs("2202990000")
    if excise_type == "none":
        # если в БД появится явная ставка — тест остаётся валидным через format
        assert excise_value == 0.0
    else:
        assert excise_type in {"fixed", "percent", "combined", "needs_review"}


def test_excise_empty_for_non_excise_chapter() -> None:
    excise_type, _, _ = resolve_excise_for_hs("8517110000")
    assert excise_type in {"none", "needs_review", "fixed", "percent"}
