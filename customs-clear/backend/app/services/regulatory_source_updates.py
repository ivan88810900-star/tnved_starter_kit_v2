"""Единая политика обновления всех зарегистрированных нормативных источников.

Структурированные официальные реестры можно безопасно обновлять автоматически.
Нормативные документы и курируемые правила только контролируются: изменение
источника не может само включить advisory/enforcement-правило.
"""

from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import os
import re
import sys
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from loguru import logger
from sqlalchemy import text as sql_text
from sqlalchemy import update as sql_update
from sqlalchemy.exc import IntegrityError

from ..db import SessionLocal
from ..models.regulatory import RegulatorySourceReview
from .regulatory_source_registry import REGULATORY_SOURCE_REGISTRY, TARIFF_RELIEF_SOURCE_REGISTRY

UpdateStrategy = Literal[
    "automatic_structured",
    "monitor_only",
    "manual_review",
    "local_reconcile",
    "optional_mirror",
]
UpdateCadence = Literal["daily", "weekly", "monthly", "all"]

BACKEND_ROOT = Path(__file__).resolve().parents[2]
LOCK_PATH = BACKEND_ROOT / "data" / "runtime" / "regulatory-source-updates.lock"
LAST_REPORT_PATH = BACKEND_ROOT / "data" / "runtime" / "regulatory-source-update-last.json"
REVIEW_EVIDENCE_GENERATIONS_PATH = (
    BACKEND_ROOT / "data" / "regulatory_review_generations.json"
)
ADAPTER_RESULT_PREFIX = "REGULATORY_SYNC_RESULT="

# Child refresh processes are a narrow data-ingestion trust boundary.  Do not
# inherit the API process environment: it commonly contains unrelated LLM,
# admin, mail, object-store and deployment credentials.  Each adapter receives
# only its scoped database credential plus non-secret transport/validation
# settings that it actually consumes.
_ADAPTER_BASE_ENV_ALLOWLIST = frozenset(
    {
        "LANG",
        "LC_ALL",
        "TZ",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "REQUESTS_CA_BUNDLE",
        "CURL_CA_BUNDLE",
    }
)
_ADAPTER_ENV_ALLOWLIST_BY_ID: dict[str, frozenset[str]] = {
    "cbr_rates": frozenset({"CBR_MAX_RATE_AGE_DAYS"}),
    "sgr_registry": frozenset(
        {
            "REGULATORY_EEC_SGR_REGISTRY_MIN_ROWS",
            "REGULATORY_EEC_SGR_REGISTRY_MAX_SHRINK_FRACTION",
        }
    ),
    "state_registries": frozenset(
        {
            "REGULATORY_EEC_FSS_NOTIFICATIONS_REGISTRY_MIN_ROWS",
            "REGULATORY_EEC_FSS_NOTIFICATIONS_REGISTRY_MAX_SHRINK_FRACTION",
            "REGULATORY_EEC_REO_VCHU_REGISTRY_MIN_ROWS",
            "REGULATORY_EEC_REO_VCHU_REGISTRY_MAX_SHRINK_FRACTION",
        }
    ),
    "ofac_sdn": frozenset(
        {
            "REGULATORY_OFAC_SDN_LIST_MIN_ROWS",
            "REGULATORY_OFAC_SDN_LIST_MAX_SHRINK_FRACTION",
        }
    ),
    "eu_sanctions": frozenset(
        {
            "REGULATORY_EU_SANCTIONS_LIST_MIN_ROWS",
            "REGULATORY_EU_SANCTIONS_LIST_MAX_SHRINK_FRACTION",
        }
    ),
    "fsa_opendata": frozenset(
        {
            "OPENDATA_USER_AGENT",
            "OPENDATA_FSA_USER_AGENT",
            "OPENDATA_HTTP_TIMEOUT",
            "REGULATORY_FSA_RSS_REGISTRY_MIN_ROWS",
            "REGULATORY_FSA_RSS_REGISTRY_MAX_SHRINK_FRACTION",
            "REGULATORY_FSA_RDS_REGISTRY_MIN_ROWS",
            "REGULATORY_FSA_RDS_REGISTRY_MAX_SHRINK_FRACTION",
        }
    ),
    "trois_opendata": frozenset(
        {
            "OPENDATA_USER_AGENT",
            "OPENDATA_HTTP_TIMEOUT",
            "REGULATORY_FTS_TROIS_REGISTRY_MIN_ROWS",
            "REGULATORY_FTS_TROIS_REGISTRY_MAX_SHRINK_FRACTION",
        }
    ),
    "customs_opendata": frozenset(
        {
            "OPENDATA_USER_AGENT",
            "OPENDATA_HTTP_TIMEOUT",
            "REGULATORY_FTS_CUSTOMS_DOCUMENT_MASKS_MIN_ROWS",
            "REGULATORY_FTS_CUSTOMS_DOCUMENT_MASKS_MAX_SHRINK_FRACTION",
        }
    ),
}


@dataclass(frozen=True)
class UpdatePolicy:
    source_id: str
    strategy: UpdateStrategy
    cadence: Literal["daily", "weekly", "monthly", "manual"]
    adapter_id: str | None = None
    reason: str = ""


@dataclass(frozen=True)
class UpdateAdapter:
    adapter_id: str
    command: tuple[str, ...]
    source_ids: tuple[str, ...]
    allowed_write_tables: tuple[str, ...]
    execution_mode: Literal["safe_apply", "validation_only"] = "safe_apply"


AUTOMATIC_ADAPTERS: tuple[UpdateAdapter, ...] = (
    UpdateAdapter(
        "cbr_rates",
        ("scripts/update_rates.py", "--strict", "--json"),
        ("cbr_exchange_rates",),
        ("exchange_rates", "source_status", "sync_log"),
    ),
    UpdateAdapter(
        "sgr_registry",
        ("scripts/sync_sgr_registry.py", "--nsi", "--strict", "--json"),
        ("eec_sgr_registry",),
        ("sgr_certificates", "source_status", "sync_log"),
    ),
    UpdateAdapter(
        "state_registries",
        ("scripts/sync_state_registries.py", "--nsi-only", "--strict", "--json"),
        ("eec_fss_notifications_registry", "eec_reo_vchu_registry"),
        ("fss_notifications", "reo_registry", "source_status", "sync_log"),
    ),
    UpdateAdapter(
        "ofac_sdn",
        (
            "scripts/sync_ofac_sanctions.py",
            "--official-only",
            "--validate-only",
            "--strict",
            "--json",
        ),
        ("ofac_sdn_list",),
        ("source_status", "sync_log"),
        "validation_only",
    ),
    UpdateAdapter(
        "eu_sanctions",
        (
            "scripts/sync_eu_sanctions.py",
            "--official-only",
            "--validate-only",
            "--strict",
            "--json",
        ),
        ("eu_sanctions_list",),
        ("source_status", "sync_log"),
        "validation_only",
    ),
    UpdateAdapter(
        "fsa_opendata",
        ("scripts/opendata_sync.py", "--source", "fsa", "--strict"),
        ("fsa_registry_evidence",),
        ("fsa_certificates", "opendata_sync_log", "source_status", "sync_log"),
    ),
    UpdateAdapter(
        "trois_opendata",
        ("scripts/opendata_sync.py", "--source", "trois", "--strict"),
        ("fts_trois_registry",),
        ("trois_registry", "opendata_sync_log", "source_status", "sync_log"),
    ),
    UpdateAdapter(
        "customs_opendata",
        ("scripts/opendata_sync.py", "--source", "customs", "--strict"),
        ("fts_customs_document_masks",),
        ("customs_doc_masks", "opendata_sync_log", "source_status", "sync_log"),
    ),
)

