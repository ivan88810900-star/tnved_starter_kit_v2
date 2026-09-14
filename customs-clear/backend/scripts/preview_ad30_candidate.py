"""Print a bounded offline AD30 review scenario; no DB or application startup.

Usage: python scripts/preview_ad30_candidate.py --input scenario.json
Omit --input (or use '-') to read stdin. Input is one strict JSON object with
as_of, facts, currency, and optional source_row_id/customs_value. Decimal values
must be strings, not JSON floating-point numbers. Output is always stdout JSON.
Exit 0: hypothetical arithmetic available, still legally unavailable/review-only.
Exit 3: valid scenario needs clarification or is outside this literal candidate.
Exit 2: invalid representation, input read failure or altered source dossier.
No exit code authorizes a rate, a legal interval, or a final payment.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, is_dataclass
from datetime import date
from decimal import Decimal
import json
import os
from pathlib import Path
import stat
import sys


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from pydantic import BaseModel
from app.services.ad30_duty_preview import preview_ad30_duty


MAX_INPUT_BYTES = 64 * 1024
_FIELDS = frozenset({"as_of", "facts", "currency", "source_row_id", "customs_value"})


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_number(_):
    raise ValueError("use a bounded plain decimal string, not a JSON float or nonfinite value")


def _integer(literal):
    if len(literal) > 25:
        raise ValueError("JSON integer exceeds the input limit")
    return int(literal)


def _read_input(filename):
    if filename == "-":
        data = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    else:
        descriptor = os.open(filename, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_INPUT_BYTES:
                raise ValueError("input requires a bounded regular JSON file")
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                data = stream.read(MAX_INPUT_BYTES + 1)
        finally:
            os.close(descriptor)
    if len(data) > MAX_INPUT_BYTES:
        raise ValueError("input exceeds the 64 KiB size limit")
    return data.decode("utf-8")


def _json_default(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if is_dataclass(value):
        return asdict(value)
    raise TypeError("unsupported output representation")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="-", help="bounded JSON file, or - for stdin")
    arguments = parser.parse_args(argv)
    try:
        payload = json.loads(_read_input(arguments.input), object_pairs_hook=_pairs,
                             parse_float=_reject_number, parse_constant=_reject_number,
                             parse_int=_integer)
        if type(payload) is not dict or set(payload) - _FIELDS:
            raise ValueError("scenario requires an object with only documented input fields")
        if not {"as_of", "facts", "currency"} <= set(payload) or type(payload["facts"]) is not dict:
            raise ValueError("scenario requires explicit as_of, facts object and currency")
        literal = payload["as_of"]
        if type(literal) is not str or len(literal) != 10:
            raise ValueError("as_of requires an explicit YYYY-MM-DD date")
        requested_date = date.fromisoformat(literal)
        if requested_date.isoformat() != literal:
            raise ValueError("as_of requires an explicit YYYY-MM-DD date")
        result = preview_ad30_duty(
            as_of=requested_date, facts=payload["facts"], currency=payload["currency"],
            source_row_id=payload.get("source_row_id"), customs_value=payload.get("customs_value"),
        )
        code = 0 if result["status"] == "calculated" else 3
    except (ValueError, TypeError, OSError, RecursionError):
        # Do not echo arbitrary supplied text, paths or source dossier content.
        result = {
            "mode": "ad30_hypothetical_source_row_preview", "status": "invalid_input",
            "reason": "invalid_input_or_unverified_source_record",
            "amount": None, "legal_applicability": "unavailable", "review_required": True,
            "legal_approval": False, "final_payable": False, "can_promote": False,
            "active_rates_written": False, "db_mutated": False,
        }
        code = 2
    print(json.dumps(result, ensure_ascii=False, allow_nan=False, default=_json_default))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
