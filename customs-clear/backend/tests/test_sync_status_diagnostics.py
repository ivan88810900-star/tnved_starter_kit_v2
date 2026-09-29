"""Fail-closed diagnostics for the normative sync scheduler."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from app.services.sync_status_diagnostics import build_sync_status_diagnostics


class SyncStatusDiagnosticsTests(unittest.TestCase):
    def _payload(
        self,
        *,
        completed_at: datetime | None,
        trigger: str = "",
        error: str = "",
        scheduler_running: bool = True,
        next_run: str | None = "2026-09-29T03:00:00+03:00",
    ) -> dict:
        return build_sync_status_diagnostics(
            completed_at=completed_at,
            last_trigger=trigger,
            last_error=error,
            scheduler_running=scheduler_running,
            next_sync_iso=next_run,
        )

    def test_failed_completion_is_not_reported_as_success(self) -> None:
        payload = self._payload(
            completed_at=datetime(2026, 9, 28, 4, 0),
            trigger="scheduled",
            error="provider timeout",
        )

        self.assertEqual(payload["latest_attempt_status"], "failed")
        self.assertEqual(payload["automatic_update_status"], "latest_scheduled_run_failed")
        self.assertIsNone(payload["last_successful_sync_at"])
        self.assertIsNone(payload["last_successful_scheduled_sync_at"])
        self.assertEqual(payload["last_success_evidence_scope"], "latest_attempt_only")
        self.assertTrue(payload["last_error_present"])
        self.assertEqual(payload["last_sync_iso"], "2026-09-28T04:00:00+00:00")

    def test_manual_success_is_not_scheduled_success_evidence(self) -> None:
        payload = self._payload(
            completed_at=datetime(2026, 9, 28, 6, 0, tzinfo=timezone.utc),
            trigger="manual",
        )

        self.assertEqual(payload["latest_attempt_status"], "succeeded")
        self.assertEqual(payload["automatic_update_status"], "no_scheduled_run_evidence")
        self.assertEqual(payload["last_successful_sync_at"], "2026-09-28T06:00:00+00:00")
        self.assertIsNone(payload["last_successful_scheduled_sync_at"])

    def test_scheduled_success_is_execution_evidence_not_currentness(self) -> None:
        payload = self._payload(
            completed_at=datetime(
                2026,
                9,
                28,
                6,
                0,
                tzinfo=timezone(timedelta(hours=3)),
            ),
            trigger="scheduled",
        )

        self.assertEqual(payload["schedule_status"], "scheduled")
        self.assertEqual(payload["automatic_update_status"], "latest_scheduled_run_succeeded")
        self.assertEqual(
            payload["last_successful_scheduled_sync_at"],
            "2026-09-28T03:00:00+00:00",
        )
        self.assertEqual(payload["diagnostic_scope"], "pipeline_execution_only")
        self.assertFalse(payload["authoritative_currentness_confirmed"])

    def test_running_scheduler_without_job_fails_closed(self) -> None:
        payload = self._payload(
            completed_at=None,
            scheduler_running=True,
            next_run=None,
        )

        self.assertEqual(payload["schedule_status"], "job_missing")
        self.assertEqual(payload["latest_attempt_status"], "never_run")
        self.assertEqual(payload["automatic_update_status"], "job_missing")


if __name__ == "__main__":
    unittest.main()
