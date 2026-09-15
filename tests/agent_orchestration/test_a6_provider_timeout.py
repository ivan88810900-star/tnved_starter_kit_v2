"""Regression coverage for the bounded Claude A6 provider timeout."""

import json
import unittest
from unittest.mock import patch

from tools.tariff_agents import audit


class A6ProviderTimeoutTests(unittest.TestCase):
    def packet(self):
        return {
            "base_sha": "a" * 40,
            "head_sha": "b" * 40,
            "packet_sha256": "c" * 64,
        }

    def environ(self):
        provider_key = "ANTHROPIC_" + "API_KEY"
        provider_value = "fixture-provider-" + "credential"
        return {provider_key: provider_value,
                "TARIFF_ANTHROPIC_MODEL": "explicit-fixture-model"}

    def findings(self, packet):
        return {"packet_sha256": packet["packet_sha256"],
                "head_sha": packet["head_sha"],
                "findings": [], "limitations": []}

    @patch.object(audit, "validate_packet")
    @patch.object(audit, "validate_findings")
    @patch.object(audit, "request_json")
    def test_live_a6_uses_extended_bounded_timeout(self, request, validate_findings,
                                                   validate_packet):
        packet = self.packet()
        findings = self.findings(packet)
        validate_packet.return_value = packet
        validate_findings.return_value = findings
        request.return_value = {
            "id": "msg_timeout_fixture",
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": json.dumps(findings)}],
        }

        result = audit.run_audit(".", packet, environ=self.environ())

        self.assertEqual(result["status"], "NEEDS_A0_VALIDATION")
        request.assert_called_once()
        self.assertEqual(request.call_args.kwargs["timeout"],
                         audit.A6_PROVIDER_TIMEOUT_SECONDS)
        self.assertGreater(audit.A6_PROVIDER_TIMEOUT_SECONDS, 45)
        self.assertLessEqual(audit.A6_PROVIDER_TIMEOUT_SECONDS, 600)

    @patch.object(audit, "validate_packet")
    @patch.object(audit, "request_json")
    def test_provider_timeout_failure_remains_fail_closed_without_retry(self, request,
                                                                        validate_packet):
        packet = self.packet()
        validate_packet.return_value = packet
        request.side_effect = audit.RuntimeBlocked("provider timeout fixture")

        result = audit.run_audit(".", packet, environ=self.environ())

        self.assertEqual(result["status"], "UNAVAILABLE")
        self.assertFalse(result["live_verified"])
        request.assert_called_once()
        self.assertEqual(request.call_args.kwargs["timeout"],
                         audit.A6_PROVIDER_TIMEOUT_SECONDS)


if __name__ == "__main__":
    unittest.main()
