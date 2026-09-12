"""Deterministic MOCK transport tests. These do not prove live API delegation."""

import base64
import json
import unittest
import urllib.error
from unittest.mock import patch

from tools.tariff_agents import runtime


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.env = {"OPENAI_API_KEY": "fixture-openai-credential", "TARIFF_OPENAI_MODEL": "configured-model"}
        self.session = {"id": "sess_fixture", "status": "idle", "required_actions": [],
                        "environment": {"id": "env_fixture"}}

    def test_preflight_does_not_equate_configuration_with_access(self):
        missing = runtime.preflight({})
        self.assertEqual(missing["agents_api"]["status"], "UNAVAILABLE")
        configured = runtime.preflight(self.env)
        self.assertEqual(configured["agents_api"]["status"], "CONFIGURED_UNVERIFIED")
        self.assertFalse(configured["agents_api"]["live_verified"])
        self.assertNotIn(self.env["OPENAI_API_KEY"], json.dumps(configured))

    @patch.object(runtime, "request_json")
    def test_missing_key_fails_before_outbound_call(self, request):
        with self.assertRaises(runtime.RuntimeBlocked):
            runtime.AgentsAPIClient({})
        request.assert_not_called()

    @patch.object(runtime, "request_json")
    def test_create_uses_native_multi_agent_and_vetted_inline_file_schema(self, request):
        request.return_value = self.session
        result = runtime.AgentsAPIClient(self.env).create_session(
            "Delegate two independent tasks.", "Review supplied code.", {"src/a.py": "print(1)\n"})
        args, kwargs = request.call_args
        self.assertEqual(args[0], "https://api.openai.com/v1/agents/sessions")
        self.assertEqual(kwargs["headers"]["OpenAI-Beta"], "agents=v1")
        payload = kwargs["payload"]
        self.assertEqual(payload["agent"]["multi_agent"], {"enabled": True, "max_concurrent_subagents": 3})
        self.assertEqual(payload["environment"]["network"], {"access": "disabled"})
        file = payload["environment"]["files"][0]
        self.assertEqual(file["type"], "inline")
        self.assertEqual(file["path"], "/workspace/src/a.py")
        self.assertEqual(base64.b64decode(file["data"]), b"print(1)\n")
        self.assertNotIn("tools", payload["agent"])
        self.assertNotIn("env", payload["environment"])
        self.assertFalse(result["repository_integration_verified"])

    @patch.object(runtime, "request_json")
    def test_no_model_or_secret_in_prompt_or_path_never_sends(self, request):
        client = runtime.AgentsAPIClient(self.env)
        for files in ({"../outside.py": "safe"}, {".env": "safe"}):
            with self.assertRaises(runtime.RuntimeBlocked):
                client.create_session("safe", "safe", files)
        with self.assertRaises(runtime.RuntimeBlocked):
            client.create_session("safe", self.env["OPENAI_API_KEY"])
        with self.assertRaises(runtime.RuntimeBlocked):
            runtime.AgentsAPIClient({"OPENAI_API_KEY": "fixture-value"}).create_session("safe", "safe")
        request.assert_not_called()

    @patch.object(runtime, "request_json")
    def test_resume_uses_events_without_claiming_completion(self, request):
        request.side_effect = [self.session, {}]
        result = runtime.AgentsAPIClient(self.env).resume_session("sess_fixture", "Continue from state.")
        payload = request.call_args.kwargs["payload"]
        self.assertEqual(payload["events"][0]["type"], "agent.session.input.message")
        self.assertFalse(result["completed"])
        self.assertEqual(result["status"], "INPUT_SUBMITTED")

    @patch.object(runtime, "request_json")
    def test_resume_does_not_blindly_repeat_required_actions(self, request):
        request.return_value = {**self.session, "status": "requires_action",
                                "required_actions": [{"type": "function_call"}]}
        with self.assertRaises(runtime.RuntimeBlocked):
            runtime.AgentsAPIClient(self.env).resume_session("sess_fixture", "Continue")
        self.assertEqual(request.call_count, 1)

    @patch.object(runtime, "request_json")
    def test_history_paginates_and_reports_facts_only(self, request):
        request.side_effect = [self.session,
            {"data": [{"id": "i1"}], "has_more": True, "last_id": "i1"},
            {"data": [{"id": "i2"}], "has_more": False},
            {"data": [{"id": "t1", "subagent_id": "a1", "status": "completed"},
                      {"id": "t2", "subagent_id": "a2", "status": "completed"},
                      {"id": "root", "subagent_id": None, "status": "completed"}], "has_more": False}]
        result = runtime.AgentsAPIClient(self.env).history("sess_fixture")
        self.assertEqual(result["observed_subagent_ids"], ["a1", "a2"])
        self.assertEqual(result["item_count"], 2)
        self.assertFalse(result["task_passed"])
        self.assertEqual(result["proof_scope"], "session_history_only")
        self.assertIn("after=i1", request.call_args_list[2].args[0])

    @patch.object(runtime, "request_json")
    def test_incomplete_history_is_not_success(self, request):
        request.side_effect = [self.session, {"data": [{"id": "i1"}], "has_more": True, "last_id": "i1"}]
        with self.assertRaisesRegex(runtime.RuntimeBlocked, "incomplete"):
            runtime.AgentsAPIClient(self.env).history("sess_fixture", max_pages=1)

    def test_event_parser_never_confuses_child_completion_with_root(self):
        events = [{"type": "agent.session.turn.completed", "turn": {"id": "t1", "subagent_id": "a1"}},
                  {"type": "agent.session.turn.completed", "turn": {"id": "t2", "subagent_id": "a1"}},
                  {"type": "agent.session.idle"},
                  {"type": "agent.session.turn.completed", "turn": {"id": "root"}}]
        proof = runtime.extract_event_proof(events, root_turn_id="root")
        self.assertEqual(proof["distinct_subagents"], 1)
        self.assertFalse(proof["root_completed"])
        events.append({"type": "agent.session.turn.failed", "turn": {"id": "root", "subagent_id": None}})
        self.assertEqual(runtime.extract_event_proof(events, root_turn_id="root")["root_outcome"], "failed")
        events.append({"type": "agent.session.turn.completed", "turn": {"id": "root", "subagent_id": None}})
        with self.assertRaises(runtime.RuntimeBlocked):
            runtime.extract_event_proof(events, root_turn_id="root")
        del events[-2]
        proof = runtime.extract_event_proof(events, root_turn_id="root")
        self.assertTrue(proof["root_completed"])
        self.assertFalse(proof["authenticated_by_parser"])
        self.assertFalse(proof["task_passed"])

    def test_transport_rejects_arbitrary_hosts_and_redirects(self):
        with self.assertRaises(runtime.RuntimeBlocked):
            runtime.request_json("https://attacker.test/v1/messages", method="POST", headers={})
        with self.assertRaises(runtime.RuntimeBlocked):
            runtime._NoRedirect().redirect_request(None, None, 302, "ignored", {}, "https://attacker.test")

    @patch.object(runtime.urllib.request, "build_opener")
    def test_http_failure_does_not_echo_body_reason_or_key(self, opener):
        credential = self.env["OPENAI_API_KEY"]
        opener.return_value.open.side_effect = urllib.error.HTTPError(
            "https://api.openai.com", 403, credential, {}, None)
        with self.assertRaises(runtime.RuntimeBlocked) as caught:
            runtime.request_json("https://api.openai.com/v1/agents/sessions", method="GET", headers={})
        self.assertEqual(str(caught.exception), "API request failed (HTTP 403)")
        self.assertNotIn(credential, str(caught.exception))


if __name__ == "__main__":
    unittest.main()
