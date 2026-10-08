"""Pure recovery/notification decisions. No network, credentials or write authority.

A scheduler wake-up is not product progress. A model-visible notification is not
user-visible delivery. These distinctions must survive new coordinator sessions.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re

RESOLVED = frozenset({"GRANTED", "AUTHORIZED", "CONSUMED", "CLOSED", "REJECTED",
                      "MERGED_AUTHORIZATION_CONSUMED", "MERGED_OWNER_AUTHORIZED_CONSUMED"})
IDENTITY_FIELDS = ("action", "pr", "exact_head_sha", "request_id", "packet_sha256",
                   "prior_request_id", "prior_packet_sha256", "contract_sha")


def _now(value):
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("Timezone-aware check time required")
    return value.astimezone(timezone.utc)


def _time(value):
    if not isinstance(value, str):
        raise ValueError("Timestamp required")
    try:
        return _now(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except (ValueError, TypeError):
        raise ValueError("Invalid timestamp") from None


def incident_key(gate):
    """Stable across poll timestamps and changing prose; exact new scope is new."""
    if not isinstance(gate, dict) or not isinstance(gate.get("action"), str) or not gate["action"].strip():
        raise ValueError("Explicit gate action required")
    identity = {key: gate.get(key) for key in IDENTITY_FIELDS}
    for value in identity.values():
        if value is not None and (type(value) not in (str, int) or
                                  (isinstance(value, str) and len(value) > 200)):
            raise ValueError("Invalid gate identity")
    raw = json.dumps(identity, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def observe(a6_state, automation, *, now, last_material_progress_at=None,
            active_coordinator=False, stall_seconds=7200):
    """Return facts for a read-only observer, not permission to perform an action.

    Missing delivery/authorization evidence is not silently promoted to success.
    A valid active coordinator prevents a paused schedule alone from implying
    stopped work. The caller must verify that coordinator from the live lease.
    """
    now = _now(now)
    if not isinstance(a6_state, dict) or not isinstance(automation, dict):
        raise ValueError("Live state and automation snapshots required")
    if type(stall_seconds) is not int or stall_seconds < 3600:
        raise ValueError("Bounded stall window required")
    gate = a6_state.get("owner_gate")
    authorization = gate.get("authorization") if isinstance(gate, dict) else None
    # Do not hard-code only merge/production actions: A6 export gates were lost
    # by that filter. Unknown authorization remains unresolved, never granted.
    if isinstance(gate, dict) and gate.get("action") and (not isinstance(authorization, str) or authorization not in RESOLVED):
        return {"status": "OWNER_ACTION_REQUIRED", "event_key": incident_key(gate),
                "owner_action_required": True, "reason": "UNRESOLVED_OWNER_GATE",
                "external_export_authorized": False}
    enabled = automation.get("is_enabled")
    if type(enabled) is not bool or type(active_coordinator) is not bool:
        return {"status": "OBSERVATION_UNAVAILABLE", "owner_action_required": False,
                "reason": "AUTOMATION_OR_COORDINATOR_STATE_UNKNOWN"}
    if not enabled and not active_coordinator:
        return {"status": "WORK_STOPPED", "owner_action_required": False,
                "reason": "COORDINATOR_SCHEDULE_DISABLED"}
    if last_material_progress_at is not None:
        progress = _time(last_material_progress_at)
        if progress > now:
            return {"status": "OBSERVATION_UNAVAILABLE", "owner_action_required": False,
                    "reason": "PROGRESS_TIMESTAMP_IN_FUTURE"}
        if (now - progress).total_seconds() >= stall_seconds and not active_coordinator:
            return {"status": "WORK_STALLED", "owner_action_required": False,
                    "reason": "NO_MATERIAL_PROGRESS"}
    return {"status": "NO_NEW_OWNER_GATE", "owner_action_required": False,
            "reason": "NOT_A_READINESS_OR_PROGRESS_PROOF"}


def notification_attempt(event_key, route, result, *, now):
    """Normalize a transport receipt without inventing delivery confirmation.

    Only a transport explicitly reporting user-visible delivery with a concrete
    message id can supply DELIVERED. notify_parent's `notified` response supplies
    MODEL_QUEUED even when it includes a turnId; it is never such a receipt.
    No arbitrary provider or exception text is persisted.
    """
    if not isinstance(event_key, str) or re.fullmatch(r"[0-9a-f]{64}", event_key) is None:
        raise ValueError("Exact incident key required")
    if not isinstance(route, str) or route not in {"notify_parent", "task_result", "email", "push"}:
        raise ValueError("Unknown notification route")
    record = {"event_key": event_key, "route": route,
              "attempted_at": _now(now).isoformat().replace("+00:00", "Z"),
              "status": "UNCONFIRMED", "user_visible_delivery_confirmed": False}
    if not isinstance(result, dict) or result.get("is_error") is True or result.get("isError") is True:
        record["status"] = "FAILED"
    elif route == "notify_parent":
        record["status"] = "MODEL_QUEUED" if result.get("status") == "notified" else "FAILED"
    elif (result.get("status") == "delivered" and result.get("user_visible") is True and
          isinstance(result.get("message_id"), str) and
          re.fullmatch(r"[A-Za-z0-9_.:-]{1,180}", result["message_id"])):
        record.update(status="DELIVERED", user_visible_delivery_confirmed=True,
                      message_id=result["message_id"])
    return record


def needs_notification(event_key, attempts, *, now, retry_seconds=3600,
                       acknowledged_event_keys=()):
    """De-duplicate by confirmed delivery/owner acknowledgement, not observation.

    A failed/internal-only attempt remains pending and is retried at a bounded
    cadence. It must not be acknowledged merely because GitHub records a gate.
    """
    now = _now(now)
    if not isinstance(event_key, str) or re.fullmatch(r"[0-9a-f]{64}", event_key) is None:
        raise ValueError("Exact incident key required")
    if type(retry_seconds) is not int or retry_seconds < 3600:
        raise ValueError("Retry interval must be at least one hour")
    if event_key in acknowledged_event_keys:
        return False
    last_attempt = None
    for item in attempts:
        if not isinstance(item, dict) or item.get("event_key") != event_key:
            continue
        try:
            when = _time(item.get("attempted_at"))
        except ValueError:
            continue
        if when > now:
            continue
        if (isinstance(item.get("route"), str) and
                item.get("route") in {"task_result", "email", "push"} and
                item.get("status") == "DELIVERED" and
                item.get("user_visible_delivery_confirmed") is True and
                isinstance(item.get("message_id"), str) and
                re.fullmatch(r"[A-Za-z0-9_.:-]{1,180}", item["message_id"])):
            return False
        # Corrupt future records cannot silence the observer indefinitely.
        if when <= now and (last_attempt is None or when > last_attempt):
            last_attempt = when
    return last_attempt is None or (now - last_attempt).total_seconds() >= retry_seconds


def recovery_status(a6_state, lease_record, *, now, publication_policy="unknown"):
    """Separate this local task from a protected external-export gate.

    Read-only classification only. A lease is not proof of a live native session,
    a caller flag is not platform clearance, and this function never sends alerts.
    """
    from .lease import validate as validate_lease

    now = _now(now)
    if publication_policy not in {"blocked", "unknown"}:
        raise ValueError("Publication policy is not an authorization switch")
    if not isinstance(a6_state, dict):
        raise ValueError("A6 state object required")
    validate_lease(lease_record)
    pending = a6_state.get("pending_live_smoke")
    if not isinstance(pending, dict):
        raise ValueError("Pending request object required")
    request_id = pending.get("request_id")
    packet_hash = pending.get("packet_sha256")
    if (not isinstance(request_id, str) or
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", request_id) is None or
            not isinstance(packet_hash, str) or
            re.fullmatch(r"[0-9a-f]{64}", packet_hash) is None or
            type(pending.get("consumed")) is not bool or
            type(pending.get("dispatched")) is not bool):
        raise ValueError("Invalid pending request identity or lifecycle")
    # Unknown execution/scheduler state is kept unknown. In particular a released
    # lease or disabled duplicate scheduler cannot establish session termination.
    observed = observe(a6_state, {"is_enabled": None}, now=now,
                       active_coordinator=None)
    lease_active = (lease_record["state"] == "active" and
                    _time(lease_record["expires_at"]) > now)
    result = {
        "status": "READ_ONLY_WORK_AVAILABLE",
        "local_analysis_and_tests_allowed": True,
        "publication": ("PLATFORM_CLEARANCE_REQUIRED" if publication_policy == "blocked"
                        else "PERMISSION_UNVERIFIED"),
        "remote_write_authorized": False,
        "external_export_authorized": False,
        "provider_called": False,
        "request_regenerated": False,
        "request_id": request_id,
        "packet_sha256": packet_hash,
        "pending_unused": not (pending["consumed"] or pending["dispatched"]),
        "lease_state": lease_record["state"],
        "lease_active_at_observation": lease_active,
        "lease_generation": lease_record["generation"],
        "native_session_status": "UNVERIFIED",
        "export_gate_status": observed["status"],
        "notification_delivery": "UNCONFIRMED",
        "notification_sent": False,
        "task_owner_action_required": (observed["owner_action_required"] or
                                       publication_policy == "blocked"),
    }
    if "event_key" in observed:
        result["export_gate_event_key"] = observed["event_key"]
    return result
