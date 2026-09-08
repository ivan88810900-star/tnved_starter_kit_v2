from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app
from app.services import scheduler as scheduler_module


class _CapturingScheduler:
    def __init__(self) -> None:
        self.running = False
        self.added: dict[str, dict[str, object]] = {}

    def add_job(self, func, trigger, **kwargs) -> None:  # noqa: ANN001
        self.added[str(kwargs["id"])] = {
            "func": func,
            "trigger": trigger,
            **kwargs,
        }

    def start(self) -> None:
        self.running = True

    def shutdown(self, *, wait: bool) -> None:
        self.running = False

    def get_job(self, job_id: str):  # noqa: ANN201
        return None


def test_scheduler_registers_separated_daily_weekly_and_monthly_windows() -> None:
    captured = _CapturingScheduler()
    scheduler_module._scheduler = None
    try:
        with (
            patch.dict(
                os.environ,
                {
                    "REGULATORY_SYNC_SCHEDULER_ENABLED": "1",
                    "REGULATORY_SYNC_TZ": "Europe/Moscow",
                    "SCHEDULER_ENABLED": "0",
                },
            ),
            patch.object(scheduler_module, "AsyncIOScheduler", return_value=captured),
        ):
            scheduler_module.start_apscheduler()

        assert set(captured.added) == {
            "regulatory_sources_daily",
            "regulatory_sources_weekly",
            "regulatory_sources_monthly",
        }
        assert str(captured.added["regulatory_sources_daily"]["trigger"]) == "cron[hour='3', minute='0']"
        assert str(captured.added["regulatory_sources_weekly"]["trigger"]) == (
            "cron[day_of_week='sun', hour='8', minute='0']"
        )
        assert str(captured.added["regulatory_sources_monthly"]["trigger"]) == (
            "cron[day='1', hour='13', minute='0']"
        )
        assert captured.added["regulatory_sources_monthly"]["args"] == ["monthly"]
        for job in captured.added.values():
            assert job["max_instances"] == 1
            assert job["coalesce"] is True
            assert job["misfire_grace_time"] == 3600
    finally:
        scheduler_module._scheduler = None


def test_scheduler_job_raises_when_update_cycle_is_not_green() -> None:
    captured = _CapturingScheduler()
    scheduler_module._scheduler = None
    try:
        with (
            patch.dict(
                os.environ,
                {
                    "REGULATORY_SYNC_SCHEDULER_ENABLED": "1",
                    "SCHEDULER_ENABLED": "0",
                },
            ),
            patch.object(scheduler_module, "AsyncIOScheduler", return_value=captured),
        ):
            scheduler_module.start_apscheduler()
        job = captured.added["regulatory_sources_daily"]
        with patch(
            "app.services.regulatory_source_updates.run_regulatory_update_cycle",
            new_callable=AsyncMock,
            return_value={"status": "partial", "results": [{"status": "error"}]},
        ):
            try:
                asyncio.run(job["func"]("daily"))
            except RuntimeError as exc:
                assert "returned partial" in str(exc)
            else:  # pragma: no cover
                raise AssertionError("APScheduler job swallowed a failed update cycle")
    finally:
        scheduler_module._scheduler = None


def test_scheduler_job_treats_durable_review_notification_as_expected() -> None:
    captured = _CapturingScheduler()
    scheduler_module._scheduler = None
    try:
        with (
            patch.dict(
                os.environ,
                {
                    "REGULATORY_SYNC_SCHEDULER_ENABLED": "1",
                    "SCHEDULER_ENABLED": "0",
                },
            ),
            patch.object(scheduler_module, "AsyncIOScheduler", return_value=captured),
        ):
            scheduler_module.start_apscheduler()
        job = captured.added["regulatory_sources_monthly"]
        with patch(
            "app.services.regulatory_source_updates.run_regulatory_update_cycle",
            new_callable=AsyncMock,
            return_value={
                "status": "review_required",
                "results": [],
                "review_required_source_ids": ["official_sgr_ntm_v2_curated"],
            },
        ):
            asyncio.run(job["func"]("monthly"))
    finally:
        scheduler_module._scheduler = None


def test_scheduler_rejects_legacy_and_regulatory_jobs_together() -> None:
    scheduler_module._scheduler = None
    try:
        with patch.dict(
            os.environ,
            {
                "REGULATORY_SYNC_SCHEDULER_ENABLED": "1",
                "SCHEDULER_ENABLED": "1",
            },
        ):
            try:
                scheduler_module.start_apscheduler()
            except RuntimeError as exc:
                assert "must not be enabled" in str(exc)
            else:  # pragma: no cover
                raise AssertionError("competing scheduler families started together")
    finally:
        scheduler_module._scheduler = None


