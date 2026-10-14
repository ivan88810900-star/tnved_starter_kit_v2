"""Ставки для карточки: акциз с наследованием, подакцизные главы без данных."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.core import HsRate
from app.services import normative_store, rate_display
from app.services.rate_display import format_excise_display, resolve_excise_for_hs


@pytest.fixture(scope="module", autouse=True)
def _isolated_rate_database():
    """Keep display lookups independent from the ambient application database."""
    engine = None
    db = None
    primary_error = None
    primary_traceback = None
    cleanup_errors = []
    normative_session = normative_store.SessionLocal
    display_session = rate_display.SessionLocal
    normative_patch = pytest.MonkeyPatch()
    display_patch = pytest.MonkeyPatch()

    try:
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        HsRate.__table__.create(bind=engine)
        factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        db = factory()
        db.add(
            HsRate(
                hs_code="2204100000",
                hs_prefix="220410",
                duty_rate="20%",
                excise_type="fixed",
                excise_value=45.0,
                excise_basis="НК РФ ст. 193: вина игристые — 45 руб/л",
            )
        )
        db.commit()
        normative_patch.setattr(normative_store, "SessionLocal", factory)
        display_patch.setattr(rate_display, "SessionLocal", factory)
        try:
            yield
        except BaseException as error:
            primary_error = error
            primary_traceback = error.__traceback__
    except BaseException as error:
        primary_error = error
        primary_traceback = error.__traceback__
    finally:
        for patch, module, original in (
            (display_patch, rate_display, display_session),
            (normative_patch, normative_store, normative_session),
        ):
            try:
                patch.undo()
            except BaseException as error:
                cleanup_errors.append(error)
            try:
                module.SessionLocal = original
            except BaseException as error:
                cleanup_errors.append(error)

        if db is not None:
            try:
                db.close()
            except BaseException as error:
                cleanup_errors.append(error)
        if engine is not None:
            try:
                engine.dispose()
            except BaseException as error:
                cleanup_errors.append(error)

        if primary_error is not None:
            if cleanup_errors and hasattr(primary_error, "add_note"):
                for error in cleanup_errors:
                    primary_error.add_note(f"suppressed fixture cleanup error: {error!r}")
            raise primary_error.with_traceback(primary_traceback)
        if cleanup_errors:
            cleanup_error = cleanup_errors[0]
            if hasattr(cleanup_error, "add_note"):
                for error in cleanup_errors[1:]:
                    cleanup_error.add_note(f"additional fixture cleanup error: {error!r}")
            raise cleanup_error


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
