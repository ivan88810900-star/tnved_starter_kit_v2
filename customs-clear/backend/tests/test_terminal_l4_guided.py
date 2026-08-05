"""Exact terminal L4 regressions for Canonical and Guided TN VED."""

from __future__ import annotations

from app.services.guided_tnved_navigation import GuidedTnvedNavigationService
from app.services.semantic_navigation import SemanticNavigationBuilder
from app.services.tree_engine import (
    NodeType,
    ParsedCommodityRecord,
    TreeBuilder,
    TreeParseResult,
)


TERMINAL_CODE = "3914000000"
TERMINAL_TITLE = (
    "Смолы ионообменные на основе полимеров товарных позиций "
    "3901 – 3913, в первичных формах"
)


def _record(code: str, description: str, duty: str = "") -> ParsedCommodityRecord:
    return ParsedCommodityRecord(
        code10=code,
        description=description,
        raw_description=description,
        import_duty=duty,
    )


def _parse_result(
    records: list[ParsedCommodityRecord],
    *,
    leaf_flags: dict[str, bool],
) -> TreeParseResult:
    return TreeParseResult(
        commodities=records,
        chapter_notes={},
        db_codes=frozenset(record.code10 for record in records),
        leaf_flags=leaf_flags,
    )


def test_exact_terminal_l4_keeps_wrapper_and_materializes_real_leaf() -> None:
    parsed = _parse_result(
        [_record(TERMINAL_CODE, TERMINAL_TITLE, "6.5%")],
        leaf_flags={TERMINAL_CODE: True},
    )

    model = TreeBuilder().build_model(parsed)
    heading = model.get_by_code("3914")
    leaf = model.get_by_code(TERMINAL_CODE)

    assert heading is not None
    assert leaf is not None
    assert heading.node_type == NodeType.HEADING
    assert heading.title == TERMINAL_TITLE
    assert model.children(heading) == (leaf,)
    assert model.parent(leaf) is heading
    assert leaf.node_type == NodeType.COMMODITY
    assert leaf.level == 4
    assert leaf.title == TERMINAL_TITLE
    assert leaf.metadata["is_leaf"] is True
    assert leaf.metadata["is_codeless"] is False
    assert leaf.metadata["is_group"] is False
    assert leaf.metadata["import_duty"] == "6.5%"


def test_nonexact_or_nonterminal_pad_behavior_is_unchanged() -> None:
    terminal_record = _record(TERMINAL_CODE, TERMINAL_TITLE, "6.5%")
    nonexact = TreeBuilder().build_model(
        _parse_result(
            [terminal_record],
            leaf_flags={TERMINAL_CODE: False},
        )
    )
    exact = TreeBuilder().build_model(
        _parse_result(
            [terminal_record],
            leaf_flags={TERMINAL_CODE: True},
        )
    )

    nonexact_heading = nonexact.get_by_code("3914")
    exact_heading = exact.get_by_code("3914")
    assert nonexact_heading is not None
    assert exact_heading is not None
    assert nonexact.children(nonexact_heading) == ()
    assert nonexact.get_by_code(TERMINAL_CODE) is None
    assert nonexact_heading.stable_id == exact_heading.stable_id

    deeper_code = "9876110000"
    with_descendant = TreeBuilder().build_model(
        _parse_result(
            [
                _record("9876000000", "Test heading: – semantic group:"),
                _record(deeper_code, "– item"),
            ],
            leaf_flags={"9876000000": True, deeper_code: True},
        )
    )
    heading = with_descendant.get_by_code("9876")
    assert heading is not None
    assert with_descendant.get_by_code("9876000000") is None
    assert [node.code for node in with_descendant.children(heading)] == [deeper_code]


def test_guided_terminal_l4_is_direct_declarable_choice_from_model_snapshot() -> None:
    model = TreeBuilder().build_model(
        _parse_result(
            [_record(TERMINAL_CODE, TERMINAL_TITLE, "6.5%")],
            leaf_flags={TERMINAL_CODE: True},
        )
    )
    service = GuidedTnvedNavigationService(
        builder=SemanticNavigationBuilder(),
        model_loader=lambda: model,
    )

    result = service.build(object(), "3914")

    assert result["status"] == "OK"
    assert result["engine"]["snapshot_id"] == model.snapshot_id
    assert result["heading"]["title"] == TERMINAL_TITLE
    assert result["integrity"]["expected_real_codes"] == 1
    assert result["integrity"]["reachable_real_codes"] == 1
    assert result["integrity"]["canonical_bound_codes"] == 1
    assert result["integrity"]["semantic_groups"] == 0
    assert result["integrity"]["rejected_unsafe_groups"] == 0
    assert len(result["choices"]) == 1
    choice = result["choices"][0]
    assert choice["code"] == TERMINAL_CODE
    assert choice["title"] == TERMINAL_TITLE
    assert choice["role"] == "declarable_code"
    assert choice["is_leaf"] is True
    assert choice["canonical_anchor"]["stable_id"] == model.get_by_code(
        TERMINAL_CODE
    ).stable_id
