"""Fail-closed regressions for source-unbound fixed antidumping rates."""

from collections.abc import Iterator
from contextlib import contextmanager

from app.db import SessionLocal
from app.models.core import HsRate
from app.services.normative_store import find_rate_for_hs, init_db
from app.services.payment_engine import _resolve_antidumping, compute_payments
from app.services.payment_quote_service import _resolve_antidumping_line, build_payment_quote


@contextmanager
def _temporary_7214_antidumping_type(value: str) -> Iterator[None]:
    init_db()
    matched, _ = find_rate_for_hs("7214990000")
    assert matched is not None
    row_id = matched.id
    with SessionLocal() as db:
        row = db.query(HsRate).filter(HsRate.id == row_id).one_or_none()
        assert row is not None
        original = (
            row.antidumping_type,
            row.antidumping_value,
            row.antidumping_condition,
            row.antidumping_countries,
        )
        row.antidumping_type = value
        row.antidumping_value = 613.0
        row.antidumping_condition = "candidate source row"
        row.antidumping_countries = "CN"
        db.commit()
    try:
        yield
    finally:
        with SessionLocal() as db:
            row = db.query(HsRate).filter(HsRate.id == row_id).one_or_none()
            assert row is not None
            (
                row.antidumping_type,
                row.antidumping_value,
                row.antidumping_condition,
                row.antidumping_countries,
            ) = original
            db.commit()


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


def test_supported_antidumping_types_are_normalized() -> None:
    fixed_amount, _, fixed_status = _resolve_antidumping(
        "  FIXED  ", 613.0, "candidate", "CN", "CN", 100_000.0, 20.0
    )
    percent_amount, _, percent_status = _resolve_antidumping(
        "  PERCENT  ", 18.0, "candidate", "CN", "CN", 100_000.0, 20.0
    )

    assert fixed_amount == 0.0
    assert fixed_status == "manual_review"
    assert percent_amount == 18_000.0
    assert percent_status == "applied"


def test_unknown_nonempty_antidumping_type_fails_closed() -> None:
    amount, reason, status = _resolve_antidumping(
        "legacy_fixed_per_kg", 613.0, "candidate", "CN", "DE", 100_000.0, 20.0
    )

    assert amount == 0.0
    assert status == "manual_review"
    assert "неизвестный тип" in reason
    assert "не применяется" not in reason.lower()


def test_fixed_antidumping_withholds_dependent_vat_and_final_totals_end_to_end() -> None:
    payload = {
        "hs_code": "7214990000",
        "customs_value": 100_000.0,
        "freight": 0.0,
        "country": "CN",
        "quantity": 20.0,
        "invoice_currency": "RUB",
    }
    with _temporary_7214_antidumping_type("  FIXED  "):
        raw = compute_payments(payload)
        quote = build_payment_quote(payload)

    breakdown = raw["breakdown"]
    assert raw["status"] == "REVIEW_REQUIRED"
    assert breakdown["antidumping_status"] == "manual_review"
    assert breakdown["antidumping"] == 0.0
    assert breakdown["vat_base"] is None
    assert breakdown["vat"] is None
    assert breakdown["vat_status"] == "manual_review"
    assert breakdown["vat_base_provisional"] > 0.0
    assert breakdown["vat_provisional"] > 0.0
    assert breakdown["total_payable"] is None
    assert breakdown["total_payable_status"] == "withheld"
    assert breakdown["total_payable_provisional"] > 0.0

    lines = {line.code: line for line in quote.line_items}
    assert quote.status == "REVIEW_REQUIRED"
    assert lines["antidumping"].status == "manual_review_required"
    assert lines["antidumping"].amount_rub is None
    assert lines["vat"].status == "manual_review_required"
    assert lines["vat"].amount_rub is None
    assert "базу НДС" in lines["vat"].reason
    assert quote.total_payable_rub is None


def test_unknown_antidumping_type_withholds_raw_and_quote_totals_end_to_end() -> None:
    payload = {
        "hs_code": "7214990000",
        "customs_value": 100_000.0,
        "country": "CN",
        "quantity": 20.0,
        "invoice_currency": "RUB",
    }
    with _temporary_7214_antidumping_type("legacy_fixed_per_kg"):
        raw = compute_payments(payload)
        quote = build_payment_quote(payload)

    assert raw["auto_detected"]["antidumping_type"] == "legacy_fixed_per_kg"
    assert raw["data_quality"]["antidumping_status"] == "manual_review"
    assert raw["breakdown"]["vat"] is None
    assert raw["breakdown"]["total_payable"] is None
    lines = {line.code: line for line in quote.line_items}
    assert lines["antidumping"].status == "manual_review_required"
    assert lines["vat"].status == "manual_review_required"
    assert quote.total_payable_rub is None
