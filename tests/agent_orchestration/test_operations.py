import copy
from datetime import datetime, timedelta, timezone
import unittest
from tools.tariff_agents.operations import (incident_key, observe,
                                            notification_attempt, needs_notification)


class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)
        self.gate = {"action": "A6_EXTERNAL_PROVIDER_EXPORT", "request_id": "core-s1-r9",
                     "packet_sha256": "a" * 64, "authorization": "REQUIRED_EXACT_REQUEST_ONLY"}
        self.key = incident_key(self.gate)

    def test_export_owner_gate_cannot_be_filtered_as_routine_noise(self):
        result = observe({"owner_gate": self.gate}, {"is_enabled": True}, now=self.now)
        self.assertEqual(result["status"], "OWNER_ACTION_REQUIRED")
        self.assertFalse(result["external_export_authorized"])

    def test_unknown_authorization_is_not_granted(self):
        for value in (None, "", "PENDING", "NOT_GRANTED", "NEW_DISTINCT_REQUEST_AND_NEW_EXACT_APPROVAL_REQUIRED"):
            with self.subTest(value=value):
                gate = {**self.gate, "authorization": value}
                self.assertTrue(observe({"owner_gate": gate}, {"is_enabled": True}, now=self.now)["owner_action_required"])

    def test_consumed_approval_not_requested_again(self):
        for value in ("CONSUMED", "GRANTED", "CLOSED", "REJECTED", "MERGED_AUTHORIZATION_CONSUMED"):
            with self.subTest(value=value):
                gate = {**self.gate, "authorization": value}
                self.assertFalse(observe({"owner_gate": gate}, {"is_enabled": True}, now=self.now)["owner_action_required"])

    def test_disabled_schedule_is_reported_without_inventing_new_owner_gate(self):
        result = observe({}, {"is_enabled": False}, now=self.now)
        self.assertEqual(result["status"], "WORK_STOPPED")
        self.assertFalse(result["owner_action_required"])

    def test_verified_active_coordinator_is_not_stopped(self):
        result = observe({}, {"is_enabled": False}, now=self.now, active_coordinator=True)
        self.assertEqual(result["status"], "NO_NEW_OWNER_GATE")

    def test_unknown_runtime_is_not_healthy(self):
        for value in (None, "true", 1, {}, []):
            with self.subTest(value=value):
                self.assertEqual(observe({}, {"is_enabled": value}, now=self.now)["status"], "OBSERVATION_UNAVAILABLE")

    def test_wake_up_not_material_progress(self):
        result = observe({}, {"is_enabled": True, "last_run_time": self.now.isoformat()},
                         now=self.now, last_material_progress_at=(self.now-timedelta(hours=3)).isoformat())
        self.assertEqual(result["status"], "WORK_STALLED")

    def test_future_progress_is_not_healthy(self):
        result = observe({}, {"is_enabled": True}, now=self.now,
                         last_material_progress_at=(self.now+timedelta(hours=3)).isoformat())
        self.assertEqual(result["status"], "OBSERVATION_UNAVAILABLE")

    def test_observation_timestamps_do_not_change_incident(self):
        for delta in ({"checked_at": "new"}, {"risk": "changed prose"}, {"authorization": "PENDING"}):
            self.assertEqual(self.key, incident_key({**self.gate, **delta}))

    def test_new_export_scope_is_new_incident(self):
        for delta in ({"request_id": "different"}, {"packet_sha256": "b"*64}, {"contract_sha": "c"*40}):
            self.assertNotEqual(self.key, incident_key({**self.gate, **delta}))

    def test_notify_parent_not_user_delivery_even_with_turn_id(self):
        item = notification_attempt(self.key, "notify_parent", {"status": "notified", "turnId": "123"}, now=self.now)
        self.assertEqual(item["status"], "MODEL_QUEUED")
        self.assertFalse(item["user_visible_delivery_confirmed"])
        self.assertTrue(needs_notification(self.key, [item], now=self.now+timedelta(hours=1)))

    def test_model_route_cannot_claim_delivered(self):
        item = notification_attempt(self.key, "notify_parent", {"status": "delivered", "user_visible": True, "message_id": "123"}, now=self.now)
        self.assertFalse(item["user_visible_delivery_confirmed"])

    def test_no_receipt_or_request_ack_does_not_mean_delivered(self):
        for raw in (None, {}, {"status": "requested"}, {"status": "SUCCESS"}, {"status": "notified"}):
            with self.subTest(raw=raw):
                item = notification_attempt(self.key, "task_result", raw, now=self.now)
                self.assertFalse(item["user_visible_delivery_confirmed"])

    def test_delivered_receipt_requires_visibility_and_id(self):
        for raw in ({"status": "delivered"}, {"status": "delivered", "user_visible": True},
                    {"status": "delivered", "user_visible": True, "message_id": ""}):
            self.assertFalse(notification_attempt(self.key, "task_result", raw, now=self.now)["user_visible_delivery_confirmed"])

    def test_verified_delivery_deduplicates(self):
        item = notification_attempt(self.key, "task_result", {"status": "delivered", "user_visible": True, "message_id": "msg-1"}, now=self.now)
        self.assertTrue(item["user_visible_delivery_confirmed"])
        self.assertFalse(needs_notification(self.key, [item], now=self.now+timedelta(days=2)))

    def test_failed_attempt_is_pending_but_bounded(self):
        item = notification_attempt(self.key, "task_result", {"isError": True}, now=self.now)
        self.assertFalse(needs_notification(self.key, [item], now=self.now+timedelta(minutes=59)))
        self.assertTrue(needs_notification(self.key, [item], now=self.now+timedelta(hours=1)))

    def test_no_free_form_error_or_secrets_persisted(self):
        item = notification_attempt(self.key, "email", {"isError": True, "message": "private data must not persist"}, now=self.now)
        self.assertNotIn("private data", str(item))

    def test_owner_acknowledgement_deduplicates(self):
        self.assertFalse(needs_notification(self.key, [], now=self.now, acknowledged_event_keys=[self.key]))

    def test_wrong_incident_does_not_silence_this_one(self):
        item = notification_attempt("b"*64, "email", {"status": "delivered", "user_visible": True, "message_id": "msg-2"}, now=self.now)
        self.assertTrue(needs_notification(self.key, [item], now=self.now))

    def test_future_receipt_cannot_silence_notifications(self):
        item = notification_attempt(self.key, "notify_parent", {"status": "notified"}, now=self.now+timedelta(days=300))
        self.assertTrue(needs_notification(self.key, [item], now=self.now))

    def test_false_delivered_flag_without_user_visible_route_not_accepted(self):
        item = {"event_key": self.key, "status": "DELIVERED", "route": "notify_parent",
                "user_visible_delivery_confirmed": True, "message_id": "123", "attempted_at": self.now.isoformat()}
        self.assertTrue(needs_notification(self.key, [item], now=self.now+timedelta(hours=1)))

    def test_pure_functions_do_not_mutate_inputs(self):
        state = {"owner_gate": copy.deepcopy(self.gate)}
        before = copy.deepcopy(state)
        observe(state, {"is_enabled": True}, now=self.now)
        self.assertEqual(state, before)

    def test_naive_time_rejected(self):
        with self.assertRaises(ValueError):
            observe({}, {"is_enabled": True}, now=datetime(2026, 10, 7))

    def test_subhourly_retry_rejected(self):
        with self.assertRaises(ValueError):
            needs_notification(self.key, [], now=self.now, retry_seconds=1)


    def test_invalid_authorization_container_is_not_granted(self):
        for value in ([], {}, 1, False):
            gate = {**self.gate, "authorization": value}
            self.assertTrue(observe({"owner_gate": gate}, {"is_enabled": True}, now=self.now)["owner_action_required"])

    def test_future_delivered_receipt_is_not_current_evidence(self):
        item = notification_attempt(self.key, "task_result", {"status": "delivered", "user_visible": True, "message_id": "msg-future"}, now=self.now+timedelta(days=1))
        self.assertTrue(needs_notification(self.key, [item], now=self.now))

    def test_invalid_event_key_type_is_controlled(self):
        for key in ([], {}, 12, None):
            with self.assertRaises(ValueError):
                needs_notification(key, [], now=self.now)

    def test_invalid_route_type_is_controlled(self):
        with self.assertRaises(ValueError):
            notification_attempt(self.key, [], {}, now=self.now)

    def test_empty_action_rejected(self):
        with self.assertRaises(ValueError):
            incident_key({"action": ""})


if __name__ == "__main__":
    unittest.main()