_DAILY_AUTOMATIC = {
    "cbr_exchange_rates": "cbr_rates",
    "eec_sgr_registry": "sgr_registry",
    "eec_fss_notifications_registry": "state_registries",
    "eec_reo_vchu_registry": "state_registries",
    "ofac_sdn_list": "ofac_sdn",
    "eu_sanctions_list": "eu_sanctions",
}
_WEEKLY_AUTOMATIC = {
    "fsa_registry_evidence": "fsa_opendata",
    "fts_trois_registry": "trois_opendata",
    "fts_customs_document_masks": "customs_opendata",
}
_MONITOR_ONLY = {
    *(entry.source_id for entry in TARIFF_RELIEF_SOURCE_REGISTRY),
    "eec_ett_tnved",
    "eec_tr_ts_catalog",
    "eec_classification_decisions",
    "fts_preliminary_classification",
    "pravo_gov_publication",
    "eec_decision30_ntm_contours",
    "rf_pp_2425_conformity",
    "eec_sgr_decision_299",
    "eec_veterinary_decision_317",
    "eec_phytosanitary_decisions_318_157",
    "rf_export_control_lists",
    "regulatory_documents_corpus",
    "trade_remedies_official",
    "trade_remedies_special_safeguard_official",
    "trade_remedies_countervailing_official",
    "rf_excise_tax_code",
    "eec_odata_vat_preferences",
}
_LOCAL_RECONCILE = {
    "official_sgr_ntm_v2_curated",
    "legacy_ntm_tr_catalog",
    "sanction_import_risks",
    "country_risks_geopolitics",
    "geo_special_duties_embargo",
}
_OPTIONAL_MIRRORS = {
    "ifcg_preliminary_mirror",
    "tks_predecisions_mirror",
    "alta_tamdoc_mirror",
    "non_tariff_measures_tks",
}
_MANUAL_REVIEW = {"regulatory_ai_extracts"}


def _build_policies() -> tuple[UpdatePolicy, ...]:
    policies: list[UpdatePolicy] = []
    for entry in REGULATORY_SOURCE_REGISTRY:
        source_id = entry.source_id
        if source_id in _DAILY_AUTOMATIC:
            policies.append(UpdatePolicy(source_id, "automatic_structured", "daily", _DAILY_AUTOMATIC[source_id]))
        elif source_id in _WEEKLY_AUTOMATIC:
            policies.append(UpdatePolicy(source_id, "automatic_structured", "weekly", _WEEKLY_AUTOMATIC[source_id]))
        elif source_id in _MONITOR_ONLY:
            policies.append(UpdatePolicy(source_id, "monitor_only", "daily", reason="Изменение официального документа требует правовой проверки."))
        elif source_id in _LOCAL_RECONCILE:
            policies.append(UpdatePolicy(source_id, "local_reconcile", "monthly", reason="Курируемый слой обновляется только после проверки первичного источника."))
        elif source_id in _OPTIONAL_MIRRORS:
            policies.append(UpdatePolicy(source_id, "optional_mirror", "manual", reason="Коммерческое зеркало не является source of truth."))
        elif source_id in _MANUAL_REVIEW:
            policies.append(UpdatePolicy(source_id, "manual_review", "manual", reason="ИИ-извлечение не допускается к автоматическому применению."))
    return tuple(policies)


UPDATE_POLICIES = _build_policies()


