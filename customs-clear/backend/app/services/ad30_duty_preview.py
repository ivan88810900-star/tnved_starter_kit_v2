"""Offline hypothetical AD30 source-row arithmetic, never an applicable payment.

An explicit row is an operand selected for a review scenario. It does not prove
producer identity, or establish which law applies on the supplied date. The
product evaluator and source-record validator are always run by this service;
caller-supplied assessments and approval markers are not accepted.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from datetime import date
from typing import Any

from .ad30_applicability import assess_ad30_candidate
from .ad30_source_facts import (
    AD30SourceFacts,
    load_ad30_source_facts,
    validate_ad30_source_facts,
)
from .ett_duty_preview import ExactNumber, _currency, _exact_number, preview_duty
from .ett_manifest import ETTDuty


def preview_ad30_duty(
    *,
    as_of: date,
    facts: Mapping[str, object],
    source_row_id: str | None,
    customs_value: ExactNumber | None,
    currency: str,
    source_facts: AD30SourceFacts | None = None,
) -> dict[str, Any]:
    """Evaluate one explicitly chosen printed row after literal scope checks.

Missing scenario operands return ``needs_clarification``. A literal scope
mismatch returns ``unavailable`` with no amount, never a zero-liability claim.
Malformed representations raise ``ValueError``. Even calculated arithmetic is
unrounded and hypothetical: temporal applicability and final payable remain
unavailable for every result. No DB, network or application startup is used.
"""
    if type(as_of) is not date:
        raise ValueError("as_of requires an explicit calendar date")
    if source_row_id is not None and (type(source_row_id) is not str or not 1 <= len(source_row_id) <= 64):
        raise ValueError("source_row_id requires a known source row identifier")
    result_currency = _currency(currency, "currency")
    value = None if customs_value is None else _exact_number(customs_value, "customs_value")
    bundle = validate_ad30_source_facts(
        load_ad30_source_facts() if source_facts is None else source_facts
    )
    rows = {row.row_id: row for row in bundle.rate_rows}
    if source_row_id is not None and source_row_id not in rows:
        raise ValueError("source_row_id is not present in the retained source dossier")
    assessment = assess_ad30_candidate(as_of=as_of, facts=facts, source_facts=bundle)
    result: dict[str, Any] = {
        "mode": "ad30_hypothetical_source_row_preview",
        "status": "needs_clarification",
        "reason": "source_candidate_scope_unresolved",
        "as_of": as_of.isoformat(),
        "source_dossier_sha256": bundle.dossier_sha256,
        "source_record_integrity_verified": bundle.source_record_integrity_verified,
        "original_artifacts_verified": False,
        "source_text_verified": False,
        "assessment": assessment,
        "row_selection_kind": "hypothetical_source_row",
        "selected_source_row": None,
        "currency": result_currency,
        "customs_value": value,
        "amount": None,
        "calculation": None,
        "missing_inputs": [],
        "legal_applicability": "unavailable",
        "temporal_applicability": "unavailable",
        "review_required": True,
        "producer_identity_verified": False,
        "amendment_history_verified": False,
        "durable_legal_retention_attested": False,
        "legal_review_verified": False,
        "legal_approval": False,
        "applied": False,
        "final_payable": False,
        "final_payable_amount": None,
        "production_ready": False,
        "can_promote": False,
        "active_rates_written": False,
        "db_mutated": False,
        "rounding_applied": False,
    }
    if source_row_id is not None:
        row = rows[source_row_id]
        source_by_id = {fact.fact_id: fact for fact in bundle.facts}
        result["selected_source_row"] = {
            "row_id": row.row_id,
            "producer_name": row.producer_name,
            "producer_address": row.producer_address,
            "rate_percent_literal": row.rate_percent_literal,
            "evidence_ids": row.evidence_ids,
            "source_evidence": [asdict(source_by_id[fact_id]) for fact_id in row.evidence_ids],
        }
    if assessment["candidate_scope"] == "outside_source_candidate":
        result.update(status="unavailable", reason="outside_literal_source_candidate")
        return result
    if assessment["candidate_scope"] != "matches_source_candidate":
        return result
    missing = [name for name, operand in (
        ("source_row_id", source_row_id), ("customs_value", value)
    ) if operand is None]
    if missing:
        result.update(reason="missing_hypothetical_scenario_inputs", missing_inputs=missing)
        return result
    # The canonical dossier fixes the raw literal and its provenance. This is
    # only decimal spelling conversion; no text parsing failure can imply zero.
    duty = ETTDuty(kind="ad_valorem", ad_valorem_percent=row.rate_percent_literal.replace(",", "."))
    calculation = preview_duty(duty, as_of=as_of, currency=result_currency, customs_value=value)
    result.update(
        status=calculation.status,
        reason="hypothetical_source_row_arithmetic" if calculation.status == "calculated" else calculation.reason,
        amount=calculation.amount,
        calculation=calculation,
    )
    return result
