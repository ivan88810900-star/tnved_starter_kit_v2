"""Политика и runner автоматических обновлений нормативных источников."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services.regulatory_source_registry import REGULATORY_SOURCE_REGISTRY
from app.services.regulatory_source_updates import (
    ADAPTER_RESULT_PREFIX,
    AUTOMATIC_ADAPTERS,
    UPDATE_POLICIES,
    _acquire_update_lock,
    _parse_adapter_result,
    _run_adapter,
    build_update_plan,
    run_regulatory_update_cycle,
    validate_update_coverage,
)


def test_every_registry_source_has_exactly_one_update_policy() -> None:
    coverage = validate_update_coverage()
    assert coverage["valid"] is True
    assert coverage["registry_source_count"] == len(REGULATORY_SOURCE_REGISTRY)
    assert coverage["policy_source_count"] == len(REGULATORY_SOURCE_REGISTRY)


def test_automatic_sources_are_only_structured_whitelist() -> None:
    actual = {p.source_id for p in UPDATE_POLICIES if p.strategy == "automatic_structured"}
    assert actual == {
        "cbr_exchange_rates",
        "eec_sgr_registry",
        "eec_fss_notifications_registry",
        "eec_reo_vchu_registry",
        "fsa_registry_evidence",
        "fts_trois_registry",
        "fts_customs_document_masks",
        "ofac_sdn_list",
        "eu_sanctions_list",
    }
    assert all(p.strategy != "automatic_structured" for p in UPDATE_POLICIES if p.source_id in {
        "eec_decision30_ntm_contours",
        "rf_export_control_lists",
        "rf_pp_2425_conformity",
        "regulatory_ai_extracts",
    })


def test_all_automatic_adapter_scripts_exist() -> None:
    backend_root = Path(__file__).resolve().parent.parent
    for adapter in AUTOMATIC_ADAPTERS:
        script = backend_root / adapter.command[0]
        assert script.is_file()
        assert ADAPTER_RESULT_PREFIX in script.read_text(encoding="utf-8")
        assert "--strict" in adapter.command
        assert adapter.allowed_write_tables


def test_sanctions_adapters_are_validation_only_and_cannot_write_enforcement_tables() -> None:
    enforcement_tables = {
        "sanction_entities",
        "sanction_risks",
        "ofac_sdn_list",
        "eu_sanctions_list",
    }
    adapters = {
        adapter.adapter_id: adapter
        for adapter in AUTOMATIC_ADAPTERS
        if adapter.adapter_id in {"ofac_sdn", "eu_sanctions"}
    }
    assert set(adapters) == {"ofac_sdn", "eu_sanctions"}
    for adapter in adapters.values():
        assert adapter.execution_mode == "validation_only"
        assert "--validate-only" in adapter.command
        assert "--official-only" in adapter.command
        assert enforcement_tables.isdisjoint(adapter.allowed_write_tables)

    plan_rows = {
        row["source_id"]: row for row in build_update_plan()["sources"]
    }
    for source_id in {"ofac_sdn_list", "eu_sanctions_list"}:
        assert plan_rows[source_id]["operational_state"] == "scheduled_validation_only"
        assert plan_rows[source_id]["adapter_execution_mode"] == "validation_only"
        assert plan_rows[source_id]["changes_enforcement_automatically"] is False


def test_adapter_result_parser_requires_machine_readable_contract() -> None:
    payload = {"status": "ok", "source_ids": ["source-a"], "rows": 12}
    stdout = f"human readable log\n{ADAPTER_RESULT_PREFIX}{json.dumps(payload)}\n"
    assert _parse_adapter_result(stdout) == payload
    assert _parse_adapter_result("completed successfully\n") is None
    assert _parse_adapter_result(f"{ADAPTER_RESULT_PREFIX}not-json\n") is None


class _FakeProcess:
    def __init__(self, stdout: str, *, return_code: int = 0, stderr: str = "") -> None:
        self.returncode = return_code
        self._stdout = stdout.encode()
        self._stderr = stderr.encode()

    async def communicate(self):
        return self._stdout, self._stderr

    def kill(self) -> None:
        return None


def test_adapter_runner_requires_matching_contract_and_injects_write_guard() -> None:
    adapter = AUTOMATIC_ADAPTERS[0]
    captured: dict[str, object] = {}
    payload = {
        "status": "ok",
        "official_source": True,
        "source_ids": list(adapter.source_ids),
        "rows": 1,
    }

    async def fake_create(*command, **kwargs):
        captured["command"] = command
        captured["env"] = kwargs["env"]
        return _FakeProcess(f"{ADAPTER_RESULT_PREFIX}{json.dumps(payload)}\n")

    with patch("app.services.regulatory_source_updates.asyncio.create_subprocess_exec", side_effect=fake_create):
        result = asyncio.run(_run_adapter(adapter, 1.0))

    assert result["status"] == "ok"
    assert result["result_contract_valid"] is True
    assert tuple(captured["command"])[1:] == adapter.command
    child_env = captured["env"]
    assert isinstance(child_env, dict)
    assert child_env["CUSTOMSCLEAR_REGULATORY_ADAPTER_MODE"] == "1"
    assert child_env["REGULATORY_SYNC_ALLOWED_WRITE_TABLES"] == ",".join(adapter.allowed_write_tables)
    assert child_env["REGULATORY_SYNC_SCHEDULER_ENABLED"] == "0"


def test_adapter_runner_rejects_false_green_without_contract() -> None:
    adapter = AUTOMATIC_ADAPTERS[0]
    with patch(
        "app.services.regulatory_source_updates.asyncio.create_subprocess_exec",
        new_callable=AsyncMock,
        return_value=_FakeProcess("updated 12 rows\n"),
    ):
        result = asyncio.run(_run_adapter(adapter, 1.0))
    assert result["status"] == "error"
    assert result["return_code"] == 0
    assert result["result_contract_valid"] is False


def test_postgresql_adapter_requires_separate_least_privilege_dsn() -> None:
    adapter = AUTOMATIC_ADAPTERS[0]
    with (
        patch.dict(os.environ, {"REGULATORY_SYNC_DATABASE_URL": ""}),
        patch("app.db.engine", SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))),
        patch(
            "app.services.regulatory_source_updates.asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
        ) as spawn,
    ):
        result = asyncio.run(_run_adapter(adapter, 1.0))
    assert result["status"] == "error"
    assert "REGULATORY_SYNC_DATABASE_URL" in result["stderr"]
    spawn.assert_not_awaited()


def test_adapter_runner_rejects_contract_for_wrong_source() -> None:
    adapter = AUTOMATIC_ADAPTERS[0]
    payload = {"status": "ok", "official_source": True, "source_ids": ["different-source"]}
    with patch(
        "app.services.regulatory_source_updates.asyncio.create_subprocess_exec",
        new_callable=AsyncMock,
        return_value=_FakeProcess(f"{ADAPTER_RESULT_PREFIX}{json.dumps(payload)}\n"),
    ):
        result = asyncio.run(_run_adapter(adapter, 1.0))
    assert result["status"] == "error"
    assert result["result_contract_valid"] is False


def test_adapter_runner_rejects_nonofficial_fallback_contract() -> None:
    adapter = AUTOMATIC_ADAPTERS[0]
    payload = {
        "status": "ok",
        "official_source": False,
        "source_ids": list(adapter.source_ids),
        "fallback_used": True,
    }
    with patch(
        "app.services.regulatory_source_updates.asyncio.create_subprocess_exec",
        new_callable=AsyncMock,
        return_value=_FakeProcess(f"{ADAPTER_RESULT_PREFIX}{json.dumps(payload)}\n"),
    ):
        result = asyncio.run(_run_adapter(adapter, 1.0))
    assert result["status"] == "error"
    assert result["result_contract_valid"] is False


def test_validation_only_adapter_requires_proof_that_no_rows_were_applied() -> None:
    adapter = next(row for row in AUTOMATIC_ADAPTERS if row.adapter_id == "ofac_sdn")
    valid_payload = {
        "status": "ok",
        "official_source": True,
        "source_ids": list(adapter.source_ids),
        "operation": "validation_only",
        "enforcement_changed": False,
        "snapshot_kind": "full",
        "rows_validated": 1200,
        "rows_applied": 0,
    }

    async def run(payload):
        with patch(
            "app.services.regulatory_source_updates.asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            return_value=_FakeProcess(f"{ADAPTER_RESULT_PREFIX}{json.dumps(payload)}\n"),
        ):
            return await _run_adapter(adapter, 1.0)

    accepted = asyncio.run(run(valid_payload))
    assert accepted["status"] == "ok"
    assert accepted["result_contract_valid"] is True
    assert accepted["enforcement_changed"] is False

    for override in (
        {"rows_applied": 1},
        {"rows_applied": False},
        {"enforcement_changed": True},
        {"operation": "apply"},
        {"snapshot_kind": "partial"},
        {"rows_validated": 0},
    ):
        rejected = asyncio.run(run({**valid_payload, **override}))
        assert rejected["status"] == "error"
        assert rejected["result_contract_valid"] is False
        assert rejected["enforcement_changed"] is None


def test_eu_validation_contract_rejects_partial_or_wrong_source_variant() -> None:
    adapter = next(row for row in AUTOMATIC_ADAPTERS if row.adapter_id == "eu_sanctions")
    valid_payload = {
        "status": "ok",
        "official_source": True,
        "source_ids": list(adapter.source_ids),
        "operation": "validation_only",
        "enforcement_changed": False,
        "snapshot_kind": "full",
        "source_variant": "consolidated_entities",
        "rows_validated": 600,
        "rows_applied": 0,
    }

    async def run(payload):
        with patch(
            "app.services.regulatory_source_updates.asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            return_value=_FakeProcess(f"{ADAPTER_RESULT_PREFIX}{json.dumps(payload)}\n"),
        ):
            return await _run_adapter(adapter, 1.0)

    accepted = asyncio.run(run(valid_payload))
    assert accepted["status"] == "ok"
    assert accepted["result_contract_valid"] is True

    for override in (
        {"snapshot_kind": "partial", "source_variant": "goods_correlation_xlsx"},
        {"snapshot_kind": "full", "source_variant": "goods_correlation_xlsx"},
        {"snapshot_kind": "full", "source_variant": None},
    ):
        rejected = asyncio.run(run({**valid_payload, **override}))
        assert rejected["status"] == "error"
        assert rejected["result_contract_valid"] is False


def test_adapter_runner_rejects_nested_partial_source_result() -> None:
    adapter = AUTOMATIC_ADAPTERS[0]
    payload = {
        "status": "ok",
        "official_source": True,
        "source_ids": list(adapter.source_ids),
        "sources": [{"source_id": adapter.source_ids[0], "status": "error"}],
    }
    with patch(
        "app.services.regulatory_source_updates.asyncio.create_subprocess_exec",
        new_callable=AsyncMock,
        return_value=_FakeProcess(f"{ADAPTER_RESULT_PREFIX}{json.dumps(payload)}\n"),
    ):
        result = asyncio.run(_run_adapter(adapter, 1.0))
    assert result["status"] == "error"
    assert result["result_contract_valid"] is False


def test_adapter_runner_rejects_nonzero_exit_even_with_valid_contract() -> None:
    adapter = AUTOMATIC_ADAPTERS[0]
    payload = {"status": "ok", "official_source": True, "source_ids": list(adapter.source_ids)}
    with patch(
        "app.services.regulatory_source_updates.asyncio.create_subprocess_exec",
        new_callable=AsyncMock,
        return_value=_FakeProcess(
            f"{ADAPTER_RESULT_PREFIX}{json.dumps(payload)}\n",
            return_code=2,
        ),
    ):
        result = asyncio.run(_run_adapter(adapter, 1.0))
    assert result["status"] == "error"
    assert result["result_contract_valid"] is True
    assert result["return_code"] == 2


def test_check_only_never_runs_adapter(tmp_path: Path) -> None:
    with (
        patch("app.services.regulatory_source_updates.LAST_REPORT_PATH", tmp_path / "last.json"),
        patch("app.services.regulatory_source_updates._run_adapter", new_callable=AsyncMock) as run,
    ):
        report = asyncio.run(run_regulatory_update_cycle("all", apply_safe=False))
    run.assert_not_awaited()
    assert report["status"] == "ok"
    assert report["enforcement_changed"] is False
    assert {row["source_id"] for row in report["policy_outcomes"]} == {
        entry.source_id for entry in REGULATORY_SOURCE_REGISTRY
    }


def test_weekly_apply_runs_each_adapter_once_and_isolates_status(tmp_path: Path) -> None:
    async def fake_run(adapter, timeout_seconds):
        return {
            "adapter_id": adapter.adapter_id,
            "source_ids": list(adapter.source_ids),
            "status": "error" if adapter.adapter_id == "trois_opendata" else "ok",
        }

    with (
        patch("app.services.regulatory_source_updates.LOCK_PATH", tmp_path / "updates.lock"),
        patch("app.services.regulatory_source_updates.LAST_REPORT_PATH", tmp_path / "last.json"),
        patch("app.services.regulatory_source_updates._run_adapter", side_effect=fake_run) as run,
    ):
        report = asyncio.run(run_regulatory_update_cycle("weekly", apply_safe=True))
    assert run.await_count == 3
    assert report["status"] == "partial"
    assert report["enforcement_changed"] is False
    assert {row["adapter_id"] for row in report["results"]} == {
        "fsa_opendata",
        "trois_opendata",
        "customs_opendata",
    }


def test_apply_is_rejected_before_adapter_in_read_only_mode(tmp_path: Path) -> None:
    with (
        patch("app.services.regulatory_source_updates.LAST_REPORT_PATH", tmp_path / "last.json"),
        patch("app.db.is_read_only_mode", return_value=True),
        patch("app.services.regulatory_source_updates._run_adapter", new_callable=AsyncMock) as run,
    ):
        try:
            asyncio.run(run_regulatory_update_cycle("daily", apply_safe=True))
        except RuntimeError as exc:
            assert "READ_ONLY" in str(exc)
        else:  # pragma: no cover - fail with a useful message
            raise AssertionError("read-only update unexpectedly started")
    run.assert_not_awaited()


def test_sqlite_update_lock_is_exclusive_and_released(tmp_path: Path) -> None:
    with patch("app.services.regulatory_source_updates.LOCK_PATH", tmp_path / "updates.lock"):
        with _acquire_update_lock() as first:
            assert first is True
            with _acquire_update_lock() as second:
                assert second is False
        with _acquire_update_lock() as after_release:
            assert after_release is True


class _ScalarResult:
    def __init__(self, value: bool) -> None:
        self.value = value

    def scalar(self) -> bool:
        return self.value


class _PostgresLockConnection:
    def __init__(self, acquired: bool) -> None:
        self.acquired = acquired
        self.statements: list[str] = []
        self.closed = False

    def execute(self, statement, parameters):
        sql = str(statement)
        self.statements.append(sql)
        if "pg_try_advisory_lock" in sql:
            return _ScalarResult(self.acquired)
        return _ScalarResult(True)

    def close(self) -> None:
        self.closed = True


def test_postgres_update_lock_is_released_only_when_acquired() -> None:
    acquired_connection = _PostgresLockConnection(True)
    acquired_engine = SimpleNamespace(
        dialect=SimpleNamespace(name="postgresql"),
        connect=lambda: acquired_connection,
    )
    with patch("app.db.engine", acquired_engine):
        with _acquire_update_lock() as acquired:
            assert acquired is True
    assert any("pg_advisory_unlock" in sql for sql in acquired_connection.statements)
    assert acquired_connection.closed is True

    rejected_connection = _PostgresLockConnection(False)
    rejected_engine = SimpleNamespace(
        dialect=SimpleNamespace(name="postgresql"),
        connect=lambda: rejected_connection,
    )
    with patch("app.db.engine", rejected_engine):
        with _acquire_update_lock() as acquired:
            assert acquired is False
    assert not any("pg_advisory_unlock" in sql for sql in rejected_connection.statements)
    assert rejected_connection.closed is True
