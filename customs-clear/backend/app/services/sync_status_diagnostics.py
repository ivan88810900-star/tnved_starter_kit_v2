"""Fail-closed status semantics for the normative update scheduler."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

MAX_AUTOMATIC_ATTEMPT_AGE = timedelta(hours=48)


def _normalize_utc(value: Any, *, naive_is_utc: bool) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        if not naive_is_utc:
            return None
        value = value.replace(tzinfo=timezone.utc)
    try:
        if value.utcoffset() is None:
            return None
        return value.astimezone(timezone.utc)
    except (OverflowError, TypeError, ValueError):
        return None


def _parse_next_run(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if raw.endswith(("Z", "z")):
        raw = f"{raw[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return _normalize_utc(parsed, naive_is_utc=False)


def build_sync_status_diagnostics(
    *,
    completed_at: Any,
    last_trigger: Any,
    last_error: Any,
    scheduler_running: Any,
    next_sync_iso: Any,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Separate run evidence from schedule presence and legal currentness.

    The stored state contains only the latest attempt.  A failed attempt must
    therefore not be relabelled as a successful sync, and a manual success must
    not prove that the scheduled job is working.  Even a scheduled success is
    pipeline-execution evidence only; it does not establish that official
    editions or amendments are complete and current.
    """
    current = _normalize_utc(now or datetime.now(timezone.utc), naive_is_utc=True)
    assert current is not None
    completed_utc = _normalize_utc(completed_at, naive_is_utc=True)
    last_iso = completed_utc.isoformat() if completed_utc else None
    scheduler_state_status = (
        "valid" if type(scheduler_running) is bool else "invalid_type"
    )
    scheduler_is_running = scheduler_running if scheduler_state_status == "valid" else False

    if last_error is None:
        error_evidence_status = "missing"
        error = ""
    elif isinstance(last_error, str):
        error_evidence_status = "valid"
        error = last_error.strip()
    else:
        error_evidence_status = "invalid_type"
        error = ""

    if last_trigger is None:
        trigger_evidence_status = "missing"
        trigger = ""
    elif isinstance(last_trigger, str):
        trigger_evidence_status = "valid"
        trigger = last_trigger.strip()
    else:
        trigger_evidence_status = "invalid_type"
        trigger = ""

    if error_evidence_status == "invalid_type":
        latest_attempt_status = "invalid_error_evidence"
    elif trigger_evidence_status == "invalid_type":
        latest_attempt_status = "invalid_trigger_evidence"
    elif completed_at is None and error:
        latest_attempt_status = "failed_without_timestamp"
    elif completed_at is None and trigger:
        latest_attempt_status = "incomplete_evidence"
    elif completed_at is None:
        latest_attempt_status = "never_run"
    elif completed_utc is None:
        latest_attempt_status = "invalid_timestamp"
    elif error:
        latest_attempt_status = "failed"
    else:
        latest_attempt_status = "succeeded"

    if completed_utc is None:
        attempt_time_status = "missing" if completed_at is None else "invalid"
    elif completed_utc > current:
        attempt_time_status = "future"
    elif current - completed_utc > MAX_AUTOMATIC_ATTEMPT_AGE:
        attempt_time_status = "stale"
    else:
        attempt_time_status = "fresh"

    next_run_missing = next_sync_iso is None or (
        isinstance(next_sync_iso, str) and not next_sync_iso.strip()
    )
    next_run_input_status = (
        "missing"
        if next_run_missing
        else "valid_type"
        if isinstance(next_sync_iso, str)
        else "invalid_type"
    )
    next_run_utc = _parse_next_run(next_sync_iso)
    if scheduler_state_status != "valid":
        schedule_status = "invalid_scheduler_state"
    elif not scheduler_is_running:
        schedule_status = "not_running"
    elif next_run_missing:
        schedule_status = "job_missing"
    elif next_run_utc is None:
        schedule_status = "invalid_next_run"
    elif completed_utc is not None and next_run_utc <= completed_utc:
        schedule_status = "next_run_not_after_attempt"
    elif next_run_utc <= current:
        schedule_status = "next_run_not_future"
    else:
        schedule_status = "scheduled"

    if schedule_status != "scheduled":
        automatic_update_status = schedule_status
    elif latest_attempt_status == "never_run":
        automatic_update_status = "awaiting_first_run"
    elif latest_attempt_status == "failed_without_timestamp":
        automatic_update_status = "latest_attempt_failed_without_timestamp"
    elif latest_attempt_status == "invalid_error_evidence":
        automatic_update_status = "invalid_error_evidence"
    elif latest_attempt_status == "invalid_trigger_evidence":
        automatic_update_status = "invalid_trigger_evidence"
    elif latest_attempt_status in ("incomplete_evidence", "invalid_timestamp"):
        automatic_update_status = "incomplete_attempt_evidence"
    elif trigger != "scheduled":
        automatic_update_status = "no_scheduled_run_evidence"
    elif latest_attempt_status == "failed":
        automatic_update_status = "latest_scheduled_run_failed"
    elif attempt_time_status == "future":
        automatic_update_status = "invalid_attempt_timestamp"
    elif attempt_time_status == "stale":
        automatic_update_status = "latest_scheduled_run_stale"
    else:
        automatic_update_status = "latest_scheduled_run_succeeded"

    success_timestamp_valid = (
        latest_attempt_status == "succeeded"
        and attempt_time_status in ("fresh", "stale")
    )

    return {
        # Compatibility fields: ``last_sync_iso`` is the latest completion,
        # not necessarily a success.
        "scheduler_running": bool(scheduler_is_running),
        "scheduler_state_status": scheduler_state_status,
        "last_sync_iso": last_iso,
        "next_sync_iso": next_sync_iso if isinstance(next_sync_iso, str) else None,
        "schedule_status": schedule_status,
        "latest_attempt_status": latest_attempt_status,
        "latest_attempt_trigger": trigger or None,
        "latest_attempt_at": last_iso,
        "latest_attempt_time_status": attempt_time_status,
        "last_successful_sync_at": last_iso if success_timestamp_valid else None,
        "last_successful_scheduled_sync_at": (
            last_iso
            if success_timestamp_valid and trigger == "scheduled"
            else None
        ),
        "last_success_evidence_scope": "latest_attempt_only",
        "in_progress_observable": False,
        "last_started_at_observable": False,
        "automatic_update_status": automatic_update_status,
        "last_error_present": error_evidence_status == "invalid_type" or bool(error),
        "last_error_evidence_status": error_evidence_status,
        "last_trigger_evidence_status": trigger_evidence_status,
        "next_run_input_status": next_run_input_status,
        "next_run_time_status": (
            "missing"
            if next_run_missing
            else "invalid"
            if next_run_utc is None
            else "valid"
        ),
        "diagnostic_scope": "pipeline_execution_only",
        "authoritative_currentness_confirmed": False,
    }
