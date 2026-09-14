"""Preserve recorded payment uncertainty across compact views and exports.

These helpers interpret saved result metadata only. They do not establish legal
eligibility or invent a finality flag for older records that did not store one.
"""
from __future__ import annotations

from typing import Any, Iterable


def payment_result_metadata(result: Any) -> dict[str, Any]:
    result = result if isinstance(result, dict) else {}
    quality = result.get("data_quality")
    quality = quality if isinstance(quality, dict) else {}
    preference = result.get("tariff_preference")
    preference = preference if isinstance(preference, dict) else {}
    status = result.get("payment_status", result.get("status"))
    status = status if isinstance(status, str) and status else None
    provisional = result.get("amounts_provisional", quality.get("amounts_provisional"))
    provisional = provisional if isinstance(provisional, bool) else None
    warning = result.get("tariff_preference_warning") or quality.get("tariff_preference_warning")
    if preference.get("status") == "needs_review":
        provisional = True
        warning = preference.get("reason") or warning
    if provisional is True:
        status = "REVIEW_REQUIRED"
    if preference.get("status") == "needs_review" and not warning:
        warning = "Применимость тарифной преференции не подтверждена."
    reason = result.get("payment_review_reason") or quality.get("payment_review_reason") or warning
    reason_codes = result.get("payment_review_reasons") or quality.get("payment_review_reasons") or []
    reason_codes = list(dict.fromkeys(code for code in reason_codes if isinstance(code, str))) if isinstance(reason_codes, list) else []
    return {
        "payment_status": status,
        "amounts_provisional": provisional,
        "tariff_preference_warning": warning if isinstance(warning, str) and warning else None,
        "payment_review_reason": reason if isinstance(reason, str) and reason else None,
        "payment_review_reasons": reason_codes,
    }


def aggregate_payment_metadata(results: Iterable[Any]) -> dict[str, Any]:
    rows = [payment_result_metadata(result) for result in results]
    flags = [row["amounts_provisional"] for row in rows]
    provisional = True if True in flags else (False if flags and all(flag is False for flag in flags) else None)
    statuses = {row["payment_status"] for row in rows}
    status = "REVIEW_REQUIRED" if provisional is True or "REVIEW_REQUIRED" in statuses else (
        next(iter(statuses)) if len(statuses) == 1 else None
    )
    warnings = list(dict.fromkeys(row["tariff_preference_warning"] for row in rows if row["tariff_preference_warning"]))
    reasons = list(dict.fromkeys(row["payment_review_reason"] for row in rows if row["payment_review_reason"]))
    reason_codes = list(dict.fromkeys(code for row in rows for code in row["payment_review_reasons"]))
    return {
        "payment_status": status,
        "amounts_provisional": provisional,
        "tariff_preference_warning": "; ".join(warnings) or None,
        "payment_review_reason": "; ".join(reasons) or None,
        "payment_review_reasons": reason_codes,
    }
