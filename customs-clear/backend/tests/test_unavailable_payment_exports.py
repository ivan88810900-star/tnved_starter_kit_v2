"""Unavailable final payments must stay unavailable in exports and history."""

from __future__ import annotations

from datetime import datetime
from io import BytesIO
from types import SimpleNamespace

from openpyxl import load_workbook

from app.services.calculation_history_service import _history_list_row
from app.services.export_service import generate_final_customs_excel


def _history_record(*, kind: str, output: dict) -> SimpleNamespace:
    return SimpleNamespace(
        id="test-history",
        document_id=None,
        user_ref="",
        currency="RUB",
        created_at=datetime(2026, 9, 29, 10, 0, 0),
        input_payload={"_history_kind": kind, "hs_code": "9999999999"},
        output_payload=output,
    )


def test_excel_keeps_unavailable_final_payment_blank_instead_of_numeric_zero() -> None:
    payload = generate_final_customs_excel(
        [
            {
                "item_description": "requires review",
                "payment_profile": {
                    "status": "REVIEW_REQUIRED",
                    "hs_code": "9999999999",
                    "breakdown": {"total_payable": None},
                    "documents": [],
                },
            },
            {
                "item_description": "confirmed zero",
                "payment_profile": {
                    "status": "OK",
                    "hs_code": "0000000000",
                    "breakdown": {"total_payable": 0.0},
                    "documents": [],
                },
            },
        ]
    )
    sheet = load_workbook(BytesIO(payload), data_only=True).active

    assert sheet["F2"].value is None
    assert sheet["F3"].value == 0


def test_compliance_history_does_not_sum_missing_item_as_zero() -> None:
    row = _history_list_row(
        _history_record(
            kind="compliance",
            output={
                "items_summary": [
                    {"hs_code": "1111111111", "total_payable": 100.0},
                    {"hs_code": "2222222222", "total_payable": None},
                ]
            },
        )
    )
    assert row["total_payable"] is None


def test_copilot_batch_history_does_not_sum_missing_item_as_zero() -> None:
    row = _history_list_row(
        _history_record(
            kind="copilot_batch",
            output={"payments": [{"total": 100.0}, {"total": None}]},
        )
    )
    assert row["total_payable"] is None


def test_history_still_sums_fully_available_totals_including_real_zero() -> None:
    compliance = _history_list_row(
        _history_record(
            kind="compliance",
            output={"items_summary": [{"total_payable": 0.0}, {"total_payable": 25.0}]},
        )
    )
    batch = _history_list_row(
        _history_record(
            kind="copilot_batch",
            output={"payments": [{"total": 0.0}, {"total": 25.0}]},
        )
    )
    assert compliance["total_payable"] == 25.0
    assert batch["total_payable"] == 25.0