def test_regulatory_jobs_status_reports_each_next_run() -> None:
    next_run = datetime(2026, 9, 2, 3, 0, tzinfo=timezone.utc)
    jobs = {
        "regulatory_sources_daily": SimpleNamespace(next_run_time=next_run),
        "regulatory_sources_weekly": SimpleNamespace(next_run_time=None),
        "regulatory_sources_monthly": SimpleNamespace(next_run_time=None),
    }
    scheduler_module._scheduler = SimpleNamespace(get_job=jobs.get, running=True)
    try:
        status = scheduler_module.regulatory_jobs_status()
    finally:
        scheduler_module._scheduler = None

    assert status["daily"]["next_run_at"] == "2026-09-02T03:00:00+00:00"
    assert status["weekly"]["next_run_at"] is None
    assert status["monthly"]["job_id"] == "regulatory_sources_monthly"


def test_updates_status_returns_persisted_report_and_schedule() -> None:
    client = TestClient(app)
    persisted = {
        "status": "partial",
        "cadence": "daily",
        "finished_at": "2026-09-01T03:01:00+00:00",
    }
    scheduled = {
        "daily": {"job_id": "regulatory_sources_daily", "next_run_at": None},
        "weekly": {"job_id": "regulatory_sources_weekly", "next_run_at": None},
        "monthly": {"job_id": "regulatory_sources_monthly", "next_run_at": None},
    }
    review_queue = {
        "durable": True,
        "status": "clear",
        "notification_required": False,
        "pending_count": 0,
        "pending_source_ids": [],
        "items": [],
    }
    with (
        patch("app.api.sources.load_last_update_report", return_value=persisted),
        patch("app.api.sources.is_read_only_mode", return_value=False),
        patch("app.api.sources.is_scheduler_running", return_value=True),
        patch("app.api.sources.regulatory_jobs_status", return_value=scheduled),
        patch("app.api.sources.regulatory_review_queue_summary", return_value=review_queue),
    ):
        response = client.get("/api/sources/updates/status")

    assert response.status_code == 200
    assert response.json() == {
        "status": "partial",
        "read_only": False,
        "scheduler": {"running": True, "jobs": scheduled},
        "last_run": persisted,
        "review_queue": review_queue,
    }


def test_updates_status_cannot_be_green_while_durable_review_is_pending() -> None:
    client = TestClient(app)
    review_queue = {
        "durable": True,
        "status": "review_required",
        "notification_required": True,
        "pending_count": 1,
        "pending_source_ids": ["official_sgr_ntm_v2_curated"],
        "items": [{"id": 7, "status": "pending"}],
    }
    with (
        patch("app.api.sources.load_last_update_report", return_value={"status": "ok"}),
        patch("app.api.sources.regulatory_review_queue_summary", return_value=review_queue),
    ):
        response = client.get("/api/sources/updates/status")

    assert response.status_code == 200
    assert response.json()["status"] == "review_required"
    assert response.json()["review_queue"]["notification_required"] is True


def test_updates_status_clears_stale_review_required_after_queue_resolution() -> None:
    client = TestClient(app)
    review_queue = {
        "durable": True,
        "status": "clear",
        "notification_required": False,
        "pending_count": 0,
        "pending_source_ids": [],
        "items": [],
    }
    with (
        patch(
            "app.api.sources.load_last_update_report",
            return_value={"status": "review_required", "cadence": "monthly"},
        ),
        patch("app.api.sources.regulatory_review_queue_summary", return_value=review_queue),
    ):
        response = client.get("/api/sources/updates/status")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_updates_reviews_exposes_machine_notification_contract() -> None:
    client = TestClient(app)
    rows = [
        {
            "id": 6,
            "source_id": "official_sgr_ntm_v2_curated",
            "status": "resolved",
        }
    ]
    summary = {
        "contract_version": 1,
        "durable": True,
        "status": "review_required",
        "notification_required": True,
        "pending_count": 1,
        "pending_source_ids": ["official_sgr_ntm_v2_curated"],
        "items": [{"id": 7, "source_id": "legacy_ntm_tr_catalog", "status": "pending"}],
    }
    with (
        patch.dict(os.environ, {"ADMIN_API_TOKEN": "test-admin-token"}),
        patch("app.api.sources.list_regulatory_source_reviews", return_value=rows),
        patch("app.api.sources.regulatory_review_queue_summary", return_value=summary),
    ):
        unauthorized = client.get("/api/sources/updates/reviews")
        response = client.get(
            "/api/sources/updates/reviews?status=resolved",
            headers={"X-Admin-Token": "test-admin-token"},
        )

    assert unauthorized.status_code == 401
    assert response.status_code == 200
    assert response.json() == {
        "status": "review_required",
        "notification_required": True,
        "review_queue": {key: value for key, value in summary.items() if key != "items"},
        "items": rows,
    }


