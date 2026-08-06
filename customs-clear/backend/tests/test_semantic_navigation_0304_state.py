"""Fail-closed official 0304 product-state regressions (TASK-SEMANTIC-007)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.guided_tnved_navigation import GuidedTnvedNavigationService
from app.services.semantic_navigation import (
    SemanticNavigationBuilder,
    SemanticNavigationValidator,
    SemanticNodeType,
    SemanticStructureExtractor,
    SourceRecord,
)
from app.services.semantic_navigation.bounded_slices import (
    STATE_0304_GROUPS,
    STATE_0304_REASON,
    STATE_0304_SCOPE_KIND,
)

HEADING = "0304"
FLAT_CODES = (
    "0304310000",
    "0304320000",
    "0304330000",
    "0304390000",
    "0304610000",
    "0304620000",
    "0304630000",
    "0304690000",
)
MARKER_DESCRIPTIONS = {
    spec.anchor_code: f"– – официальный предшественник – {spec.title}:"
    for spec in STATE_0304_GROUPS
}
MARKER_DESCRIPTIONS["0304498000"] = (
    "– – – – прочее – прочее, свежее или охлажденное:"
)
MARKER_DESCRIPTIONS["0304799000"] = (
    "– – – прочее – филе прочей рыбы, мороженое:"
)
MARKER_DESCRIPTIONS["0304898000"] = "– – – – прочее – прочее, мороженое:"


def _records() -> list[SourceRecord]:
    records = [
        SourceRecord(
            code=HEADING,
            description="Филе рыбное и прочее мясо рыбы",
            is_leaf=False,
        ),
        SourceRecord(
            code="0304000000",
            description="Филе рыбное и прочее мясо рыбы:",
            is_leaf=False,
        ),
    ]
    signatures = {
        code: (parent, is_leaf)
        for spec in STATE_0304_GROUPS
        for code, parent, is_leaf in spec.signature
    }
    signatures.update(
        {
            "0304310000": (HEADING, True),
            "0304320000": (HEADING, True),
            "0304330000": (HEADING, True),
            "0304390000": (HEADING, True),
            "0304610000": (HEADING, True),
            "0304620000": (HEADING, True),
            "0304630000": (HEADING, True),
            "0304690000": (HEADING, True),
        }
    )
    descriptions = dict(MARKER_DESCRIPTIONS)
    descriptions["0304740000"] = (
        "– – мерлузы и американского нитеперого налима: "
        "– – – мерлузы рода Merluccius:"
    )
    descriptions["0304880000"] = (
        "– – акул, скатов и ромбовых скатов: – – – акул:"
    )
    for code, (parent, is_leaf) in signatures.items():
        records.append(
            SourceRecord(
                code=code,
                description=descriptions.get(
                    code,
                    f"– – официальный товар {code}",
                ),
                is_leaf=is_leaf,
                parent_code=parent,
            )
        )
    return records


def _bounded_groups(tree):  # noqa: ANN001, ANN202
    return [
        node
        for node in tree.group_nodes()
        if node.metadata.get("reason") == STATE_0304_REASON
    ]


def _signature(node) -> tuple[tuple[str, str, bool], ...]:  # noqa: ANN001
    return tuple(
        (
            str(descendant.code),
            str(descendant.metadata.get("canonical_parent_code") or ""),
            descendant.metadata.get("leaf_evidence"),
        )
        for descendant in node.iter_descendants()
        if descendant.carries_real_code and descendant.code
    )


def test_exact_five_state_chain_preserves_full_titles_and_generic_policy() -> None:
    extraction = SemanticStructureExtractor().extract(HEADING, _records())
    bounded = [
        group for group in extraction.groups if group.reason == STATE_0304_REASON
    ]

    assert [group.title for group in bounded] == [
        spec.title for spec in STATE_0304_GROUPS
    ]
    assert [group.source_code for group in bounded] == [
        spec.anchor_code for spec in STATE_0304_GROUPS
    ]
    assert all(group.raw == f"– {group.title}:" for group in bounded)
    assert all(group.dash_depth == 1 for group in bounded)
    assert all(group.confidence == "high" for group in bounded)
    assert all(
        group.verified_scope_kind == STATE_0304_SCOPE_KIND for group in bounded
    )

    # B/E remain honest generic rejections; their acceptance is only the exact
    # bounded override and does not widen generic extraction policy.
    rejected_sources = {
        candidate.source_code
        for candidate in extraction.rejected
        if candidate.reason == "generic_subcategory"
    }
    assert {"0304498000", "0304898000"}.issubset(rejected_sources)

    # Existing deeper groups under C/D must target the upgraded full titles.
    by_source = {group.source_code: group for group in extraction.groups}
    assert by_source["0304740000"].parent_title_hint == STATE_0304_GROUPS[2].title
    assert by_source["0304880000"].parent_title_hint == STATE_0304_GROUPS[3].title


def test_builder_publishes_five_exact_states_and_keeps_03046_flat() -> None:
    tree = SemanticNavigationBuilder().build_heading_from_records(
        HEADING,
        _records(),
    )
    bounded = _bounded_groups(tree)

    assert len(tree.root.children) == 13
    assert tuple(
        str(node.code) for node in tree.root.children if node.code
    ) == FLAT_CODES
    assert len(bounded) == 5
    assert [group.title for group in bounded] == [
        spec.title for spec in STATE_0304_GROUPS
    ]
    assert [_signature(group) for group in bounded] == [
        spec.signature for spec in STATE_0304_GROUPS
    ]
    assert [
        sum(
            descendant.node_type == SemanticNodeType.LEAF
            for descendant in group.iter_descendants()
        )
        for group in bounded
    ] == [spec.leaf_count for spec in STATE_0304_GROUPS]
    assert {
        node.title
        for node in tree.group_nodes()
        if node.node_type == SemanticNodeType.CLASSIFICATION_SUBGROUP
    }.issuperset({"мерлузы рода Merluccius", "акул"})
    assert set(tree.real_codes_in_tree()) == set(tree.expected_real_codes)


def test_shuffled_records_produce_the_same_exact_state() -> None:
    expected = SemanticNavigationBuilder().build_heading_from_records(
        HEADING,
        _records(),
    )
    shuffled = SemanticNavigationBuilder().build_heading_from_records(
        HEADING,
        list(reversed(_records())),
    )

    assert [_signature(group) for group in _bounded_groups(expected)] == [
        _signature(group) for group in _bounded_groups(shuffled)
    ]


@pytest.mark.parametrize(
    "drift",
    (
        "marker",
        "depth",
        "finality",
        "hidden_boundary",
        "missing",
        "extra",
        "same_count_substitution",
        "parent",
        "leaf",
        "leaf_unknown",
        "missing_pad",
        "extra_flat_code",
        "flat_parent",
        "inner_whitespace",
        "unicode_normalization",
    ),
)
def test_any_source_or_topology_drift_disables_all_five_states(drift: str) -> None:
    records = _records()
    by_code = {record.code: record for record in records}
    if drift == "marker":
        by_code["0304390000"].description = by_code[
            "0304390000"
        ].description.replace("свежее", "копченое")
    elif drift == "depth":
        by_code["0304498000"].description = by_code[
            "0304498000"
        ].description.replace(
            "– прочее, свежее или охлажденное:",
            "– – прочее, свежее или охлажденное:",
        )
    elif drift == "finality":
        by_code["0304690000"].description += " – – поздний подзаголовок:"
    elif drift == "hidden_boundary":
        by_code["0304450000"].description += " – скрытая категория:"
    elif drift == "missing":
        records.remove(by_code["0304520000"])
    elif drift == "extra":
        records.append(
            SourceRecord(
                code="0304580000",
                description="– – лишний товар",
                is_leaf=True,
                parent_code=HEADING,
            )
        )
    elif drift == "same_count_substitution":
        records.remove(by_code["0304520000"])
        records.append(
            SourceRecord(
                code="0304580000",
                description="– – подмененный товар",
                is_leaf=True,
                parent_code=HEADING,
            )
        )
    elif drift == "parent":
        by_code["0304741100"].parent_code = "0304710000"
    elif drift == "leaf":
        by_code["0304820000"].is_leaf = True
    elif drift == "leaf_unknown":
        by_code["0304820000"].is_leaf = None
    elif drift == "missing_pad":
        records.remove(by_code["0304000000"])
    elif drift == "extra_flat_code":
        records.append(
            SourceRecord(
                code="0304611000",
                description="– – новый вложенный товар",
                is_leaf=True,
                parent_code="0304610000",
            )
        )
    elif drift == "flat_parent":
        by_code["0304610000"].parent_code = "0304590000"
    elif drift == "inner_whitespace":
        by_code["0304390000"].description = by_code[
            "0304390000"
        ].description.replace("филе прочей", "филе  прочей")
    else:
        by_code["0304390000"].description = by_code[
            "0304390000"
        ].description.replace("й", "и\u0306")

    extraction = SemanticStructureExtractor().extract(HEADING, records)
    assert all(group.reason != STATE_0304_REASON for group in extraction.groups)

    tree = SemanticNavigationBuilder().build_heading_from_records(HEADING, records)
    assert _bounded_groups(tree) == []
    assert set(tree.real_codes_in_tree()) == set(tree.expected_real_codes)


@pytest.mark.parametrize(
    "malformation",
    (
        "partial_state",
        "topology_after_extract",
        "flat_parent_after_extract",
        "missing_pad_after_extract",
    ),
)
def test_builder_atomically_unwraps_all_states_and_preserves_subgroups(
    malformation: str,
) -> None:
    extraction = SemanticStructureExtractor().extract(HEADING, _records())
    if malformation == "partial_state":
        extraction.groups.remove(
            next(
                group
                for group in extraction.groups
                if group.reason == STATE_0304_REASON
                and group.source_code == "0304498000"
            )
        )
    elif malformation == "topology_after_extract":
        extraction.records_by_code["0304820000"].is_leaf = None
    elif malformation == "flat_parent_after_extract":
        extraction.records_by_code["0304610000"].parent_code = "0304590000"
    else:
        del extraction.records_by_code["0304000000"]

    tree = SemanticNavigationBuilder()._assemble(
        HEADING,
        "Филе рыбное и прочее мясо рыбы",
        extraction,
    )

    assert _bounded_groups(tree) == []
    assert {
        node.title for node in tree.group_nodes()
    }.issuperset({"мерлузы рода Merluccius", "акул"})
    assert set(tree.real_codes_in_tree()) == set(tree.expected_real_codes)


def test_validator_retains_one_honest_oversized_warning() -> None:
    tree = SemanticNavigationBuilder().build_heading_from_records(HEADING, _records())
    result = SemanticNavigationValidator().validate(
        tree,
        db_codes=tree.expected_real_codes,
    )

    warnings = [
        issue
        for issue in result.issues
        if issue.code == "oversized_unsplit_group"
    ]
    assert not result.critical_issues
    assert len(warnings) == 1
    assert warnings[0].severity == "warning"
    assert "33" in warnings[0].message
    assert "limit=30" in warnings[0].message


def test_codeless_guide_ids_are_deterministic_and_title_sensitive() -> None:
    class CanonicalStub:
        @staticmethod
        def get_by_code(code: str):  # noqa: ANN205
            return SimpleNamespace(stable_id=f"node-{code}")

        @staticmethod
        def get_by_display_code(code: str):  # noqa: ANN205
            return None

    service = GuidedTnvedNavigationService()
    first = SemanticNavigationBuilder().build_heading_from_records(
        HEADING,
        _records(),
    )
    second = SemanticNavigationBuilder().build_heading_from_records(
        HEADING,
        list(reversed(_records())),
    )
    service._bind_to_canonical(first, CanonicalStub())
    service._bind_to_canonical(second, CanonicalStub())

    first_groups = _bounded_groups(first)
    second_groups = _bounded_groups(second)
    assert [group.id for group in first_groups] == [
        group.id for group in second_groups
    ]
    coded_ids_before = {
        node.code: node.id
        for node in first.all_nodes()
        if node.carries_real_code and node.code
    }

    target = first_groups[1]
    prior_group_id = target.id
    target.title = f"{target.title} (новая принятая редакция)"
    service._bind_to_canonical(first, CanonicalStub())

    assert target.id != prior_group_id
    assert {
        node.code: node.id
        for node in first.all_nodes()
        if node.carries_real_code and node.code
    } == coded_ids_before


@pytest.mark.parametrize(
    "tamper",
    ("root_order", "title_case", "raw_depth", "all_identity_fields"),
)
def test_builder_rejects_misplaced_or_unrecognizably_tampered_wrapper(
    tamper: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = SemanticNavigationBuilder._apply_controlled_nesting

    def corrupt_after_nesting(root):  # noqa: ANN001, ANN202
        fallbacks = original(root)
        bounded = [
            node
            for node in root.children
            if node.metadata.get("reason") == STATE_0304_REASON
        ]
        if tamper == "root_order":
            first_index = root.children.index(bounded[0])
            second_index = root.children.index(bounded[1])
            root.children[first_index], root.children[second_index] = (
                root.children[second_index],
                root.children[first_index],
            )
        elif tamper == "title_case":
            bounded[0].title = bounded[0].title.upper()
        elif tamper == "raw_depth":
            bounded[0].metadata["raw"] = f"– – {bounded[0].title}:"
        else:
            target = bounded[1]
            target.title = "измененный заголовок"
            target.metadata["extracted_from"] = "0304000001"
            target.metadata["reason"] = "changed"
            target.metadata["verified_scope_kind"] = "changed"
        return fallbacks

    monkeypatch.setattr(
        SemanticNavigationBuilder,
        "_apply_controlled_nesting",
        staticmethod(corrupt_after_nesting),
    )
    tree = SemanticNavigationBuilder().build_heading_from_records(
        HEADING,
        _records(),
    )

    assert _bounded_groups(tree) == []
    assert all(
        node.node_type != SemanticNodeType.CLASSIFICATION_GROUP
        for node in tree.root.children
    )
    assert set(tree.real_codes_in_tree()) == set(tree.expected_real_codes)
