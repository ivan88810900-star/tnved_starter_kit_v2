"""Strict selection of the simple numeric forms supported by remedy rows."""
from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from .official_rate_validation import explicit_nonnegative_rate


def normalize_trade_remedy_rate(raw: dict[str, Any], *, family_alias: str) -> tuple[str, float, float]:
    """Reject missing, contradictory or unsupported rates before database planning.

    Only one percent or specific component can be imported. An explicitly zero
    inactive component is harmless; a second nonzero component needs an operator
    that the current ingestion contract cannot preserve.
    """
    if "needs_verification" in raw and type(raw["needs_verification"]) is not bool:
        raise ValueError("invalid_needs_verification_type")
    forms: list[str] = []
    for key in ("rate_type", family_alias + "_type", "duty_type"):
        if key not in raw:
            continue
        value = raw[key]
        if not isinstance(value, str) or value.strip().lower() not in {"percent", "fixed", "specific"}:
            raise ValueError("unsupported_rate_type:" + key)
        forms.append(value.strip().lower())
    if len({"specific" if form == "fixed" else form for form in forms}) > 1:
        raise ValueError("conflicting_rate_types")

    numeric: dict[str, Decimal] = {}
    generic_keys = ("rate_value", family_alias + "_value")
    specific_keys = ("rate_specific", "rate_specific_value")
    for key in (*generic_keys, "rate_percent", *specific_keys):
        if key in raw:
            try:
                explicit_nonnegative_rate(raw[key])
                # Compare the validated source values before the Float storage
                # conversion can collapse distinct decimal aliases to one value.
                numeric[key] = Decimal(str(raw[key]).strip().replace(",", "."))
            except ValueError as exc:
                raise ValueError("invalid_numeric_rate:" + key + ":" + str(exc)) from exc

    if forms:
        rate_type = forms[0]
    elif "rate_percent" in numeric and not any(numeric.get(key, 0) for key in specific_keys):
        rate_type = "percent"
    elif any(key in numeric for key in specific_keys) and not numeric.get("rate_percent", 0):
        rate_type = "specific"
    else:
        raise ValueError("missing_or_ambiguous_rate_type")

    if rate_type == "percent":
        selected_keys = (*generic_keys, "rate_percent")
        inactive_keys = specific_keys
    else:
        selected_keys = (*generic_keys, *specific_keys)
        inactive_keys = ("rate_percent",)
    values = [numeric[key] for key in selected_keys if key in numeric]
    if not values:
        raise ValueError("missing_rate_value")
    if any(value != values[0] for value in values[1:]):
        raise ValueError("conflicting_rate_values")
    if any(numeric.get(key, 0) != 0 for key in inactive_keys):
        raise ValueError("unsupported_multiple_rate_components")

    if rate_type != "percent":
        currencies: list[str] = []
        for key in ("currency_code", "currency"):
            if key not in raw:
                continue
            value = raw[key]
            if not isinstance(value, str) or re.fullmatch(r"[A-Z]{3}", value.strip().upper()) is None:
                raise ValueError("missing_or_invalid_specific_currency")
            currencies.append(value.strip().upper())
        if not currencies:
            raise ValueError("missing_or_invalid_specific_currency")
        if len(set(currencies)) > 1:
            raise ValueError("conflicting_specific_currencies")

        units: list[str] = []
        for key in ("specific_uom", "specific_unit", "unit", "uom", "rate_unit", "rate_uom",
                    "rate_specific_unit", "rate_specific_uom", "quantity_unit"):
            if key not in raw or raw[key] is None:
                continue
            value = raw[key]
            if not isinstance(value, str):
                raise ValueError("invalid_specific_unit")
            if value.strip():
                units.append(value.strip().casefold())
        if len(set(units)) > 1:
            raise ValueError("conflicting_specific_units")
        if units:
            # SpecialDuty has no unit column. Do not discard an explicit source
            # denominator and reinterpret it as the payment quantity argument.
            raise ValueError("unsupported_explicit_specific_unit")
    amount = float(values[0])
    return rate_type, amount if rate_type == "percent" else 0.0, amount if rate_type != "percent" else 0.0
