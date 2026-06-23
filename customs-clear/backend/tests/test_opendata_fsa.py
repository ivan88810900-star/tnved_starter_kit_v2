"""Тесты импорта FSA opendata (dedupe по registry_number)."""

from __future__ import annotations

import unittest

from app.db import SessionLocal
from app.models.tnved import FsaCertificate
from app.services.normative_store import init_db
from app.services.opendata_fsa import _upsert_fsa_rows


class FsaUpsertDedupeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_db()

    def test_duplicate_registry_number_in_batch_collapses(self) -> None:
        reg = "ЕАЭС RU С-CN.АБ12.В.01234/24"
        rows = [
            {
                "registry_number": reg,
                "doc_type": "СС",
                "status": "Действует",
                "product_name": "Первая строка",
            },
            {
                "registry_number": reg,
                "doc_type": "СС",
                "status": "Действует",
                "product_name": "Последняя строка",
            },
        ]
        stats = _upsert_fsa_rows(rows, snapshot_id="test-dedupe-snap")
        self.assertEqual(stats["created"], 1)
        self.assertEqual(stats["updated"], 0)
        self.assertEqual(stats["skipped"], 0)

        with SessionLocal() as db:
            count = db.query(FsaCertificate).filter(FsaCertificate.registry_number == reg).count()
            row = db.query(FsaCertificate).filter(FsaCertificate.registry_number == reg).one()
        self.assertEqual(count, 1)
        self.assertEqual(row.product_name, "Последняя строка")

        stats2 = _upsert_fsa_rows(rows, snapshot_id="test-dedupe-snap-2")
        self.assertEqual(stats2["created"], 0)
        self.assertEqual(stats2["updated"], 1)


if __name__ == "__main__":
    unittest.main()
