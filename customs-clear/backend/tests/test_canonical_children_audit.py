"""Gate-2 offline audit — self-contained smoke на синтетическом heading."""

from __future__ import annotations

import unittest

try:
    from app.db import SessionLocal
    from app.models.tnved import Chapter, Commodity, Section
    from app.services.normative_store import init_db
    from app.services.tree_engine.audit import (
        MIN_GATE2_COMMODITIES,
        CanonicalChildrenAuditReport,
        audit_canonical_children,
    )

    _OK = True
except ImportError:  # pragma: no cover
    _OK = False


@unittest.skipUnless(_OK, "canonical audit tests need backend dependencies")
class CanonicalChildrenAuditTests(unittest.TestCase):
    _section_id: int | None = None
    _chapter_id: int | None = None

    @classmethod
    def setUpClass(cls) -> None:
        init_db()
        with SessionLocal() as db:
            section = Section(roman_number="MMD", title="Audit section", notes="audit notes")
            db.add(section)
            db.flush()
            chapter = Chapter(
                section_id=section.id,
                code="98",
                title="Audit chapter",
                notes="audit chapter notes",
            )
            db.add(chapter)
            db.flush()
            rows = [
                ("9898", "Audit heading"),
                ("9898110001", "– audit leaf"),
                ("9898130000", "– – audit synthetic L6"),
            ]
            for code, description in rows:
                db.add(
                    Commodity(
                        chapter_id=chapter.id,
                        code=code,
                        description=description,
                        unit="",
                        import_duty="",
                    )
                )
            db.commit()
            cls._section_id = section.id
            cls._chapter_id = chapter.id

    @classmethod
    def tearDownClass(cls) -> None:
        with SessionLocal() as db:
            if cls._chapter_id is not None:
                db.query(Commodity).filter(Commodity.chapter_id == cls._chapter_id).delete()
                db.query(Chapter).filter(Chapter.id == cls._chapter_id).delete()
            if cls._section_id is not None:
                db.query(Section).filter(Section.id == cls._section_id).delete()
            db.commit()

    def test_seeded_prefix_has_zero_mismatch(self) -> None:
        with SessionLocal() as db:
            report = audit_canonical_children(db, prefix="9898")
        self.assertTrue(report.ok, msg=report.as_dict())
        self.assertFalse(report.gate2_ok, "prefix-smoke нельзя принять за полный Gate-2")
        self.assertEqual(report.commodity_count, 3)
        self.assertGreater(report.checked, 0)
        self.assertEqual(report.mismatches, 0)
        self.assertEqual(report.unresolved, 0)
        self.assertEqual(report.matches, report.checked)

    def test_empty_prefix_is_not_a_green_gate(self) -> None:
        with SessionLocal() as db:
            report = audit_canonical_children(db, prefix="77779999")
        self.assertFalse(report.ok)
        self.assertFalse(report.gate2_ok)
        self.assertEqual(report.commodity_count, 0)

    def test_gate2_requires_minimum_database_coverage(self) -> None:
        common = {
            "prefix": "",
            "chapter_paths": 1,
            "node_paths": 1,
            "checked": 2,
            "matches": 2,
            "mismatches": 0,
            "unresolved": 0,
            "duration_ms": 1.0,
        }
        partial = CanonicalChildrenAuditReport(
            commodity_count=MIN_GATE2_COMMODITIES - 1,
            **common,
        )
        full = CanonicalChildrenAuditReport(
            commodity_count=MIN_GATE2_COMMODITIES,
            **common,
        )
        self.assertTrue(partial.ok)
        self.assertFalse(partial.gate2_ok)
        self.assertTrue(full.gate2_ok)


if __name__ == "__main__":
    unittest.main()
