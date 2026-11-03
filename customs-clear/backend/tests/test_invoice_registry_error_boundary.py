"""Failure boundary for invoice state-registry lookups."""

from __future__ import annotations

import sqlite3
from typing import Any

import pytest
from sqlalchemy.exc import OperationalError

from app.services import invoice_analyzer


_SECRET_ERROR = "registry failure https://provider.invalid?key=SECRET"


def _compute(monkeypatch: pytest.MonkeyPatch, error: Exception) -> dict[str, Any]:
    def fail_lookup(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise error

    monkeypatch.setattr(invoice_analyzer, "lookup_state_registries", fail_lookup)
    return invoice_analyzer._compute_registry_check_payload(
        {"name_ru": "Тестовый товар"},
        {"manufacturer": "Test Maker"},
        "3304990000",
        object(),  # type: ignore[arg-type]
    )


def test_database_failure_returns_explicit_unavailable_without_raw_log_leakage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warnings: list[tuple[Any, ...]] = []
    monkeypatch.setattr(
        invoice_analyzer.logger,
        "warning",
        lambda *args, **kwargs: warnings.append(args),
    )
    error = OperationalError(
        "SELECT * FROM registry WHERE token='SECRET'",
        {},
        sqlite3.OperationalError(_SECRET_ERROR),
    )

    result = _compute(monkeypatch, error)

    assert result["status"] == invoice_analyzer._REGISTRY_DB_UNAVAILABLE_MSG
    assert result["recommendation"] == invoice_analyzer._REGISTRY_DB_UNAVAILABLE_MSG
    assert result["sgr"]["status"] == invoice_analyzer._REGISTRY_DB_UNAVAILABLE_MSG
    assert result["status"] != invoice_analyzer._REGISTRY_CHECK_EMPTY["status"]
    assert warnings
    warning_material = " ".join(str(value) for call in warnings for value in call)
    assert type(error).__name__ in warning_material
    assert "SECRET" not in warning_material
    assert "provider.invalid" not in warning_material


@pytest.mark.parametrize("error_type", [TypeError, ValueError, RuntimeError])
def test_unexpected_programming_errors_propagate_without_raw_log_leakage(
    monkeypatch: pytest.MonkeyPatch,
    error_type: type[Exception],
) -> None:
    warnings: list[tuple[Any, ...]] = []
    monkeypatch.setattr(
        invoice_analyzer.logger,
        "warning",
        lambda *args, **kwargs: warnings.append(args),
    )
    error = error_type(_SECRET_ERROR)

    with pytest.raises(error_type, match="provider\\.invalid") as caught:
        _compute(monkeypatch, error)

    assert caught.value is error
    assert warnings == []
