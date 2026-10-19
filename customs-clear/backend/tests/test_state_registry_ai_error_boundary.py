"""Failure-boundary tests for optional FSS registry AI disambiguation."""

from __future__ import annotations

import builtins
import json
import unittest
from unittest.mock import patch

import httpx
from loguru import logger

from app.models.core import FssNotification
from app.services.state_registry_match import _ai_disambiguate_fss


def _candidates() -> list[FssNotification]:
    return [
        FssNotification(
            id=1,
            number="RU0001",
            name="Маршрутизатор Alpha",
            brand="Example",
            status="active",
        ),
        FssNotification(
            id=2,
            number="RU0002",
            name="Маршрутизатор Beta",
            brand="Example",
            status="active",
        ),
    ]


class RegistryAiErrorBoundaryTests(unittest.TestCase):
    def test_valid_provider_index_selects_requested_candidate(self) -> None:
        rows = _candidates()
        with patch(
            "app.services.invoice_analyzer._gemini_generate",
            return_value='{"best_index": 1}',
        ) as generate:
            result = _ai_disambiguate_fss(rows, product_context="Beta")

        self.assertIs(result, rows[1])
        generate.assert_called_once()

    def test_transport_failure_falls_back_without_logging_sensitive_details(self) -> None:
        rows = _candidates()
        secret = "https://provider.invalid/generate?key=SECRET-REGISTRY-AI"
        error = httpx.HTTPStatusError(
            secret,
            request=httpx.Request("POST", "https://provider.invalid"),
            response=httpx.Response(503),
        )
        messages: list[str] = []
        sink_id = logger.add(
            lambda message: messages.append(str(message)), format="{message}"
        )
        try:
            with patch(
                "app.services.invoice_analyzer._gemini_generate",
                side_effect=error,
            ):
                result = _ai_disambiguate_fss(rows, product_context="Beta")
        finally:
            logger.remove(sink_id)

        logged = "".join(messages)
        self.assertIs(result, rows[0])
        self.assertIn("HTTPStatusError", logged)
        self.assertNotIn(secret, logged)
        self.assertNotIn("SECRET-REGISTRY-AI", logged)
        self.assertNotIn("key=", logged)

    def test_missing_provider_configuration_uses_first_ranked_candidate(self) -> None:
        rows = _candidates()
        messages: list[str] = []
        sink_id = logger.add(
            lambda message: messages.append(str(message)), format="{message}"
        )
        try:
            with patch(
                "app.services.invoice_analyzer._gemini_generate",
                side_effect=RuntimeError("Не задан GEMINI_API_KEY или GOOGLE_API_KEY"),
            ):
                result = _ai_disambiguate_fss(rows, product_context="Beta")
        finally:
            logger.remove(sink_id)

        self.assertIs(result, rows[0])
        self.assertIn("RuntimeError", "".join(messages))

    def test_missing_optional_provider_import_falls_back_with_class_only_log(self) -> None:
        rows = _candidates()
        secret = "missing-module-with-SECRET-REGISTRY-AI"
        real_import = builtins.__import__

        def fail_invoice_analyzer_import(
            name: str,
            globals: dict[str, object] | None = None,
            locals: dict[str, object] | None = None,
            fromlist: tuple[str, ...] = (),
            level: int = 0,
        ) -> object:
            if name == "invoice_analyzer" and level == 1:
                raise ModuleNotFoundError(secret)
            return real_import(name, globals, locals, fromlist, level)

        messages: list[str] = []
        sink_id = logger.add(
            lambda message: messages.append(str(message)), format="{message}"
        )
        try:
            with patch("builtins.__import__", side_effect=fail_invoice_analyzer_import):
                result = _ai_disambiguate_fss(rows, product_context="Beta")
        finally:
            logger.remove(sink_id)

        logged = "".join(messages)
        self.assertIs(result, rows[0])
        self.assertIn("ModuleNotFoundError", logged)
        self.assertNotIn(secret, logged)
        self.assertNotIn("SECRET-REGISTRY-AI", logged)

    def test_malformed_and_out_of_range_output_use_first_ranked_candidate(self) -> None:
        rows = _candidates()
        malformed_secret = "SECRET-MALFORMED-REGISTRY-AI"
        responses = (
            f'{{"best_index": {malformed_secret}}}',
            '{"best_index": null}',
            '{"best_index": 99}',
            "not-json",
            None,
        )
        messages: list[str] = []
        sink_id = logger.add(
            lambda message: messages.append(str(message)), format="{message}"
        )
        try:
            for raw in responses:
                with self.subTest(raw=raw), patch(
                    "app.services.invoice_analyzer._gemini_generate",
                    return_value=raw,
                ):
                    result = _ai_disambiguate_fss(rows, product_context="Beta")
                    self.assertIs(result, rows[0])
        finally:
            logger.remove(sink_id)

        logged = "".join(messages)
        self.assertIn(json.JSONDecodeError.__name__, logged)
        self.assertIn(TypeError.__name__, logged)
        self.assertNotIn(malformed_secret, logged)

    def test_programming_errors_are_not_swallowed(self) -> None:
        rows = _candidates()
        for error in (
            TypeError("type programming defect"),
            ValueError("value programming defect"),
            AttributeError("attribute programming defect"),
            RuntimeError("runtime programming defect"),
        ):
            with self.subTest(error_type=type(error).__name__), patch(
                "app.services.invoice_analyzer._gemini_generate",
                side_effect=error,
            ):
                with self.assertRaises(type(error)):
                    _ai_disambiguate_fss(rows, product_context="Beta")


if __name__ == "__main__":
    unittest.main()
