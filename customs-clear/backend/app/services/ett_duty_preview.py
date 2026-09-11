"""Exact, offline arithmetic for an explicitly selected ETT candidate expression.

This module never selects applicable law, reads a DB, fetches exchange rates, or
produces a final customs payment. Its input duty is the existing immutable
``ETTDuty`` contract. Currency factors are caller-supplied observations, including
unverified source references; their shape and quote digest do not authenticate the
factor. No statutory rounding, cross-rate, unit conversion or quantity inference
is performed. Quantities mean the total specified basis for this calculation,
including total engine displacement where that is the explicit duty unit.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from fractions import Fraction
from typing import Literal
from urllib.parse import urlsplit

from .ett_manifest import ETTDuty


ExactNumber = Decimal | int | str
Currency = Literal["EUR", "USD", "RUB"]
_CURRENCIES = frozenset({"EUR", "USD", "RUB"})
_UNITS = frozenset({
    "kg", "g", "tonne", "litre", "m3", "m2", "m", "unit", "pair", "kwh",
    "engine_displacement_cm3",
})
_NUMBER = re.compile(r"(?:0|[1-9][0-9]{0,23})(?:\.[0-9]{1,12})?\Z", re.ASCII)
_HASH = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)


@dataclass(frozen=True)
class ETTPreviewExchangeRate:
    """A declared directed factor: one source unit buys ``multiplier`` target units.

    ``as_of`` is the explicitly asserted applicable date, not a retrieval date.
    Source fields are references only: original bytes and extraction of this
    factor from them are not verified by this arithmetic module.
    """

    from_currency: Currency
    to_currency: Currency
    as_of: date
    multiplier: ExactNumber
    source_url: str
    source_artifact_sha256: str
    source_locator: str
    source_text: str
    source_text_sha256: str


@dataclass(frozen=True)
class ETTDutyPreviewStep:
    """An exact trace operation in the result currency.

    For ``multiply_divide``, multiply every operand except the last and divide
    by the last operand. The inputs retain their explicit currencies and units
    in the parent result. No intermediate monetary rounding is implied.
    """

    operation: Literal["multiply_divide", "max", "min", "sum"]
    operands: tuple[Decimal, ...]
    result: Decimal


@dataclass(frozen=True)
class ETTDutyPreview:
    status: Literal["calculated", "needs_clarification", "unavailable"]
    reason: str
    duty: ETTDuty
    as_of: date
    currency: Currency
    customs_value: Decimal | None = None
    quantity: Decimal | None = None
    quantity_unit: str | None = None
    exchange_rate: ETTPreviewExchangeRate | None = None
    amount: Decimal | None = None
    ad_valorem_amount: Decimal | None = None
    specific_amount: Decimal | None = None
    cap_amount: Decimal | None = None
    missing_facts: tuple[str, ...] = ()
    trace: tuple[ETTDutyPreviewStep, ...] = ()
    mode: Literal["candidate_preview"] = field(default="candidate_preview", init=False)
    legally_approved: Literal[False] = field(default=False, init=False)
    final_payable: Literal[False] = field(default=False, init=False)
    source_evidence_verified: Literal[False] = field(default=False, init=False)
    rounding_applied: Literal[False] = field(default=False, init=False)


def _exact_number(value: object, name: str) -> Decimal:
    """Bound inputs before conversion, accepting no implicit float/bool coercion."""
    if type(value) is int:
        if value.bit_length() > 80:
            raise ValueError(f"{name} exceeds the size limit")
        text = str(value)
    elif type(value) is str:
        text = value
    elif type(value) is Decimal:
        if not value.is_finite():
            raise ValueError(f"{name} must be finite")
        _, digits, exponent = value.as_tuple()
        if len(digits) > 36 or not -12 <= exponent <= 24:
            raise ValueError(f"{name} exceeds the size limit")
        text = format(value, "f")
    else:
        raise ValueError(f"{name} requires an exact decimal, never float or bool")
    if len(text) > 37 or _NUMBER.fullmatch(text) is None:
        raise ValueError(f"{name} requires a nonnegative bounded plain decimal")
    return Decimal(text)


def _currency(value: object, name: str) -> Currency:
    if type(value) is not str or value not in _CURRENCIES:
        raise ValueError(f"{name} requires an explicit EUR, USD or RUB currency")
    return value  # type: ignore[return-value]


def _source_text(value: object, name: str, maximum: int) -> str:
    if type(value) is not str or not 1 <= len(value) <= maximum or not value.strip() or "\x00" in value:
        raise ValueError(f"{name} requires bounded nonempty text")
    return value


def _exchange_rate(value: ETTPreviewExchangeRate) -> ETTPreviewExchangeRate:
    if type(value) is not ETTPreviewExchangeRate:
        raise ValueError("exchange_rate requires ETTPreviewExchangeRate")
    source = _currency(value.from_currency, "from_currency")
    target = _currency(value.to_currency, "to_currency")
    if source == target:
        raise ValueError("exchange_rate requires two different currencies")
    if type(value.as_of) is not date:
        raise ValueError("exchange_rate.as_of requires an explicit date")
    multiplier = _exact_number(value.multiplier, "exchange_rate.multiplier")
    if multiplier == 0:
        raise ValueError("exchange_rate.multiplier must be positive")
    url = _source_text(value.source_url, "source_url", 4096)
    if any(ord(char) < 33 or ord(char) == 127 for char in url) or "\\" in url:
        raise ValueError("source_url contains forbidden characters")
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username is not None or parsed.password is not None or parsed.fragment:
        raise ValueError("source_url requires an absolute HTTPS reference without credentials or fragments")
    for name in ("source_artifact_sha256", "source_text_sha256"):
        candidate = getattr(value, name)
        if type(candidate) is not str or _HASH.fullmatch(candidate) is None:
            raise ValueError(f"{name} requires a lowercase SHA-256")
    locator = _source_text(value.source_locator, "source_locator", 512)
    text = _source_text(value.source_text, "source_text", 100_000)
    if hashlib.sha256(text.encode("utf-8")).hexdigest() != value.source_text_sha256:
        raise ValueError("exchange_rate source text digest mismatch")
    return ETTPreviewExchangeRate(
        source, target, value.as_of, multiplier, url, value.source_artifact_sha256,
        locator, text, value.source_text_sha256,
    )


def _decimal_exact(value: Fraction) -> Decimal:
    """Construct a terminating decimal exactly, without consulting decimal context.

    A rational may terminate only after all factors cancel (e.g. 1 * 1 * 3 / 3).
    Rounding an intermediate division would lose that property. After reduction,
    only factors two and five in the denominator admit a finite decimal result.
    """
    denominator = value.denominator
    twos = fives = 0
    while denominator % 2 == 0:
        denominator //= 2
        twos += 1
    while denominator % 5 == 0:
        denominator //= 5
        fives += 1
    if denominator != 1:
        raise ArithmeticError("nonterminating_decimal")
    scale = max(twos, fives)
    coefficient = value.numerator * 2 ** (scale - twos) * 5 ** (scale - fives)
    return Decimal((0, tuple(int(char) for char in str(coefficient)), -scale))


def preview_duty(
    duty: ETTDuty,
    *,
    as_of: date,
    currency: Currency,
    customs_value: ExactNumber | None = None,
    quantity: ExactNumber | None = None,
    quantity_unit: str | None = None,
    exchange_rate: ETTPreviewExchangeRate | None = None,
) -> ETTDutyPreview:
    """Evaluate one candidate expression with explicit, provisional inputs.

    Invalid representations raise ``ValueError``. Missing inputs return
    ``needs_clarification``; contradictory units/currency/date return
    ``unavailable``. No result invents zero or a rounding policy. A mathematically
    nonterminating component also returns ``unavailable`` instead of rounding it.
    This function does not prove the duty applies on ``as_of``; callers must first
    use the separate manifest resolver and retain its evidence and status.
    """
    if not isinstance(duty, ETTDuty):
        raise ValueError("duty requires a validated ETTDuty")
    duty = ETTDuty.model_validate(duty)
    if type(as_of) is not date:
        raise ValueError("as_of requires an explicit date, not a datetime or string")
    currency = _currency(currency, "currency")
    value = None if customs_value is None else _exact_number(customs_value, "customs_value")
    units = None if quantity is None else _exact_number(quantity, "quantity")
    if quantity_unit is not None and (type(quantity_unit) is not str or quantity_unit not in _UNITS):
        raise ValueError("quantity_unit requires an explicit supported ETT unit")
    fx = None if exchange_rate is None else _exchange_rate(exchange_rate)
    base = dict(duty=duty, as_of=as_of, currency=currency, customs_value=value,
                quantity=units, quantity_unit=quantity_unit, exchange_rate=fx)

    requires_specific = duty.specific_amount is not None
    requires_fx = requires_specific and duty.currency != currency
    if requires_specific and quantity_unit is not None and quantity_unit != duty.unit:
        return ETTDutyPreview(status="unavailable", reason="quantity_unit_mismatch", **base)
    if fx is not None:
        if not requires_fx or fx.from_currency != duty.currency or fx.to_currency != currency:
            return ETTDutyPreview(status="unavailable", reason="exchange_rate_pair_mismatch", **base)
        if fx.as_of != as_of:
            return ETTDutyPreview(status="unavailable", reason="exchange_rate_date_mismatch", **base)
    missing: list[str] = []
    if duty.ad_valorem_percent is not None and value is None:
        missing.append("customs_value")
    if requires_specific:
        if units is None or units == 0:
            missing.append("quantity")
        if quantity_unit is None:
            missing.append("quantity_unit")
        if requires_fx and fx is None:
            missing.append("exchange_rate")
    if missing:
        return ETTDutyPreview(status="needs_clarification", reason="missing_calculation_inputs",
                              missing_facts=tuple(missing), **base)

    trace: list[ETTDutyPreviewStep] = []

    def component(operands: tuple[Decimal, ...]) -> Decimal:
        number = Fraction(1)
        for operand in operands[:-1]:
            number *= Fraction(operand)
        number /= Fraction(operands[-1])
        result = _decimal_exact(number)
        trace.append(ETTDutyPreviewStep("multiply_divide", operands, result))
        return result

    try:
        ad = None if duty.ad_valorem_percent is None else component((value, duty.ad_valorem_percent, Decimal(100)))
        specific = None if not requires_specific else component((
            duty.specific_amount, units, Decimal(1) if fx is None else fx.multiplier,
            duty.unit_quantity,
        ))
        cap = None if duty.ad_valorem_cap_percent is None else component((value, duty.ad_valorem_cap_percent, Decimal(100)))
        if duty.kind == "ad_valorem":
            amount = ad
        elif duty.kind == "specific":
            amount = specific
        elif duty.kind == "combined_sum":
            amount = _decimal_exact(Fraction(ad) + Fraction(specific))
            trace.append(ETTDutyPreviewStep("sum", (ad, specific), amount))
        else:
            amount = max(ad, specific)
            trace.append(ETTDutyPreviewStep("max", (ad, specific), amount))
            if duty.kind == "capped_combined_max":
                amount = min(cap, amount)
                trace.append(ETTDutyPreviewStep("min", (cap, trace[-1].result), amount))
    except ArithmeticError:
        return ETTDutyPreview(status="unavailable", reason="nonterminating_decimal", **base)
    return ETTDutyPreview(
        status="calculated", reason="exact_provisional_arithmetic", amount=amount,
        ad_valorem_amount=ad, specific_amount=specific, cap_amount=cap,
        trace=tuple(trace), **base,
    )
