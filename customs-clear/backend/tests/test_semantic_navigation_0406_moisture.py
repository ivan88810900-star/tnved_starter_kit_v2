"""Exact bounded 0406 moisture-chain regressions (TASK-SEMANTIC-008)."""

from __future__ import annotations

from copy import deepcopy

import pytest

from app.services.semantic_navigation import (
    SemanticNavigationBuilder,
    SemanticNavigationValidator,
    SemanticNodeType,
    SemanticStructureExtractor,
    SourceRecord,
)
from app.services.semantic_navigation.bounded_slices import (
    CHEESE_0406_AFTER_CODE,
    CHEESE_0406_AFTER_DESCRIPTION,
    CHEESE_0406_ANCHOR_CODE,
    CHEESE_0406_ANCHOR_DESCRIPTION,
    CHEESE_0406_GROUPS,
    CHEESE_0406_HIGH_TITLE,
    CHEESE_0406_LOW_TITLE,
    CHEESE_0406_MIDDLE_ANCHOR_CODE,
    CHEESE_0406_MIDDLE_DESCRIPTION,
    CHEESE_0406_MIDDLE_TITLE,
    CHEESE_0406_PAD_CODE,
    CHEESE_0406_PARENT_CODE,
    CHEESE_0406_REASON,
    CHEESE_0406_STOP_CODE,
    CHEESE_0406_STOP_DESCRIPTION,
    CHEESE_0406_TOP_SIGNATURE,
    CHEESE_0406_TOP_TITLE,
)


def _records() -> list[SourceRecord]:
    records = [
        SourceRecord(code="0406", description="Сыры и творог", is_leaf=False),
        SourceRecord(
            code=CHEESE_0406_PAD_CODE,
            description="Сыры и творог",
            is_leaf=False,
        ),
        SourceRecord(
            code=CHEESE_0406_PARENT_CODE,
            description="– сыры прочие",
            is_leaf=False,
            parent_code="0406",
        ),
        SourceRecord(
            code=CHEESE_0406_ANCHOR_CODE,
            description=CHEESE_0406_ANCHOR_DESCRIPTION,
            is_leaf=True,
            parent_code=CHEESE_0406_PARENT_CODE,
        ),
    ]
    for code, parent, is_leaf in CHEESE_0406_TOP_SIGNATURE:
        if code == CHEESE_0406_MIDDLE_ANCHOR_CODE:
            description = CHEESE_0406_MIDDLE_DESCRIPTION
        elif code == CHEESE_0406_STOP_CODE:
            description = CHEESE_0406_STOP_DESCRIPTION
        else:
            description = f"– – – – – – – официальный товар {code}"
        records.append(
            SourceRecord(
                code=code,
                description=description,
                is_leaf=is_leaf,
                parent_code=parent,
            )
        )
    records.append(
        SourceRecord(
            code=CHEESE_0406_AFTER_CODE,
            description=CHEESE_0406_AFTER_DESCRIPTION,
            is_leaf=False,
            parent_code=CHEESE_0406_PARENT_CODE,
        )
    )
    records.append(
        SourceRecord(
            code="0406909901",
            description="– – – – – – Белый сыр из коровьего молока",
            is_leaf=True,
            parent_code=CHEESE_0406_AFTER_CODE,
        )
    )
    return records


def _bounded_groups(tree_or_extraction):
    nodes = (
        tree_or_extraction.groups
        if hasattr(tree_or_extraction, "groups")
        else tree_or_extraction.group_nodes()
    )
    return [
        node
        for node in nodes
        if getattr(node, "reason", None) == CHEESE_0406_REASON
        or getattr(node, "metadata", {}).get("reason") == CHEESE_0406_REASON
    ]


def _real_signature(node):
    return tuple(
        (
            str(child.code),
            str(child.metadata.get("canonical_parent_code") or ""),
            child.metadata.get("leaf_evidence"),
        )
        for child in node.iter_descendants()
        if child.carries_real_code and child.code
    )


def test_extractor_accepts_only_exact_chain_and_keeps_generic_rejection() -> None:
    extraction = SemanticStructureExtractor().extract("0406", _records())
    groups = _bounded_groups(extraction)

    assert [group.title for group in groups] == [
        CHEESE_0406_TOP_TITLE,
        CHEESE_0406_LOW_TITLE,
        CHEESE_0406_MIDDLE_TITLE,
    ]
    assert [group.verified_scope_leaf_count for group in groups] == [17, 3, 13]
    assert any(
        rejected.source_code == CHEESE_0406_ANCHOR_CODE
        and rejected.reason == "generic_subcategory"
        for rejected in extraction.rejected
    )


