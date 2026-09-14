"""Invoice/document exports retain payment review requirements after compaction."""
from __future__ import annotations

import asyncio
from contextlib import nullcontext

import fitz
import pytest

from app.services import invoice_batch_service as invoices
from app.services.payment_result_status import payment_result_metadata
from app.services.ved_intel_analyze_core import slim_ved_intel_for_persist
from app.services.ved_report_pdf import build_ved_report_html, build_ved_report_pdf


GENERIC_REASON = "Источник ставки пошлины не найден; сумма предварительная."


def payment(*, pending: bool = True, reason: str = GENERIC_REASON) -> dict:
    return {
        "status": "REVIEW_REQUIRED" if pending else "OK",
        "amounts_provisional": pending,
        "payment_review_reason": reason if pending else None,
        "payment_review_reasons": ["missing_duty_source"] if pending else [],
        "breakdown": {"duty": 100, "vat": 250, "excise": 0, "customs_fee": 10, "total_payable": 360},
    }


@pytest.mark.parametrize("pending", [True, False])
def test_invoice_line_preserves_review_status_without_changing_arithmetic(monkeypatch, pending):
    monkeypatch.setattr(invoices, "compute_payments", lambda _: payment(pending=pending))
    row = invoices.calculate_line_payments({"hs_code": "7112300000", "quantity": 2, "unit_price": 1000})
    assert row["total_payable"] == 360
    assert row["amounts_provisional"] is pending
    assert row["payment_status"] == ("REVIEW_REQUIRED" if pending else "OK")
    assert row["payments_status"] == row["payment_status"]
    assert row["payment_review_reason"] == (GENERIC_REASON if pending else None)
    assert row["tariff_preference_warning"] is None


@pytest.mark.parametrize("pending", [True, False])
def test_invoice_batch_totals_carry_aggregate_review(monkeypatch, pending):
    monkeypatch.setattr(invoices, "SessionLocal", lambda: nullcontext(object()))
    monkeypatch.setattr(invoices, "compute_payments", lambda row: payment(
        pending=pending and row["country"] == "BR",
    ))
    result = asyncio.run(invoices.calculate_batch_lines([
        {"hs_code": "7112300000", "quantity": 1, "unit_price": 1000, "country": "BR"},
        {"hs_code": "7112910000", "quantity": 1, "unit_price": 1000, "country": "CN"},
    ], auto_classify=False))
    assert result["status"] == ("REVIEW_REQUIRED" if pending else "OK")
    assert result["totals"]["total_payable"] == 720
    assert result["amounts_provisional"] is pending
    assert result["totals"]["amounts_provisional"] is pending
    assert result["totals"]["payment_review_reason"] == (GENERIC_REASON if pending else None)
    assert result["tariff_preference_warning"] is None


def test_invoice_older_result_does_not_gain_finality(monkeypatch):
    monkeypatch.setattr(invoices, "SessionLocal", lambda: nullcontext(object()))
    monkeypatch.setattr(invoices, "compute_payments", lambda _: {"status": "OK", "breakdown": {"total_payable": 10}})
    result = asyncio.run(invoices.calculate_batch_lines([{"hs_code": "7112300000"}], auto_classify=False))
    assert result["amounts_provisional"] is None
    assert result["totals"]["amounts_provisional"] is None


def test_persisted_document_light_rows_keep_generic_reason_and_preference_evidence():
    pending = payment()
    pending["tariff_preference"] = {"status": "needs_review", "reason": "Право на преференцию не подтверждено.", "applied": False}
    intel = {"ved_intel_status": "OK", "copilot_batch": {"bundles": [
        {"effective_hs_code": "7112300000", "payment": pending, "non_tariff": {"status": "OK"}},
        {"effective_hs_code": "7112910000", "payment": payment(pending=False)},
        {"effective_hs_code": "7112920000", "payment": {"breakdown": {"total_payable": 20}}},
    ]}}
    slim = slim_ved_intel_for_persist(intel)
    assert "copilot_batch" not in slim
    assert slim["amounts_provisional"] is True
    assert slim["payment_status"] == "REVIEW_REQUIRED"
    assert slim["payment_review_reason"] == GENERIC_REASON
    row = slim["copilot_batch_light"][0]
    assert row["payment_review_reason"] == GENERIC_REASON
    assert row["payment_review_reasons"] == ["missing_duty_source"]
    assert row["tariff_preference"] == pending["tariff_preference"]
    assert slim["copilot_batch_light"][2]["amounts_provisional"] is None
    assert slim["ved_intel_status"] == "OK"  # Document pipeline completion is a separate status.


def report_payload() -> dict:
    return {"status": "OK", "copilot_positions": [
        {"effective_hs_code": "7112300000", "non_tariff_status": "OK", "total_payable": 360,
         **payment_result_metadata(payment())},
        {"effective_hs_code": "7112910000", "non_tariff_status": "OK", "total_payable": 360,
         **payment_result_metadata(payment(pending=False))},
        {"effective_hs_code": "7112920000", "non_tariff_status": "OK", "total_payable": 20},
    ]}


def test_pdf_html_labels_pending_and_unknown_amounts_and_escapes_reason():
    data = report_payload()
    data["copilot_positions"][0]["payment_review_reason"] += " <script>alert(1)</script>"
    html = build_ved_report_html(data)
    assert "Платежи предварительные: требуется проверка" in html
    assert "Статус проверки суммы не сохранён" in html
    assert "REVIEW_REQUIRED" in html
    assert GENERIC_REASON in html
    assert "&lt;script&gt;" in html
    assert "<script>" not in html


def test_generated_pdf_retains_review_reason_and_unknown_status():
    pdf = build_ved_report_pdf(report_payload())
    with fitz.open(stream=pdf, filetype="pdf") as doc:
        text = " ".join(page.get_text() for page in doc)
        text = " ".join(text.split())
    assert "REVIEW_REQUIRED" in text
    assert "Платежи предварительные" in text
    assert "Статус проверки суммы не сохранён" in text
    assert "Источник ставки пошлины не найден" in text
    assert "7112300000" in text and "7112920000" in text
