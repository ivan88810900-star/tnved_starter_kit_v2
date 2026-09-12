"""Strict scalar checks before legacy official-bundle normalization.

The existing storage contract uses floats. This helper accepts those historical
JSON numbers, but never substitutes a value for an absent/invalid source cell or
converts a positive unrepresentable value to zero. It does not establish legal
applicability or convert a permissive legacy normalizer into an official parser.
"""

from decimal import Decimal
import json
import math
import re


_PLAIN_DECIMAL = re.compile(r"-?[0-9]+(?:[.,][0-9]+)?\Z", re.ASCII)


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate_json_key: {rate_value_diagnostic(key)}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> object:
    raise ValueError(f"nonfinite_json_number: {value}")


def load_official_rate_json(source: bytes | str) -> object:
    """Decode one original UTF-8 source with no ambiguous object or numeric data.

    Duplicate names are rejected at every nesting level, including equivalent
    JSON escape spellings and equal repeated values. Otherwise a later zero,
    country, rate type or revision could silently replace its earlier source
    value before any domain validator sees it. Decimal numbers retain their
    source magnitude; nonstandard NaN/Infinity tokens are rejected everywhere,
    including metadata. This returns parsed data, never replacement source bytes.
    """
    if type(source) is bytes:
        source = source.decode("utf-8")
    if type(source) is not str:
        raise ValueError("official_json_requires_utf8_source")
    return json.loads(source, parse_float=Decimal, object_pairs_hook=_unique_json_object,
                      parse_constant=_reject_json_constant)


def explicit_nonnegative_rate(value: object) -> float:
    """Return a finite explicit scalar or raise a stable diagnostic reason."""
    if value is None:
        raise ValueError("missing_rate_value")
    if type(value) is bool or type(value) not in (str, int, float, Decimal):
        raise ValueError("invalid_rate_value_type")
    if type(value) is str:
        if len(value) > 128:
            raise ValueError("rate_value_size_limit")
        text = value.strip()
        if not text:
            raise ValueError("missing_rate_value")
        if _PLAIN_DECIMAL.fullmatch(text) is None:
            raise ValueError("invalid_rate_value_format")
        number = Decimal(text.replace(",", "."))
    elif type(value) is int:
        if value.bit_length() > 213:
            raise ValueError("rate_value_size_limit")
        number = Decimal(value)
    elif type(value) is float:
        if not math.isfinite(value):
            raise ValueError("nonfinite_rate_value")
        number = Decimal(str(value))
    else:
        number = value
    if not number.is_finite():
        raise ValueError("nonfinite_rate_value")
    _, digits, exponent = number.as_tuple()
    if len(digits) > 64 or not -400 <= exponent <= 400:
        raise ValueError("rate_value_size_limit")
    if number < 0:
        raise ValueError("negative_rate_value")
    converted = float(number)
    if not math.isfinite(converted):
        raise ValueError("unrepresentable_rate_value")
    if number != 0 and converted == 0:
        raise ValueError("rate_value_underflow")
    return converted


def rate_value_diagnostic(value: object) -> str:
    """Bound source-cell evidence; do not render arbitrary objects/containers."""
    if type(value) is str:
        return repr(value[:160]) + (" [truncated]" if len(value) > 160 else "")
    if type(value) is int and value.bit_length() > 213:
        return "<integer exceeds 64 digits>"
    if type(value) is Decimal and len(value.as_tuple().digits) > 64:
        return "<Decimal exceeds 64 digits>"
    if value is None or type(value) in (int, float, bool, Decimal):
        return repr(value)
    return f"<{type(value).__name__}>"
