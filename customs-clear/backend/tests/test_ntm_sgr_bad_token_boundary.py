"""Fail-closed regressions for the description-only SGR ``БАД`` hint."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.ntm_v2 import NtmApplicabilityRuleV2, NtmMeasureV2
from app.services.ntm_layers import get_sgr_requirement
from app.services.ntm_v2_import import import_ntm_layers_to_ntm_v2


@pytest.fixture
def memory_sessionmaker(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[NtmMeasureV2.__table__, NtmApplicabilityRuleV2.__table__],
    )
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr("app.db.SessionLocal", factory)
    return factory


@pytest.mark.parametrize(
    "description",
    [
        "набор для бадминтона",
        "баденский сувенир",
        "ведро-бадья",
        "супербад как торговое наименование",
        "бад\u0301минтон",
        "бад\u200dминтон",
        "бад＿минтон",
        "супер\u200dбад",
        "супер＿бад",
    ],
)
def test_legacy_sgr_does_not_match_bad_inside_another_token(description: str) -> None:
    assert get_sgr_requirement("9506999000", description) is None


@pytest.mark.parametrize(
    ("description", "expected_trigger"),
    [
        ("БАД витаминный комплекс", "бад"),
        ("Капсулы (БАД), 60 шт.", "бад"),
        ("БАД-комплекс", "бад"),
        ("БАД\u00a0в капсулах", "бад"),
        ("БАД\u2003в капсулах", "бад"),
        ("состав БАДа", "бада"),
        ("прилагается к БАДу", "баду"),
        ("набор с БАДом", "бадом"),
        ("информация о БАДе", "баде"),
        ("БАДы в таблетках", "бады"),
        ("комплект БАДов", "бадов"),
        ("добавки к БАДам", "бадам"),
        ("набор с БАДами", "бадами"),
        ("маркировка на БАДах", "бадах"),
        (
            "биологически активная добавка",
            "биологически активная добавка",
        ),
        ("биодобавка в капсулах", "биодобавка"),
    ],
)
def test_legacy_sgr_preserves_explicit_bad_wording(
    description: str,
    expected_trigger: str,
) -> None:
    row = get_sgr_requirement("9506999000", description)
    assert row is not None
    assert row["trigger"] == expected_trigger


@pytest.mark.parametrize(
    ("description", "expect_sgr"),
    [
        ("набор для бадминтона", False),
        ("бад\u200dминтон", False),
        ("бад＿минтон", False),
        ("БАД витаминный комплекс", True),
        ("состав БАДа", True),
        ("биодобавка в капсулах", True),
    ],
)
def test_v2_imported_sgr_uses_same_token_boundary(
    memory_sessionmaker: sessionmaker,
    description: str,
    expect_sgr: bool,
) -> None:
    import_ntm_layers_to_ntm_v2()
    from app.services.ntm_engine_v2 import evaluate_ntm_v2

    result = evaluate_ntm_v2(
        hs_code="9506999000",
        description=description,
        source_kinds={"legacy_ntm_layers"},
    )
    sgr_rows = [row for row in result["requirements"] if row.get("measure_kind") == "sgr"]
    assert bool(sgr_rows) is expect_sgr
