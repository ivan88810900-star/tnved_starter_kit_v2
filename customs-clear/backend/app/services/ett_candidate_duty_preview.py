"""Resolve and quote-check a local candidate before provisional duty arithmetic.

Original PDF/HTML evidence is replayed through the existing bounded verifier.
This workflow therefore reads source objects and may use temporary PDF worker
files; it does not read a database, acquire sources, approve law or apply rates.
Quotation existence is deliberately separate from legal interpretation and from
the caller-supplied, unverified currency factor.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any

from .ett_artifacts import LocalArtifactStore
from .ett_duty_preview import ETTPreviewExchangeRate, preview_duty
from .ett_manifest import ETTManifest
from .ett_metadata_binding import verify_manifest_source_evidence
from .ett_resolver import resolve_rate


_INPUT_FIELDS = frozenset({
    "currency", "customs_value", "quantity", "quantity_unit", "exchange_rate",
})


def _calculation_inputs(value: Mapping[str, Any]) -> dict[str, Any]:
    if type(value) is not dict or set(value) - _INPUT_FIELDS:
        raise ValueError("calculation inputs require an object with known fields")
    if "currency" not in value:
        raise ValueError("calculation currency is required")
    result = dict(value)
    if value.get("exchange_rate") is not None:
        supplied = value["exchange_rate"]
        if type(supplied) is not dict:
            raise ValueError("exchange_rate requires an object")
        exchange = dict(supplied)
        literal = exchange.get("as_of")
        if type(literal) is not str:
            raise ValueError("exchange_rate.as_of requires an explicit ISO date")
        parsed = date.fromisoformat(literal)
        if parsed.isoformat() != literal:
            raise ValueError("exchange_rate.as_of requires an explicit ISO date")
        exchange["as_of"] = parsed
        result["exchange_rate"] = ETTPreviewExchangeRate(**exchange)
    return result


def preview_candidate_duty(
    manifest: ETTManifest,
    store: LocalArtifactStore,
    *,
    code: str,
    as_of: date,
    destination: str,
    calculation_inputs: Mapping[str, Any],
    facts: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    """Keep uncertainty and source failures ahead of any monetary result.

    ``quantity`` is the explicitly supplied total basis in the selected duty unit;
    product characteristics in ``facts`` do not silently supply or convert it.
    Even successful exact arithmetic is unrounded and is not a final payment.
    """
    inputs = _calculation_inputs(calculation_inputs)
    resolution = resolve_rate(manifest, code, as_of, destination, facts)
    result = {
        "mode": "candidate_preview", "status": resolution.status,
        "reason": resolution.reason, "resolution": resolution,
        "calculation": None, "source_quote_verification": None,
        "review_required": True, "legal_approval": False, "final_payable": False,
        "production_ready": False, "can_promote": False, "active_rates_written": False,
    }
    if resolution.status != "resolved":
        return result
    verification = verify_manifest_source_evidence(manifest, store)
    result["source_quote_verification"] = verification
    if not verification["source_evidence_verified"]:
        result.update(status="unavailable", reason="candidate_source_quotes_unverified")
        return result
    calculation = preview_duty(resolution.duty, as_of=as_of, **inputs)
    result.update(status=calculation.status, reason=calculation.reason,
                  calculation=calculation)
    return result
