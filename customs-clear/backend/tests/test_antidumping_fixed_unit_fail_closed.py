"""Fail-closed regressions for source-unbound fixed antidumping rates."""

from app.services.payment_engine import _resolve_antidumping
from app.services.payment_quote_service import _resolve_antidumping_line


def test_fixed_antidumping_does_not_use_generic_quantity() -> None:
    amount, reason, status = _resolve_antidumping(
        "fixed",
        613.0,
        "candidate source row",
        "CN",
        "CN",
        100_000.0,
        20.0,
    )

    assert amount == 0.0
    assert status == "manual_review"
    assert "валюта, единица и знаменатель" in reason
    assert "20.0" in reason


def test_fixed_antidumping_review_withholds_quote_amount_and_final_signal() -> None:
    amount, reason, status = _resolve_antidumping(
        "fixed",
        613.0,
        "candidate source row",
        "CN",
        "CN",
        100_000.0,
        20.0,
    )
    line = _resolve_antidumping_line(
        raw={
            "auto_detected": {
                "antidumping_type": "fixed",
                "antidumping_value": 613.0,
            },
            "breakdown": {
                "antidumping": amount,
                "antidumping_reason": reason,
                "antidumping_status": status,
            },
            "data_quality": {"antidumping_status": status},
        }
    )

    assert line.status == "manual_review_required"
    assert line.amount_rub is None
    assert "универсальное количество" in (line.reason or "")


def test_percentage_antidumping_remains_computable() -> None:
    amount, reason, status = _resolve_antidumping(
        "percent",
        18.0,
        "candidate source row",
        "CN",
        "CN",
        100_000.0,
        20.0,
    )

    assert amount == 18_000.0
    assert status == "applied"
    assert "18.0%" in reason


def test_fixed_antidumping_country_mismatch_remains_not_applicable() -> None:
    amount, reason, status = _resolve_antidumping(
        "fixed",
        613.0,
        "candidate source row",
        "CN",
        "DE",
        100_000.0,
        20.0,
    )

    assert amount == 0.0
    assert status == "n/a"
    assert "не входит в список" in reason