def _utc_naive(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is not None:
        current = current.astimezone(timezone.utc).replace(tzinfo=None)
    return current


def _review_period(value: datetime | None = None) -> str:
    return _utc_naive(value).strftime("%Y-%m")


def _review_datetime_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _review_evidence_generation_contract() -> dict[str, dict[str, Any]]:
    """Load and validate the checked-in monotonic evidence-generation contract."""
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        payload = json.loads(
            REVIEW_EVIDENCE_GENERATIONS_PATH.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate_keys,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(
            "regulatory review evidence-generation manifest is missing or invalid"
        ) from exc
    if (
        not isinstance(payload, dict)
        or set(payload) != {"contract_version", "sources"}
        or payload.get("contract_version") != 1
    ):
        raise RuntimeError(
            "regulatory review evidence-generation manifest contract_version must be 1"
        )
    sources = payload.get("sources")
    if not isinstance(sources, dict) or set(sources) != _LOCAL_RECONCILE:
        actual = sorted(sources) if isinstance(sources, dict) else []
        raise RuntimeError(
            "regulatory review evidence-generation source set differs from the managed "
            f"source set: expected={sorted(_LOCAL_RECONCILE)!r}, actual={actual!r}"
        )
    normalized: dict[str, dict[str, Any]] = {}
    for source_id, raw_entry in sources.items():
        if not isinstance(raw_entry, dict) or set(raw_entry) != {
            "generation",
            "artifacts",
        }:
            raise RuntimeError(
                f"invalid evidence-generation entry for {source_id!r}"
            )
        generation = raw_entry.get("generation")
        if isinstance(generation, bool) or not isinstance(generation, int) or generation < 1:
            raise RuntimeError(
                f"evidence generation for {source_id!r} must be a positive integer"
            )
        raw_artifacts = raw_entry.get("artifacts")
        if not isinstance(raw_artifacts, list) or not raw_artifacts:
            raise RuntimeError(
                f"evidence-generation artifacts for {source_id!r} must be non-empty"
            )
        artifacts: list[dict[str, str]] = []
        for artifact in raw_artifacts:
            if not isinstance(artifact, dict) or set(artifact) != {"path", "sha256"}:
                raise RuntimeError(
                    f"invalid evidence-generation artifact for {source_id!r}"
                )
            relative_path = artifact.get("path")
            digest = artifact.get("sha256")
            if not isinstance(relative_path, str) or not relative_path.strip():
                raise RuntimeError(
                    f"invalid evidence-generation artifact path for {source_id!r}"
                )
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise RuntimeError(
                    f"invalid evidence-generation artifact sha256 for {source_id!r}"
                )
            artifacts.append({"path": relative_path, "sha256": digest})
        artifact_paths = [artifact["path"] for artifact in artifacts]
        if len(artifact_paths) != len(set(artifact_paths)):
            raise RuntimeError(
                f"duplicate evidence-generation artifact path for {source_id!r}"
            )
        normalized[str(source_id)] = {
            "generation": generation,
            "artifacts": sorted(artifacts, key=lambda artifact: artifact["path"]),
        }
    return normalized


def _source_evidence_binding(source_id: str) -> dict[str, Any]:
    """Bind exact bytes/metadata to a checked-in monotonic evidence generation."""
    entries = [entry for entry in REGULATORY_SOURCE_REGISTRY if entry.source_id == source_id]
    if len(entries) != 1:
        raise RuntimeError(
            f"review evidence requires exactly one registry entry for {source_id!r}"
        )
    entry = entries[0]
    if not entry.local_paths:
        raise RuntimeError(f"review evidence has no local artifacts for {source_id!r}")

    generation_contract = _review_evidence_generation_contract()[source_id]
    declared_artifacts = generation_contract["artifacts"]
    declared_paths = [artifact["path"] for artifact in declared_artifacts]
    registry_paths = sorted(entry.local_paths)
    if declared_paths != registry_paths:
        raise RuntimeError(
            f"evidence-generation paths differ from registry local_paths for {source_id!r}: "
            f"expected={registry_paths!r}, actual={declared_paths!r}"
        )
    declared_sha_by_path = {
        artifact["path"]: artifact["sha256"] for artifact in declared_artifacts
    }

    artifacts: list[dict[str, Any]] = []
    for relative_path in sorted(entry.local_paths):
        artifact_path = (BACKEND_ROOT / relative_path).resolve()
        if not artifact_path.is_relative_to(BACKEND_ROOT) or not artifact_path.is_file():
            raise RuntimeError(
                f"review evidence artifact is missing or outside backend root: {relative_path!r}"
            )
        payload = artifact_path.read_bytes()
        artifact_sha256 = hashlib.sha256(payload).hexdigest()
        if declared_sha_by_path[relative_path] != artifact_sha256:
            raise RuntimeError(
                "local regulatory review artifact changed without an evidence-generation "
                f"manifest update for {source_id!r}: {relative_path!r}"
            )
        artifacts.append(
            {
                "path": artifact_path.relative_to(BACKEND_ROOT).as_posix(),
                "sha256": artifact_sha256,
                "size_bytes": len(payload),
            }
        )

    official_url = str(entry.official_url or "").strip()
    if official_url:
        evidence_scope = "local_artifacts_plus_registry_metadata"
        limitation = (
            "Binding covers checked-in local artifacts and recorded upstream metadata; "
            "it does not assert that the live upstream content is unchanged."
        )
    else:
        evidence_scope = "local_fixture_only_no_official_upstream"
        limitation = (
            "Binding covers a local fixture only; this source has no official upstream URL "
            "and cannot establish current legal completeness."
        )
    manifest = {
        "contract_version": 1,
        "source_id": entry.source_id,
        "title": entry.title,
        "description": entry.description,
        "authority_level": entry.authority_level,
        "official_url": official_url,
        "monitor_urls": list(entry.monitor_urls),
        "source_status_code": entry.source_status_code,
        "sync_script": entry.sync_script,
        "refresh_cadence": entry.refresh_cadence,
        "local_artifacts": artifacts,
        "known_gaps": list(entry.known_gaps),
        "evidence_generation": generation_contract["generation"],
        "generation_manifest_path": REVIEW_EVIDENCE_GENERATIONS_PATH.relative_to(
            BACKEND_ROOT
        ).as_posix(),
        "evidence_scope": evidence_scope,
        "binding_limitation": limitation,
    }
    canonical = json.dumps(
        manifest,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "evidence_sha256": hashlib.sha256(canonical).hexdigest(),
        "evidence_generation": generation_contract["generation"],
        "evidence_scope": evidence_scope,
        "evidence_manifest": manifest,
    }


def _review_row_dict(row: RegulatorySourceReview) -> dict[str, Any]:
    return {
        "id": int(row.id),
        "source_id": str(row.source_id),
        "due_period": str(row.due_period),
        "strategy": str(row.strategy),
        "cadence": str(row.cadence),
        "status": str(row.status),
        "reason": str(row.reason or ""),
        "evidence_sha256": str(row.evidence_sha256),
        "evidence_generation": int(row.evidence_generation),
        "evidence_scope": str(row.evidence_scope),
        "evidence_manifest": row.evidence_manifest,
        "first_raised_at": _review_datetime_iso(row.first_raised_at),
        "last_raised_at": _review_datetime_iso(row.last_raised_at),
        "occurrence_count": int(row.occurrence_count or 0),
        "resolved_at": _review_datetime_iso(row.resolved_at),
        "resolved_by": str(row.resolved_by or ""),
        "asserted_by": str(row.asserted_by or ""),
        "resolution_ref": str(row.resolution_ref or ""),
        "superseded_at": _review_datetime_iso(row.superseded_at),
        "superseded_by_evidence_sha256": str(
            row.superseded_by_evidence_sha256 or ""
        ),
        "superseded_by_generation": (
            int(row.superseded_by_generation)
            if row.superseded_by_generation is not None
            else None
        ),
    }


def list_regulatory_source_reviews(
    *,
    status: Literal["pending", "resolved", "superseded", "all"] = "pending",
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Read the durable review queue without relying on the rotating JSON report."""
    bounded_limit = max(1, min(int(limit), 1000))
    with SessionLocal() as db:
        query = db.query(RegulatorySourceReview)
        if status != "all":
            query = query.filter(RegulatorySourceReview.status == status)
        rows = (
            query.order_by(
                RegulatorySourceReview.first_raised_at.asc(),
                RegulatorySourceReview.id.asc(),
            )
            .limit(bounded_limit)
            .all()
        )
        return [_review_row_dict(row) for row in rows]


def regulatory_review_queue_summary() -> dict[str, Any]:
    pending = list_regulatory_source_reviews(status="pending")
    source_id_values = [str(row["source_id"]) for row in pending]
    duplicate_source_ids = sorted(
        {
            source_id
            for source_id in source_id_values
            if source_id_values.count(source_id) > 1
        }
    )
    if duplicate_source_ids:
        raise RuntimeError(
            "durable regulatory review queue contains duplicate pending sources: "
            + ", ".join(duplicate_source_ids)
        )
    source_ids = sorted(source_id_values)
    return {
        "contract_version": 1,
        "durable": True,
        "status": "review_required" if pending else "clear",
        "notification_required": bool(pending),
        "notification_event": "regulatory_source_review_required" if pending else None,
        "managed_source_ids": sorted(_LOCAL_RECONCILE),
        "pending_count": len(pending),
        "pending_source_ids": source_ids,
        "oldest_pending_at": pending[0]["first_raised_at"] if pending else None,
        "items": pending,
    }


def _new_pending_review(
    *,
    policy: UpdatePolicy,
    binding: dict[str, Any],
    due_period: str,
    raised_at: datetime,
) -> RegulatorySourceReview:
    return RegulatorySourceReview(
        source_id=policy.source_id,
        due_period=due_period,
        strategy=policy.strategy,
        cadence=policy.cadence,
        status="pending",
        reason=policy.reason,
        evidence_sha256=binding["evidence_sha256"],
        evidence_generation=binding["evidence_generation"],
        evidence_scope=binding["evidence_scope"],
        evidence_manifest=binding["evidence_manifest"],
        first_raised_at=raised_at,
        last_raised_at=raised_at,
        occurrence_count=1,
    )


class _ReviewQueueConcurrentMutation(RuntimeError):
    """Internal signal to retry the complete five-source queue transaction."""


class RegulatoryReviewEvidenceConflict(RuntimeError):
    """A deployment attempts to reactivate or fork durable evidence lineage."""


def _refresh_pending_review_with_cas(
    db: Any,
    *,
    pending_id: int,
    expected_evidence_sha256: str,
    expected_evidence_generation: int,
    policy: UpdatePolicy,
    binding: dict[str, Any],
    due_period: str,
    raised_at: datetime,
) -> dict[str, Any]:
    """Refresh one pending row without ever mutating concurrently reviewed bytes.

    A reviewer may resolve the old digest between the queue read and update.  A
    normal ORM flush would then overwrite the digest on the now-resolved row.
    This CAS touches only the exact still-pending snapshot. Changed bytes never
    overwrite it: the predecessor is marked ``superseded`` and a new pending
    evidence row is appended in the same transaction.
    """
    original_evidence = str(expected_evidence_sha256)
    original_generation = int(expected_evidence_generation)
    successor_evidence = str(binding["evidence_sha256"])
    successor_generation = int(binding["evidence_generation"])
    if (
        original_evidence == successor_evidence
        and original_generation == successor_generation
    ):
        result = db.execute(
            sql_update(RegulatorySourceReview)
            .where(
                RegulatorySourceReview.id == int(pending_id),
                RegulatorySourceReview.status == "pending",
                RegulatorySourceReview.evidence_sha256 == original_evidence,
                RegulatorySourceReview.evidence_generation == original_generation,
            )
            .values(
                reason=policy.reason,
                last_raised_at=raised_at,
                occurrence_count=RegulatorySourceReview.occurrence_count + 1,
            )
            .execution_options(synchronize_session=False)
        )
        if int(result.rowcount or 0) != 1:
            # Abort *all five* source updates and re-read in a new transaction. On
            # retry a resolved old row remains immutable and changed bytes create a
            # fresh pending row; an already-current concurrent update is carried.
            raise _ReviewQueueConcurrentMutation(
                f"regulatory review {pending_id} changed during evidence refresh"
            )
        return {
            "action": "carried",
            "evidence_changed": False,
            "evidence_sha256": original_evidence,
            "evidence_generation": original_generation,
            "superseded_evidence_sha256": None,
            "superseded_evidence_generation": None,
        }
    if successor_generation <= original_generation:
        raise RegulatoryReviewEvidenceConflict(
            "regulatory review evidence generation must increase for changed "
            f"evidence: source={policy.source_id}, current={original_generation}, "
            f"observed={successor_generation}"
        )
    if original_evidence == successor_evidence:
        # A digest binds the generation itself; equality here is either a broken
        # test adapter or a cryptographic collision. Never create an ambiguous edge.
        raise RegulatoryReviewEvidenceConflict(
            f"regulatory review evidence digest was reused across generations for "
            f"{policy.source_id}"
        )
    result = db.execute(
        sql_update(RegulatorySourceReview)
        .where(
            RegulatorySourceReview.id == int(pending_id),
            RegulatorySourceReview.status == "pending",
            RegulatorySourceReview.evidence_sha256 == original_evidence,
            RegulatorySourceReview.evidence_generation == original_generation,
            RegulatorySourceReview.superseded_at.is_(None),
            RegulatorySourceReview.superseded_by_evidence_sha256 == "",
            RegulatorySourceReview.superseded_by_generation.is_(None),
        )
        .values(
            status="superseded",
            superseded_at=raised_at,
            superseded_by_evidence_sha256=successor_evidence,
            superseded_by_generation=successor_generation,
        )
        .execution_options(synchronize_session=False)
    )
    if int(result.rowcount or 0) != 1:
        raise _ReviewQueueConcurrentMutation(
            f"regulatory review {pending_id} changed during supersession"
        )
    db.add(
        _new_pending_review(
            policy=policy,
            binding=binding,
            due_period=due_period,
            raised_at=raised_at,
        )
    )
    return {
        "action": "superseded_and_created",
        "evidence_changed": True,
        "evidence_sha256": successor_evidence,
        "evidence_generation": successor_generation,
        "superseded_evidence_sha256": original_evidence,
        "superseded_evidence_generation": original_generation,
    }


def _raise_scheduled_regulatory_reviews(
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Idempotently persist each due local-reconcile review.

    An unresolved item is carried forward and touched on the next monthly pass;
    after resolution a new period creates a new row, preserving review history.
    Failure to write the complete set aborts the transaction and the scheduler
    cycle, so a local JSON report can never masquerade as a durable notification.
    """
    raised_at = _utc_naive(now)
    due_period = _review_period(raised_at)
    policies = sorted(
        (
            policy
            for policy in UPDATE_POLICIES
            if policy.strategy == "local_reconcile" and policy.cadence == "monthly"
        ),
        key=lambda policy: policy.source_id,
    )
    source_ids = [policy.source_id for policy in policies]
    if set(source_ids) != _LOCAL_RECONCILE or len(source_ids) != len(_LOCAL_RECONCILE):
        raise RuntimeError(
            "scheduled regulatory review policy set differs from the managed source set: "
            f"expected={sorted(_LOCAL_RECONCILE)!r}, actual={source_ids!r}"
        )
    for transaction_attempt in range(3):
        # Recompute after every concurrency retry so a stale refresh process
        # cannot restore an older local snapshot over a newer queue binding.
        bindings = {
            policy.source_id: _source_evidence_binding(policy.source_id)
            for policy in policies
        }
        created_source_ids: list[str] = []
        carried_source_ids: list[str] = []
        evidence_changed_source_ids: list[str] = []
        superseded_source_ids: list[str] = []
        already_reviewed_source_ids: list[str] = []

        with SessionLocal() as db:
            try:
                pending_rows = (
                    db.query(RegulatorySourceReview)
                    .filter(
                        RegulatorySourceReview.source_id.in_(source_ids),
                        RegulatorySourceReview.status == "pending",
                    )
                    .all()
                )
                pending_by_source = {str(row.source_id): row for row in pending_rows}
                current_rows = (
                    db.query(RegulatorySourceReview)
                    .filter(
                        RegulatorySourceReview.source_id.in_(source_ids),
                        RegulatorySourceReview.due_period == due_period,
                    )
                    .all()
                )
                history_rows = (
                    db.query(RegulatorySourceReview)
                    .filter(RegulatorySourceReview.source_id.in_(source_ids))
                    # Per-source supersession is serialized by the pending-row
                    # CAS. The append-only primary key is therefore a safer
                    # lineage order than replica-local wall clocks.
                    .order_by(RegulatorySourceReview.id.desc())
                    .all()
                )
                latest_by_source: dict[str, RegulatorySourceReview] = {}
                history_by_source: dict[str, list[RegulatorySourceReview]] = {}
                for row in history_rows:
                    source_id = str(row.source_id)
                    latest_by_source.setdefault(source_id, row)
                    history_by_source.setdefault(source_id, []).append(row)
                for policy in policies:
                    binding = bindings[policy.source_id]
                    successor_evidence = str(binding["evidence_sha256"])
                    successor_generation = int(binding["evidence_generation"])
                    source_history = history_by_source.get(policy.source_id, [])
                    if any(
                        str(row.evidence_sha256) == successor_evidence
                        and bool(str(row.superseded_by_evidence_sha256 or ""))
                        for row in source_history
                    ):
                        # A digest that already lost its place in this source's
                        # immutable lineage cannot become active again merely
                        # because an older rolling replica starts later.
                        raise RegulatoryReviewEvidenceConflict(
                            f"historically superseded evidence reappeared for "
                            f"{policy.source_id}: {successor_evidence}"
                        )
                    latest = latest_by_source.get(policy.source_id)
                    pending = pending_by_source.get(policy.source_id)
                    if pending is not None:
                        outcome = _refresh_pending_review_with_cas(
                            db,
                            pending_id=int(pending.id),
                            expected_evidence_sha256=str(pending.evidence_sha256),
                            expected_evidence_generation=int(
                                pending.evidence_generation
                            ),
                            policy=policy,
                            binding=binding,
                            due_period=due_period,
                            raised_at=raised_at,
                        )
                        if outcome["evidence_changed"]:
                            evidence_changed_source_ids.append(policy.source_id)
                        if outcome["action"] == "superseded_and_created":
                            created_source_ids.append(policy.source_id)
                            superseded_source_ids.append(policy.source_id)
                        elif outcome["action"] == "carried":
                            carried_source_ids.append(policy.source_id)
                        else:  # pragma: no cover - private helper contract
                            raise RuntimeError(
                                f"unsupported review refresh action: {outcome['action']}"
                            )
                        continue
                    # An unchanged snapshot already reviewed in this period is
                    # idempotent. A new digest appends a successor and records
                    # the transition on the latest resolved predecessor.
                    resolved_for_source = [
                        row
                        for row in current_rows
                        if str(row.source_id) == policy.source_id
                        and str(row.status) == "resolved"
                    ]
                    if any(
                        str(row.evidence_sha256) == successor_evidence
                        and int(row.evidence_generation) == successor_generation
                        and not str(row.superseded_by_evidence_sha256 or "")
                        for row in resolved_for_source
                    ):
                        already_reviewed_source_ids.append(policy.source_id)
                        continue
                    latest_binding = (
                        str(latest.evidence_sha256),
                        int(latest.evidence_generation),
                    ) if latest is not None else None
                    candidate_binding = (successor_evidence, successor_generation)
                    if latest is not None and latest_binding != candidate_binding:
                        predecessor_successor = str(
                            latest.superseded_by_evidence_sha256 or ""
                        )
                        predecessor_successor_generation = (
                            int(latest.superseded_by_generation)
                            if latest.superseded_by_generation is not None
                            else None
                        )
                        if successor_generation <= int(latest.evidence_generation):
                            raise RegulatoryReviewEvidenceConflict(
                                "regulatory review evidence generation did not increase "
                                f"for {policy.source_id}: current="
                                f"{int(latest.evidence_generation)}, observed="
                                f"{successor_generation}"
                            )
                        if str(latest.evidence_sha256) == successor_evidence:
                            raise RegulatoryReviewEvidenceConflict(
                                "regulatory review evidence digest was reused across "
                                f"generations for {policy.source_id}"
                            )
                        if str(latest.status) == "resolved" and not predecessor_successor:
                            transition = db.execute(
                                sql_update(RegulatorySourceReview)
                                .where(
                                    RegulatorySourceReview.id == int(latest.id),
                                    RegulatorySourceReview.status == "resolved",
                                    RegulatorySourceReview.evidence_sha256
                                    == str(latest.evidence_sha256),
                                    RegulatorySourceReview.evidence_generation
                                    == int(latest.evidence_generation),
                                    RegulatorySourceReview.superseded_at.is_(None),
                                    RegulatorySourceReview.superseded_by_evidence_sha256
                                    == "",
                                    RegulatorySourceReview.superseded_by_generation.is_(
                                        None
                                    ),
                                )
                                .values(
                                    superseded_at=raised_at,
                                    superseded_by_evidence_sha256=successor_evidence,
                                    superseded_by_generation=successor_generation,
                                )
                                .execution_options(synchronize_session=False)
                            )
                            if int(transition.rowcount or 0) != 1:
                                raise _ReviewQueueConcurrentMutation(
                                    f"resolved regulatory review {latest.id} changed "
                                    "during supersession"
                                )
                            superseded_source_ids.append(policy.source_id)
                            evidence_changed_source_ids.append(policy.source_id)
                        elif (
                            predecessor_successor == successor_evidence
                            and predecessor_successor_generation
                            == successor_generation
                        ):
                            # Recovery for a transaction imported from an older
                            # schema/tool that recorded the edge but lacks its
                            # successor row. Normal runtime transitions are
                            # atomic and do not enter this branch.
                            pass
                        else:
                            raise RegulatoryReviewEvidenceConflict(
                                f"regulatory review lineage fork for {policy.source_id}: "
                                "expected successor "
                                f"{predecessor_successor or 'missing'}@"
                                f"{predecessor_successor_generation or 'missing'}, "
                                f"observed {successor_evidence}@{successor_generation}"
                            )
                    db.add(
                        _new_pending_review(
                            policy=policy,
                            binding=binding,
                            due_period=due_period,
                            raised_at=raised_at,
                        )
                    )
                    created_source_ids.append(policy.source_id)
                handled_source_ids = (
                    set(created_source_ids)
                    | set(carried_source_ids)
                    | set(already_reviewed_source_ids)
                )
                if handled_source_ids != set(source_ids):
                    raise RuntimeError(
                        "durable regulatory review transaction did not handle the exact "
                        "managed source set"
                    )
                db.commit()
                break
            except (IntegrityError, _ReviewQueueConcurrentMutation) as exc:
                db.rollback()
                if transaction_attempt >= 2:
                    raise RuntimeError(
                        "durable regulatory review queue could not converge after "
                        "a concurrent mutation"
                    ) from exc
                # A concurrent refresh may have inserted the one allowed
                # pending row after our scan, or resolved/updated a row after
                # it was loaded. Retry the whole atomic set from fresh state;
                # never delete or overwrite the winner.
                continue
            except Exception:
                db.rollback()
                raise
    else:  # pragma: no cover - loop either breaks or raises on final attempt
        raise RuntimeError("durable regulatory review queue transaction did not converge")

    summary = regulatory_review_queue_summary()
    summary.update(
        {
            "checked_period": due_period,
            "expected_source_ids": source_ids,
            "created_source_ids": created_source_ids,
            "carried_source_ids": carried_source_ids,
            "evidence_changed_source_ids": evidence_changed_source_ids,
            "superseded_source_ids": superseded_source_ids,
            "already_reviewed_source_ids": already_reviewed_source_ids,
        }
    )
    return summary


def _validated_resolution_ref(value: str) -> str:
    reference = str(value or "").strip()
    if not reference:
        raise ValueError("resolution_ref is required")
    if len(reference) > 2048:
        raise ValueError("resolution_ref exceeds 2048 characters")
    if re.fullmatch(r"#[1-9][0-9]*", reference):
        return reference
    repository = os.getenv(
        "REGULATORY_REVIEW_GITHUB_REPOSITORY",
        "ivan88810900-star/tnved_starter_kit_v2",
    ).strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise RuntimeError("REGULATORY_REVIEW_GITHUB_REPOSITORY is invalid")
    same_repository_url = re.compile(
        rf"https://github\.com/{re.escape(repository)}/(?:issues|pull)/[1-9][0-9]*"
        r"(?:#issuecomment-[1-9][0-9]*)?"
    )
    if same_repository_url.fullmatch(reference):
        return reference
    raise ValueError(
        "resolution_ref must be #<issue-or-pr> or a same-repository GitHub issue/PR URL"
    )


def resolve_regulatory_source_review(
    review_id: int,
    *,
    authenticated_actor: str,
    asserted_by: str,
    resolution_ref: str,
    evidence_sha256: str,
    evidence_generation: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    """CAS-resolve a pending item against the exact reviewed evidence digest."""
    actor = str(authenticated_actor or "").strip()
    asserted = str(asserted_by or "").strip()
    reference = _validated_resolution_ref(resolution_ref)
    binding = str(evidence_sha256 or "").strip().lower()
    generation = evidence_generation
    if not actor:
        raise ValueError("authenticated_actor is required")
    if not asserted:
        raise ValueError("asserted_by is required")
    if len(actor) > 128:
        raise ValueError("authenticated_actor exceeds 128 characters")
    if len(asserted) > 128:
        raise ValueError("asserted_by exceeds 128 characters")
    if not re.fullmatch(r"[0-9a-f]{64}", binding):
        raise ValueError("evidence_sha256 must contain exactly 64 lowercase hex characters")
    if isinstance(generation, bool) or not isinstance(generation, int) or generation < 1:
        raise ValueError("evidence_generation must be a positive integer")
    resolved_at = _utc_naive(now)
    with SessionLocal() as db:
        try:
            current_row = db.get(RegulatorySourceReview, int(review_id))
            if current_row is None:
                raise KeyError(f"regulatory source review {review_id} was not found")
            if str(current_row.status) == "pending":
                if str(current_row.evidence_sha256) != binding:
                    raise ValueError(
                        "evidence_sha256 does not match the current review snapshot"
                    )
                if int(current_row.evidence_generation) != generation:
                    raise ValueError(
                        "evidence_generation does not match the current review snapshot"
                    )
                current_local_binding = _source_evidence_binding(
                    str(current_row.source_id)
                )
                if (
                    str(current_local_binding["evidence_sha256"]) != binding
                    or int(current_local_binding["evidence_generation"]) != generation
                ):
                    raise ValueError(
                        "current local evidence changed after this review was raised; "
                        "resolution is blocked pending explicit supersession"
                    )
            result = db.execute(
                sql_update(RegulatorySourceReview)
                .where(
                    RegulatorySourceReview.id == int(review_id),
                    RegulatorySourceReview.status == "pending",
                    RegulatorySourceReview.evidence_sha256 == binding,
                    RegulatorySourceReview.evidence_generation == generation,
                )
                .values(
                    status="resolved",
                    resolved_at=resolved_at,
                    resolved_by=actor,
                    asserted_by=asserted,
                    resolution_ref=reference,
                )
            )
            updated = int(result.rowcount or 0)
            if updated != 1:
                db.rollback()
            else:
                # Re-read local bytes after the SQL CAS as a narrow TOCTOU
                # guard.  Runtime artifacts are expected to be immutable; if a
                # deployment changes them during resolution, roll back rather
                # than authorize bytes the reviewer did not bind.
                final_local_binding = _source_evidence_binding(
                    str(current_row.source_id)
                )
                if (
                    str(final_local_binding["evidence_sha256"]) != binding
                    or int(final_local_binding["evidence_generation"]) != generation
                ):
                    raise ValueError(
                        "current local evidence changed during resolution; "
                        "the review remains pending"
                    )
                db.commit()
                row = db.get(RegulatorySourceReview, int(review_id))
                if row is None:  # pragma: no cover - defensive after committed PK update
                    raise RuntimeError("resolved regulatory review disappeared after commit")
                return _review_row_dict(row)
        except Exception:
            db.rollback()
            raise

    # The CAS lost or the submitted binding is stale. Re-read after ending the
    # failed transaction so PostgreSQL and SQLite both observe the winner.
    with SessionLocal() as db:
        row = db.get(RegulatorySourceReview, int(review_id))
        if row is None:
            raise KeyError(f"regulatory source review {review_id} was not found")
        if row.status == "resolved":
            if (
                row.evidence_sha256 == binding
                and int(row.evidence_generation) == generation
                and row.resolved_by == actor
                and row.asserted_by == asserted
                and row.resolution_ref == reference
            ):
                return _review_row_dict(row)
            raise ValueError("review is already resolved with different audit evidence")
        if row.status == "superseded":
            raise ValueError(
                "review evidence was superseded by "
                f"{row.superseded_by_evidence_sha256}; resolve the current pending item"
            )
        if row.status == "pending" and row.evidence_sha256 != binding:
            raise ValueError("evidence_sha256 does not match the current review snapshot")
        if row.status == "pending" and int(row.evidence_generation) != generation:
            raise ValueError(
                "evidence_generation does not match the current review snapshot"
            )
        if row.status == "pending":
            raise ValueError("review resolution lost a concurrent compare-and-set race")
        raise ValueError(f"unsupported regulatory review status: {row.status}")


def validate_update_coverage() -> dict[str, Any]:
    registry_ids = {entry.source_id for entry in REGULATORY_SOURCE_REGISTRY}
    policy_ids = [policy.source_id for policy in UPDATE_POLICIES]
    duplicates = sorted({source_id for source_id in policy_ids if policy_ids.count(source_id) > 1})
    missing = sorted(registry_ids - set(policy_ids))
    unknown = sorted(set(policy_ids) - registry_ids)

    adapter_by_id = {adapter.adapter_id: adapter for adapter in AUTOMATIC_ADAPTERS}
    invalid_adapters: list[str] = []
    unsafe_adapters: list[str] = []
    missing_scripts: list[str] = []
    for policy in UPDATE_POLICIES:
        if policy.strategy != "automatic_structured":
            continue
        adapter = adapter_by_id.get(policy.adapter_id or "")
        if adapter is None or policy.source_id not in adapter.source_ids:
            invalid_adapters.append(policy.source_id)
            continue
        if not adapter.allowed_write_tables or "--strict" not in adapter.command:
            unsafe_adapters.append(adapter.adapter_id)
        if adapter.execution_mode == "validation_only" and (
            "--validate-only" not in adapter.command
            or any(
                table
                in {
                    "sanction_entities",
                    "sanction_risks",
                    "ofac_sdn_list",
                    "eu_sanctions_list",
                }
                for table in adapter.allowed_write_tables
            )
        ):
            unsafe_adapters.append(adapter.adapter_id)
        script = BACKEND_ROOT / adapter.command[0]
        if not script.is_file():
            missing_scripts.append(str(script.relative_to(BACKEND_ROOT)))

    duplicate_adapter_ids = sorted(
        {
            adapter.adapter_id
            for adapter in AUTOMATIC_ADAPTERS
            if sum(row.adapter_id == adapter.adapter_id for row in AUTOMATIC_ADAPTERS) > 1
        }
    )
    adapter_ids = {adapter.adapter_id for adapter in AUTOMATIC_ADAPTERS}
    missing_child_env_policies = sorted(
        adapter_ids - set(_ADAPTER_ENV_ALLOWLIST_BY_ID)
    )
    unknown_child_env_policies = sorted(
        set(_ADAPTER_ENV_ALLOWLIST_BY_ID) - adapter_ids
    )
    invalid_evidence_generation_source_ids: list[str] = []
    for source_id in sorted(_LOCAL_RECONCILE):
        try:
            _source_evidence_binding(source_id)
        except RuntimeError:
            invalid_evidence_generation_source_ids.append(source_id)
    valid = not (
        duplicates
        or missing
        or unknown
        or invalid_adapters
        or missing_scripts
        or unsafe_adapters
        or duplicate_adapter_ids
        or missing_child_env_policies
        or unknown_child_env_policies
        or invalid_evidence_generation_source_ids
    )
    return {
        "valid": valid,
        "registry_source_count": len(registry_ids),
        "policy_source_count": len(policy_ids),
        "missing_source_ids": missing,
        "unknown_source_ids": unknown,
        "duplicate_source_ids": duplicates,
        "invalid_adapter_source_ids": sorted(invalid_adapters),
        "unsafe_adapter_ids": sorted(set(unsafe_adapters)),
        "duplicate_adapter_ids": duplicate_adapter_ids,
        "missing_child_env_policy_adapter_ids": missing_child_env_policies,
        "unknown_child_env_policy_adapter_ids": unknown_child_env_policies,
        "invalid_evidence_generation_source_ids": (
            invalid_evidence_generation_source_ids
        ),
        "missing_scripts": sorted(set(missing_scripts)),
    }


def build_update_plan() -> dict[str, Any]:
    coverage = validate_update_coverage()
    adapter_by_id = {adapter.adapter_id: adapter for adapter in AUTOMATIC_ADAPTERS}
    rows = []
    for policy in UPDATE_POLICIES:
        operational_state = {
            "automatic_structured": "scheduled_safe_apply",
            # Revision coverage is artifact-specific.  Many official landing
            # pages can prove availability/identity only; the source-monitor
            # report exposes that gap instead of calling HTML drift legal drift.
            "monitor_only": "scheduled_source_monitor",
            "local_reconcile": "scheduled_review_due",
            "optional_mirror": "disabled_by_policy",
            "manual_review": "manual_review_required",
        }[policy.strategy]
        adapter = adapter_by_id.get(policy.adapter_id or "")
        if adapter is not None and adapter.execution_mode == "validation_only":
            operational_state = "scheduled_validation_only"
        rows.append(
            {
                "source_id": policy.source_id,
                "strategy": policy.strategy,
                "cadence": policy.cadence,
                "adapter_id": policy.adapter_id,
                "reason": policy.reason,
                "operational_state": operational_state,
                "adapter_execution_mode": adapter.execution_mode if adapter else None,
                "changes_enforcement_automatically": False,
            }
        )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "coverage": coverage,
        "safe_apply_strategies": ["automatic_structured"],
        "validation_only_adapter_ids": sorted(
            adapter.adapter_id
            for adapter in AUTOMATIC_ADAPTERS
            if adapter.execution_mode == "validation_only"
        ),
        "commercial_mirrors_enabled": False,
        "enforcement_auto_promotion": False,
        "adapter_write_guard": "explicit_table_allowlist",
        "monitor_contract": {
            "revision_coverage": "direct_validated_artifacts_only",
            "html_legal_pages": "availability_identity_only",
            "coverage_gaps_reported": True,
            "coverage_gaps_approvable": False,
        },
        "sources": rows,
    }


def _eligible_adapter_ids(cadence: UpdateCadence) -> list[str]:
    wanted = {"daily", "weekly", "monthly"} if cadence == "all" else {cadence}
    ids: list[str] = []
    for policy in UPDATE_POLICIES:
        if policy.strategy != "automatic_structured" or policy.cadence not in wanted:
            continue
        if policy.adapter_id and policy.adapter_id not in ids:
            ids.append(policy.adapter_id)
    return ids


_CREDENTIAL_URL_RE = re.compile(r"(https?://)([^/@\s:]+):([^/@\s]+)@", re.IGNORECASE)
_SECRET_QUERY_RE = re.compile(
    r"([?&](?:token|api[_-]?key|secret|password|signature|sig)=)[^&#\s]+",
    re.IGNORECASE,
)
_BEARER_RE = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)


def _redact_output(value: str) -> str:
    text = _CREDENTIAL_URL_RE.sub(r"\1***:***@", value or "")
    text = _SECRET_QUERY_RE.sub(r"\1***", text)
    return _BEARER_RE.sub("Bearer ***", text)


def _redact_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _redact_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_json(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_json(item) for item in value]
    if isinstance(value, str):
        return _redact_output(value)
    return value


def _parse_adapter_result(stdout: str) -> dict[str, Any] | None:
    for line in reversed((stdout or "").splitlines()):
        if not line.startswith(ADAPTER_RESULT_PREFIX):
            continue
        try:
            payload = json.loads(line[len(ADAPTER_RESULT_PREFIX) :])
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None
    return None


def _policy_outcomes(cadence: UpdateCadence) -> list[dict[str, Any]]:
    wanted = {"daily", "weekly", "monthly", "manual"} if cadence == "all" else {cadence}
    outcomes: list[dict[str, Any]] = []
    for policy in UPDATE_POLICIES:
        if policy.cadence not in wanted:
            continue
        status = {
            "automatic_structured": "scheduled",
            "monitor_only": "scheduled_in_external_monitor",
            "local_reconcile": "review_due",
            "optional_mirror": "disabled_by_policy",
            "manual_review": "manual_review_required",
        }[policy.strategy]
        outcomes.append(
            {
                "source_id": policy.source_id,
                "strategy": policy.strategy,
                "cadence": policy.cadence,
                "status": status,
                "adapter_id": policy.adapter_id,
                "reason": policy.reason,
            }
        )
    return outcomes


def _persist_last_report(report: dict[str, Any]) -> None:
    LAST_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = LAST_REPORT_PATH.with_name(
        f".{LAST_REPORT_PATH.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    )
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, LAST_REPORT_PATH)


def load_last_update_report() -> dict[str, Any] | None:
    try:
        payload = json.loads(LAST_REPORT_PATH.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _nested_contract_sources_ok(payload: dict[str, Any]) -> bool:
    sources = payload.get("sources")
    if sources is None:
        return True
    if isinstance(sources, dict):
        rows = list(sources.values())
    elif isinstance(sources, list):
        rows = sources
    else:
        return False
    return bool(rows) and all(
        isinstance(row, dict) and row.get("status") in {"ok", "skipped"}
        for row in rows
    )


def _adapter_contract_ok(adapter: UpdateAdapter, payload: dict[str, Any] | None) -> bool:
    if not (
        payload
        and payload.get("status") == "ok"
        and payload.get("official_source") is True
        and set(payload.get("source_ids") or ()) == set(adapter.source_ids)
        and _nested_contract_sources_ok(payload)
    ):
        return False
    if adapter.execution_mode != "validation_only":
        return True
    rows_validated = payload.get("rows_validated")
    rows_applied = payload.get("rows_applied")
    expected_variant = {
        "eu_sanctions": "consolidated_entities",
    }.get(adapter.adapter_id)
    return bool(
        payload.get("operation") == "validation_only"
        and payload.get("enforcement_changed") is False
        and payload.get("snapshot_kind") == "full"
        and (expected_variant is None or payload.get("source_variant") == expected_variant)
        and isinstance(rows_applied, int)
        and not isinstance(rows_applied, bool)
        and rows_applied == 0
        and isinstance(rows_validated, int)
        and not isinstance(rows_validated, bool)
        and rows_validated > 0
    )


@contextmanager
def _acquire_update_lock():
    """Serialize refreshes across processes and PostgreSQL application replicas."""
    from ..db import engine

    if engine.dialect.name == "postgresql":
        lock_key = 6071225431917494273  # stable signed bigint: "TARIFF" namespace
        connection = engine.connect()
        acquired = bool(
            connection.execute(
                sql_text("SELECT pg_try_advisory_lock(:lock_key)"),
                {"lock_key": lock_key},
            ).scalar()
        )
        try:
            yield acquired
        finally:
            if acquired:
                connection.execute(
                    sql_text("SELECT pg_advisory_unlock(:lock_key)"),
                    {"lock_key": lock_key},
                )
            connection.close()
        return

    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    lock_file = LOCK_PATH.open("a+")
    acquired = False
    try:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except BlockingIOError:
            acquired = False
        yield acquired
    finally:
        if acquired:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()


def _adapter_child_environment(
    adapter: UpdateAdapter,
    *,
    database_url: str,
) -> dict[str, str]:
    """Build the complete, secret-minimized environment for one adapter."""
    if adapter.adapter_id not in _ADAPTER_ENV_ALLOWLIST_BY_ID:
        raise RuntimeError(
            f"regulatory adapter has no child-environment policy: {adapter.adapter_id}"
        )
    scoped_database_url = str(database_url or "").strip()
    if not scoped_database_url:
        raise RuntimeError("regulatory adapter database URL is empty")

    child_env = {
        # The interpreter path itself is absolute.  A fixed system search path
        # prevents a parent deployment secret/path injection from crossing the
        # subprocess boundary while retaining conventional helper discovery.
        "PATH": os.defpath,
        "HOME": str(BACKEND_ROOT / "data" / "runtime" / "adapter-home"),
        "XDG_CONFIG_HOME": str(
            BACKEND_ROOT / "data" / "runtime" / "adapter-home" / "config"
        ),
        "NETRC": os.devnull,
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUNBUFFERED": "1",
        "DATABASE_URL": scoped_database_url,
        "CUSTOMSCLEAR_READ_ONLY": "0",
        "CUSTOMSCLEAR_REGULATORY_ADAPTER_MODE": "1",
        "REGULATORY_SYNC_ALLOWED_WRITE_TABLES": ",".join(
            adapter.allowed_write_tables
        ),
        "REGULATORY_SYNC_SCHEDULER_ENABLED": "0",
        "SCHEDULER_ENABLED": "0",
    }
    allowed_from_parent = (
        _ADAPTER_BASE_ENV_ALLOWLIST
        | _ADAPTER_ENV_ALLOWLIST_BY_ID[adapter.adapter_id]
    )
    for name in allowed_from_parent:
        value = os.getenv(name)
        if value is not None and value != "":
            child_env[name] = value
    return child_env


async def _run_adapter(adapter: UpdateAdapter, timeout_seconds: float) -> dict[str, Any]:
    command = (sys.executable, *adapter.command)
    started = datetime.now(timezone.utc)
    from ..db import engine

    if engine.dialect.name == "postgresql":
        adapter_database_url = (os.getenv("REGULATORY_SYNC_DATABASE_URL") or "").strip()
        if not adapter_database_url:
            return {
                "adapter_id": adapter.adapter_id,
                "source_ids": list(adapter.source_ids),
                "execution_mode": adapter.execution_mode,
                "status": "error",
                "duration_seconds": 0.0,
                "stderr": (
                    "REGULATORY_SYNC_DATABASE_URL is required for PostgreSQL "
                    "and must use a least-privilege update role"
                ),
            }
    elif engine.dialect.name == "sqlite":
        # engine.url is already normalized to an absolute path by app.db.
        adapter_database_url = str(engine.url)
    else:
        return {
            "adapter_id": adapter.adapter_id,
            "source_ids": list(adapter.source_ids),
            "execution_mode": adapter.execution_mode,
            "status": "error",
            "duration_seconds": 0.0,
            "stderr": (
                f"unsupported regulatory adapter database dialect: "
                f"{engine.dialect.name}"
            ),
        }
    child_env = _adapter_child_environment(
        adapter,
        database_url=adapter_database_url,
    )
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(BACKEND_ROOT),
            env=child_env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
        stdout_text = stdout.decode("utf-8", errors="replace")
        stderr_text = stderr.decode("utf-8", errors="replace")
        adapter_result = _parse_adapter_result(stdout_text)
        contract_ok = _adapter_contract_ok(adapter, adapter_result)
        process_ok = process.returncode == 0
        return {
            "adapter_id": adapter.adapter_id,
            "source_ids": list(adapter.source_ids),
            "execution_mode": adapter.execution_mode,
            "status": "ok" if process_ok and contract_ok else "error",
            "return_code": process.returncode,
            "result_contract_valid": contract_ok,
            "enforcement_changed": (
                bool(adapter_result.get("enforcement_changed"))
                if contract_ok and adapter_result
                else None
            ),
            "adapter_result": _redact_json(adapter_result),
            "duration_seconds": round((datetime.now(timezone.utc) - started).total_seconds(), 3),
            "stdout": _redact_output(stdout_text[-4000:]),
            "stderr": _redact_output(stderr_text[-4000:]),
        }
    except asyncio.TimeoutError:
        process.kill()
        await process.communicate()
        return {
            "adapter_id": adapter.adapter_id,
            "source_ids": list(adapter.source_ids),
            "execution_mode": adapter.execution_mode,
            "status": "timeout",
            "duration_seconds": round((datetime.now(timezone.utc) - started).total_seconds(), 3),
            "stderr": f"timeout after {timeout_seconds:g}s",
        }
    except Exception as exc:
        return {
            "adapter_id": adapter.adapter_id,
            "source_ids": list(adapter.source_ids),
            "execution_mode": adapter.execution_mode,
            "status": "error",
            "duration_seconds": round((datetime.now(timezone.utc) - started).total_seconds(), 3),
            "stderr": _redact_output(str(exc)),
        }


async def run_regulatory_update_cycle(
    cadence: UpdateCadence = "daily",
    *,
    apply_safe: bool = False,
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    """Проверить план или последовательно применить безопасные структурированные sync."""
    coverage = validate_update_coverage()
    if not coverage["valid"]:
        raise RuntimeError(f"Regulatory update policy coverage is invalid: {coverage}")
    if cadence not in ("daily", "weekly", "monthly", "all"):
        raise ValueError(f"Unsupported cadence: {cadence}")
    if apply_safe:
        from ..db import is_read_only_mode

        if is_read_only_mode():
            raise RuntimeError("Regulatory source updates are disabled in CUSTOMSCLEAR_READ_ONLY mode")

    adapter_ids = _eligible_adapter_ids(cadence)
    policy_outcomes = _policy_outcomes(cadence)
    scheduled_review_due_source_ids = [
        row["source_id"]
        for row in policy_outcomes
        if row["status"] in {"review_due", "manual_review_required"}
    ]
    report: dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "cadence": cadence,
        "mode": "apply_safe" if apply_safe else "check_only",
        "coverage": coverage,
        "eligible_adapter_ids": adapter_ids,
        "policy_outcomes": policy_outcomes,
        "results": [],
        "enforcement_changed": False,
        "enforcement_change_guard": "adapter_table_allowlist",
        "scheduled_review_due_source_ids": scheduled_review_due_source_ids,
        "review_required_source_ids": scheduled_review_due_source_ids,
        "review_queue": None,
    }
    if not apply_safe:
        report["status"] = "ok"
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        _persist_last_report(report)
        return report

    with _acquire_update_lock() as acquired:
        if not acquired:
            report["status"] = "skipped_locked"
            report["finished_at"] = datetime.now(timezone.utc).isoformat()
            _persist_last_report(report)
            return report
        if cadence in {"monthly", "all"}:
            review_queue = _raise_scheduled_regulatory_reviews()
            report["review_queue"] = review_queue
            manual_source_ids = {
                row["source_id"]
                for row in policy_outcomes
                if row["status"] == "manual_review_required"
            }
            report["review_required_source_ids"] = sorted(
                set(review_queue["pending_source_ids"]) | manual_source_ids
            )
        adapters = {adapter.adapter_id: adapter for adapter in AUTOMATIC_ADAPTERS}
        timeout = timeout_seconds or float(os.getenv("REGULATORY_SOURCE_UPDATE_TIMEOUT_SECONDS", "1800"))
        for adapter_id in adapter_ids:
            result = await _run_adapter(adapters[adapter_id], timeout)
            report["results"].append(result)
            logger.info("Regulatory source update {}: {}", adapter_id, result["status"])
        report["enforcement_changed"] = any(
            row.get("enforcement_changed") is True for row in report["results"]
        )
        adapters_ok = bool(report["results"]) and all(
            row["status"] == "ok" for row in report["results"]
        )
        if not adapters_ok and report["results"]:
            report["status"] = "partial"
        elif report["review_required_source_ids"]:
            report["status"] = "review_required"
        elif adapters_ok or report["review_queue"] is not None:
            report["status"] = "ok"
        else:
            report["status"] = "no_automatic_adapters"
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    _persist_last_report(report)
    return report
