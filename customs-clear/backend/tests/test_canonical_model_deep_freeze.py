"""Deep-immutability regressions for the published CanonicalModel graph."""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from app.services.tree_engine import (
    CanonicalModel,
    CanonicalModelValidationError,
    ClassificationGroupNode,
    CommodityNode,
    HeadingNode,
    NodeType,
    ParsedCommodityRecord,
    TreeBuilder,
    TreeParseResult,
    TreeSerializer,
    TreeNode,
    assign_stable_ids,
    compute_snapshot_id,
)


def _published_fixture():
    heading = HeadingNode(
        title="Лошади",
        code="0101",
        metadata={
            "display_code": "0101",
            "is_leaf": False,
            "is_codeless": False,
            "is_group": True,
            "nested": {
                "labels": ["official", {"tags": {"animal", "live"}}],
                "buffer": bytearray(b"tnved"),
            },
        },
    )
    branch = ClassificationGroupNode(
        title="Племенные животные",
        code="0101210000",
        level=6,
        metadata={
            "display_code": "010121",
            "is_leaf": False,
            "is_codeless": True,
            "is_group": True,
        },
    )
    leaf = CommodityNode(
        title="Чистопородные племенные лошади",
        code="0101210000",
        level=10,
        metadata={
            "display_code": "0101210000",
            "is_leaf": True,
            "is_codeless": False,
            "is_group": False,
            "import_duty": "0%",
            "notes": "",
        },
    )
    branch.add_child(leaf)
    heading.add_child(branch)
    roots = [heading]
    assign_stable_ids(roots)
    snapshot_id = compute_snapshot_id(roots)
    stable_ids = tuple(node.stable_id for node in (heading, branch, leaf))
    model = CanonicalModel.from_roots(roots, snapshot_id=snapshot_id)
    return model, heading, branch, leaf, snapshot_id, stable_ids


def test_tree_builder_build_output_remains_mutable_before_publication() -> None:
    records = [
        ParsedCommodityRecord(
            code10="0101",
            description="Лошади",
            raw_description="Лошади",
            import_duty="",
        ),
        ParsedCommodityRecord(
            code10="0101210000",
            description="– – чистопородные племенные животные",
            raw_description="– – чистопородные племенные животные",
            import_duty="0%",
        ),
    ]
    roots = TreeBuilder().build(
        TreeParseResult(
            commodities=records,
            chapter_notes={},
            db_codes=frozenset(record.code10 for record in records),
            leaf_flags={"0101210000": True},
        )
    )

    heading = roots[0]
    assert heading.is_frozen is False
    heading.title = "Лошади (изменено до публикации)"
    heading.metadata["build_stage"] = True
    original_count = len(heading.children)
    temporary = CommodityNode(title="Временный", code="0101299999", level=10)
    heading.add_child(temporary)
    assert temporary.parent is heading
    assert len(heading.children) == original_count + 1
    heading.children.pop()


def test_published_graph_freezes_scalar_attributes_and_cannot_be_thawed() -> None:
    model, heading, branch, leaf, snapshot_id, stable_ids = _published_fixture()

    assert all(node.is_frozen for node in (heading, branch, leaf))
    mutations = (
        ("title", "changed"),
        ("level", 99),
        ("node_type", NodeType.HEADING),
        ("id", "changed"),
        ("code", "9999999999"),
        ("stable_id", "node-changed"),
        ("snapshot_id", "snap-changed"),
        ("parent", None),
        ("_frozen", False),
    )
    for name, value in mutations:
        with pytest.raises(AttributeError):
            setattr(leaf, name, value)
    with pytest.raises(AttributeError):
        del leaf.title
    with pytest.raises(AttributeError):
        del leaf._frozen
    for node in (heading, branch, leaf):
        with pytest.raises(AttributeError):
            node.__dict__["title"] = "bypass"

    assert model.snapshot_id == snapshot_id
    assert tuple(node.stable_id for node in (heading, branch, leaf)) == stable_ids
    assert compute_snapshot_id(model.roots) == model.snapshot_id


