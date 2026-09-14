"""Strict lexical interpretation of an already isolated, complete ETT duty cell.

``parsed`` means only that the entire cell has one supported expression. It
does not establish the table boundary, legal applicability, effective dates or
the meaning of any footnotes. Callers must establish the cell's completeness
from PDF evidence; a code-row fragment must never be passed as a complete cell.

No numeric tail, inferred zero, description number or unknown condition is
discarded. Fused text such as ``563С)`` is ambiguous without glyph evidence and
is deliberately unresolved. Original text and recognized marker offsets are
retained; offsets are Python Unicode-codepoint offsets, not UTF-8 byte offsets.
"""
from __future__ import annotations

import re
import unicodedata
from decimal import Decimal
from typing import Any

from pydantic import ValidationError

from app.services.ett_manifest import ETTDuty


PARSER_NAME = "ett_isolated_duty_cell"
PARSER_VERSION = "2"
MAX_CELL_CHARACTERS = 8192
_WHITESPACE = " \t\r\n\u00a0\u202f"
_W = "[ \\t\\r\\n\\u00a0\\u202f]"
# No Unicode digit folding, exponent, binary float or thousands separator.
_NUMBER = r"(?:0|[1-9][0-9]{0,23})(?:,[0-9]{1,12})?"
_CURRENCY = rf"(?:евро|доллар(?:а|ов)?{_W}+США)"
_UNITS = {
    "кг": "kg", "г": "g", "т": "tonne", "л": "litre",
    "м": "m", "м2": "m2", "м²": "m2", "м3": "m3", "м³": "m3",
    "шт": "unit", "пару": "pair", "кВт·ч": "kwh",
}
_ENGINE_UNIT = rf"см[3³]{_W}+объема{_W}+двигателя"
_UNIT = "(?:" + _ENGINE_UNIT + "|" + "|".join(re.escape(unit) for unit in _UNITS) + ")"
_SPECIFIC = (
    rf"(?P<amount>{_NUMBER}){_W}+(?P<currency>{_CURRENCY}){_W}+за{_W}+"
    rf"(?P<quantity>{_NUMBER}){_W}+(?P<unit>{_UNIT})"
)
_SPECIFIC_RE = re.compile(_SPECIFIC)
_AD_VALOREM_RE = re.compile(rf"(?P<percent>{_NUMBER})(?P<symbol>{_W}*%)?")
_COMBINED_RE = re.compile(
    rf"(?P<percent>{_NUMBER})(?P<symbol>{_W}*%)?"
    rf"(?:(?:{_W}*,{_W}*но{_W}+не{_W}+менее{_W}+)(?P<maximum>)"
    rf"|{_W}+плюс{_W}+|{_W}*\+{_W}*){_SPECIFIC}"
)
_CAPPED_RE = re.compile(
    rf"(?P<cap>{_NUMBER})(?P<cap_symbol>{_W}*%)?{_W}*,{_W}*либо{_W}+"
    rf"(?P<percent>{_NUMBER})(?P<symbol>{_W}*%)?{_W}*,{_W}*но{_W}+не{_W}+менее{_W}+"
    rf"{_SPECIFIC}{_W}*,{_W}*в{_W}+зависимости{_W}+от{_W}+того{_W}*,{_W}*"
    rf"какая{_W}+из{_W}+исчисленных{_W}+сумм{_W}+таможенной{_W}+пошлины{_W}+ниже"
)
# Both forms occur in actual retained EEC PDFs. Markers may abut a letter unit
# ("кг63С)") or an explicit percent sign, but never split a numeric token.
_MARKER_TAIL = re.compile(rf"(?<![0-9.,м])(?P<number>[1-9][0-9]{{0,3}}){_W}*[СC]\){_W}*\Z")


def _decimal_text(raw: str) -> str:
    return raw.replace(",", ".")


def _specific_components(match: re.Match[str]) -> dict[str, str]:
    unit = "engine_displacement_cm3" if re.fullmatch(_ENGINE_UNIT, match["unit"]) else _UNITS[match["unit"]]
    return {
        "specific_amount": _decimal_text(match["amount"]),
        "currency": "EUR" if match["currency"] == "евро" else "USD",
        "unit": unit,
        "unit_quantity": _decimal_text(match["quantity"]),
    }


