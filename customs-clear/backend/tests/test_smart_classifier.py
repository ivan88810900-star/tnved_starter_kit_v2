"""Unit-тесты SmartClassifier (без реальных вызовов LLM/Vision)."""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from app.services.smart_classifier import ClassifyResult, SmartClassifier


class SmartClassifierNeedsWebSearchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clf = SmartClassifier()

    def test_short_description_triggers_search(self) -> None:
        self.assertTrue(self.clf._needs_web_search("двигатель", None, "", ""))

    def test_equipment_without_digits_triggers_search(self) -> None:
        self.assertTrue(self.clf._needs_web_search("электрический насос", None, "", ""))

    def test_equipment_with_specs_skips_search(self) -> None:
        self.assertFalse(self.clf._needs_web_search("насос 380V 7.5kW", None, "", ""))

    def test_article_and_manufacturer_without_description(self) -> None:
        self.assertTrue(self.clf._needs_web_search("", None, "YL-90L-4", "Dongfa"))


class SmartClassifierTranslateTests(unittest.IsolatedAsyncioTestCase):
    async def test_chinese_triggers_translation(self) -> None:
        clf = SmartClassifier()
        with patch("app.services.smart_classifier.complete_text", new_callable=AsyncMock) as mock_ct:
            mock_ct.return_value = "Электродвигатель трёхфазный 7.5 кВт 380 В"
            out = await clf._translate_if_needed("电动机 三相异步 功率7.5KW 电压380V")
        self.assertIn("Электродвигатель", out)
        mock_ct.assert_awaited_once()

    async def test_russian_skips_translation(self) -> None:
        clf = SmartClassifier()
        with patch("app.services.smart_classifier.complete_text", new_callable=AsyncMock) as mock_ct:
            out = await clf._translate_if_needed("насос центробежный 380V")
        self.assertEqual(out, "насос центробежный 380V")
        mock_ct.assert_not_awaited()


class SmartClassifierClassifyTests(unittest.IsolatedAsyncioTestCase):
    async def test_classify_returns_parsed_results(self) -> None:
        clf = SmartClassifier()
        raw_json = (
            '{"results":[{"hs_code":"8501529000","confidence":0.9,'
            '"description":"Двигатель","rationale":"тест"}]}'
        )
        with (
            patch("app.services.smart_classifier.is_llm_configured", return_value=True),
            patch.object(
                clf,
                "_translate_if_needed",
                new_callable=AsyncMock,
                return_value="электрический двигатель 380V",
            ),
            patch.object(clf, "_analyze_image", new_callable=AsyncMock, return_value=None),
            patch.object(clf, "_search_web", new_callable=AsyncMock, return_value=""),
            patch(
                "app.services.smart_classifier._ask_llm",
                new_callable=AsyncMock,
                return_value={"text": raw_json, "provider": "anthropic"},
            ),
        ):
            result = await clf.classify(description="двигатель 380V")
        self.assertIsInstance(result, ClassifyResult)
        self.assertEqual(result.results[0]["hs_code"], "8501529000")
        self.assertEqual(result.status, "OK")

    async def test_missing_web_result_requires_manual_review(self) -> None:
        clf = SmartClassifier()
        raw_json = (
            '{"results":[{"hs_code":"8501529000","confidence":0.9,'
            '"description":"Двигатель","rationale":"предварительно","recommended":true}]}'
        )
        with (
            patch("app.services.smart_classifier.is_llm_configured", return_value=True),
            patch.object(clf, "_translate_if_needed", new_callable=AsyncMock, return_value="двигатель"),
            patch.object(clf, "_search_web", new_callable=AsyncMock, return_value=""),
            patch(
                "app.services.smart_classifier._ask_llm",
                new_callable=AsyncMock,
                return_value={"text": raw_json, "provider": "anthropic"},
            ),
        ):
            result = await clf.classify(description="двигатель", article="YL-90L-4", manufacturer="Dongfa")

        self.assertEqual(result.status, "MANUAL_REVIEW")
        self.assertTrue(result.extra["manual_review_required"])
        self.assertEqual(result.extra["web_search_status"], "unavailable")
        self.assertFalse(result.web_search_used)
        self.assertNotIn("web_context", result.to_api_dict())
        self.assertFalse(result.results[0]["recommended"])

    async def test_confirmed_web_result_preserves_classification(self) -> None:
        clf = SmartClassifier()
        raw_json = '{"results":[{"hs_code":"8501529000","confidence":0.9,"recommended":true}]}'
        with (
            patch("app.services.smart_classifier.is_llm_configured", return_value=True),
            patch.object(clf, "_translate_if_needed", new_callable=AsyncMock, return_value="двигатель"),
            patch.object(clf, "_search_web", new_callable=AsyncMock, return_value="7,5 кВт; 380 В"),
            patch(
                "app.services.smart_classifier._ask_llm",
                new_callable=AsyncMock,
                return_value={"text": raw_json, "provider": "anthropic"},
            ),
        ):
            result = await clf.classify(description="двигатель", article="YL-90L-4", manufacturer="Dongfa")

        self.assertEqual(result.status, "OK")
        self.assertNotIn("manual_review_required", result.extra)
        self.assertEqual(result.extra["web_search_status"], "confirmed")
        self.assertTrue(result.web_search_used)
        self.assertEqual(result.results[0]["hs_code"], "8501529000")

    async def test_group_classification_missing_web_result_requires_manual_review(self) -> None:
        SmartClassifier.clear_packing_caches()
        clf = SmartClassifier()
        raw_json = '{"results":[{"hs_code":"8501529000","confidence":0.7}]}'
        try:
            with (
                patch.object(clf, "_search_web", new_callable=AsyncMock, return_value=""),
                patch(
                    "app.services.smart_classifier._ask_llm",
                    new_callable=AsyncMock,
                    return_value={"text": raw_json, "provider": "anthropic"},
                ),
            ):
                result = await clf.get_or_classify_group(
                    ("двигатель", "YL-90L-4"),
                    description="двигатель",
                    translated="двигатель",
                    visual_context=None,
                    article="YL-90L-4",
                )

            self.assertEqual(result.status, "MANUAL_REVIEW")
            self.assertTrue(result.extra["manual_review_required"])
            self.assertEqual(result.extra["web_search_status"], "unavailable")
            self.assertFalse(result.results[0]["recommended"])
        finally:
            SmartClassifier.clear_packing_caches()


class SmartClassifierWebSearchTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_web_search_does_not_call_text_completion_fallback(self) -> None:
        clf = SmartClassifier()
        with (
            patch.object(clf, "_claude_web_search", new_callable=AsyncMock, return_value=""),
            patch("app.services.smart_classifier.complete_text", new_callable=AsyncMock) as mock_complete,
        ):
            context = await clf._search_web("двигатель", "YL-90L-4", "Dongfa")

        self.assertEqual(context, "")
        mock_complete.assert_not_awaited()

    async def test_claude_web_search_requires_actual_tool_result(self) -> None:
        clf = SmartClassifier()
        generated_only = {"content": [{"type": "text", "text": "Вероятно, 7,5 кВт"}]}
        with (
            patch("app.services.smart_classifier._anthropic_key_env", return_value="test-key"),
            patch(
                "app.services.smart_classifier.anthropic_messages_request",
                new_callable=AsyncMock,
                return_value=generated_only,
            ),
        ):
            self.assertEqual(await clf._claude_web_search("Dongfa YL-90L-4"), "")

    async def test_claude_web_search_rejects_tool_results_without_valid_http_url(self) -> None:
        clf = SmartClassifier()
        invalid_results = (
            {"type": "web_search_result"},
            {"type": "web_search_result", "url": ""},
            {"type": "web_search_result", "url": "   "},
            {"type": "web_search_result", "url": "ftp://example.test/spec"},
            {"type": "web_search_result", "url": "javascript:alert(1)"},
            {"type": "web_search_result", "url": "https://"},
            {"type": "web_search_result", "url": "https://exa mple.test/spec"},
        )
        for invalid_result in invalid_results:
            response = {
                "content": [
                    {"type": "web_search_tool_result", "content": [invalid_result]},
                    {"type": "text", "text": "Вероятно, мощность 7,5 кВт"},
                ]
            }
            with self.subTest(invalid_result=invalid_result):
                with (
                    patch("app.services.smart_classifier._anthropic_key_env", return_value="test-key"),
                    patch(
                        "app.services.smart_classifier.anthropic_messages_request",
                        new_callable=AsyncMock,
                        return_value=response,
                    ),
                ):
                    self.assertEqual(await clf._claude_web_search("Dongfa YL-90L-4"), "")

    async def test_claude_web_search_accepts_actual_tool_result(self) -> None:
        clf = SmartClassifier()
        response = {
            "content": [
                {
                    "type": "web_search_tool_result",
                    "content": [{"type": "web_search_result", "url": "https://example.test/spec"}],
                },
                {"type": "text", "text": "Мощность 7,5 кВт"},
            ]
        }
        with (
            patch("app.services.smart_classifier._anthropic_key_env", return_value="test-key"),
            patch(
                "app.services.smart_classifier.anthropic_messages_request",
                new_callable=AsyncMock,
                return_value=response,
            ),
        ):
            self.assertEqual(await clf._claude_web_search("Dongfa YL-90L-4"), "Мощность 7,5 кВт")


if __name__ == "__main__":
    unittest.main()
