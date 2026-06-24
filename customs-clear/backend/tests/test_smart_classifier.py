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
            patch.object(clf, "_translate_if_needed", new_callable=AsyncMock, return_value="двигатель 380V"),
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


if __name__ == "__main__":
    unittest.main()
