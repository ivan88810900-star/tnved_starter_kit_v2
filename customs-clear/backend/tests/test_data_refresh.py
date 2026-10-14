"""Tests for data refresh workflow — Issue #89."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, AsyncMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.services.data_refresh_service import (
    STALE_THRESHOLD_DAYS,
    CURRENCY_STALE_HOURS,
    _BUNDLE_DOMAINS,
    _bundle_revision_date,
    check_data_freshness,
)


BACKEND_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module", autouse=True)
def _isolated_data_refresh_database(tmp_path_factory: pytest.TempPathFactory):
    database = tmp_path_factory.mktemp("data-refresh") / "data-refresh.db"
    database_url = f"sqlite:///{database}"
    engine = create_engine(database_url, connect_args={"check_same_thread": False})
    session_local = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    with (
        patch.dict(os.environ, {"DATABASE_URL": database_url}),
        patch("app.services.data_refresh_service.SessionLocal", session_local),
    ):
        yield
    engine.dispose()


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

    def test_script_check_only_mode(self, tmp_path: Path) -> None:
        import subprocess

        database = tmp_path / "data-refresh.db"
        result = subprocess.run(
            [sys.executable, "-m", "scripts.data_refresh", "--check-only", "--json"],
            cwd=str(BACKEND_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
            env={**os.environ, "DATABASE_URL": f"sqlite:///{database}"},
        )
        diagnostics = (
            f"exit code: {result.returncode}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
        assert result.returncode in {0, 1}, (
            f"data refresh check failed\n{diagnostics}"
        )
        if not result.stdout.strip():
            pytest.fail(f"data refresh check produced empty stdout\n{diagnostics}", pytrace=False)
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            pytest.fail(f"data refresh check produced invalid JSON: {exc}\n{diagnostics}", pytrace=False)
        assert result.returncode == (0 if data["all_fresh"] else 1)
        assert "domains" in data
        assert "currency" in data
        assert "all_fresh" in data

    @pytest.mark.parametrize(
        ("stdout", "stderr", "expected"),
        [
            ("", "ModuleNotFoundError: loguru", "empty stdout"),
            ("not-json", "unexpected output", "invalid JSON"),
        ],
    )
    def test_script_invalid_output_reports_diagnostics(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        stdout: str,
        stderr: str,
        expected: str,
    ) -> None:
        import subprocess

        completed = subprocess.CompletedProcess(
            args=[sys.executable, "-m", "scripts.data_refresh"],
            returncode=1,
            stdout=stdout,
            stderr=stderr,
        )
        monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: completed)

        with pytest.raises(pytest.fail.Exception) as exc_info:
            self.test_script_check_only_mode(tmp_path)

        message = str(exc_info.value)
        assert expected in message
        assert "exit code: 1" in message
        assert f"stdout:\n{stdout}" in message
        assert f"stderr:\n{stderr}" in message


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
