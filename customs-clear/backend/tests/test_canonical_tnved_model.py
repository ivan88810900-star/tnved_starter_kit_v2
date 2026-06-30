"""Canonical TNVED Model — этап 1 (ADR-0001 / TASK-CANONICAL-001).

Проверяет deterministic stable_id, snapshot_id и неизменность структуры/legacy
сериализации. Canonical path не должен зависеть от uuid4.
"""

from __future__ import annotations

import re
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
        StructureNormalizer,
        TreeBuilder,
        TreeNode,
        TreeParser,
        TreeSerializer,
        TreeValidator,
        compute_snapshot_id,
    )

    _OK = True
except ImportError:
    _OK = False

_SAMPLE_HEADINGS = ("0101", "0302", "0304", "8517", "9401")
_STABLE_ID_RE = re.compile(r"^node-[0-9a-f]{24}$")
_UUID4_HEX_RE = re.compile(r"^[0-9a-f]{32}$")


def _flatten(roots: "list[TreeNode]") -> list[tuple]:
    """Pre-order проекция дерева для сравнения (без объектных id)."""
    out: list[tuple] = []

    def walk(node: TreeNode) -> None:
        out.append(
            (
                node.code or "",
                node.metadata.get("display_code") or "",
                node.node_type.value,
                node.stable_id,
            )
        )
        for ch in node.children:
            walk(ch)

    for root in roots:
        walk(root)
    return out


def _all_nodes(roots: "list[TreeNode]") -> "list[TreeNode]":
    out: list[TreeNode] = []

    def walk(node: TreeNode) -> None:
        out.append(node)
        for ch in node.children:
            walk(ch)

    for root in roots:
        walk(root)
    return out


@unittest.skipUnless(_OK, "canonical model tests need FastAPI app deps")
class CanonicalTnvedModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_db()
        cls.parser = TreeParser()
        cls.builder = TreeBuilder()
        with SessionLocal() as db:
            cls.parsed = cls.parser.parse(db)

    # -- stable_id ---------------------------------------------------------

    def test_stable_id_non_empty(self) -> None:
        roots = self.builder.build(self.parsed)
        nodes = _all_nodes(roots)
        self.assertTrue(nodes, "дерево не должно быть пустым")
        for node in nodes:
            self.assertTrue(node.stable_id, f"пустой stable_id у {node.code or node.title}")
            self.assertEqual(node.id, node.stable_id, "id должен совпадать со stable_id")

    def test_stable_id_format_not_uuid4(self) -> None:
        roots = self.builder.build(self.parsed)
        for node in _all_nodes(roots):
            self.assertRegex(node.stable_id, _STABLE_ID_RE)
            self.assertNotRegex(
                node.stable_id, _UUID4_HEX_RE, "stable_id не должен быть uuid4-hex"
            )

    def test_stable_id_unique(self) -> None:
        roots = self.builder.build(self.parsed)
        ids = [n.stable_id for n in _all_nodes(roots)]
        self.assertEqual(len(ids), len(set(ids)), "stable_id должны быть уникальны")

    def test_two_builds_identical_stable_ids(self) -> None:
        roots_a = self.builder.build(self.parsed)
        roots_b = self.builder.build(self.parsed)
        self.assertEqual(
            _flatten(roots_a),
            _flatten(roots_b),
            "две сборки дают разные stable_id/структуру",
        )

    def test_snapshot_id_deterministic(self) -> None:
        snap_a = compute_snapshot_id(self.parsed.db_codes)
        snap_b = compute_snapshot_id(self.parsed.db_codes)
        self.assertTrue(snap_a.startswith("snap-"))
        self.assertEqual(snap_a, snap_b)

    def test_snapshot_id_present_on_nodes(self) -> None:
        roots = self.builder.build(self.parsed)
        expected = compute_snapshot_id(self.parsed.db_codes)
        for node in _all_nodes(roots):
            self.assertEqual(node.snapshot_id, expected)

    # -- структура / legacy сериализация ----------------------------------

    def test_structure_unchanged_between_builds(self) -> None:
        serializer = TreeSerializer()
        roots_a = self.builder.build(self.parsed)
        roots_b = self.builder.build(self.parsed)
        fp_a = [TreeSerializer.structure_fingerprint(d) for d in serializer.serialize_roots(roots_a)]
        fp_b = [TreeSerializer.structure_fingerprint(d) for d in serializer.serialize_roots(roots_b)]
        self.assertEqual(fp_a, fp_b, "структура дерева изменилась между сборками")

    def test_legacy_serializer_identical_between_builds(self) -> None:
        serializer = TreeSerializer()
        roots_a = self.builder.build(self.parsed)
        roots_b = self.builder.build(self.parsed)
        self.assertEqual(
            serializer.serialize_roots(roots_a),
            serializer.serialize_roots(roots_b),
            "legacy-сериализация недетерминирована",
        )

    def test_legacy_serializer_matches_build_tree(self) -> None:
        """Стабильные id не влияют на legacy-сериализацию (она их не содержит):
        совпадение с эталоном _build_tree сохранено."""
        serializer = TreeSerializer()
        roots = self.builder.build(self.parsed)
        heading_map = {n.code: n for n in roots if n.code}
        with SessionLocal() as db:
            chapter_notes = collect_chapter_notes(db)
            for code in _SAMPLE_HEADINGS:
                rows = (
                    exclude_obsolete_reserved(
                        db.query(Commodity).filter(Commodity.code.like(f"{code}%"))
                    )
                    .order_by(Commodity.code.asc())
                    .all()
                )
                legacy_flat = build_tree(rows, chapter_notes)
                legacy = next((n for n in legacy_flat if n.get("code") == code), None)
                self.assertIsNotNone(legacy, f"legacy missing {code}")
                v2 = heading_map.get(code)
                self.assertIsNotNone(v2, f"v2 missing {code}")
                self.assertEqual(
                    TreeSerializer.structure_fingerprint(legacy),  # type: ignore[arg-type]
                    TreeSerializer.structure_fingerprint(serializer.to_legacy_dict(v2)),
                    f"structure mismatch for {code}",
                )

    def test_serialized_dict_has_no_id_fields(self) -> None:
        """Контракт API не меняется: stable_id/id не попадают в legacy-словарь."""
        serializer = TreeSerializer()
        roots = self.builder.build(self.parsed)
        sample = serializer.to_legacy_dict(roots[0])
        for forbidden in ("id", "stable_id", "snapshot_id"):
            self.assertNotIn(forbidden, sample)

    # -- validator / recovery skeleton ------------------------------------

    def test_validator_ok_with_stable_ids(self) -> None:
        validator = TreeValidator()
        roots = self.builder.build(self.parsed)
        result = validator.validate(roots, parse_result=self.parsed)
        self.assertTrue(
            result.ok,
            msg=f"validator issues: {[i.message for i in result.issues[:5]]}",
        )

    def test_structure_normalizer_is_identity(self) -> None:
        normalizer = StructureNormalizer()
        roots = self.builder.build(self.parsed)
        same = normalizer.normalize(roots, parse_result=self.parsed)
        self.assertIs(same, roots, "skeleton normalize должен быть pass-through")


if __name__ == "__main__":
    unittest.main()