def test_updates_reviews_allows_admin_to_audit_superseded_history() -> None:
    client = TestClient(app)
    rows = [
        {
            "id": 8,
            "source_id": "official_sgr_ntm_v2_curated",
            "status": "superseded",
            "superseded_by_evidence_sha256": "b" * 64,
        }
    ]
    summary = {
        "contract_version": 1,
        "durable": True,
        "status": "clear",
        "notification_required": False,
        "pending_count": 0,
        "pending_source_ids": [],
        "items": [],
    }
    with (
        patch.dict(os.environ, {"ADMIN_API_TOKEN": "test-admin-token"}),
        patch(
            "app.api.sources.list_regulatory_source_reviews",
            return_value=rows,
        ) as list_reviews,
        patch("app.api.sources.regulatory_review_queue_summary", return_value=summary),
    ):
        response = client.get(
            "/api/sources/updates/reviews?status=superseded",
            headers={"X-Admin-Token": "test-admin-token"},
        )

    assert response.status_code == 200
    assert response.json()["items"] == rows
    list_reviews.assert_called_once_with(status="superseded", limit=200)


def test_review_resolution_requires_admin_token_and_records_evidence() -> None:
    client = TestClient(app)
    evidence_sha256 = "a" * 64
    resolved = {
        "id": 7,
        "status": "resolved",
        "resolution_ref": "#321",
        "evidence_sha256": evidence_sha256,
        "evidence_generation": 3,
    }
    with (
        patch.dict(os.environ, {"ADMIN_API_TOKEN": "test-admin-token"}),
        patch("app.security.auth_mod.SECRET_KEY", "test-audit-key"),
        patch("app.api.sources.is_read_only_mode", return_value=False),
        patch(
            "app.api.sources.resolve_regulatory_source_review",
            return_value=resolved,
        ) as resolve_review,
    ):
        unauthorized = client.post(
            "/api/sources/updates/reviews/7/resolve",
            json={
                "asserted_by": "legal-reviewer",
                "resolution_ref": "#321",
                "evidence_sha256": evidence_sha256,
                "evidence_generation": 3,
            },
        )
        response = client.post(
            "/api/sources/updates/reviews/7/resolve",
            headers={"X-Admin-Token": "test-admin-token"},
            json={
                "asserted_by": "legal-reviewer",
                "resolution_ref": "#321",
                "evidence_sha256": evidence_sha256,
                "evidence_generation": 3,
            },
        )

    assert unauthorized.status_code == 401
    assert response.status_code == 200
    assert response.json() == {"status": "resolved", "review": resolved}
    authenticated_actor = (
        "admin-token:hmac-sha256:"
        + hmac.new(
            b"test-audit-key",
            b"test-admin-token",
            hashlib.sha256,
        ).hexdigest()[:16]
    )
    resolve_review.assert_called_once_with(
        7,
        authenticated_actor=authenticated_actor,
        asserted_by="legal-reviewer",
        resolution_ref="#321",
        evidence_sha256=evidence_sha256,
        evidence_generation=3,
    )


def test_review_resolution_is_blocked_in_read_only_mode() -> None:
    client = TestClient(app)
    with (
        patch.dict(os.environ, {"ADMIN_API_TOKEN": "test-admin-token"}),
        patch("app.api.sources.is_read_only_mode", return_value=True),
        patch("app.api.sources.resolve_regulatory_source_review") as resolve_review,
    ):
        response = client.post(
            "/api/sources/updates/reviews/7/resolve",
            headers={"X-Admin-Token": "test-admin-token"},
            json={
                "asserted_by": "legal-reviewer",
                "resolution_ref": "#321",
                "evidence_sha256": "a" * 64,
                "evidence_generation": 1,
            },
        )

    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "read_only_mode"
    resolve_review.assert_not_called()


def test_updates_run_is_blocked_in_read_only_mode() -> None:
    client = TestClient(app)
    with (
        patch.dict(os.environ, {"ADMIN_API_TOKEN": "test-admin-token"}),
        patch("app.api.sources.is_read_only_mode", return_value=True),
        patch("app.api.sources.run_regulatory_update_cycle", new_callable=AsyncMock) as run_cycle,
    ):
        response = client.post(
            "/api/sources/updates/run?cadence=daily",
            headers={"X-Admin-Token": "test-admin-token"},
        )

    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "read_only_mode"
    run_cycle.assert_not_awaited()
