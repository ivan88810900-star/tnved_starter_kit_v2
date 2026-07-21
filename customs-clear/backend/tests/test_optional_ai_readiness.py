"""Optional AI readiness remains explicit, aggregate-only and fallback-safe."""

from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock, patch

from app.services.embedding_service import (
    ingest_tnved_embeddings_batch,
    semantic_ingest_enabled,
    semantic_search_enabled,
    semantic_search_tnved,
)
from app.services.optional_ai_readiness import build_optional_ai_readiness_report


class OptionalAiReadinessTests(unittest.IsolatedAsyncioTestCase):
    def test_semantic_read_and_ingest_flags_default_off(self) -> None:
        with patch.dict(
            os.environ,
            {
                "TNVED_SEMANTIC_SEARCH_ENABLED": "0",
                "TNVED_SEMANTIC_INGEST_ENABLED": "0",
            },
            clear=False,
        ):
            self.assertFalse(semantic_search_enabled())
            self.assertFalse(semantic_ingest_enabled())
            with self.assertRaisesRegex(RuntimeError, "semantic_search_disabled"):
                semantic_search_tnved("чайник")
            with self.assertRaisesRegex(RuntimeError, "semantic_ingest_disabled"):
                ingest_tnved_embeddings_batch(limit=1)

    async def test_contract_mode_does_not_call_external_ai(self) -> None:
        with (
            patch(
                "app.services.optional_ai_readiness.embeddings_stats",
                return_value={"search_ready": False, "search_enabled": False},
            ),
            patch("app.services.optional_ai_readiness.llm_provider_chain", return_value=[]),
            patch("app.services.optional_ai_readiness._ask_llm", new=AsyncMock()) as ask,
            patch("app.services.optional_ai_readiness.embed_texts_openai") as embed,
        ):
            report = await build_optional_ai_readiness_report()

        self.assertTrue(report["ok"])
        self.assertFalse(report["external_calls_requested"])
        self.assertFalse(report["secrets_in_report"])
        self.assertTrue(all(report["contracts"].values()))
        ask.assert_not_awaited()
        embed.assert_not_called()

    async def test_live_llm_accepts_only_grounded_synthetic_response(self) -> None:
        response = '{"answer":"Synthetic readiness check passed. [S1]","citation_ids":["S1"]}'
        with (
            patch(
                "app.services.optional_ai_readiness.embeddings_stats",
                return_value={"search_ready": False},
            ),
            patch(
                "app.services.optional_ai_readiness.llm_provider_chain",
                return_value=[("anthropic", "secret-test-key")],
            ),
            patch(
                "app.services.optional_ai_readiness._ask_llm",
                new=AsyncMock(return_value={"provider": "anthropic", "text": response}),
            ),
        ):
            report = await build_optional_ai_readiness_report(live_llm=True)

        self.assertTrue(report["ok"])
        self.assertEqual(report["live_llm"]["provider"], "anthropic")
        self.assertFalse(report["live_llm"]["response_text_stored"])
        self.assertNotIn("secret-test-key", str(report))

    async def test_live_llm_rejects_unknown_citation(self) -> None:
        response = '{"answer":"Unsupported. [S2]","citation_ids":["S2"]}'
        with (
            patch(
                "app.services.optional_ai_readiness.embeddings_stats",
                return_value={"search_ready": False},
            ),
            patch(
                "app.services.optional_ai_readiness.llm_provider_chain",
                return_value=[("gemini", "secret-test-key")],
            ),
            patch(
                "app.services.optional_ai_readiness._ask_llm",
                new=AsyncMock(return_value={"provider": "gemini", "text": response}),
            ),
        ):
            report = await build_optional_ai_readiness_report(live_llm=True)

        self.assertFalse(report["ok"])
        self.assertEqual(report["live_llm"]["reason"], "grounding_contract_failed")


if __name__ == "__main__":
    unittest.main()
