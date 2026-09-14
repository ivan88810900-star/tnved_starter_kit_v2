"""Versioned, default-OFF enforcement bridge for exact official NTM rows.

The bridge is intentionally narrower than the exact advisory evaluators.  A
row must be exact, complete, positive and named in the frozen allowlist below.
Even then it changes broker requirements only when the separate feature flag is
explicitly enabled.  The normal runtime therefore exposes a shadow audit only.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from typing import Any

CURATED_ENFORCEMENT_FLAG = "NTM_V2_OFFICIAL_CURATED_ENFORCEMENT_ENABLED"
CURATED_ALLOWLIST_VERSION = "official-ntm-curated-2026-08-15.1"
TRUSTED_EVIDENCE_KINDS = frozenset(
    {"trusted_official_registry_adapter", "trusted_document_adapter"}
)

# These are exact rule identifiers, not HS prefixes.  Adding a rule requires a
# source-backed negative-test set and a new allowlist version.
CURATED_RULE_ALLOWLIST: dict[str, dict[str, str]] = {
    "D30-2.30-HCB-2903920000": {
        "family": "licensing",
        "permit_type": "ЛЗ/заключение",
    },
    "RF-PP1284-2.1.1-AMITON": {
        "family": "export_control_dual_use",
        "permit_type": "ЛЗ/разрешение ФСТЭК",
    },
}


def _env_truthy(name: str) -> bool:
    return (os.getenv(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def is_official_curated_enforcement_enabled() -> bool:
    """The exact official bridge is always OFF unless explicitly enabled."""

    return _env_truthy(CURATED_ENFORCEMENT_FLAG)


def _rule_id(row: Mapping[str, Any]) -> str:
    return str(row.get("curated_enforcement_key") or row.get("rule_id") or "").strip()


def _eligibility_failure(row: Mapping[str, Any]) -> str | None:
    rule_id = _rule_id(row)
    policy = CURATED_RULE_ALLOWLIST.get(rule_id)
    if policy is None:
        return "rule_not_in_versioned_allowlist"
    if row.get("applicability") != "definite":
        return "applicability_not_definite"
    if row.get("requirement_applicable") is False:
        return "negative_or_excluded_result"
    if row.get("candidate_only") is True:
        return "candidate_only_result"
    if list(row.get("missing_facts") or []):
        return "structured_facts_incomplete"
    if str(row.get("family") or "") != policy["family"]:
        return "family_mismatch"
    if str(row.get("permit_type") or "") != policy["permit_type"]:
        return "permit_type_mismatch"
    if row.get("enforcement_eligible") is not True:
        return "source_policy_disallows_enforcement"
    if row.get("curated_allowlist_eligible") is not True:
        return "exact_rule_not_allowlist_eligible"
    if str(row.get("evidence_trust") or "") not in TRUSTED_EVIDENCE_KINDS:
        return "untrusted_caller_supplied_evidence"
    if row.get("trusted_source_verified") is not True:
        return "trusted_source_not_verified"
    return None


def collect_curated_enforcement_candidates(
    requirements: Iterable[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Return exact eligible rows and auditable rejected-row reasons."""

    eligible: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    for raw in requirements:
        row = dict(raw)
        rule_id = _rule_id(row)
        if not rule_id:
            continue
        failure = _eligibility_failure(row)
        if failure:
            rejected.append({"rule_id": rule_id, "reason": failure})
            continue
        eligible.append(row)
    return eligible, rejected


def apply_curated_official_enforcement(
    broker_required_permits: Iterable[Mapping[str, Any]],
    exact_requirements: Iterable[Mapping[str, Any]],
    *,
    enabled: bool | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Apply eligible exact rows only behind the explicit rollout flag."""

    broker = [dict(row) for row in broker_required_permits]
    exact_rows = [dict(row) for row in exact_requirements]
    eligible, rejected = collect_curated_enforcement_candidates(exact_rows)
    flag_enabled = (
        is_official_curated_enforcement_enabled() if enabled is None else bool(enabled)
    )
    existing = {(str(row.get("permit_type") or ""), row.get("tr_ts")) for row in broker}
    applied_rule_ids: list[str] = []
    duplicate_rule_ids: list[str] = []
    if flag_enabled:
        for row in eligible:
            key = (str(row.get("permit_type") or ""), row.get("tr_ts"))
            rule_id = _rule_id(row)
            if key in existing:
                duplicate_rule_ids.append(rule_id)
                continue
            existing.add(key)
            broker.append(
                {
                    "permit_type": key[0],
                    "tr_ts": key[1],
                    "tr_ts_full_name": "",
                    "description": str(row.get("rule_name") or rule_id),
                    "legal_ref": str(
                        row.get("source_url") or row.get("source_revision") or ""
                    ),
                    "matched_prefix": str(
                        row.get("hs_prefix") or row.get("matched_hs_scope") or ""
                    ),
                    "priority": 100,
                    "trigger": None,
                    "source": str(
                        row.get("source")
                        or row.get("source_kind")
                        or "official_ntm_exact"
                    ),
                    "source_label": row.get("source_label"),
                    "applicability": "definite",
                    "official_rule_id": rule_id,
                    "allowlist_version": CURATED_ALLOWLIST_VERSION,
                    "used_for_missing_check": True,
                }
            )
            applied_rule_ids.append(rule_id)

    audit = {
        "flag": CURATED_ENFORCEMENT_FLAG,
        "enabled": flag_enabled,
        "default": False,
        "allowlist_version": CURATED_ALLOWLIST_VERSION,
        "allowlist_rule_ids": sorted(CURATED_RULE_ALLOWLIST),
        "trusted_evidence_kinds": sorted(TRUSTED_EVIDENCE_KINDS),
        "shadow_candidate_rule_ids": sorted(
            {
                _rule_id(row)
                for row in exact_rows
                if _rule_id(row) in CURATED_RULE_ALLOWLIST
                and row.get("applicability") == "definite"
                and not list(row.get("missing_facts") or [])
            }
        ),
        "eligible_rule_ids": sorted(_rule_id(row) for row in eligible),
        "applied_rule_ids": sorted(applied_rule_ids),
        "duplicate_rule_ids": sorted(duplicate_rule_ids),
        "rejected": rejected,
        "broker_changed": bool(applied_rule_ids),
    }
    return broker, audit


__all__ = [
    "CURATED_ALLOWLIST_VERSION",
    "CURATED_ENFORCEMENT_FLAG",
    "CURATED_RULE_ALLOWLIST",
    "TRUSTED_EVIDENCE_KINDS",
    "apply_curated_official_enforcement",
    "collect_curated_enforcement_candidates",
    "is_official_curated_enforcement_enabled",
]
