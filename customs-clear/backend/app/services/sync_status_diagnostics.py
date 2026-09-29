"""Fail-closed status semantics for the normative update scheduler."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _utc_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.isoformat()


def build_sync_status_diagnostics(
    *,
    completed_at: datetime | None,
    last_trigger: str | None,
    last_error: str | None,
    scheduler_running: bool,
    next_sync_iso: str | None,
) -> dict[str, Any]:
    """Separate run evidence from schedule presence and legal currentness.

    The stored state contains only the latest attempt.  A failed attempt must
    therefore not be relabelled as a successful sync, and a manual success must
    not prove that the scheduled job is working.  Even a scheduled success is
    pipeline-execution evidence only; it does not establish that official
    editions or amendments are complete and current.
    """
    last_iso = _utc_iso(completed_at)
    error = str(last_error or "").strip()
    trigger = str(last_trigger or "").strip()

    if last_iso is None:
        latest_attempt_status = "never_run"
    elif error:
        latest_attempt_status = "failed"
    else:
        latest_attempt_status = "succeeded"

    if not scheduler_running:
        schedule_status = "not_running"
    elif not next_sync_iso:
        schedule_status = "job_missing"
    else:
        schedule_status = "scheduled"

    if schedule_status != "scheduled":
        automatic_update_status = schedule_status
    elif latest_attempt_status == "never_run":
        automatic_update_status = "awaiting_first_run"
    elif trigger != "scheduled":
        automatic_update_status = "no_scheduled_run_evidence"
    elif latest_attempt_status == "failed":
        automatic_update_status = "latest_scheduled_run_failed"
    else:
        automatic_update_status = "latest_scheduled_run_succeeded"

    return {
        # Compatibility fields: ``last_sync_iso`` is the latest completion,
        # not necessarily a success.
        "scheduler_running": scheduler_running,
        "last_sync_iso": last_iso,
        "next_sync_iso": next_sync_iso,
        "schedule_status": schedule_status,
        "latest_attempt_status": latest_attempt_status,
        "latest_attempt_trigger": trigger or None,
        "latest_attempt_at": last_iso,
        "last_successful_sync_at": last_iso if latest_attempt_status == "succeeded" else None,
        "last_successful_scheduled_sync_at": (
            last_iso
            if latest_attempt_status == "succeeded" and trigger == "scheduled"
            else None
        ),
        "last_success_evidence_scope": "latest_attempt_only",
        "automatic_update_status": automatic_update_status,
        "last_error_present": bool(error),
        "diagnostic_scope": "pipeline_execution_only",
        "authoritative_currentness_confirmed": False,
    }
