"""Failure boundaries for optional grounding dependencies."""

from __future__ import annotations

import asyncio
import sqlite3
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
import requests
from sqlalchemy.exc import (
    InvalidRequestError,
    OperationalError,
    ProgrammingError,
    StatementError,
)

from app.services import grounded_assistant


_SECRET_ERROR = "grounding failure https://provider.invalid?key=SECRET"


def _patch_stage(
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
    error: BaseException,
    warnings: list[tuple[Any, ...]] | None = None,
) -> tuple[dict[str, Any], list[tuple[Any, ...]]]:
    warnings = warnings if warnings is not None else []
    monkeypatch.setattr(
        grounded_assistant.logger,
        "warning",
        lambda *args, **kwargs: warnings.append(args),
    )
    monkeypatch.setattr(grounded_assistant, "canonical_anchor_for_hs", lambda code: None)
    monkeypatch.setattr(
        grounded_assistant,
        "canonical_anchors_for_hs_codes",
        lambda codes: {},
    )

    if stage == "tnved":
        monkeypatch.setattr(
            grounded_assistant,
            "get_tnved_context_for_hs",
            lambda code: (_ for _ in ()).throw(error),
        )
    else:
        monkeypatch.setattr(
            grounded_assistant,
            "get_tnved_context_for_hs",
            lambda code: {},
        )

    if stage == "ntm":
        non_tariff = AsyncMock(side_effect=error)
    else:
        non_tariff = AsyncMock(
            return_value={"normative_block": {}, "risk_block": {}}
        )
    monkeypatch.setattr(grounded_assistant, "check_position_non_tariff", non_tariff)

    if stage == "search":
        monkeypatch.setattr(
            grounded_assistant,
            "search_commodities_smart",
            lambda query, limit: (_ for _ in ()).throw(error),
        )
    else:
        monkeypatch.setattr(
            grounded_assistant,
            "search_commodities_smart",
            lambda query, limit: {"results": []},
        )

    context = {} if stage == "search" else {"hs_code": "8516108008"}
    bundle = asyncio.run(
        grounded_assistant.build_chat_grounding_bundle(
            message="электрический чайник",
            history=[],
            current_context=context,
        )
    )
    return bundle, warnings


@pytest.mark.parametrize(
    ("stage", "error", "limitation"),
    [
        (
            "tnved",
            sqlite3.OperationalError(_SECRET_ERROR),
            "Карточка ТН ВЭД временно недоступна",
        ),
        (
            "ntm",
            OperationalError(
                "SELECT secret",
                {},
                sqlite3.OperationalError(_SECRET_ERROR),
            ),
            "Нетарифные требования и риск-контур временно не удалось проверить",
        ),
        (
            "search",
            httpx.ConnectError(
                _SECRET_ERROR,
                request=httpx.Request("GET", "https://provider.invalid?key=SECRET"),
            ),
            "Не удалось подобрать кандидатов ТН ВЭД",
        ),
        (
            "tnved",
            OSError(_SECRET_ERROR),
            "Карточка ТН ВЭД временно недоступна",
        ),
        (
            "ntm",
            TimeoutError(_SECRET_ERROR),
            "Нетарифные требования и риск-контур временно не удалось проверить",
        ),
        (
            "search",
            requests.ConnectionError(_SECRET_ERROR),
            "Не удалось подобрать кандидатов ТН ВЭД",
        ),
    ],
)
def test_bounded_dependency_failures_keep_conservative_fallback_without_log_leakage(
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
    error: BaseException,
    limitation: str,
) -> None:
    bundle, warnings = _patch_stage(monkeypatch, stage, error)

    assert any(limitation in item for item in bundle["limitations"])
    assert warnings
    warning_material = " ".join(str(value) for call in warnings for value in call)
    assert type(error).__name__ in warning_material
    assert "SECRET" not in warning_material
    assert "provider.invalid" not in warning_material


@pytest.mark.parametrize("stage", ["tnved", "ntm", "search"])
@pytest.mark.parametrize(
    "error_type",
    [TypeError, ValueError, AttributeError, AssertionError, KeyError, RuntimeError],
)
def test_unexpected_programming_errors_propagate_without_logging(
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
    error_type: type[BaseException],
) -> None:
    error = error_type(_SECRET_ERROR)
    warnings: list[tuple[Any, ...]] = []

    with pytest.raises(error_type) as caught:
        _patch_stage(monkeypatch, stage, error, warnings)

    assert caught.value is error
    assert warnings == []


@pytest.mark.parametrize("stage", ["tnved", "ntm", "search"])
@pytest.mark.parametrize(
    "error",
    [
        sqlite3.ProgrammingError(_SECRET_ERROR),
        ProgrammingError(
            "SELECT broken",
            {},
            sqlite3.ProgrammingError(_SECRET_ERROR),
        ),
        InvalidRequestError(_SECRET_ERROR),
        StatementError(
            _SECRET_ERROR,
            "SELECT broken",
            {},
            ValueError(_SECRET_ERROR),
        ),
    ],
)
def test_sql_and_orm_programming_errors_propagate_without_logging(
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
    error: BaseException,
) -> None:
    warnings: list[tuple[Any, ...]] = []

    with pytest.raises(type(error)) as caught:
        _patch_stage(monkeypatch, stage, error, warnings)

    assert caught.value is error
    assert warnings == []
