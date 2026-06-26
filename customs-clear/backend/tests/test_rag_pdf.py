"""RAG: извлечение текста из PDF (через _read_pdf_text)."""
from __future__ import annotations

import asyncio
import importlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class RagPdfTests(unittest.TestCase):
    def test_pdf_snippet_retrieval(self):
        async def _run():
            with tempfile.TemporaryDirectory() as d:
                (Path(d) / "doc.pdf").write_bytes(b"%PDF-1.4 minimal")

                with patch.dict("os.environ", {"RAG_DOCS_DIR": d}):
                    import app.services.rag_service as rs

                    importlib.reload(rs)

                    def fake_pdf(_path: Path) -> str:
                        return "таможня декларант пылесос электрический импорт"

                    with patch.object(rs, "_read_pdf_text", fake_pdf):
                        return await rs.retrieve_snippets("пылесос декларант", limit=3)

        out = asyncio.run(_run())
        self.assertTrue(len(out) >= 1)
        joined = " ".join((x.get("snippet") or "").lower() for x in out)
        self.assertIn("пылесос", joined)


if __name__ == "__main__":
    unittest.main()
