"""Порядок LLM-провайдеров: Anthropic primary, Gemini fallback."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from app.services.claude_service import _choose_provider, llm_provider_chain


class LlmProviderChainTests(unittest.TestCase):
    def test_anthropic_preferred_by_default(self) -> None:
        with patch.dict(
            os.environ,
            {
                "LLM_PROVIDER": "anthropic",
                "ANTHROPIC_API_KEY": "sk-ant-test",
                "GEMINI_API_KEY": "gem-test",
            },
            clear=False,
        ):
            chain = llm_provider_chain()
            self.assertEqual(chain[0][0], "anthropic")
            self.assertEqual(len(chain), 2)
            provider, _ = _choose_provider()
            self.assertEqual(provider, "anthropic")

    def test_gemini_primary_when_configured(self) -> None:
        with patch.dict(
            os.environ,
            {
                "LLM_PROVIDER": "gemini",
                "ANTHROPIC_API_KEY": "sk-ant-test",
                "GEMINI_API_KEY": "gem-test",
            },
            clear=False,
        ):
            chain = llm_provider_chain()
            self.assertEqual(chain[0][0], "gemini")


if __name__ == "__main__":
    unittest.main()
