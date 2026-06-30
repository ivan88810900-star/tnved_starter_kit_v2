"""Демонстрация Tree Model v2: Builder → Validator → Serializer vs legacy _build_tree."""

from __future__ import annotations

import unittest

try:
    from app.db import SessionLocal
    from app.models.tnved import Commodity
    from app.services.normative_store import init_db
    from app.services.tnved_tree import (
        build_tree,
        collect_chapter_notes,
        exclude_obsolete_reserved,
    )
    from app.services.tree_engine import (
        TreeBuilder,
        TreeParser,
        TreeSerializer,
        TreeValidator,
    )

    _OK = True
except ImportError:
    _OK = False

_SAMPLE_HEADINGS = ("0101", "0302", "0304", "8517", "9401")


@unittest.skipUnless(_OK, "tree_engine v2 tests need FastAPI app deps")
class TreeEngineV2SmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_db()

    def _legacy_heading_tree(self, db, heading_code: str) -> dict | None:
        rows = (
            exclude_obsolete_reserved(
                db.query(Commodity).filter(Commodity.code.like(f"{heading_code}%"))
            )
            .order_by(Commodity.code.asc())
            .limit(500_000)
            .all()
        )
        chapter_notes = collect_chapter_notes(db)
        flat = build_tree(rows, chapter_notes)
        for node in flat:
            if node.get("code") == heading_code:
                return node
        return None

    def test_pipeline_matches_legacy_structure_for_sample_headings(self) -> None:
        parser = TreeParser()
        builder = TreeBuilder()
        validator = TreeValidator()
        serializer = TreeSerializer()

        with SessionLocal() as db:
            parsed = parser.parse(db)
            roots = builder.build(parsed)
            result = validator.validate(roots, parse_result=parsed)
            self.assertTrue(
                result.ok,
                msg=f"Validator issues: {[i.message for i in result.issues[:5]]}",
            )

            heading_map = {n.code: n for n in roots if n.code}
            for code in _SAMPLE_HEADINGS:
                legacy = self._legacy_heading_tree(db, code)
                self.assertIsNotNone(legacy, msg=f"legacy missing heading {code}")
                v2_node = heading_map.get(code)
                self.assertIsNotNone(v2_node, msg=f"v2 missing heading {code}")

                legacy_fp = TreeSerializer.structure_fingerprint(legacy)  # type: ignore[arg-type]
                v2_fp = TreeSerializer.structure_fingerprint(
                    serializer.to_legacy_dict(v2_node)  # type: ignore[arg-type]
                )
                self.assertEqual(
                    legacy_fp,
                    v2_fp,
                    msg=f"structure mismatch for heading {code}",
                )

    def test_round_trip_preserves_child_counts(self) -> None:
        parser = TreeParser()
        builder = TreeBuilder()
        serializer = TreeSerializer()

        with SessionLocal() as db:
            parsed = parser.parse(db)
            roots = builder.build(parsed)
            reserialized = serializer.serialize_roots(roots)
            self.assertEqual(len(roots), len(reserialized))
            for orig, ser in zip(roots, reserialized):
                self.assertEqual(orig.code, ser.get("code"))
                self.assertEqual(len(orig.children), len(ser.get("children") or []))

    def test_stable_ids_are_deterministic(self) -> None:
        """ADR-0001 этап 1: stable_id детерминирован, не пуст, не uuid4."""
        parser = TreeParser()
        builder = TreeBuilder()

        with SessionLocal() as db:
            parsed = parser.parse(db)
            roots_a = builder.build(parsed)
            roots_b = builder.build(parsed)

        def ids(roots: list) -> list[str]:
            out: list[str] = []

            def walk(node) -> None:
                out.append(node.stable_id)
                for ch in node.children:
                    walk(ch)

            for root in roots:
                walk(root)
            return out

        ids_a = ids(roots_a)
        self.assertTrue(all(ids_a), "найден пустой stable_id")
        self.assertTrue(all(i.startswith("node-") for i in ids_a))
        self.assertEqual(ids_a, ids(roots_b), "две сборки дали разные stable_id")
        self.assertEqual(len(ids_a), len(set(ids_a)), "stable_id не уникальны")


if __name__ == "__main__":
    unittest.main()
