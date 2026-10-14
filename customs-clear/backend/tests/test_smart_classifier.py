"""Unit-тесты SmartClassifier (без реальных вызовов LLM/Vision)."""
from __future__ import annotations

import base64
import socket
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from app.services.smart_classifier import (
    ClassifyResult,
    SmartClassifier,
    _fetch_image_as_base64,
    _normalize_image_base64,
    _validate_public_image_url,
)

_TEST_IMAGE_BYTES = {
    "image/jpeg": b"\xff\xd8\xff",
    "image/png": b"\x89PNG\r\n\x1a\n",
    "image/gif": b"GIF89a",
    "image/webp": b"RIFF\x00\x00\x00\x00WEBP",
}
_TEST_IMAGE_B64 = {
    media_type: base64.standard_b64encode(data).decode("ascii")
    for media_type, data in _TEST_IMAGE_BYTES.items()
}


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


class SmartClassifierImageUrlSafetyTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _dns_answer(address: str) -> tuple[int, int, int, str, tuple[str, int]]:
        family = socket.AF_INET6 if ":" in address else socket.AF_INET
        return (family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, 443))

    @staticmethod
    def _install_stream_response(client_cls: MagicMock, response: object) -> tuple[MagicMock, MagicMock]:
        client = client_cls.return_value.__aenter__.return_value
        client.stream = MagicMock()
        stream_context = MagicMock()
        client.stream.return_value = stream_context
        stream_context.__aenter__.return_value = response
        return client, stream_context

    async def test_safe_public_host_is_accepted(self) -> None:
        with patch(
            "app.services.smart_classifier.socket.getaddrinfo",
            return_value=[self._dns_answer("93.184.216.34")],
        ) as resolver:
            await _validate_public_image_url("https://images.example.test/photo.jpg")

        resolver.assert_called_once_with(
            "images.example.test",
            443,
            type=socket.SOCK_STREAM,
        )

    async def test_mixed_public_and_private_dns_answers_are_rejected(self) -> None:
        with patch(
            "app.services.smart_classifier.socket.getaddrinfo",
            return_value=[
                self._dns_answer("93.184.216.34"),
                self._dns_answer("127.0.0.1"),
            ],
        ):
            with self.assertRaisesRegex(ValueError, "non-public"):
                await _validate_public_image_url("https://images.example.test/photo.jpg")

    async def test_ipv6_local_and_special_literals_are_rejected_without_dns(self) -> None:
        urls = (
            "http://[::1]/image.jpg",
            "http://[fe80::1]/image.jpg",
            "http://[fc00::1]/image.jpg",
            "http://[::]/image.jpg",
            "http://[ff02::1]/image.jpg",
            "http://[::ffff:127.0.0.1]/image.jpg",
        )
        with patch("app.services.smart_classifier.socket.getaddrinfo") as resolver:
            for url in urls:
                with self.subTest(url=url), self.assertRaises(ValueError):
                    await _validate_public_image_url(url)
        resolver.assert_not_called()

    async def test_credentials_localhost_and_encoded_edge_hosts_are_rejected(self) -> None:
        urls = (
            "https://user:password@images.example.test/photo.jpg",
            "https://localhost/photo.jpg",
            "https://LOCALHOST./photo.jpg",
            "http://%31%32%37.0.0.1/photo.jpg",
            "http://[fe80::1%25eth0]/photo.jpg",
            "https://images.example.test\\@127.0.0.1/photo.jpg",
            "https://images.example.test:99999/photo.jpg",
            "file:///etc/passwd",
            "https:///hostless.jpg",
            "https://images.example.test/has a space.jpg",
        )
        with patch("app.services.smart_classifier.socket.getaddrinfo") as resolver:
            for url in urls:
                with self.subTest(url=url), self.assertRaises(ValueError):
                    await _validate_public_image_url(url)
        resolver.assert_not_called()

    async def test_redirect_to_private_address_is_blocked_before_second_request(self) -> None:
        first_url = "https://images.example.test/photo.jpg"
        redirect = httpx.Response(
            302,
            headers={"location": "http://169.254.169.254/latest/meta-data"},
            request=httpx.Request("GET", first_url),
        )
        with (
            patch(
                "app.services.smart_classifier.socket.getaddrinfo",
                return_value=[self._dns_answer("93.184.216.34")],
            ),
            patch("app.services.smart_classifier.httpx.AsyncClient") as client_cls,
        ):
            client, stream_context = self._install_stream_response(client_cls, redirect)
            with self.assertRaisesRegex(ValueError, "non-public"):
                await _fetch_image_as_base64(first_url)

        client.stream.assert_called_once_with(
            "GET",
            "https://93.184.216.34/photo.jpg",
            headers={"Host": "images.example.test"},
            extensions={"sni_hostname": "images.example.test"},
        )
        stream_context.__aexit__.assert_awaited_once()
        self.assertFalse(client_cls.call_args.kwargs["follow_redirects"])
        self.assertFalse(client_cls.call_args.kwargs["trust_env"])

    async def test_safe_public_image_is_fetched_and_encoded(self) -> None:
        url = "https://images.example.test/photo.jpg"
        image_bytes = _TEST_IMAGE_BYTES["image/png"]
        response = httpx.Response(
            200,
            headers={"content-type": "image/png; charset=binary"},
            content=image_bytes,
            request=httpx.Request("GET", url),
        )
        with (
            patch(
                "app.services.smart_classifier.socket.getaddrinfo",
                return_value=[self._dns_answer("93.184.216.34")],
            ),
            patch("app.services.smart_classifier.httpx.AsyncClient") as client_cls,
        ):
            client, stream_context = self._install_stream_response(client_cls, response)
            encoded, media_type = await _fetch_image_as_base64(url)

        self.assertEqual(encoded, base64.standard_b64encode(image_bytes).decode("ascii"))
        self.assertEqual(media_type, "image/png")
        client.stream.assert_called_once_with(
            "GET",
            "https://93.184.216.34/photo.jpg",
            headers={"Host": "images.example.test"},
            extensions={"sni_hostname": "images.example.test"},
        )
        stream_context.__aexit__.assert_awaited_once()

    async def test_remote_supported_raster_types_preserve_type_and_data(self) -> None:
        url = "https://images.example.test/photo"
        for media_type, image_bytes in _TEST_IMAGE_BYTES.items():
            response = httpx.Response(
                200,
                headers={"content-type": f"{media_type.upper()}; charset=binary"},
                content=image_bytes,
                request=httpx.Request("GET", url),
            )
            with self.subTest(media_type=media_type):
                with (
                    patch(
                        "app.services.smart_classifier.socket.getaddrinfo",
                        return_value=[self._dns_answer("93.184.216.34")],
                    ),
                    patch("app.services.smart_classifier.httpx.AsyncClient") as client_cls,
                ):
                    _client, stream_context = self._install_stream_response(client_cls, response)
                    encoded, normalized_type = await _fetch_image_as_base64(url)

                self.assertEqual(encoded, base64.standard_b64encode(image_bytes).decode("ascii"))
                self.assertEqual(normalized_type, media_type)
                stream_context.__aexit__.assert_awaited_once()

    async def test_remote_non_raster_unsupported_and_mismatched_bytes_are_rejected(self) -> None:
        url = "https://images.example.test/photo"
        cases = (
            ("image/png", b"<html></html>"),
            ("image/svg+xml", b"<svg></svg>"),
            ("image/png", _TEST_IMAGE_BYTES["image/jpeg"]),
        )
        for content_type, image_bytes in cases:
            response = httpx.Response(
                200,
                headers={"content-type": content_type},
                content=image_bytes,
                request=httpx.Request("GET", url),
            )
            with self.subTest(content_type=content_type, image_bytes=image_bytes):
                with (
                    patch(
                        "app.services.smart_classifier.socket.getaddrinfo",
                        return_value=[self._dns_answer("93.184.216.34")],
                    ),
                    patch("app.services.smart_classifier.httpx.AsyncClient") as client_cls,
                ):
                    _client, stream_context = self._install_stream_response(client_cls, response)
                    with self.assertRaises(ValueError):
                        await _fetch_image_as_base64(url)

                stream_context.__aexit__.assert_awaited_once()

    async def test_remote_invalid_image_bytes_never_reach_provider(self) -> None:
        url = "https://images.example.test/photo.png"
        response = httpx.Response(
            200,
            headers={"content-type": "image/png"},
            content=b"<html></html>",
            request=httpx.Request("GET", url),
        )
        clf = SmartClassifier()
        with (
            patch(
                "app.services.smart_classifier.socket.getaddrinfo",
                return_value=[self._dns_answer("93.184.216.34")],
            ),
            patch("app.services.smart_classifier.httpx.AsyncClient") as client_cls,
            patch("app.services.smart_classifier._anthropic_key_env", return_value="test-key"),
            patch(
                "app.services.smart_classifier.anthropic_messages_request",
                new_callable=AsyncMock,
            ) as provider,
        ):
            _client, stream_context = self._install_stream_response(client_cls, response)
            with self.assertRaisesRegex(ValueError, "fetched safely"):
                await clf._analyze_image(None, url, "товар")

        provider.assert_not_awaited()
        stream_context.__aexit__.assert_awaited_once()

    async def test_non_image_content_type_is_rejected_and_stream_is_closed(self) -> None:
        url = "https://images.example.test/not-an-image"
        response = httpx.Response(
            200,
            headers={"content-type": "text/plain"},
            content=b"not an image",
            request=httpx.Request("GET", url),
        )
        with (
            patch(
                "app.services.smart_classifier.socket.getaddrinfo",
                return_value=[self._dns_answer("93.184.216.34")],
            ),
            patch("app.services.smart_classifier.httpx.AsyncClient") as client_cls,
        ):
            _client, stream_context = self._install_stream_response(client_cls, response)
            with self.assertRaisesRegex(ValueError, "content type"):
                await _fetch_image_as_base64(url)

        stream_context.__aexit__.assert_awaited_once()

    async def test_missing_image_content_type_is_rejected_and_stream_is_closed(self) -> None:
        url = "https://images.example.test/no-content-type"
        response = httpx.Response(
            200,
            content=b"untyped bytes",
            request=httpx.Request("GET", url),
        )
        with (
            patch(
                "app.services.smart_classifier.socket.getaddrinfo",
                return_value=[self._dns_answer("93.184.216.34")],
            ),
            patch("app.services.smart_classifier.httpx.AsyncClient") as client_cls,
        ):
            _client, stream_context = self._install_stream_response(client_cls, response)
            with self.assertRaisesRegex(ValueError, "content type"):
                await _fetch_image_as_base64(url)

        stream_context.__aexit__.assert_awaited_once()

    async def test_declared_oversize_image_is_rejected_before_streaming(self) -> None:
        url = "https://images.example.test/large.jpg"
        response = MagicMock()
        response.status_code = 200
        response.headers = {
            "content-type": "image/jpeg",
            "content-length": str(10 * 1024 * 1024 + 1),
        }
        response.raise_for_status = MagicMock()
        response.aiter_bytes = MagicMock()
        with (
            patch(
                "app.services.smart_classifier.socket.getaddrinfo",
                return_value=[self._dns_answer("93.184.216.34")],
            ),
            patch("app.services.smart_classifier.httpx.AsyncClient") as client_cls,
        ):
            _client, stream_context = self._install_stream_response(client_cls, response)
            with self.assertRaisesRegex(ValueError, "maximum allowed size"):
                await _fetch_image_as_base64(url)

        response.aiter_bytes.assert_not_called()
        stream_context.__aexit__.assert_awaited_once()

    async def test_chunked_oversize_image_is_rejected_and_stream_is_closed(self) -> None:
        url = "https://images.example.test/chunked.jpg"
        response = MagicMock()
        response.status_code = 200
        response.headers = {"content-type": "image/jpeg"}
        response.raise_for_status = MagicMock()

        async def oversized_chunks():
            yield b"a" * (10 * 1024 * 1024)
            yield b"b"

        response.aiter_bytes = MagicMock(side_effect=oversized_chunks)
        with (
            patch(
                "app.services.smart_classifier.socket.getaddrinfo",
                return_value=[self._dns_answer("93.184.216.34")],
            ),
            patch("app.services.smart_classifier.httpx.AsyncClient") as client_cls,
        ):
            _client, stream_context = self._install_stream_response(client_cls, response)
            with self.assertRaisesRegex(ValueError, "maximum allowed size"):
                await _fetch_image_as_base64(url)

        stream_context.__aexit__.assert_awaited_once()

    async def test_fetch_failure_never_forwards_untrusted_url_to_provider(self) -> None:
        clf = SmartClassifier()
        with (
            patch(
                "app.services.smart_classifier._fetch_image_as_base64",
                new_callable=AsyncMock,
                side_effect=ValueError("blocked"),
            ),
            patch("app.services.smart_classifier.anthropic_messages_request", new_callable=AsyncMock) as provider,
            patch("app.services.smart_classifier._ask_llm", new_callable=AsyncMock) as fallback,
        ):
            with self.assertRaisesRegex(ValueError, "fetched safely"):
                await clf._analyze_image(None, "http://127.0.0.1/secret", "товар")

        provider.assert_not_awaited()
        fallback.assert_not_awaited()

    async def test_classify_after_blocked_image_never_includes_url_in_model_prompt(self) -> None:
        clf = SmartClassifier()
        blocked_url = "http://127.0.0.1/secret"
        llm = AsyncMock(
            return_value={
                "text": '{"results":[{"hs_code":"3926909709","recommended":true}]}',
                "provider": "test",
            }
        )
        with (
            patch("app.services.smart_classifier.is_llm_configured", return_value=True),
            patch(
                "app.services.smart_classifier._fetch_image_as_base64",
                new_callable=AsyncMock,
                side_effect=ValueError("blocked"),
            ),
            patch("app.services.smart_classifier._ask_llm", llm),
        ):
            result = await clf.classify(
                description="пластиковая запасная часть",
                image_url=blocked_url,
            )

        self.assertEqual(result.status, "MANUAL_REVIEW")
        self.assertIsNone(result.visual_analysis)
        self.assertTrue(result.extra["manual_review_required"])
        self.assertEqual(result.extra["image_analysis_status"], "unavailable")
        self.assertFalse(result.results[0]["recommended"])
        self.assertTrue(llm.await_count)
        for call in llm.await_args_list:
            self.assertNotIn(blocked_url, repr(call))

    async def test_image_only_blocked_url_returns_error_without_model_call(self) -> None:
        clf = SmartClassifier()
        blocked_url = "http://127.0.0.1/secret"
        with (
            patch("app.services.smart_classifier.is_llm_configured", return_value=True),
            patch(
                "app.services.smart_classifier._fetch_image_as_base64",
                new_callable=AsyncMock,
                side_effect=ValueError("blocked"),
            ),
            patch("app.services.smart_classifier._ask_llm", new_callable=AsyncMock) as llm,
            patch(
                "app.services.smart_classifier.anthropic_messages_request",
                new_callable=AsyncMock,
            ) as provider,
        ):
            result = await clf.classify(description=None, image_url=blocked_url)

        self.assertEqual(result.status, "ERROR")
        self.assertEqual(result.results, [])
        self.assertEqual(result.extra["error_code"], "image_unavailable")
        self.assertTrue(result.extra["manual_review_required"])
        self.assertEqual(result.extra["image_analysis_status"], "unavailable")
        llm.assert_not_awaited()
        provider.assert_not_awaited()

    async def test_image_only_whitespace_url_returns_error_without_model_call(self) -> None:
        clf = SmartClassifier()
        with (
            patch("app.services.smart_classifier.is_llm_configured", return_value=True),
            patch.object(clf, "_analyze_image", new_callable=AsyncMock) as analyze,
            patch("app.services.smart_classifier._ask_llm", new_callable=AsyncMock) as llm,
        ):
            result = await clf.classify(description=None, image_url=" \t\n ")

        self.assertEqual(result.status, "ERROR")
        self.assertEqual(result.results, [])
        self.assertEqual(result.extra["error_code"], "image_unavailable")
        self.assertTrue(result.extra["manual_review_required"])
        self.assertEqual(result.extra["image_analysis_status"], "unavailable")
        analyze.assert_not_awaited()
        llm.assert_not_awaited()

    async def test_whitespace_base64_with_text_cannot_return_recommended_result(self) -> None:
        clf = SmartClassifier()
        llm = AsyncMock(
            return_value={
                "text": '{"results":[{"hs_code":"3926909709","recommended":true}]}',
                "provider": "test",
            }
        )
        with (
            patch("app.services.smart_classifier.is_llm_configured", return_value=True),
            patch.object(clf, "_analyze_image", new_callable=AsyncMock) as analyze,
            patch("app.services.smart_classifier._ask_llm", llm),
        ):
            result = await clf.classify(
                description="пластиковая запасная часть",
                image_base64="   ",
            )

        self.assertEqual(result.status, "MANUAL_REVIEW")
        self.assertTrue(result.extra["manual_review_required"])
        self.assertEqual(result.extra["image_analysis_status"], "unavailable")
        self.assertFalse(result.results[0]["recommended"])
        analyze.assert_not_awaited()
        llm.assert_awaited_once()

    async def test_existing_base64_image_path_is_preserved(self) -> None:
        clf = SmartClassifier()
        with (
            patch("app.services.smart_classifier._anthropic_key_env", return_value="test-key"),
            patch(
                "app.services.smart_classifier.anthropic_messages_request",
                new_callable=AsyncMock,
                return_value={"content": [{"type": "text", "text": "изображение товара"}]},
            ) as provider,
        ):
            result = await clf._analyze_image(
                f"data:image/png;base64,{_TEST_IMAGE_B64['image/png']}",
                None,
                "товар",
            )

        self.assertEqual(result, "изображение товара")
        payload = provider.await_args.args[0]
        source = payload["messages"][0]["content"][0]["source"]
        self.assertEqual(
            source,
            {
                "type": "base64",
                "media_type": "image/png",
                "data": _TEST_IMAGE_B64["image/png"],
            },
        )

    async def test_base64_takes_precedence_without_forwarding_secondary_url(self) -> None:
        clf = SmartClassifier()
        secondary_url = "http://127.0.0.1/secret"
        with (
            patch("app.services.smart_classifier._anthropic_key_env", return_value="test-key"),
            patch("app.services.smart_classifier._fetch_image_as_base64", new_callable=AsyncMock) as fetch,
            patch(
                "app.services.smart_classifier.anthropic_messages_request",
                new_callable=AsyncMock,
                return_value={"content": [{"type": "text", "text": "изображение товара"}]},
            ) as provider,
            patch("app.services.smart_classifier._ask_llm", new_callable=AsyncMock) as text_only,
        ):
            result = await clf._analyze_image(
                f"data:image/png;base64,{_TEST_IMAGE_B64['image/png']}",
                secondary_url,
                "товар",
            )

        self.assertEqual(result, "изображение товара")
        fetch.assert_not_awaited()
        provider.assert_awaited_once()
        self.assertNotIn(secondary_url, repr(provider.await_args))
        text_only.assert_not_awaited()

    async def test_safe_url_is_forwarded_only_as_downloaded_base64(self) -> None:
        clf = SmartClassifier()
        image_url = "https://images.example.test/photo.jpg"
        with (
            patch("app.services.smart_classifier._anthropic_key_env", return_value="test-key"),
            patch(
                "app.services.smart_classifier._fetch_image_as_base64",
                new_callable=AsyncMock,
                return_value=(_TEST_IMAGE_B64["image/png"], "image/png"),
            ) as fetch,
            patch(
                "app.services.smart_classifier.anthropic_messages_request",
                new_callable=AsyncMock,
                return_value={"content": [{"type": "text", "text": "изображение товара"}]},
            ) as provider,
            patch("app.services.smart_classifier._ask_llm", new_callable=AsyncMock) as text_only,
        ):
            result = await clf._analyze_image(None, image_url, "товар")

        self.assertEqual(result, "изображение товара")
        fetch.assert_awaited_once_with(image_url)
        provider.assert_awaited_once()
        self.assertNotIn(image_url, repr(provider.await_args))
        source = provider.await_args.args[0]["messages"][0]["content"][0]["source"]
        self.assertEqual(
            source,
            {
                "type": "base64",
                "media_type": "image/png",
                "data": _TEST_IMAGE_B64["image/png"],
            },
        )
        text_only.assert_not_awaited()

    async def test_gemini_only_image_request_does_not_invent_visual_context(self) -> None:
        clf = SmartClassifier()
        with (
            patch("app.services.smart_classifier.is_llm_configured", return_value=True),
            patch("app.services.smart_classifier._anthropic_key_env", return_value=None),
            patch("app.services.smart_classifier._ask_llm", new_callable=AsyncMock) as text_only,
        ):
            result = await clf.classify(
                description=None,
                image_base64=f"data:image/png;base64,{_TEST_IMAGE_B64['image/png']}",
            )

        self.assertEqual(result.status, "ERROR")
        self.assertEqual(result.results, [])
        self.assertEqual(result.extra["error_code"], "image_unavailable")
        self.assertEqual(result.extra["image_analysis_status"], "unavailable")
        text_only.assert_not_awaited()


