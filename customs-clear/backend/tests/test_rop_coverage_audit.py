"""Tests for ROP chapter coverage audit (#144)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

try:
    from app.db import Base
    from app.models.rop import RopGoodsRate, RopPackagingDefault, RopPackagingRate
    from app.models.tnved import Chapter, Section
    from app.services.rop_coverage_audit import build_rop_chapter_coverage, coverage_summary
    from scripts.import_rop_rates import main as import_rop_rates

    _OK = True
except ImportError:
    _OK = False


@unittest.skipIf(not _OK, "deps missing")
class RopCoverageAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(
            bind=cls.engine,
            tables=[
                Section.__table__,
                Chapter.__table__,
                RopGoodsRate.__table__,
                RopPackagingRate.__table__,
                RopPackagingDefault.__table__,
            ],
        )
        cls.SessionLocal = sessionmaker(bind=cls.engine, autocommit=False, autoflush=False)
        with patch("scripts.import_rop_rates.SessionLocal", cls.SessionLocal):
            if import_rop_rates([]) != 0:
                raise AssertionError("ROP fixture import failed")
        cls.db = cls.SessionLocal()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.db.close()
        cls.engine.dispose()

    def test_matrix_has_97_chapters(self) -> None:
        matrix = build_rop_chapter_coverage(self.db, calendar_year=2026)
        self.assertGreaterEqual(len(matrix), 97)

    def test_chapter_61_subject(self) -> None:
        matrix = build_rop_chapter_coverage(self.db, calendar_year=2026)
        ch61 = next(r for r in matrix if r["chapter"] == "61")
        self.assertIn(ch61["subject_to_rop"], ("yes", "partial"))
        self.assertTrue(ch61["matched_groups"])

    def test_chapter_26_not_subject(self) -> None:
        matrix = build_rop_chapter_coverage(self.db, calendar_year=2026)
        ch26 = next(r for r in matrix if r["chapter"] == "26")
        self.assertTrue(ch26["not_subject"])

    def test_summary_counts(self) -> None:
        matrix = build_rop_chapter_coverage(self.db, calendar_year=2026)
        s = coverage_summary(matrix)
        self.assertEqual(s["total_chapters"], len(matrix))


if __name__ == "__main__":
    unittest.main()
