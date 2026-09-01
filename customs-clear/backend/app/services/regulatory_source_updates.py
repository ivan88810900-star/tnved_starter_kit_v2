"""Единая политика обновления всех зарегистрированных нормативных источников.

Структурированные официальные реестры можно безопасно обновлять автоматически.
Нормативные документы и курируемые правила только контролируются: изменение
источника не может само включить advisory/enforcement-правило.
"""

from __future__ import annotations

import asyncio
import fcntl
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
LAST_REPORT_PATH = BACKEND_ROOT / "data" / "runtime" / "regulatory-source-update-last.json"
ADAPTER_RESULT_PREFIX = "REGULATORY_SYNC_RESULT="


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
    valid = not (
        duplicates
        or missing
        or unknown
        or invalid_adapters
        or missing_scripts
        or unsafe_adapters
        or duplicate_adapter_ids
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
        "missing_scripts": sorted(set(missing_scripts)),
    }


def build_update_plan() -> dict[str, Any]:
    coverage = validate_update_coverage()
    adapter_by_id = {adapter.adapter_id: adapter for adapter in AUTOMATIC_ADAPTERS}
    rows = []
    for policy in UPDATE_POLICIES:
        operational_state = {
            "automatic_structured": "scheduled_safe_apply",
            "monitor_only": "scheduled_drift_monitor",
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


async def _run_adapter(adapter: UpdateAdapter, timeout_seconds: float) -> dict[str, Any]:
    command = (sys.executable, *adapter.command)
    started = datetime.now(timezone.utc)
    child_env = dict(os.environ)
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
        child_env["DATABASE_URL"] = adapter_database_url
    child_env.update(
        {
            "CUSTOMSCLEAR_REGULATORY_ADAPTER_MODE": "1",
            "REGULATORY_SYNC_ALLOWED_WRITE_TABLES": ",".join(adapter.allowed_write_tables),
            "REGULATORY_SYNC_SCHEDULER_ENABLED": "0",
            "SCHEDULER_ENABLED": "0",
        }
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
    report: dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "cadence": cadence,
        "mode": "apply_safe" if apply_safe else "check_only",
        "coverage": coverage,
        "eligible_adapter_ids": adapter_ids,
        "policy_outcomes": _policy_outcomes(cadence),
        "results": [],
        "enforcement_changed": False,
        "enforcement_change_guard": "adapter_table_allowlist",
        "review_required_source_ids": [
            row["source_id"]
            for row in _policy_outcomes(cadence)
            if row["status"] in {"review_due", "manual_review_required"}
        ],
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
        elif adapters_ok:
            report["status"] = "ok"
        else:
            report["status"] = "no_automatic_adapters"
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    _persist_last_report(report)
    return report
