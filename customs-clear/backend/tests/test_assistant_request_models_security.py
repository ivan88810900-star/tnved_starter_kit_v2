"""Pydantic-модели assistant: клиентское поле api_key не сохраняется (extra=ignore)."""
from __future__ import annotations

import unittest

from app.api.assistant import AssistantChatRequest, CopilotBatchRequest, CopilotRequest


class AssistantRequestModelsSecurityTests(unittest.TestCase):
    def test_assistant_chat_request_drops_client_api_key(self) -> None:
        req = AssistantChatRequest.model_validate(
            {
                "message": "привет",
                "history": [{"role": "user", "text": "x"}],
                "api_key": "client-supplied-must-not-appear-in_dump",
            }
        )
        dumped = req.model_dump(mode="json")
        self.assertNotIn("api_key", dumped)

    def test_copilot_request_drops_client_api_key(self) -> None:
        req = CopilotRequest.model_validate(
            {
                "description": "чайник",
                "api_key": "client-supplied-must-not-appear-in_dump",
            }
        )
        self.assertNotIn("api_key", req.model_dump(mode="json"))

    def test_copilot_batch_request_drops_client_api_key(self) -> None:
        req = CopilotBatchRequest.model_validate(
            {
                "items": [{"description": "телефон", "hs_code": ""}],
                "api_key": "client-supplied-must-not-appear-in_dump",
            }
        )
        self.assertNotIn("api_key", req.model_dump(mode="json"))


if __name__ == "__main__":
    unittest.main()
