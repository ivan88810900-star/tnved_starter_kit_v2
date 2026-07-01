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
        CanonicalModel,
        CanonicalModelValidationError,
        CommodityNode,
        HeadingNode,
        StructureNormalizer,
        TreeBuilder,
        TreeNode,
        TreeParser,
        TreeSerializer,
        TreeValidator,
        assign_stable_ids,
        compute_snapshot_id,
    )

    _OK = True
except ImportError:
    _OK = False

_SAMPLE_HEADINGS = ("0101", "0302", "0304", "8517", "9401")
# Краевые кейсы parity: pad-код, одиночный L6, mixed L6 (subheading-group),
# ведущие тире, уровневая (не префиксная) вложенность.
_EDGE_HEADINGS = ("0101", "0301", "0302", "0303", "0305", "5208", "8517", "9401")
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


def _content_fingerprint(node: dict) -> tuple:
    """Полный контентный отпечаток узла (сверх structure_fingerprint).

    Учитывает name / display_code / is_leaf / is_codeless / is_group /
    import_duty / notes рекурсивно — для content-parity с legacy build_tree.
    """
    return (
        node.get("code") or "",
        node.get("name") or "",
        node.get("display_code") or "",
        bool(node.get("is_leaf")),
        bool(node.get("is_codeless")),
        bool(node.get("is_group")),
        node.get("import_duty") or "",
        node.get("notes") or "",
        tuple(_content_fingerprint(ch) for ch in (node.get("children") or [])),
    )


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

    def test_structure_parity_with_legacy_edge_headings(self) -> None:
        """Parity StructureNormalizer→Builder vs legacy build_tree на краевых кейсах."""
        serializer = TreeSerializer()
        roots = self.builder.build(self.parsed)
        heading_map = {n.code: n for n in roots if n.code}
        with SessionLocal() as db:
            chapter_notes = collect_chapter_notes(db)
            for code in _EDGE_HEADINGS:
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
                    f"structure mismatch for edge heading {code}",
                )

    def test_full_tree_parity_with_legacy(self) -> None:
        """Полная parity дерева целиком: каждый heading совпадает с legacy build_tree."""
        serializer = TreeSerializer()
        roots = self.builder.build(self.parsed)
        v2_map = {n.code: serializer.to_legacy_dict(n) for n in roots if n.code}
        with SessionLocal() as db:
            rows = (
                exclude_obsolete_reserved(db.query(Commodity).order_by(Commodity.code.asc()))
                .all()
            )
            chapter_notes = collect_chapter_notes(db)
        legacy_flat = build_tree(rows, chapter_notes)
        legacy_map = {n.get("code"): n for n in legacy_flat if n.get("code")}
        self.assertEqual(set(v2_map), set(legacy_map), "набор heading-кодов отличается")
        mismatches: list[str] = []
        for code, legacy in legacy_map.items():
            if TreeSerializer.structure_fingerprint(legacy) != TreeSerializer.structure_fingerprint(
                v2_map[code]
            ):
                mismatches.append(code)
        self.assertEqual(mismatches, [], f"structure mismatch на {len(mismatches)} heading(s): {mismatches[:10]}")

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

    def test_structure_normalizer_is_pure_and_deterministic(self) -> None:
        """StructureNormalizer — чистый и детерминированный (без БД, без uuid4)."""
        normalizer = StructureNormalizer()
        leaf_flags = self.builder._compute_leaf_flags(self.parsed)
        rec_a = normalizer.normalize(
            self.parsed.commodities,
            chapter_notes=self.parsed.chapter_notes,
            leaf_flags=leaf_flags,
        )
        rec_b = normalizer.normalize(
            self.parsed.commodities,
            chapter_notes=self.parsed.chapter_notes,
            leaf_flags=leaf_flags,
        )
        self.assertTrue(rec_a, "recovery вернул пустой результат")
        codes_a = [(h.code, len(h.entries)) for h in rec_a]
        codes_b = [(h.code, len(h.entries)) for h in rec_b]
        self.assertEqual(codes_a, codes_b, "recovery недетерминирован")

    def test_synthetic_l6_marked_is_synthetic(self) -> None:
        """Механизм L6-синтеза (KNOWN_PITFALLS §2): одиночный L6 без строки в
        hs_rates → бескодовый заголовок + синтетический лист is_synthetic.

        Детерминированный unit-кейс (leaf_flags пуст ⇒ L6 не лист)."""
        from app.services.tree_engine import ParsedCommodityRecord

        records = [
            ParsedCommodityRecord(
                code10="0302",
                description="Рыба",
                raw_description="Рыба",
                import_duty="",
            ),
            ParsedCommodityRecord(
                code10="0302130000",
                description="– – лосось",
                raw_description="– – лосось",
                import_duty="5%",
            ),
        ]
        normalizer = StructureNormalizer()
        recovered = normalizer.normalize(records, chapter_notes={}, leaf_flags={})
        heading = next(h for h in recovered if h.code == "0302")
        entry = next(e for e in heading.entries if e.code == "0302130000")
        self.assertTrue(entry.is_codeless, "одиночный non-leaf L6 → бескодовый заголовок")
        self.assertEqual(entry.display_code, "030213")
        self.assertIsNotNone(entry.synthetic_leaf)
        self.assertTrue(entry.synthetic_leaf.is_synthetic)
        self.assertTrue(entry.synthetic_leaf.is_leaf)
        self.assertEqual(entry.synthetic_leaf.code, "0302130000")

    def test_synthetic_leaf_materialized_in_tree(self) -> None:
        """Builder материализует синтетический лист как дочерний узел заголовка."""
        from app.services.tree_engine import ParsedCommodityRecord, TreeParseResult

        records = [
            ParsedCommodityRecord(
                code10="0302",
                description="Рыба",
                raw_description="Рыба",
                import_duty="",
            ),
            ParsedCommodityRecord(
                code10="0302130000",
                description="– – лосось",
                raw_description="– – лосось",
                import_duty="5%",
            ),
        ]
        # Подменяем leaf-флаги пустыми, чтобы форсировать синтез без БД.
        builder = TreeBuilder()
        builder._compute_leaf_flags = lambda parse_result: {}  # type: ignore[method-assign]
        parsed = TreeParseResult(
            commodities=records,
            chapter_notes={},
            db_codes=frozenset({"0302", "0302130000"}),
        )
        roots = builder.build(parsed)
        heading = next(r for r in roots if r.code == "0302")
        wrapper = next(c for c in heading.children if c.code == "0302130000")
        self.assertTrue(wrapper.metadata.get("is_codeless"))
        self.assertEqual(len(wrapper.children), 1)
        leaf = wrapper.children[0]
        self.assertTrue(leaf.metadata.get("is_leaf"))
        self.assertTrue(leaf.metadata.get("is_synthetic"))

    # -- CanonicalModel: материализация / индексы -------------------------

    def test_build_model_returns_canonical_model(self) -> None:
        model = self.builder.build_model(self.parsed)
        self.assertIsInstance(model, CanonicalModel)
        self.assertTrue(model.snapshot_id.startswith("snap-"))
        self.assertEqual(model.snapshot_id, compute_snapshot_id(self.parsed.db_codes))
        self.assertTrue(len(model) > 0)

    def test_build_does_not_return_model(self) -> None:
        """Additive API: build() по-прежнему отдаёт list[TreeNode]."""
        roots = self.builder.build(self.parsed)
        self.assertIsInstance(roots, list)
        self.assertTrue(all(isinstance(n, TreeNode) for n in roots))
        self.assertNotIsInstance(roots, CanonicalModel)

    def test_indexes_cover_all_nodes(self) -> None:
        model = self.builder.build_model(self.parsed)
        roots = list(model.roots)
        all_nodes = _all_nodes(roots)
        self.assertEqual(len(model.node_by_stable_id), len(all_nodes))
        for node in all_nodes:
            self.assertIs(model.get(node.stable_id), node)

    def test_get_by_code_and_display_code(self) -> None:
        model = self.builder.build_model(self.parsed)
        heading = model.get_by_code("0302")
        self.assertIsNotNone(heading, "heading 0302 должен быть адресуем по коду")
        self.assertEqual(heading.code, "0302")
        by_display = model.get_by_display_code("0302")
        self.assertIsNotNone(by_display)
        self.assertEqual(by_display.metadata.get("display_code") or by_display.code, "0302")

    def test_get_by_code_prefers_leaf_on_collision(self) -> None:
        """Коллизия код↔synthetic-leaf: индекс возвращает реальный лист."""
        from app.services.tree_engine import ParsedCommodityRecord, TreeParseResult

        records = [
            ParsedCommodityRecord(
                code10="0302", description="Рыба", raw_description="Рыба", import_duty=""
            ),
            ParsedCommodityRecord(
                code10="0302130000",
                description="– – лосось",
                raw_description="– – лосось",
                import_duty="5%",
            ),
        ]
        builder = TreeBuilder()
        builder._compute_leaf_flags = lambda parse_result: {}  # type: ignore[method-assign]
        parsed = TreeParseResult(
            commodities=records,
            chapter_notes={},
            db_codes=frozenset({"0302", "0302130000"}),
        )
        model = builder.build_model(parsed)
        node = model.get_by_code("0302130000")
        self.assertIsNotNone(node)
        self.assertTrue(node.metadata.get("is_leaf"), "по коду должен вернуться лист, а не обёртка")

    def test_parent_children_consistency(self) -> None:
        model = self.builder.build_model(self.parsed)
        for node in _all_nodes(list(model.roots)):
            for child in model.children(node):
                self.assertIs(model.parent(child), node)
        for root in model.roots:
            self.assertIsNone(model.parent(root), "корень не имеет parent")

    def test_children_accepts_id_and_node(self) -> None:
        model = self.builder.build_model(self.parsed)
        heading = model.get_by_code("0302")
        by_node = model.children(heading)
        by_id = model.children(heading.stable_id)
        self.assertEqual([n.stable_id for n in by_node], [n.stable_id for n in by_id])

    def test_path_from_root_to_node(self) -> None:
        model = self.builder.build_model(self.parsed)
        # берём произвольный глубокий лист
        deep = next(
            (n for n in _all_nodes(list(model.roots)) if model.parent(n) is not None
             and model.parent(model.parent(n)) is not None),
            None,
        )
        self.assertIsNotNone(deep, "должен быть узел глубины ≥ 3")
        path = model.path(deep)
        self.assertGreaterEqual(len(path), 3)
        self.assertIsNone(model.parent(path[0]), "путь начинается с корня")
        self.assertIs(path[-1], deep, "путь заканчивается искомым узлом")
        for parent_node, child_node in zip(path, path[1:]):
            self.assertIs(model.parent(child_node), parent_node)

    def test_descendants_matches_manual_walk(self) -> None:
        model = self.builder.build_model(self.parsed)
        heading = model.get_by_code("0302")
        manual: list[str] = []

        def walk(node: TreeNode) -> None:
            for ch in node.children:
                manual.append(ch.stable_id)
                walk(ch)

        walk(heading)
        got = [n.stable_id for n in model.descendants(heading)]
        self.assertEqual(sorted(got), sorted(manual))
        self.assertNotIn(heading.stable_id, got, "descendants не включает сам узел")

    def test_lookup_miss_returns_none(self) -> None:
        model = self.builder.build_model(self.parsed)
        self.assertIsNone(model.get("node-does-not-exist"))
        self.assertIsNone(model.get_by_code("0000000001"))
        self.assertEqual(model.children("node-does-not-exist"), ())
        self.assertEqual(model.path("node-does-not-exist"), ())
        self.assertEqual(model.descendants("node-does-not-exist"), ())

    # -- CanonicalModel: freeze / read-only -------------------------------

    def test_model_is_read_only(self) -> None:
        model = self.builder.build_model(self.parsed)
        with self.assertRaises(AttributeError):
            model.roots = ()  # type: ignore[misc]
        with self.assertRaises(AttributeError):
            model.snapshot_id = "snap-hacked"  # type: ignore[misc]
        with self.assertRaises(AttributeError):
            del model._roots  # type: ignore[attr-defined]

    def test_roots_and_children_are_tuples(self) -> None:
        model = self.builder.build_model(self.parsed)
        self.assertIsInstance(model.roots, tuple)
        heading = model.get_by_code("0302")
        self.assertIsInstance(model.children(heading), tuple)
        self.assertIsInstance(model.path(heading), tuple)
        self.assertIsInstance(model.descendants(heading), tuple)

    def test_indexes_are_immutable_views(self) -> None:
        model = self.builder.build_model(self.parsed)
        heading = model.get_by_code("0302")
        for mapping in (
            model.node_by_stable_id,
            model.node_by_code,
            model.node_by_display_code,
            model.parent_by_stable_id,
            model.children_by_stable_id,
        ):
            with self.assertRaises(TypeError):
                mapping["x"] = heading  # type: ignore[index]

    # -- CanonicalModel: validator gate -----------------------------------

    def test_validator_gate_blocks_invalid_tree(self) -> None:
        """Невалидное дерево (лист с детьми + дубль кода) → модель не создаётся."""
        heading = HeadingNode(title="H", code="0101")
        leaf = CommodityNode(
            title="L", code="0101210000", level=10, metadata={"is_leaf": True}
        )
        bad_child = CommodityNode(
            title="C", code="0101210000", level=10, metadata={"is_leaf": True}
        )
        leaf.add_child(bad_child)
        heading.add_child(leaf)
        assign_stable_ids([heading], snapshot_id="snap-test")
        with self.assertRaises(CanonicalModelValidationError):
            CanonicalModel.from_roots([heading], snapshot_id="snap-test")

    def test_validator_gate_passes_for_real_tree(self) -> None:
        model = self.builder.build_model(self.parsed)
        self.assertIsInstance(model, CanonicalModel)

    # -- CanonicalModel: content parity vs legacy -------------------------

    def test_full_tree_content_parity_with_legacy(self) -> None:
        """Полная контент-parity: name/display_code/флаги/import_duty/notes."""
        serializer = TreeSerializer()
        model = self.builder.build_model(self.parsed)
        v2_map = {
            n.code: serializer.to_legacy_dict(n) for n in model.roots if n.code
        }
        with SessionLocal() as db:
            rows = (
                exclude_obsolete_reserved(db.query(Commodity).order_by(Commodity.code.asc())).all()
            )
            chapter_notes = collect_chapter_notes(db)
        legacy_flat = build_tree(rows, chapter_notes)
        legacy_map = {n.get("code"): n for n in legacy_flat if n.get("code")}
        self.assertEqual(set(v2_map), set(legacy_map), "набор heading-кодов отличается")
        mismatches: list[str] = []
        for code, legacy in legacy_map.items():
            if _content_fingerprint(legacy) != _content_fingerprint(v2_map[code]):
                mismatches.append(code)
        self.assertEqual(
            mismatches,
            [],
            f"content mismatch на {len(mismatches)} heading(s): {mismatches[:10]}",
        )


if __name__ == "__main__":
    unittest.main()
