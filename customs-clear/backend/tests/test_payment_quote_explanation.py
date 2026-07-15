"""Deterministic tests for the Smart Payments explanation contract."""

from __future__ import annotations

from unittest.mock import patch

from app.services.payment_quote_service import build_payment_quote


def _raw_quote() -> dict:
    return {
        "status": "OK",
        "country": "CN",
        "customs_value": 100_000.0,
        "freight": 0.0,
        "insurance": 150.0,
        "auto_detected": {
            "excise_type": "none",
            "antidumping_type": "none",
        },
        "breakdown": {
            "duty_rate": 10.0,
            "duty": 10_000.0,
            "vat_rate": 22.0,
            "vat_base": 110_000.0,
            "vat": 24_200.0,
            "customs_fee": 1_231.0,
            "excise": 0.0,
            "excise_reason": "Не применяется",
            "antidumping": 0.0,
            "antidumping_status": "n/a",
            "antidumping_reason": "Не применяется",
            "special_duties_amount": 0.0,
            "total_payable": 35_431.0,
        },
        "data_quality": {
            "confidence": "high",
            "matched_prefix": "8509400000",
            "match_length": 10,
            "source_code": "EEC_ETT",
            "antidumping_status": "n/a",
        },
        "legal_basis": {
            "duty": "ЕТТ ЕАЭС: адвалорная ставка 10%.",
            "customs_fee": "Шкала таможенных сборов РФ 2026.",
        },
        "sources": [{"name": "ЕТТ ЕАЭС", "integrated": True}],
        "special_duties": [],
        "geo": {"embargo": False},
    }


def _line(quote, code: str):
    return next(item for item in quote.line_items if item.code == code)


def test_quote_exposes_calculation_bases_and_canonical_anchor() -> None:
    anchor = {
        "stable_id": "node-0123456789abcdef01234567",
        "snapshot_id": "snap-v2-0123456789abcdef0123456789abcdef",
        "code": "8509400000",
        "node_type": "commodity",
    }
    with (
        patch("app.services.payment_quote_service.get_rates_map", return_value={"RUB": 1.0}),
        patch("app.services.payment_quote_service.compute_payments", return_value=_raw_quote()),
        patch(
            "app.services.payment_quote_service._special_duties_configured_for_hs",
            return_value=False,
        ),
        patch(
            "app.services.payment_quote_service.canonical_anchor_for_hs",
            return_value=anchor,
        ),
    ):
        quote = build_payment_quote(
            {
                "hs_code": "8509400000",
                "customs_value": 100_000,
                "invoice_currency": "RUB",
                "country": "CN",
            }
        )

    duty = _line(quote, "duty")
    vat = _line(quote, "vat")
    fee = _line(quote, "customs_fee")
    assert duty.basis_label == "Таможенная стоимость"
    assert duty.basis_amount_rub == 100_000.0
    assert vat.basis_amount_rub == 110_000.0
    assert "пошлина" in vat.basis_label.lower()
    assert fee.basis_amount_rub == 100_000.0
    assert quote.canonical_anchor is not None
    assert quote.canonical_anchor.model_dump() == anchor
    assert quote.total_payable_rub is None
    assert quote.total_partial_rub == 35_431.0


def test_explanation_fields_are_additive_for_non_formula_lines() -> None:
    with (
        patch("app.services.payment_quote_service.get_rates_map", return_value={"RUB": 1.0}),
        patch("app.services.payment_quote_service.compute_payments", return_value=_raw_quote()),
        patch(
            "app.services.payment_quote_service._special_duties_configured_for_hs",
            return_value=False,
        ),
        patch("app.services.payment_quote_service.canonical_anchor_for_hs", return_value=None),
    ):
        quote = build_payment_quote(
            {"hs_code": "8509400000", "customs_value": 100_000, "invoice_currency": "RUB"}
        )

    excise = _line(quote, "excise")
    assert excise.reason == "Не применяется"
    assert excise.source == "hs_rates (НК РФ ст. 193)"
    assert excise.basis_label == ""
    assert excise.basis_amount_rub is None
    assert quote.canonical_anchor is None
