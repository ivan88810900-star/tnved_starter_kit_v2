"""Ставки для карточки: акциз с наследованием и fail-closed provenance."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.core import HsRate, SourceStatus
from app.models.tnved import HsDutyRule
from app.services.rate_display import format_duty_rule_label, format_excise_display, resolve_excise_for_hs


_SYNCED_AT = datetime(2026, 5, 1, 12, 0, 0)
_SOURCE_URL = "https://www.nalog.gov.ru/rn77/about_fts/docs/12345678"
_REVISION = "excise:2026-05-01"


@contextmanager
def _isolated_rate_store():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[HsRate.__table__, SourceStatus.__table__, HsDutyRule.__table__],
    )
    sm = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    with (
        patch("app.services.rate_display.SessionLocal", sm),
        patch("app.services.normative_store.SessionLocal", sm),
    ):
        yield sm


def _add_excise_status(sm, *, stale: bool = False, revision: str = _REVISION) -> None:
    with sm() as db:
        db.add(
            SourceStatus(
                source_code="EEC_EXCISE",
                source_name="Synthetic official excise fixture",
                source_url=_SOURCE_URL,
                revision=revision,
                synced_at=_SYNCED_AT,
                is_stale=stale,
            )
        )
        db.commit()


def _add_parent_rate(
    sm,
    *,
    source_code: str = "EEC_EXCISE",
    revision: str = _REVISION,
    source_url: str = _SOURCE_URL,
    synced_at: datetime | None = _SYNCED_AT,
) -> None:
    with sm() as db:
        db.add(
            HsRate(
                hs_code="2204100000",
                hs_prefix="2204",
                duty_rate="0%",
                excise_type="fixed",
                excise_value=45.0,
                excise_basis="synthetic verified fixture, RUB/l",
                excise_source_code=source_code,
                excise_source_revision=revision,
                excise_source_url=source_url,
                excise_synced_at=synced_at,
            )
        )
        db.commit()


def test_excise_inherited_only_from_verified_parent() -> None:
    with _isolated_rate_store() as sm:
        _add_excise_status(sm)
        _add_parent_rate(sm)
        excise_type, excise_value, excise_basis = resolve_excise_for_hs("2204101100")

    assert excise_type == "fixed"
    assert excise_value == 45.0
    assert format_excise_display(excise_type, excise_value, excise_basis) == "45 ₽/л"


def test_excise_unverified_parent_is_withheld() -> None:
    with _isolated_rate_store() as sm:
        _add_parent_rate(sm, source_code="", revision="", source_url="", synced_at=None)
        result = resolve_excise_for_hs("2204101100")

    assert result == ("needs_review", 0.0, "")
    assert format_excise_display(*result) == "Уточните ставку"


def test_excise_stale_source_status_is_withheld() -> None:
    with _isolated_rate_store() as sm:
        _add_excise_status(sm, stale=True)
        _add_parent_rate(sm)
        result = resolve_excise_for_hs("2204101100")

    assert result == ("needs_review", 0.0, "")


def test_excise_row_revision_must_match_source_status() -> None:
    with _isolated_rate_store() as sm:
        _add_excise_status(sm)
        _add_parent_rate(sm, revision="excise:2026-04-01")
        result = resolve_excise_for_hs("2204101100")

    assert result == ("needs_review", 0.0, "")


def test_excise_row_url_and_sync_time_must_be_official_and_not_newer_than_status() -> None:
    with _isolated_rate_store() as sm:
        _add_excise_status(sm)
        _add_parent_rate(sm, source_url="https://example.invalid/stale")
        url_result = resolve_excise_for_hs("2204101100")

    with _isolated_rate_store() as sm:
        _add_excise_status(sm)
        _add_parent_rate(sm, synced_at=datetime(2026, 5, 1, 12, 0, 1))
        future_row_result = resolve_excise_for_hs("2204101100")

    with _isolated_rate_store() as sm:
        _add_excise_status(sm)
        _add_parent_rate(
            sm,
            source_url="https://www.nalog.gov.ru/rn77/taxation/taxes/akciz/",
            synced_at=datetime(2026, 5, 1, 11, 59, 59),
        )
        older_official_row_result = resolve_excise_for_hs("2204101100")

    assert url_result == ("needs_review", 0.0, "")
    assert future_row_result == ("needs_review", 0.0, "")
    assert older_official_row_result[0:2] == ("fixed", 45.0)


def test_excise_needs_review_for_alcohol_without_data() -> None:
    with _isolated_rate_store():
        assert resolve_excise_for_hs("2202990000") == ("needs_review", 0.0, "")


def test_excise_empty_for_non_excise_chapter() -> None:
    with _isolated_rate_store():
        assert resolve_excise_for_hs("8517110000") == ("none", 0.0, "")


def test_unbound_structured_duty_rule_is_not_rendered_as_confirmed_rate() -> None:
    with _isolated_rate_store() as sm:
        with sm() as db:
            db.add(
                HsDutyRule(
                    commodity_code="8501100000",
                    type="specific",
                    ad_valorem_pct=None,
                    specific_amount=2,
                    specific_currency="EUR",
                    specific_uom="kg",
                )
            )
            db.commit()

        with patch("app.services.payment_engine.SessionLocal", sm):
            label = format_duty_rule_label("8501100000", "")

    assert label == "Уточните ставку"


def test_combined_duty_display_distinguishes_add_from_max() -> None:
    add_rule = SimpleNamespace(
        type="combined_add",
        ad_valorem_pct=5,
        specific_amount=2,
        specific_currency="EUR",
        specific_uom="kg",
    )
    max_rule = SimpleNamespace(
        type="combined_max",
        ad_valorem_pct=5,
        specific_amount=2,
        specific_currency="EUR",
        specific_uom="kg",
    )

    with patch("app.services.rate_display._find_duty_rule_for_hs", return_value=(add_rule, 10)):
        assert format_duty_rule_label("8501100000", "") == "5% + 2 EUR/kg"
    with patch("app.services.rate_display._find_duty_rule_for_hs", return_value=(max_rule, 10)):
        assert format_duty_rule_label("8501100000", "") == "5%, но не менее 2 EUR/kg"
