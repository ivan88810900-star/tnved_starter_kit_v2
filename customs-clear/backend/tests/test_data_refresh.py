"""Tests for data refresh workflow — Issue #89."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys
from unittest.mock import patch

from app.services.data_refresh_service import (
    STALE_THRESHOLD_DAYS,
    CURRENCY_STALE_HOURS,
    _BUNDLE_DOMAINS,
    _bundle_revision_date,
    check_data_freshness,
)


BACKEND_ROOT = Path(__file__).resolve().parent.parent


class TestBundleFreshness:
    def test_bundle_domains_are_defined(self) -> None:
        assert len(_BUNDLE_DOMAINS) == 6
        assert "EEC_ETT" in _BUNDLE_DOMAINS
        assert "EEC_EXCISE" in _BUNDLE_DOMAINS
        assert "EEC_ANTI_DUMPING" in _BUNDLE_DOMAINS

    def test_all_bundles_exist(self) -> None:
        for domain, rel_path in _BUNDLE_DOMAINS.items():
            p = BACKEND_ROOT / rel_path
            assert p.is_file(), f"Bundle missing for {domain}: {rel_path}"

    def test_bundle_revision_dates_parseable(self) -> None:
        for domain, rel_path in _BUNDLE_DOMAINS.items():
            rev_date = _bundle_revision_date(rel_path)
            assert rev_date is not None, f"Cannot parse revision date for {domain}"

    def test_bundles_have_revision_field(self) -> None:
        for domain, rel_path in _BUNDLE_DOMAINS.items():
            p = BACKEND_ROOT / rel_path
            with open(p) as f:
                data = json.load(f)
            assert "revision" in data, f"No revision field in {domain}"
            rev = data["revision"]
            assert ":" in rev, f"Revision format invalid in {domain}: {rev}"


class TestFreshnessCheck:
    def test_check_returns_structure(self) -> None:
        report = check_data_freshness()
        assert "checked_at" in report
        assert "stale_count" in report
        assert "all_fresh" in report
        assert "currency" in report
        assert "domains" in report
        assert isinstance(report["domains"], list)
        assert len(report["domains"]) == 6

    def test_domain_entries_have_fields(self) -> None:
        report = check_data_freshness()
        for d in report["domains"]:
            assert "domain" in d
            assert "exists" in d
            assert "is_stale" in d
            assert "revision_date" in d

    def test_currency_entry_has_fields(self) -> None:
        report = check_data_freshness()
        cur = report["currency"]
        assert "is_stale" in cur
        assert "currencies" in cur

    def test_stale_threshold_configured(self) -> None:
        assert STALE_THRESHOLD_DAYS == 90
        assert CURRENCY_STALE_HOURS == 48


class TestDataRefreshScript:
    def test_script_exists(self) -> None:
        script = BACKEND_ROOT / "scripts" / "data_refresh.py"
        assert script.is_file()

    def test_script_check_only_mode(self) -> None:
        import subprocess
        result = subprocess.run(
            [sys.executable, "-m", "scripts.data_refresh", "--check-only", "--json"],
            cwd=str(BACKEND_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
        data = json.loads(result.stdout)
        assert "domains" in data
        assert "currency" in data
        assert "all_fresh" in data


class TestAutoUpdaterIntegration:
    def test_auto_updater_has_freshness_job(self) -> None:
        auto_updater = BACKEND_ROOT / "scripts" / "auto_updater.py"
        content = auto_updater.read_text()
        assert "data_freshness_weekly" in content
        assert "data_refresh.py" in content
        assert "freshness" in content

    def test_auto_updater_run_once_freshness(self) -> None:
        auto_updater = BACKEND_ROOT / "scripts" / "auto_updater.py"
        content = auto_updater.read_text()
        assert '"freshness"' in content


class TestApplicationStartup:
    def test_exchange_refresh_does_not_block_lifespan(self) -> None:
        from app import main as main_module

        async def scenario() -> None:
            refresh_started = asyncio.Event()

            async def slow_refresh() -> dict[str, object]:
                refresh_started.set()
                await asyncio.Event().wait()
                return {"status": "OK"}

            with (
                patch.object(main_module, "is_read_only_mode", return_value=False),
                patch.object(main_module, "init_db"),
                patch.object(main_module, "update_exchange_rates_from_cbrf", slow_refresh),
                patch("app.services.permits_jobs.mark_interrupted_jobs_on_startup"),
                patch("app.services.ved_intel_jobs.mark_interrupted_ved_intel_jobs_on_startup"),
                patch("app.services.scheduler.start_apscheduler"),
                patch("app.services.scheduler.shutdown_apscheduler"),
            ):
                async with main_module.lifespan(main_module.app):
                    await asyncio.wait_for(refresh_started.wait(), timeout=0.5)

        asyncio.run(asyncio.wait_for(scenario(), timeout=1.0))

    def test_read_only_lifespan_skips_all_startup_mutations(self) -> None:
        from app import main as main_module

        async def scenario() -> None:
            with (
                patch.object(main_module, "is_read_only_mode", return_value=True),
                patch.object(main_module, "init_db") as init_db_mock,
                patch.object(main_module, "update_exchange_rates_from_cbrf") as refresh_mock,
                patch("app.services.permits_jobs.mark_interrupted_jobs_on_startup") as permits_mock,
                patch("app.services.ved_intel_jobs.mark_interrupted_ved_intel_jobs_on_startup") as ved_mock,
                patch("app.services.scheduler.start_apscheduler") as scheduler_start_mock,
                patch("app.services.scheduler.shutdown_apscheduler") as scheduler_stop_mock,
            ):
                async with main_module.lifespan(main_module.app):
                    pass

                init_db_mock.assert_not_called()
                refresh_mock.assert_not_called()
                permits_mock.assert_not_called()
                ved_mock.assert_not_called()
                scheduler_start_mock.assert_not_called()
                scheduler_stop_mock.assert_not_called()

        asyncio.run(asyncio.wait_for(scenario(), timeout=1.0))


class TestGitHubWorkflow:
    def test_workflow_exists(self) -> None:
        wf = Path(__file__).resolve().parent.parent.parent.parent / ".github" / "workflows" / "scheduled-data-refresh.yml"
        assert wf.is_file()

    def test_workflow_has_cbr_check(self) -> None:
        wf = Path(__file__).resolve().parent.parent.parent.parent / ".github" / "workflows" / "scheduled-data-refresh.yml"
        content = wf.read_text()
        assert "cbr_check" in content
        assert "cbr.ru" in content

    def test_workflow_has_manual_dispatch(self) -> None:
        wf = Path(__file__).resolve().parent.parent.parent.parent / ".github" / "workflows" / "scheduled-data-refresh.yml"
        content = wf.read_text()
        assert "workflow_dispatch" in content


class TestSchedulerIntegration:
    def test_scheduler_has_real_regulatory_source_updates(self) -> None:
        scheduler_file = BACKEND_ROOT / "app" / "services" / "scheduler.py"
        content = scheduler_file.read_text()
        assert "regulatory_sources_daily" in content
        assert "regulatory_sources_weekly" in content
        assert "run_regulatory_update_cycle" in content
        assert "sync_daily_regulatory_data" not in content

    def test_workflow_validates_plan_and_persists_monitor_state(self) -> None:
        wf = BACKEND_ROOT.parent.parent / ".github" / "workflows" / "scheduled-data-refresh.yml"
        content = wf.read_text()
        assert "run_regulatory_source_updates.py" in content
        assert "source-monitor-state.json" in content
        assert "issues: write" in content
        assert "gh issue" in content
