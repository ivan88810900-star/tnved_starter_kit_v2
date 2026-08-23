"""Единая политика обновления всех зарегистрированных нормативных источников.

Структурированные официальные реестры можно безопасно обновлять автоматически.
Нормативные документы и курируемые правила только контролируются: изменение
источника не может само включить advisory/enforcement-правило.
"""

from __future__ import annotations

import asyncio
import fcntl
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from loguru import logger

from .regulatory_source_registry import REGULATORY_SOURCE_REGISTRY

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


AUTOMATIC_ADAPTERS: tuple[UpdateAdapter, ...] = (
    UpdateAdapter("cbr_rates", ("scripts/update_rates.py",), ("cbr_exchange_rates",)),
    UpdateAdapter("sgr_registry", ("scripts/sync_sgr_registry.py",), ("eec_sgr_decision_299",)),
    UpdateAdapter(
        "state_registries",
        ("scripts/sync_state_registries.py",),
        ("eec_fss_notifications_registry", "eec_reo_vchu_registry"),
    ),
    UpdateAdapter("ofac_sdn", ("scripts/sync_ofac_sanctions.py",), ("ofac_sdn_list",)),
    UpdateAdapter("eu_sanctions", ("scripts/sync_eu_sanctions.py",), ("eu_sanctions_list",)),
    UpdateAdapter(
        "fsa_opendata",
        ("scripts/opendata_sync.py", "--source", "fsa"),
        ("fsa_registry_evidence",),
    ),
    UpdateAdapter(
        "trois_opendata",
        ("scripts/opendata_sync.py", "--source", "trois"),
        ("fts_trois_registry",),
    ),
    UpdateAdapter(
        "customs_opendata",
        ("scripts/opendata_sync.py", "--source", "customs"),
        ("fts_customs_document_masks",),
    ),
)

_DAILY_AUTOMATIC = {
    "cbr_exchange_rates": "cbr_rates",
    "eec_sgr_decision_299": "sgr_registry",
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
    "eec_ett_tnved",
    "eec_tr_ts_catalog",
    "eec_classification_decisions",
    "fts_preliminary_classification",
    "pravo_gov_publication",
    "eec_decision30_ntm_contours",
    "rf_pp_2425_conformity",
    "eec_veterinary_decision_317",
    "eec_phytosanitary_decisions_318_157",
    "rf_export_control_lists",
    "regulatory_documents_corpus",
    "trade_remedies_official",
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


def validate_update_coverage() -> dict[str, Any]:
    registry_ids = {entry.source_id for entry in REGULATORY_SOURCE_REGISTRY}
    policy_ids = [policy.source_id for policy in UPDATE_POLICIES]
    duplicates = sorted({source_id for source_id in policy_ids if policy_ids.count(source_id) > 1})
    missing = sorted(registry_ids - set(policy_ids))
    unknown = sorted(set(policy_ids) - registry_ids)

    adapter_by_id = {adapter.adapter_id: adapter for adapter in AUTOMATIC_ADAPTERS}
    invalid_adapters: list[str] = []
    missing_scripts: list[str] = []
    for policy in UPDATE_POLICIES:
        if policy.strategy != "automatic_structured":
            continue
        adapter = adapter_by_id.get(policy.adapter_id or "")
        if adapter is None or policy.source_id not in adapter.source_ids:
            invalid_adapters.append(policy.source_id)
            continue
        script = BACKEND_ROOT / adapter.command[0]
        if not script.is_file():
            missing_scripts.append(str(script.relative_to(BACKEND_ROOT)))

    valid = not (duplicates or missing or unknown or invalid_adapters or missing_scripts)
    return {
        "valid": valid,
        "registry_source_count": len(registry_ids),
        "policy_source_count": len(policy_ids),
        "missing_source_ids": missing,
        "unknown_source_ids": unknown,
        "duplicate_source_ids": duplicates,
        "invalid_adapter_source_ids": sorted(invalid_adapters),
        "missing_scripts": sorted(set(missing_scripts)),
    }


def build_update_plan() -> dict[str, Any]:
    coverage = validate_update_coverage()
    rows = []
    for policy in UPDATE_POLICIES:
        rows.append(
            {
                "source_id": policy.source_id,
                "strategy": policy.strategy,
                "cadence": policy.cadence,
                "adapter_id": policy.adapter_id,
                "reason": policy.reason,
                "changes_enforcement_automatically": False,
            }
        )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "coverage": coverage,
        "safe_apply_strategies": ["automatic_structured"],
        "commercial_mirrors_enabled": False,
        "enforcement_auto_promotion": False,
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


async def _run_adapter(adapter: UpdateAdapter, timeout_seconds: float) -> dict[str, Any]:
    command = (sys.executable, *adapter.command)
    started = datetime.now(timezone.utc)
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(BACKEND_ROOT),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
        return {
            "adapter_id": adapter.adapter_id,
            "source_ids": list(adapter.source_ids),
            "status": "ok" if process.returncode == 0 else "error",
            "return_code": process.returncode,
            "duration_seconds": round((datetime.now(timezone.utc) - started).total_seconds(), 3),
            "stdout": stdout.decode("utf-8", errors="replace")[-4000:],
            "stderr": stderr.decode("utf-8", errors="replace")[-4000:],
        }
    except asyncio.TimeoutError:
        process.kill()
        await process.communicate()
        return {
            "adapter_id": adapter.adapter_id,
            "source_ids": list(adapter.source_ids),
            "status": "timeout",
            "duration_seconds": round((datetime.now(timezone.utc) - started).total_seconds(), 3),
            "stderr": f"timeout after {timeout_seconds:g}s",
        }
    except Exception as exc:
        return {
            "adapter_id": adapter.adapter_id,
            "source_ids": list(adapter.source_ids),
            "status": "error",
            "duration_seconds": round((datetime.now(timezone.utc) - started).total_seconds(), 3),
            "stderr": str(exc),
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

    adapter_ids = _eligible_adapter_ids(cadence)
    report: dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "cadence": cadence,
        "mode": "apply_safe" if apply_safe else "check_only",
        "coverage": coverage,
        "eligible_adapter_ids": adapter_ids,
        "results": [],
        "enforcement_changed": False,
    }
    if not apply_safe:
        report["status"] = "ok"
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        return report

    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    lock_file = LOCK_PATH.open("a+")
    try:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            report["status"] = "skipped_locked"
            report["finished_at"] = datetime.now(timezone.utc).isoformat()
            return report

        adapters = {adapter.adapter_id: adapter for adapter in AUTOMATIC_ADAPTERS}
        timeout = timeout_seconds or float(os.getenv("REGULATORY_SOURCE_UPDATE_TIMEOUT_SECONDS", "1800"))
        for adapter_id in adapter_ids:
            result = await _run_adapter(adapters[adapter_id], timeout)
            report["results"].append(result)
            logger.info("Regulatory source update {}: {}", adapter_id, result["status"])
        report["status"] = "ok" if all(row["status"] == "ok" for row in report["results"]) else "partial"
    finally:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        finally:
            lock_file.close()
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    return report