def test_builder_publishes_exact_two_level_chain_under_canonical_parent() -> None:
    tree = SemanticNavigationBuilder().build_heading_from_records("0406", _records())
    bounded = _bounded_groups(tree)
    top = next(node for node in bounded if node.title == CHEESE_0406_TOP_TITLE)
    low = next(node for node in bounded if node.title == CHEESE_0406_LOW_TITLE)
    middle = next(node for node in bounded if node.title == CHEESE_0406_MIDDLE_TITLE)
    parent = next(
        node for node in tree.all_nodes() if node.code == CHEESE_0406_PARENT_CODE
    )

    assert top in parent.children
    assert top.node_type == SemanticNodeType.CLASSIFICATION_GROUP
    assert low.node_type == middle.node_type == SemanticNodeType.CLASSIFICATION_SUBGROUP
    assert [node.title for node in top.children[:2]] == [
        CHEESE_0406_LOW_TITLE,
        CHEESE_0406_MIDDLE_TITLE,
    ]
    assert top.children[2].code == CHEESE_0406_STOP_CODE
    assert top.children[2].title == CHEESE_0406_HIGH_TITLE
    assert _real_signature(top) == CHEESE_0406_GROUPS[0].signature
    assert _real_signature(low) == CHEESE_0406_GROUPS[1].signature
    assert _real_signature(middle) == CHEESE_0406_GROUPS[2].signature
    assert SemanticNavigationValidator().validate(tree).ok


def test_shuffled_input_is_deterministic() -> None:
    records = _records()
    first = SemanticNavigationBuilder().build_heading_from_records("0406", records)
    second = SemanticNavigationBuilder().build_heading_from_records(
        "0406", list(reversed(records))
    )
    first_top = next(
        node for node in _bounded_groups(first) if node.title == CHEESE_0406_TOP_TITLE
    )
    second_top = next(
        node for node in _bounded_groups(second) if node.title == CHEESE_0406_TOP_TITLE
    )
    assert _real_signature(first_top) == _real_signature(second_top)


@pytest.mark.parametrize(
    ("mutation"),
    [
        "missing_pad",
        "missing_leaf",
        "extra_leaf",
        "same_count_substitution",
        "wrong_parent",
        "nonleaf",
        "anchor_text",
        "middle_text",
        "stop_text",
        "after_text",
        "hidden_shallow_boundary",
    ],
)
def test_source_or_topology_drift_fails_closed(mutation: str) -> None:
    records = deepcopy(_records())
    by_code = {record.code: record for record in records}
    if mutation == "missing_pad":
        records.remove(by_code[CHEESE_0406_PAD_CODE])
    elif mutation == "missing_leaf":
        records.remove(by_code["0406907400"])
    elif mutation == "extra_leaf":
        records.append(
            SourceRecord(
                code="0406907450",
                description="– – – – – – – extra",
                is_leaf=True,
                parent_code=CHEESE_0406_PARENT_CODE,
            )
        )
    elif mutation == "same_count_substitution":
        by_code["0406907400"].code = "0406907450"
    elif mutation == "wrong_parent":
        by_code["0406907400"].parent_code = "0406"
    elif mutation == "nonleaf":
        by_code["0406907400"].is_leaf = False
    elif mutation == "anchor_text":
        by_code[CHEESE_0406_ANCHOR_CODE].description += " "
    elif mutation == "middle_text":
        by_code[CHEESE_0406_MIDDLE_ANCHOR_CODE].description += " "
    elif mutation == "stop_text":
        by_code[CHEESE_0406_STOP_CODE].description += ":"
    elif mutation == "after_text":
        by_code[CHEESE_0406_AFTER_CODE].description = "– – – – – иные:"
    else:
        by_code["0406907400"].description += " – – – – – новая категория:"

    extraction = SemanticStructureExtractor().extract("0406", records)
    tree = SemanticNavigationBuilder().build_heading_from_records("0406", records)
    assert _bounded_groups(extraction) == []
    assert _bounded_groups(tree) == []
    assert set(tree.real_codes_in_tree()) == tree.expected_real_codes


@pytest.mark.parametrize(
    "field",
    ["title", "raw", "reason", "scope", "parent", "leaf_count", "all_identity"],
)
def test_builder_tamper_spills_all_codes(monkeypatch, field: str) -> None:
    original = SemanticNavigationBuilder._apply_controlled_nesting

    def tamper(root):
        fallbacks = original(root)
        target = next(
            node
            for node in root.children
            if node.metadata.get("reason") == CHEESE_0406_REASON
        )
        if field == "title":
            target.title = target.title.upper()
        elif field == "raw":
            target.metadata["raw"] = f"– – {target.title}:"
        elif field == "reason":
            target.metadata["reason"] = "tampered"
        elif field == "scope":
            target.metadata["verified_scope_end_inclusive"] = "0406909200"
        elif field == "parent":
            target.metadata["verified_scope_parent_code"] = "0406"
        elif field == "leaf_count":
            target.metadata["verified_scope_leaf_count"] = 16
        else:
            target.title = "tampered"
            target.source = "tampered"
            target.metadata["reason"] = "tampered"
            target.metadata["verified_scope_kind"] = "tampered"
            target.metadata["verified_scope_end_inclusive"] = "tampered"
        return fallbacks

    monkeypatch.setattr(
        SemanticNavigationBuilder,
        "_apply_controlled_nesting",
        staticmethod(tamper),
    )
    tree = SemanticNavigationBuilder().build_heading_from_records("0406", _records())
    assert _bounded_groups(tree) == []
    assert set(tree.real_codes_in_tree()) == tree.expected_real_codes
