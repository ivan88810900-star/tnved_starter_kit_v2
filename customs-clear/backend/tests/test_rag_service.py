"""RAG: токенный поиск по файлам."""
from __future__ import annotations

import asyncio
import importlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class RagRetrieveTests(unittest.TestCase):
    def test_empty_dir_returns_empty(self):
        async def _run():
            with tempfile.TemporaryDirectory() as d:
                with patch.dict("os.environ", {"RAG_DOCS_DIR": d}):
                    import app.services.rag_service as rs

                    importlib.reload(rs)
                    return await rs.retrieve_snippets("любой запрос", limit=3)

        out = asyncio.run(_run())
        self.assertEqual(out, [])

    def test_token_match_finds_snippet(self):
        async def _run():
            with tempfile.TemporaryDirectory() as d:
                p = Path(d) / "hint.md"
                p.write_text(
                    "Для декларанта: при импорте пылесосов учитывайте ТР ТС 004/2011 о безопасности.",
                    encoding="utf-8",
                )
                with patch.dict("os.environ", {"RAG_DOCS_DIR": d}):
                    import app.services.rag_service as rs

                    importlib.reload(rs)
                    return await rs.retrieve_snippets("пылесос импорт декларант", limit=2)

        out = asyncio.run(_run())
        self.assertTrue(len(out) >= 1)
        self.assertIn("пылесос", (out[0].get("snippet") or "").lower())


if __name__ == "__main__":
    unittest.main()
