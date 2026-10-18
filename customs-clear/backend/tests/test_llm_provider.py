"""Порядок LLM-провайдеров: Anthropic primary, Gemini fallback."""

from __future__ import annotations

import json
import os
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from loguru import logger

from app.services.claude_service import (
    _choose_provider,
    classify_hs_code,
    complete_text,
    llm_provider_chain,
)


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


class CompleteTextProviderChainTests(unittest.IsolatedAsyncioTestCase):
    async def test_complete_text_honors_gemini_preference_and_max_tokens(self) -> None:
        gemini = AsyncMock(return_value={"provider": "gemini", "text": " gemini ", "raw": {}})
        anthropic = AsyncMock(return_value={"provider": "anthropic", "text": "anthropic", "raw": {}})

        with (
            patch(
                "app.services.claude_service.llm_provider_chain",
                return_value=[("gemini", "gem-key"), ("anthropic", "ant-key")],
            ),
            patch("app.services.claude_service._call_gemini", gemini),
            patch("app.services.claude_service._call_anthropic", anthropic),
        ):
            result = await complete_text("prompt", system_prompt="system", max_tokens=321)

        self.assertEqual(result, "gemini")
        gemini.assert_awaited_once_with("system", "prompt", "gem-key", max_tokens=321)
        anthropic.assert_not_awaited()

    async def test_complete_text_falls_back_after_bounded_provider_failure(self) -> None:
        gemini = AsyncMock(side_effect=httpx.ConnectError("offline"))
        anthropic = AsyncMock(
            return_value={"provider": "anthropic", "text": "fallback", "raw": {}}
        )

        with (
            patch(
                "app.services.claude_service.llm_provider_chain",
                return_value=[("gemini", "gem-key"), ("anthropic", "ant-key")],
            ),
            patch("app.services.claude_service._call_gemini", gemini),
            patch("app.services.claude_service._call_anthropic", anthropic),
        ):
            result = await complete_text("prompt", max_tokens=512)

        self.assertEqual(result, "fallback")
        gemini.assert_awaited_once_with("Отвечай кратко.", "prompt", "gem-key", max_tokens=512)
        anthropic.assert_awaited_once_with(
            "Отвечай кратко.",
            "prompt",
            "ant-key",
            max_tokens=512,
        )

    async def test_provider_failure_log_does_not_expose_request_url_or_key(self) -> None:
        secret = "gemini-super-secret"
        request_url = f"https://generativelanguage.googleapis.com/v1/models/test?key={secret}"
        request = httpx.Request("POST", request_url)
        response = httpx.Response(503, request=request)
        gemini = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "provider unavailable",
                request=request,
                response=response,
            )
        )
        anthropic = AsyncMock(
            return_value={"provider": "anthropic", "text": "fallback", "raw": {}}
        )
        messages: list[str] = []
        sink_id = logger.add(lambda message: messages.append(str(message)), format="{message}")

        try:
            with (
                patch(
                    "app.services.claude_service.llm_provider_chain",
                    return_value=[("gemini", secret), ("anthropic", "ant-key")],
                ),
                patch("app.services.claude_service._call_gemini", gemini),
                patch("app.services.claude_service._call_anthropic", anthropic),
            ):
                result = await complete_text("prompt")
        finally:
            logger.remove(sink_id)

        logged = "".join(messages)
        self.assertEqual(result, "fallback")
        self.assertIn("HTTPStatusError", logged)
        self.assertIn("AI сервис временно недоступен", logged)
        self.assertNotIn(secret, logged)
        self.assertNotIn(request_url, logged)
        self.assertNotIn("?key=", logged)
        anthropic.assert_awaited_once()

    async def test_complete_text_sanitizes_exhausted_provider_error(self) -> None:
        gemini_secret = "gemini-super-secret"
        anthropic_secret = "anthropic-super-secret"

        def provider_error(provider: str, secret: str) -> httpx.HTTPStatusError:
            request = httpx.Request(
                "POST",
                f"https://{provider}.example.test/messages?key={secret}",
            )
            response = httpx.Response(503, request=request)
            return httpx.HTTPStatusError(
                "provider unavailable",
                request=request,
                response=response,
            )

        gemini = AsyncMock(side_effect=provider_error("gemini", gemini_secret))
        anthropic = AsyncMock(side_effect=provider_error("anthropic", anthropic_secret))
        messages: list[str] = []
        sink_id = logger.add(lambda message: messages.append(str(message)), format="{message}")

        try:
            with (
                patch(
                    "app.services.claude_service.llm_provider_chain",
                    return_value=[
                        ("gemini", gemini_secret),
                        ("anthropic", anthropic_secret),
                    ],
                ),
                patch("app.services.claude_service._call_gemini", gemini),
                patch("app.services.claude_service._call_anthropic", anthropic),
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "^AI сервис временно недоступен$",
                ) as caught:
                    await complete_text("prompt")
                logger.warning(f"Translation failed, using original: {caught.exception}")
        finally:
            logger.remove(sink_id)

        logged = "".join(messages)
        self.assertTrue(caught.exception.__suppress_context__)
        self.assertIsNone(caught.exception.__cause__)
        self.assertIn("Translation failed, using original: AI сервис временно недоступен", logged)
        for sensitive_value in (
            gemini_secret,
            anthropic_secret,
            "gemini.example.test",
            "anthropic.example.test",
            "?key=",
        ):
            self.assertNotIn(sensitive_value, logged)
        gemini.assert_awaited_once()
        anthropic.assert_awaited_once()

    async def test_complete_text_falls_back_after_empty_provider_result(self) -> None:
        gemini = AsyncMock(return_value={"provider": "gemini", "text": "", "raw": {}})
        anthropic = AsyncMock(
            return_value={"provider": "anthropic", "text": "fallback", "raw": {}}
        )

        with (
            patch(
                "app.services.claude_service.llm_provider_chain",
                return_value=[("gemini", "gem-key"), ("anthropic", "ant-key")],
            ),
            patch("app.services.claude_service._call_gemini", gemini),
            patch("app.services.claude_service._call_anthropic", anthropic),
        ):
            result = await complete_text("prompt")

        self.assertEqual(result, "fallback")
        anthropic.assert_awaited_once()

    async def test_complete_text_does_not_swallow_unrelated_type_error(self) -> None:
        gemini = AsyncMock(side_effect=TypeError("programming defect"))
        anthropic = AsyncMock(
            return_value={"provider": "anthropic", "text": "must not run", "raw": {}}
        )

        with (
            patch(
                "app.services.claude_service.llm_provider_chain",
                return_value=[("gemini", "gem-key"), ("anthropic", "ant-key")],
            ),
            patch("app.services.claude_service._call_gemini", gemini),
            patch("app.services.claude_service._call_anthropic", anthropic),
        ):
            with self.assertRaisesRegex(TypeError, "programming defect"):
                await complete_text("prompt")

        anthropic.assert_not_awaited()


class ClassifyProviderFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_exhausted_invalid_json_is_fail_closed_without_sensitive_leakage(
        self,
    ) -> None:
        anthropic_secret = "anthropic-classify-secret"
        gemini_secret = "gemini-classify-secret"
        anthropic_fragment = "anthropic-raw-fragment"
        gemini_fragment = "gemini-raw-fragment"
        anthropic = AsyncMock(
            side_effect=json.JSONDecodeError(
                "invalid provider JSON",
                anthropic_fragment,
                0,
            )
        )
        gemini = AsyncMock(
            side_effect=json.JSONDecodeError(
                "invalid provider JSON",
                gemini_fragment,
                0,
            )
        )
        messages: list[str] = []
        sink_id = logger.add(lambda message: messages.append(str(message)), format="{message}")

        try:
            with (
                patch(
                    "app.services.claude_service.llm_provider_chain",
                    return_value=[
                        ("anthropic", anthropic_secret),
                        ("gemini", gemini_secret),
                    ],
                ),
                patch("app.services.claude_service._call_anthropic", anthropic),
                patch("app.services.claude_service._call_gemini", gemini),
            ):
                result = await classify_hs_code("насос", use_journal_hints=False)
        finally:
            logger.remove(sink_id)

        logged = "".join(messages)
        serialized = json.dumps(result, ensure_ascii=False)
        self.assertEqual(
            result,
            {
                "status": "ERROR",
                "error_code": "llm_unavailable",
                "query": "насос",
                "results": [],
                "note": "AI сервис временно недоступен",
            },
        )
        self.assertIn("JSONDecodeError", logged)
        self.assertIn("AI сервис временно недоступен", logged)
        for sensitive_value in (
            anthropic_secret,
            gemini_secret,
            anthropic_fragment,
            gemini_fragment,
            "?key=",
        ):
            self.assertNotIn(sensitive_value, logged)
            self.assertNotIn(sensitive_value, serialized)
        anthropic.assert_awaited_once()
        gemini.assert_awaited_once()

    async def test_classify_does_not_swallow_programming_errors(self) -> None:
        for error in (
            TypeError("type programming defect"),
            ValueError("value programming defect"),
            AttributeError("attribute programming defect"),
        ):
            with self.subTest(error_type=type(error).__name__):
                call = AsyncMock(side_effect=error)
                with (
                    patch(
                        "app.services.claude_service._choose_provider",
                        return_value=("anthropic", "ant-key"),
                    ),
                    patch("app.services.claude_service._ask_llm", call),
                ):
                    with self.assertRaises(type(error)) as caught:
                        await classify_hs_code("насос", use_journal_hints=False)

                self.assertEqual(str(caught.exception), str(error))
                call.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