def test_children_and_parent_are_frozen_through_every_model_view() -> None:
    model, heading, branch, leaf, _, _ = _published_fixture()

    assert isinstance(heading.children, tuple)
    assert isinstance(branch.children, tuple)
    assert model.roots[0] is heading
    assert model.get(leaf.stable_id) is leaf
    assert model.get_by_code("0101210000") is leaf
    assert model.get_by_display_code("010121") is branch
    assert model.children(heading) == (branch,)
    assert model.parent(branch) is heading
    assert model.path(leaf) == (heading, branch, leaf)
    assert model.descendants(heading) == (branch, leaf)

    with pytest.raises(AttributeError):
        heading.children.append(leaf)
    with pytest.raises(TypeError):
        heading.children[0] = leaf
    with pytest.raises(AttributeError):
        heading.children = ()
    outsider = CommodityNode(title="Чужой", code="0101299999", level=10)
    with pytest.raises(AttributeError):
        heading.add_child(outsider)
    assert outsider.parent is None

    for node in model.node_by_stable_id.values():
        assert tuple(node.children) == model.children(node)
        assert node.parent is model.parent(node)
    assert compute_snapshot_id(model.roots) == model.snapshot_id


def test_metadata_is_recursively_frozen_and_serialization_is_unchanged() -> None:
    model, heading, _, leaf, _, _ = _published_fixture()

    assert isinstance(heading.metadata, Mapping)
    with pytest.raises(TypeError):
        heading.metadata["is_leaf"] = True
    with pytest.raises(AttributeError):
        heading.metadata = {}

    nested = heading.metadata["nested"]
    assert isinstance(nested, Mapping)
    assert isinstance(nested["labels"], tuple)
    assert isinstance(nested["labels"][1], Mapping)
    assert isinstance(nested["labels"][1]["tags"], frozenset)
    assert nested["buffer"] == b"tnved"
    with pytest.raises(TypeError):
        nested["extra"] = True
    with pytest.raises(AttributeError):
        nested["labels"].append("changed")
    with pytest.raises(TypeError):
        nested["labels"][1]["tags"] = frozenset()
    with pytest.raises(AttributeError):
        nested["labels"][1]["tags"].add("changed")

    serialized = TreeSerializer().serialize_roots(model.roots)
    assert isinstance(serialized, list)
    assert isinstance(serialized[0], dict)
    payload = serialized[0]
    assert payload["code"] == "0101"
    assert payload["children"][0]["children"][0]["code"] == leaf.code
    assert payload["children"][0]["children"][0]["import_duty"] == "0%"
    assert compute_snapshot_id(model.roots) == model.snapshot_id


def test_publication_detaches_mutable_container_aliases() -> None:
    heading = HeadingNode(
        title="Лошади",
        code="0101",
        metadata={
            "display_code": "0101",
            "is_leaf": False,
            "is_group": True,
            "nested": {"labels": ["official"]},
        },
    )
    leaf = CommodityNode(
        title="Племенные лошади",
        code="0101210001",
        level=10,
        metadata={"display_code": "0101210001", "is_leaf": True},
    )
    heading.add_child(leaf)
    metadata_alias = heading.metadata
    nested_list_alias = metadata_alias["nested"]["labels"]
    children_alias = heading.children
    assign_stable_ids([heading])
    snapshot_id = compute_snapshot_id([heading])

    model = CanonicalModel.from_roots([heading], snapshot_id=snapshot_id)
    metadata_alias["is_leaf"] = True
    nested_list_alias.append("mutated alias")
    children_alias.clear()

    published = model.roots[0]
    assert published.metadata["is_leaf"] is False
    assert published.metadata["nested"]["labels"] == ("official",)
    assert published.children == (leaf,)
    assert compute_snapshot_id(model.roots) == model.snapshot_id


def test_published_roots_cannot_be_republished_without_retained_inputs() -> None:
    model, _, _, _, _, _ = _published_fixture()

    with pytest.raises(ValueError, match="published roots cannot be republished"):
        CanonicalModel.from_roots(model.roots)


