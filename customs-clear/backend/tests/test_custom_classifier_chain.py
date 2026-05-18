"""Цепочка ONNX → HTTP в call_custom_classifier."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from app.services import custom_classifier_service as ccs


def test_call_custom_classifier_returns_onnx_without_http() -> None:
    async def _run() -> None:
        with patch.object(ccs, "_call_onnx_classifier", new_callable=AsyncMock) as mo:
            mo.return_value = {
                "status": "OK",
                "classifier_source": "onnx_local",
                "results": [{"code": "8509400000"}],
            }
            with patch("app.services.custom_classifier_service.httpx.AsyncClient") as hc:
                out = await ccs.call_custom_classifier("электрический чайник для кухни")
                assert out is not None
                assert out.get("classifier_source") == "onnx_local"
                hc.assert_not_called()

    asyncio.run(_run())
