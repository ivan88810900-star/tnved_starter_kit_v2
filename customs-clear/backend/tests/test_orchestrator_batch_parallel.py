"""Порядок результатов batch при параллельном выполнении."""
from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from app.services.assistant_orchestrator import run_copilot_batch


class BatchParallelOrderTests(unittest.IsolatedAsyncioTestCase):
    async def test_order_matches_input_despite_finish_times(self):
        async def slow_pipeline(*, description: str, **kwargs):
            if description == "second":
                await asyncio.sleep(0.08)
            else:
                await asyncio.sleep(0.001)
            return {
                "effective_hs_code": description[:4] if description else "",
                "pipeline": [],
                "classification": None,
                "non_tariff": {"status": "OK", "hs_code": ""},
                "payment": None,
                "description": description,
                "country": kwargs.get("country"),
                "permits_input": [],
                "permits_verification": None,
            }

        items = [
            {"description": "first", "hs_code": "1111111111", "country": "CN", "permits": []},
            {"description": "second", "hs_code": "2222222222", "country": "CN", "permits": []},
            {"description": "third", "hs_code": "3333333333", "country": "CN", "permits": []},
        ]

        with patch(
            "app.services.assistant_orchestrator.run_copilot_pipeline",
            new_callable=AsyncMock,
            side_effect=slow_pipeline,
        ):
            out = await run_copilot_batch(items, run_registry_verify=False)

        bundles = out["bundles"]
        self.assertEqual(len(bundles), 3)
        self.assertEqual(bundles[0]["description"], "first")
        self.assertEqual(bundles[1]["description"], "second")
        self.assertEqual(bundles[2]["description"], "third")


if __name__ == "__main__":
    unittest.main()
