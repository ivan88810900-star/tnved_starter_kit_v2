"""Tests for data refresh workflow — Issue #89."""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, AsyncMock

import pytest

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
            ["python3", "-m", "scripts.data_refresh", "--check-only", "--json"],
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
    def test_scheduler_has_currency_refresh(self) -> None:
        scheduler_file = BACKEND_ROOT / "app" / "services" / "scheduler.py"
        content = scheduler_file.read_text()
        assert "refresh_currency_rates_daily" in content
        assert "update_exchange_rates_from_cbrf" in content
