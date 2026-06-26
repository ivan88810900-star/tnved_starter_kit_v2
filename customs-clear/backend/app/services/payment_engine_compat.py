"""Импорт расчёта платежей: основной модуль или заглушка, если файл payment_engine.py отсутствует."""

from __future__ import annotations

import importlib.util
from typing import Any, Callable

_compare: Callable[[dict[str, Any]], dict[str, Any]] | None = None
_compute: Callable[[dict[str, Any]], dict[str, Any]] | None = None
_get_rule: Callable[[str], dict[str, Any] | None] | None = None
_get_meta: Callable[[str], dict[str, Any] | None] | None = None


def _load() -> None:
    global _compare, _compute, _get_rule, _get_meta
    if _compute is not None:
        return
    spec = importlib.util.find_spec("app.services.payment_engine")
    if spec is None:
        from . import payment_engine_stub as _stub

        _compute = _stub.compute_payments
        _compare = _stub.compare_payment_scenarios
        _get_rule = lambda _hs: None
        _get_meta = lambda _hs: None
        return
    from . import payment_engine as _pe

    _compute = _pe.compute_payments
    _compare = _pe.compare_payment_scenarios
    _get_rule = _pe.get_duty_rule_info
    _get_meta = getattr(_pe, "get_commodity_meta_info", lambda _hs: None)


def compute_payments(payload: dict[str, Any]) -> dict[str, Any]:
    _load()
    assert _compute is not None
    return _compute(payload)


def compare_payment_scenarios(payload: dict[str, Any]) -> dict[str, Any]:
    _load()
    assert _compare is not None
    return _compare(payload)


def get_duty_rule_info(hs_code: str) -> dict[str, Any] | None:
    _load()
    assert _get_rule is not None
    return _get_rule(hs_code)


def get_commodity_meta_info(hs_code: str) -> dict[str, Any] | None:
    _load()
    assert _get_meta is not None
    return _get_meta(hs_code)
