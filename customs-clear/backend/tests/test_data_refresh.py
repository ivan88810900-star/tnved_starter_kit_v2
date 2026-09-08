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
    refresh_currency_rates,
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


class TestCurrencyRefresh:
    def test_failed_cbr_result_is_not_reported_as_green(self) -> None:
        async def failed_refresh(**_kwargs: object) -> dict[str, object]:
            return {
                "status": "ERROR",
                "source": "preserved_last_good",
                "updated": 0,
                "error": "upstream unavailable",
            }

        with patch(
            "app.services.exchange_rates.update_exchange_rates_from_cbrf",
            failed_refresh,
        ):
            result = asyncio.run(refresh_currency_rates())

        assert result["status"] == "error"
        assert result["source"] == "preserved_last_good"
        assert result["updated"] == 0
        assert result["error"] == "upstream unavailable"


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

            async def slow_refresh(**_kwargs: object) -> dict[str, object]:
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

    def test_scheduler_startup_failure_aborts_application_startup(self) -> None:
        from app import main as main_module

        async def scenario() -> None:
            with (
                patch.object(main_module, "is_read_only_mode", return_value=False),
                patch.object(main_module, "init_db"),
                patch.object(main_module, "update_exchange_rates_from_cbrf") as refresh_mock,
                patch("app.services.permits_jobs.mark_interrupted_jobs_on_startup"),
                patch("app.services.ved_intel_jobs.mark_interrupted_ved_intel_jobs_on_startup"),
                patch(
                    "app.services.scheduler.start_apscheduler",
                    side_effect=RuntimeError("conflicting scheduler configuration"),
                ),
            ):
                try:
                    async with main_module.lifespan(main_module.app):
                        raise AssertionError("lifespan yielded after scheduler failure")
                except RuntimeError as exc:
                    assert "conflicting scheduler configuration" in str(exc)
                else:  # pragma: no cover
                    raise AssertionError("scheduler startup failure was swallowed")
                refresh_mock.assert_not_called()

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

    def test_workflow_validates_live_cbr_without_a_database(self) -> None:
        wf = Path(__file__).resolve().parent.parent.parent.parent / ".github" / "workflows" / "scheduled-data-refresh.yml"
        content = wf.read_text()
        assert "name: Regulatory source monitor" in content
        assert "scripts/update_rates.py --validate-only --json" in content
        assert "scripts/update_rates.py --validate-only --json --strict" in content
        assert "python -m scripts.data_refresh --check-only --json" not in content
        assert "data-freshness.json" not in content

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
        assert "regulatory-source-monitor-v4-" in content
        assert 'state.get("version") != 4' in content
        assert "issues: write" in content
        assert content.count("issues: write") == 1
        assert "actions/github-script@" in content
        assert "notify:" in content
        assert "if: always()" in content
        assert "--accept-changes --approval-ref" in content
        assert "persist-credentials: false" in content
        assert "retention-days: 90" in content
        assert "if-no-files-found: error" in content
        assert "uses: actions/checkout@v" not in content
        assert "uses: actions/setup-python@v" not in content

    def test_workflow_is_fail_closed_for_legal_review_and_full_catalog(self) -> None:
        wf = BACKEND_ROOT.parent.parent / ".github" / "workflows" / "scheduled-data-refresh.yml"
        content = wf.read_text()
        assert "approval_source_ids:" in content
        assert "approval_source_digests:" in content
        assert "approval_source_ids must exactly match pending source IDs" in content
        assert "approval_source_digests must exactly match pending source digests" in content
        assert "REGULATORY_BASELINE_APPROVAL_SHA256=" in content
        assert "comment by the trusted dispatcher" in content
        assert "collaborators/$GITHUB_ACTOR/permission" in content
        assert "--jq '.permission // \"\"'" in content
        assert ".role_name" not in content
        assert 'case "$actor_permission" in' in content
        assert "admin|write)" in content
        assert "effective write or admin access" in content
        assert "gh api \"repos/$GITHUB_REPOSITORY/issues/$approval_issue_number\"" in content
        assert (
            ".all_available == true and .revision_monitor_gate_ok == true "
            "and .review_required == false"
        ) in content
        assert 'report.get("revision_monitor_gate_ok") is not True' in content
        assert "sourceReport?.revision_monitor_gate_ok !== true" in content
        assert "revision_candidate_source_count" in content
        assert "revision_covered_source_count" in content
        assert "revision_gap_source_count" in content
        assert "revision_unavailable_source_count" in content
        assert "explicit_availability_source_count" in content
        assert "availability_only_source_count" in content
        assert "Number(sourceReport?.revision_gap_source_count || 0) > 0" in content
        assert "pending_review_exit" in content
        assert "saved source-state universe differs from the current monitor universe" in content
        assert "saved pending digests differ from the current review set" in content
        assert "--allow-partial" not in content
        assert "--database data/runtime/ntm-full-catalog.db" in content
        assert "scripts/import_pdf.py" in content

    def test_workflow_notifies_exact_monthly_local_reconcile_set(self) -> None:
        wf = BACKEND_ROOT.parent.parent / ".github" / "workflows" / "scheduled-data-refresh.yml"
        content = wf.read_text()
        assert "readJson('regulatory-source-update-plan.json')" in content
        assert "source?.operational_state === 'scheduled_review_due'" in content
        assert "!localReviewContractValid" in content
        assert "Monthly curated regulatory-source review ${reviewPeriod}" in content
        assert "state: 'all'" in content
        assert "context.ref === `refs/heads/${defaultBranch}`" in content
        assert "localReviewContractValid && isDefaultBranch" in content
        assert "regulatory-local-review:${reviewPeriod}:v1" in content
        assert "issue.user?.login === 'github-actions[bot]'" in content
        assert "Closing this GitHub issue records notification handling only" in content
        for source_id in (
            "official_sgr_ntm_v2_curated",
            "legacy_ntm_tr_catalog",
            "sanction_import_risks",
            "country_risks_geopolitics",
            "geo_special_duties_embargo",
        ):
            assert source_id in content

    def test_workflow_approval_binding_uses_python_compatible_ascii_order(self) -> None:
        wf = BACKEND_ROOT.parent.parent / ".github" / "workflows" / "scheduled-data-refresh.yml"
        content = wf.read_text()
        # Python json.dumps(sort_keys=True) is the verifier. JavaScript locale
        # collation orders underscores differently and can make a multi-source
        # approval marker impossible to reproduce.
        assert ".localeCompare(" not in content
        assert "left.source_id < right.source_id" in content
        assert "left.source_id > right.source_id" in content
        assert sorted(["rf_pp_2425_conformity", "rf_pp1284_chemical_control"]) == [
            "rf_pp1284_chemical_control",
            "rf_pp_2425_conformity",
        ]

    def test_workflow_uploads_evidence_before_saving_baseline(self) -> None:
        wf = BACKEND_ROOT.parent.parent / ".github" / "workflows" / "scheduled-data-refresh.yml"
        content = wf.read_text()
        upload = content.index("- name: Upload regulatory evidence bundle")
        persistence_gate = content.index("- name: Validate state persistence after evidence upload")
        save = content.index("- name: Save reviewed or pending official-source state")
        assert upload < persistence_gate < save
        assert "steps.state_persistence_gate.outcome == 'success'" in content

    def test_workflow_uses_minimal_exactly_pinned_dependencies(self) -> None:
        wf = BACKEND_ROOT.parent.parent / ".github" / "workflows" / "scheduled-data-refresh.yml"
        content = wf.read_text()
        lock = BACKEND_ROOT / "requirements-monitor.txt"
        lines = [
            line.strip()
            for line in lock.read_text().splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        pins = [line for line in lines if "==" in line]
        hashes = [line for line in lines if line.startswith("--hash=sha256:")]
        assert pins
        assert all("==" in pin for pin in pins)
        assert len(hashes) == len(pins)
        assert "--only-binary=:all:" in content
        assert "--require-hashes" in content
        assert "--requirement requirements-monitor.txt" in content
        assert "--requirement requirements.txt" not in content

    def test_pr_ci_rebuilds_locked_monitor_environment_and_validates_workflow(self) -> None:
        ci = BACKEND_ROOT.parent.parent / ".github" / "workflows" / "ci.yml"
        content = ci.read_text()
        validator = BACKEND_ROOT / "scripts" / "validate_scheduled_workflow_contract.py"
        assert validator.is_file()
        assert "workflow-contract:" in content
        assert "--only-binary=:all:" in content
        assert "--require-hashes" in content
        assert "--requirement requirements-monitor.txt" in content
        assert "python -m pip check" in content
        assert "python scripts/validate_scheduled_workflow_contract.py" in content
        assert "scripts/run_regulatory_source_updates.py" in content
        assert "--plan --strict" in content
        assert "scripts/build_ntm_full_catalog_baseline.py --check-sources-only" in content
