"""In-memory кэш (Redis в CI может отсутствовать)."""
from __future__ import annotations

import asyncio
import unittest

from app.services.cache_layer import PERMITS_PREFIX, cache_get, cache_set, purge_prefix


class CacheLayerTests(unittest.IsolatedAsyncioTestCase):
    async def test_set_get_purge(self):
        await purge_prefix(PERMITS_PREFIX)
        await cache_set(PERMITS_PREFIX, "k1", {"a": 1}, ttl=60)
        v = await cache_get(PERMITS_PREFIX, "k1")
        self.assertEqual(v, {"a": 1})
        await purge_prefix(PERMITS_PREFIX)
        v2 = await cache_get(PERMITS_PREFIX, "k1")
        self.assertIsNone(v2)


if __name__ == "__main__":
    unittest.main()