def test_reachable_published_child_fails_before_stamping_mutable_root() -> None:
    model, _, _, published_leaf, _, _ = _published_fixture()
    mutable_root = HeadingNode(title="Другие живые животные", code="0106")
    assign_stable_ids([mutable_root])
    mutable_root.snapshot_id = "root-snapshot-before-preflight"
    mutable_root.children.append(published_leaf)
    child_snapshot_before = published_leaf.snapshot_id

    with pytest.raises(ValueError, match="published descendants"):
        CanonicalModel.from_roots(
            [mutable_root],
            snapshot_id="must-not-be-stamped",
        )

    assert mutable_root.snapshot_id == "root-snapshot-before-preflight"
    assert mutable_root.is_frozen is False
    assert isinstance(mutable_root.children, list)
    assert published_leaf.snapshot_id == child_snapshot_before
    assert published_leaf.is_frozen is True

    mutable_root.children.clear()
    retry_snapshot = compute_snapshot_id([mutable_root])
    retry_model = CanonicalModel.from_roots(
        [mutable_root],
        snapshot_id=retry_snapshot,
    )
    assert retry_model.roots == (mutable_root,)


def test_all_node_classes_are_slotted_without_dict_bypass() -> None:
    nodes = (
        TreeNode(title="База", level=0, node_type=NodeType.HEADING),
        HeadingNode(title="Лошади", code="0101"),
        ClassificationGroupNode(title="Группа", code=None, level=6),
        CommodityNode(title="Лист", code="0101210000", level=10),
    )

    for node in nodes:
        assert not hasattr(node, "__dict__")


def test_root_with_parent_fails_validator_and_remains_mutable() -> None:
    foreign_parent = HeadingNode(title="Чужой корень", code="0102")
    root = HeadingNode(title="Лошади", code="0101")
    root.parent = foreign_parent
    assign_stable_ids([root])
    snapshot_id = compute_snapshot_id([root])

    with pytest.raises(CanonicalModelValidationError) as exc_info:
        CanonicalModel.from_roots([root], snapshot_id=snapshot_id)

    assert "root_has_parent" in {issue.code for issue in exc_info.value.issues}
    assert root.is_frozen is False
    assert isinstance(root.children, list)
    root.metadata["retryable"] = True
    root.parent = None
    model = CanonicalModel.from_roots([root], snapshot_id=snapshot_id)
    assert model.roots == (root,)
    assert root.is_frozen is True


def test_direct_constructor_cannot_bypass_publication_gate() -> None:
    root = HeadingNode(title="Лошади", code="0101")
    assign_stable_ids([root])
    snapshot_id = compute_snapshot_id([root])

    with pytest.raises(TypeError, match="published through CanonicalModel.from_roots"):
        CanonicalModel([root], snapshot_id)

    assert root.is_frozen is False
    root.title = "Лошади — всё ещё Builder output"


def test_cyclic_metadata_failure_is_atomic_and_graph_is_retryable() -> None:
    cyclic: dict[str, object] = {}
    cyclic["self"] = cyclic
    root = HeadingNode(
        title="Лошади",
        code="0101",
        metadata={"display_code": "0101", "cycle": cyclic},
    )
    leaf = CommodityNode(
        title="Племенные лошади",
        code="0101210000",
        level=10,
        metadata={"display_code": "0101210000", "is_leaf": True},
    )
    root.add_child(leaf)
    original_children = root.children
    original_root_metadata = root.metadata
    original_leaf_metadata = leaf.metadata
    assign_stable_ids([root])
    snapshot_id = compute_snapshot_id([root])

    with pytest.raises(ValueError, match="cyclic metadata"):
        CanonicalModel.from_roots([root], snapshot_id=snapshot_id)

    assert root.is_frozen is False
    assert leaf.is_frozen is False
    assert root.children is original_children
    assert isinstance(root.children, list)
    assert root.metadata is original_root_metadata
    assert leaf.metadata is original_leaf_metadata
    root.title = "Лошади после исправления metadata"
    del cyclic["self"]
    cyclic["fixed"] = True

    snapshot_id = compute_snapshot_id([root])
    model = CanonicalModel.from_roots([root], snapshot_id=snapshot_id)
    assert model.roots == (root,)
    assert root.is_frozen is True
    assert leaf.is_frozen is True
