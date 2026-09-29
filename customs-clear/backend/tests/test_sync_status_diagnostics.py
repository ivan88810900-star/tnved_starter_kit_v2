"""Fail-closed diagnostics for the normative sync scheduler."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from app.services.sync_status_diagnostics import build_sync_status_diagnostics


class SyncStatusDiagnosticsTests(unittest.TestCase):
    NOW = datetime(2026, 9, 29, 0, 0, tzinfo=timezone.utc)

    def _payload(
        self,
        *,
        completed_at: datetime | None,
        trigger: str = "",
        error: str = "",
        scheduler_running: bool = True,
        next_run: str | None = "2026-09-29T06:00:00+03:00",
    ) -> dict:
        return build_sync_status_diagnostics(
            completed_at=completed_at,
            last_trigger=trigger,
            last_error=error,
            scheduler_running=scheduler_running,
            next_sync_iso=next_run,
            now=self.NOW,
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

    def test_naive_database_timestamp_is_explicitly_utc(self) -> None:
        payload = self._payload(
            completed_at=datetime(2026, 9, 28, 23, 30),
            trigger="scheduled",
        )

        self.assertEqual(payload["latest_attempt_at"], "2026-09-28T23:30:00+00:00")
        self.assertEqual(payload["latest_attempt_time_status"], "fresh")
        self.assertEqual(payload["automatic_update_status"], "latest_scheduled_run_succeeded")

    def test_future_completion_timestamp_fails_closed(self) -> None:
        payload = self._payload(
            completed_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
            trigger="scheduled",
            next_run="2099-01-02T03:00:00+00:00",
        )

        self.assertEqual(payload["latest_attempt_time_status"], "future")
        self.assertEqual(payload["automatic_update_status"], "invalid_attempt_timestamp")
        self.assertIsNone(payload["last_successful_sync_at"])

    def test_stale_scheduled_completion_is_not_current_health(self) -> None:
        payload = self._payload(
            completed_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
            trigger="scheduled",
        )

        self.assertEqual(payload["latest_attempt_time_status"], "stale")
        self.assertEqual(payload["automatic_update_status"], "latest_scheduled_run_stale")

    def test_malformed_completion_timestamp_fails_closed(self) -> None:
        payload = self._payload(
            completed_at="not-a-datetime",  # type: ignore[arg-type]
            trigger="scheduled",
        )

        self.assertEqual(payload["latest_attempt_status"], "invalid_timestamp")
        self.assertEqual(payload["latest_attempt_time_status"], "invalid")
        self.assertEqual(payload["automatic_update_status"], "incomplete_attempt_evidence")
        self.assertIsNone(payload["last_sync_iso"])
        self.assertIsNone(payload["last_successful_sync_at"])

    def test_malformed_next_run_fails_closed(self) -> None:
        payload = self._payload(
            completed_at=datetime(2026, 9, 28, 23, 0, tzinfo=timezone.utc),
            trigger="scheduled",
            next_run="not-a-date",
        )

        self.assertEqual(payload["schedule_status"], "invalid_next_run")
        self.assertEqual(payload["next_run_time_status"], "invalid")
        self.assertEqual(payload["automatic_update_status"], "invalid_next_run")

    def test_past_next_run_fails_closed(self) -> None:
        payload = self._payload(
            completed_at=datetime(2026, 9, 28, 22, 0, tzinfo=timezone.utc),
            trigger="scheduled",
            next_run="2026-09-28T23:00:00+00:00",
        )

        self.assertEqual(payload["schedule_status"], "next_run_not_future")
        self.assertEqual(payload["automatic_update_status"], "next_run_not_future")

    def test_next_run_before_completion_fails_closed(self) -> None:
        payload = self._payload(
            completed_at=datetime(2026, 9, 28, 23, 0, tzinfo=timezone.utc),
            trigger="scheduled",
            next_run="2026-09-28T22:00:00+00:00",
        )

        self.assertEqual(payload["schedule_status"], "next_run_not_after_attempt")
        self.assertEqual(payload["automatic_update_status"], "next_run_not_after_attempt")

    def test_error_without_completion_timestamp_surfaces_failure(self) -> None:
        payload = self._payload(
            completed_at=None,
            trigger="scheduled",
            error="download failed",
        )

        self.assertEqual(payload["latest_attempt_status"], "failed_without_timestamp")
        self.assertEqual(
            payload["automatic_update_status"],
            "latest_attempt_failed_without_timestamp",
        )
        self.assertIsNone(payload["last_successful_sync_at"])

    def test_partial_attempt_evidence_is_explicit_and_in_progress_unobservable(self) -> None:
        payload = self._payload(
            completed_at=None,
            trigger="scheduled",
        )

        self.assertEqual(payload["latest_attempt_status"], "incomplete_evidence")
        self.assertEqual(payload["automatic_update_status"], "incomplete_attempt_evidence")
        self.assertFalse(payload["in_progress_observable"])

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