class SmartClassifierBase64SafetyTests(unittest.IsolatedAsyncioTestCase):
    def test_supported_data_uri_raster_types_are_normalized(self) -> None:
        for media_type in ("image/jpeg", "image/png", "image/gif", "image/webp"):
            with self.subTest(media_type=media_type):
                encoded = _TEST_IMAGE_B64[media_type]
                payload, normalized_type = _normalize_image_base64(
                    f"data:{media_type};base64,{encoded}"
                )
                self.assertEqual(payload, encoded)
                self.assertEqual(normalized_type, media_type)

    def test_bare_base64_infers_supported_raster_type(self) -> None:
        for media_type in ("image/jpeg", "image/png", "image/gif", "image/webp"):
            with self.subTest(media_type=media_type):
                encoded = _TEST_IMAGE_B64[media_type]
                self.assertEqual(_normalize_image_base64(encoded), (encoded, media_type))

    def test_active_or_unsupported_media_types_are_rejected(self) -> None:
        values = (
            "data:text/html;base64,PGh0bWw+PC9odG1sPg==",
            "data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=",
            "data:application/octet-stream;base64,YWJj",
        )
        for value in values:
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "unsupported"):
                _normalize_image_base64(value)

    def test_malformed_data_uri_and_invalid_base64_are_rejected(self) -> None:
        values = (
            "data:image/png,YWJj",
            "data:image/png;charset=utf-8;base64,YWJj",
            "data:image/png;base64,",
            "data:image/png;base64,%%%",
            "data:image/png;base64,YW Jj",
            "data:image/png;base64,YQ=",
            "%%%",
            "",
        )
        for value in values:
            with self.subTest(value=value), self.assertRaises(ValueError):
                _normalize_image_base64(value)

    def test_decoded_size_limit_is_enforced(self) -> None:
        encoded = _TEST_IMAGE_B64["image/jpeg"]
        with patch("app.services.smart_classifier._MAX_IMAGE_BYTES", 2):
            with self.assertRaisesRegex(ValueError, "maximum allowed size"):
                _normalize_image_base64(encoded)

    def test_non_image_and_mismatched_declared_media_are_rejected(self) -> None:
        html_as_bare_jpeg = base64.standard_b64encode(b"<html></html>").decode("ascii")
        svg_as_png = base64.standard_b64encode(b"<svg></svg>").decode("ascii")
        jpeg_as_png = _TEST_IMAGE_B64["image/jpeg"]
        values = (
            html_as_bare_jpeg,
            f"data:image/png;base64,{html_as_bare_jpeg}",
            f"data:image/png;base64,{svg_as_png}",
            f"data:image/png;base64,{jpeg_as_png}",
        )
        for value in values:
            with self.subTest(value=value), self.assertRaises(ValueError):
                _normalize_image_base64(value)

    async def test_invalid_image_only_base64_fails_before_any_provider_or_model(self) -> None:
        clf = SmartClassifier()
        with (
            patch("app.services.smart_classifier.is_llm_configured", return_value=True),
            patch(
                "app.services.smart_classifier.anthropic_messages_request",
                new_callable=AsyncMock,
            ) as provider,
            patch("app.services.smart_classifier._ask_llm", new_callable=AsyncMock) as model,
        ):
            result = await clf.classify(
                description=None,
                image_base64="data:text/html;base64,PGh0bWw+PC9odG1sPg==",
            )

        self.assertEqual(result.status, "ERROR")
        self.assertEqual(result.results, [])
        self.assertEqual(result.extra["error_code"], "image_unavailable")
        self.assertEqual(result.extra["image_analysis_status"], "unavailable")
        provider.assert_not_awaited()
        model.assert_not_awaited()

    async def test_invalid_base64_with_text_is_manual_review_and_never_reaches_vision(self) -> None:
        clf = SmartClassifier()
        invalid_payload = "data:image/png;base64,%%%"
        model = AsyncMock(
            return_value={
                "text": '{"results":[{"hs_code":"3926909709","recommended":true}]}',
                "provider": "test",
            }
        )
        with (
            patch("app.services.smart_classifier.is_llm_configured", return_value=True),
            patch(
                "app.services.smart_classifier.anthropic_messages_request",
                new_callable=AsyncMock,
            ) as provider,
            patch("app.services.smart_classifier._ask_llm", model),
        ):
            result = await clf.classify(
                description="пластиковая запасная часть",
                image_base64=invalid_payload,
            )

        self.assertEqual(result.status, "MANUAL_REVIEW")
        self.assertEqual(result.extra["image_analysis_status"], "unavailable")
        self.assertTrue(result.extra["manual_review_required"])
        self.assertFalse(result.results[0]["recommended"])
        provider.assert_not_awaited()
        for call in model.await_args_list:
            self.assertNotIn(invalid_payload, repr(call))

    async def test_invalid_group_image_marks_fresh_and_cached_classification_unavailable(self) -> None:
        SmartClassifier.clear_packing_caches()
        clf = SmartClassifier()
        group_key = ("пластиковая запасная часть", "A-1")
        raw_json = '{"results":[{"hs_code":"3926909709","recommended":true}]}'
        try:
            with patch(
                "app.services.smart_classifier.anthropic_messages_request",
                new_callable=AsyncMock,
            ) as provider:
                visual = await clf.get_or_analyze_vision(
                    group_key,
                    image_base64="data:image/png;base64,%%%",
                    description=group_key[0],
                )

            self.assertIsNone(visual)
            provider.assert_not_awaited()

            with patch(
                "app.services.smart_classifier._ask_llm",
                new_callable=AsyncMock,
                return_value={"text": raw_json, "provider": "test"},
            ) as model:
                fresh = await clf.get_or_classify_group(
                    group_key,
                    description=group_key[0],
                    translated=group_key[0],
                    visual_context=visual,
                    article=group_key[1],
                )
                cached = await clf.get_or_classify_group(
                    group_key,
                    description=group_key[0],
                    translated=group_key[0],
                    visual_context=visual,
                    article=group_key[1],
                )

            model.assert_awaited_once()
            for result in (fresh, cached):
                self.assertEqual(result.status, "MANUAL_REVIEW")
                self.assertTrue(result.extra["manual_review_required"])
                self.assertEqual(result.extra["image_analysis_status"], "unavailable")
                self.assertFalse(result.results[0]["recommended"])
        finally:
            SmartClassifier.clear_packing_caches()

    async def test_group_image_is_validated_before_vision_cache_hit(self) -> None:
        SmartClassifier.clear_packing_caches()
        clf = SmartClassifier()
        group_key = ("пластиковая запасная часть", "A-2")
        try:
            with (
                patch("app.services.smart_classifier._anthropic_key_env", return_value="test-key"),
                patch(
                    "app.services.smart_classifier.anthropic_messages_request",
                    new_callable=AsyncMock,
                    return_value={"content": [{"type": "text", "text": "vision"}]},
                ) as provider,
            ):
                valid = await clf.get_or_analyze_vision(
                    group_key,
                    image_base64=_TEST_IMAGE_B64["image/png"],
                    description=group_key[0],
                )
                invalid = await clf.get_or_analyze_vision(
                    group_key,
                    image_base64="data:image/png;base64,%%%",
                    description=group_key[0],
                )

            self.assertEqual(valid, "vision")
            self.assertIsNone(invalid)
            provider.assert_awaited_once()
        finally:
            SmartClassifier.clear_packing_caches()

    async def test_valid_cached_group_image_stays_normal_and_clear_drops_failure_marker(self) -> None:
        SmartClassifier.clear_packing_caches()
        clf = SmartClassifier()
        valid_key = ("пластиковая запасная часть", "A-3")
        failed_key = ("пластиковая запасная часть", "A-4")
        raw_json = '{"results":[{"hs_code":"3926909709","recommended":true}]}'
        try:
            with (
                patch("app.services.smart_classifier._anthropic_key_env", return_value="test-key"),
                patch(
                    "app.services.smart_classifier.anthropic_messages_request",
                    new_callable=AsyncMock,
                    return_value={"content": [{"type": "text", "text": "vision"}]},
                ) as provider,
            ):
                first = await clf.get_or_analyze_vision(
                    valid_key,
                    image_base64=_TEST_IMAGE_B64["image/gif"],
                    description=valid_key[0],
                )
                second = await clf.get_or_analyze_vision(
                    valid_key,
                    image_base64=_TEST_IMAGE_B64["image/gif"],
                    description=valid_key[0],
                )

            self.assertEqual(first, "vision")
            self.assertEqual(second, "vision")
            provider.assert_awaited_once()

            with patch(
                "app.services.smart_classifier._ask_llm",
                new_callable=AsyncMock,
                return_value={"text": raw_json, "provider": "test"},
            ):
                valid_result = await clf.get_or_classify_group(
                    valid_key,
                    description=valid_key[0],
                    translated=valid_key[0],
                    visual_context=second,
                    article=valid_key[1],
                )
            self.assertEqual(valid_result.status, "OK")
            self.assertNotEqual(valid_result.results[0].get("recommended"), False)
            self.assertNotIn("image_analysis_status", valid_result.extra)

            await clf.get_or_analyze_vision(
                failed_key,
                image_base64="data:image/png;base64,%%%",
                description=failed_key[0],
            )
            SmartClassifier.clear_packing_caches()

            with patch(
                "app.services.smart_classifier._ask_llm",
                new_callable=AsyncMock,
                return_value={"text": raw_json, "provider": "test"},
            ):
                after_clear = await clf.get_or_classify_group(
                    failed_key,
                    description=failed_key[0],
                    translated=failed_key[0],
                    visual_context=None,
                    article=failed_key[1],
                )
            self.assertEqual(after_clear.status, "OK")
            self.assertNotEqual(after_clear.results[0].get("recommended"), False)
            self.assertNotIn("image_analysis_status", after_clear.extra)
        finally:
            SmartClassifier.clear_packing_caches()


if __name__ == "__main__":
    unittest.main()