def _markers(raw: str) -> tuple[str, list[dict[str, Any]]]:
    body = raw.rstrip(_WHITESPACE)
    markers = []
    while match := _MARKER_TAIL.search(body):
        # The digit suffix of м2/м3 can be part of a fused footnote (м263С)).
        # The negative lookbehind above disallows splitting that numeric run.
        start, end = match.span()
        if not body[:start].strip(_WHITESPACE):
            # A whole numeric run followed by C) may fuse the duty and marker.
            # Without a preceding expression we cannot even assign its ID.
            break
        end = len(body[:end].rstrip(_WHITESPACE))
        markers.append({
            "footnote_id": match["number"] + "C",
            "raw_text": raw[start:end],
            "start": start,
            "end": end,
        })
        body = body[:start].rstrip(_WHITESPACE)
    markers.reverse()
    return body.strip(_WHITESPACE), markers


def parse_duty_cell(raw_text: str, *, percent_header_confirmed: bool) -> dict[str, Any]:
    """Return a JSON-ready lexical result, permanently outside active rates.

    Bare numbers require the independently confirmed percentage column header;
    an explicit ``%`` carries its own lexical unit. The caller's boolean does
    not certify PDF provenance. Supported footnote markers remain unresolved
    legal references even when the surrounding expression is fully parsed.
    """
    if type(raw_text) is not str or type(percent_header_confirmed) is not bool:
        raise ValueError("A string cell and an explicit boolean header confirmation are required")
    result: dict[str, Any] = {
        "status": "unresolved", "raw_text": raw_text, "duty": None,
        "footnote_ids": [], "footnote_markers": [], "unparsed_reason": None,
        "percent_header_confirmed": percent_header_confirmed,
        "legal_interpretation_verified": False, "can_promote": False,
    }
    if len(raw_text) > MAX_CELL_CHARACTERS:
        result["unparsed_reason"] = "cell_size_limit"
        return result
    if not raw_text.strip(_WHITESPACE):
        result["unparsed_reason"] = "empty_cell"
        return result
    if any((unicodedata.category(char).startswith("C") or char.isspace()) and char not in _WHITESPACE for char in raw_text):
        result["unparsed_reason"] = "unsupported_unicode_or_control_character"
        return result
    body, markers = _markers(raw_text)
    result["footnote_markers"] = markers
    result["footnote_ids"] = list(dict.fromkeys(marker["footnote_id"] for marker in markers))

    components: dict[str, str] | None = None
    if match := _AD_VALOREM_RE.fullmatch(body):
        if not percent_header_confirmed and not match["symbol"]:
            result["unparsed_reason"] = "percent_header_unconfirmed"
            return result
        components = {"kind": "ad_valorem", "ad_valorem_percent": _decimal_text(match["percent"])}
    elif match := _SPECIFIC_RE.fullmatch(body):
        components = {"kind": "specific", **_specific_components(match)}
    elif match := _COMBINED_RE.fullmatch(body):
        if not percent_header_confirmed and not match["symbol"]:
            result["unparsed_reason"] = "percent_header_unconfirmed"
            return result
        components = {
            "kind": "combined_max" if match["maximum"] is not None else "combined_sum",
            "ad_valorem_percent": _decimal_text(match["percent"]),
            **_specific_components(match),
        }
    elif match := _CAPPED_RE.fullmatch(body):
        if not percent_header_confirmed and not (match["symbol"] and match["cap_symbol"]):
            result["unparsed_reason"] = "percent_header_unconfirmed"
            return result
        components = {
            "kind": "capped_combined_max", "ad_valorem_cap_percent": _decimal_text(match["cap"]),
            "ad_valorem_percent": _decimal_text(match["percent"]),
            **_specific_components(match),
        }
    if components is None:
        result["unparsed_reason"] = "unsupported_or_ambiguous_complete_cell"
        return result
    try:
        duty = ETTDuty.model_validate(components)
    except ValidationError:
        result["unparsed_reason"] = "expression_outside_duty_schema"
        return result
    serialized = {key: format(value, "f") if isinstance(value, Decimal) else value
                  for key, value in duty.model_dump(exclude_none=True).items()}
    result.update(status="parsed", duty=serialized)
    return result
