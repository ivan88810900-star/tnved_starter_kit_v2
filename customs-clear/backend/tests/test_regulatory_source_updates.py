"""Политика и runner автоматических обновлений нормативных источников."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.services.regulatory_source_registry import REGULATORY_SOURCE_REGISTRY
from app.services.regulatory_source_updates import (
    AUTOMATIC_ADAPTERS,
    UPDATE_POLICIES,
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
        "eec_sgr_decision_299",
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
        assert (backend_root / adapter.command[0]).is_file()


def test_check_only_never_runs_adapter() -> None:
    with patch("app.services.regulatory_source_updates._run_adapter", new_callable=AsyncMock) as run:
        report = asyncio.run(run_regulatory_update_cycle("all", apply_safe=False))
    run.assert_not_awaited()
    assert report["status"] == "ok"
    assert report["enforcement_changed"] is False


def test_weekly_apply_runs_each_adapter_once_and_isolates_status(tmp_path: Path) -> None:
    async def fake_run(adapter, timeout_seconds):
        return {
            "adapter_id": adapter.adapter_id,
            "source_ids": list(adapter.source_ids),
            "status": "error" if adapter.adapter_id == "trois_opendata" else "ok",
        }

    with (
        patch("app.services.regulatory_source_updates.LOCK_PATH", tmp_path / "updates.lock"),
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
