"""Самодостаточные проверки controlled hierarchy без зависимости от полной БД."""

from __future__ import annotations

from app.services.semantic_navigation import (
    MAX_UNSPLIT_GROUP_CODES,
    ExtractedGroup,
    ExtractionResult,
    SemanticNavigationBuilder,
    SemanticNavigationValidator,
    SemanticNodeType,
    SemanticStructureExtractor,
    SourceRecord,
)
from scripts.diagnose_guided_tnved_navigation import _hierarchy_checks


def _extract(heading: str, records: list[SourceRecord]) -> ExtractionResult:
    return SemanticStructureExtractor().extract(heading, records)


def _assemble(extraction: ExtractionResult, title: str = "Тестовая позиция"):
    return SemanticNavigationBuilder()._assemble(
        extraction.heading,
        title,
        extraction,
    )


def _group(tree, title: str):
    return next(node for node in tree.group_nodes() if node.title == title)


def test_dash_depth_and_parent_hints_are_extracted_from_official_text() -> None:
    extraction = _extract(
        "5208",
        [
            SourceRecord(
                "5208000000",
                "Ткани хлопчатобумажные: – неотбеленные:",
            ),
            SourceRecord(
                "5208110000",
                "– – полотна массой не более 100 г/м² "
                "– – полотняного переплетения:",
            ),
            SourceRecord(
                "5208120000",
                "– – прочие – отбеленные:",
            ),
            SourceRecord(
                "5208210000",
                "– – полотна массой не более 100 г/м² "
                "– – полотняного переплетения:",
            ),
            SourceRecord("5208220000", "– – прочие"),
        ],
    )

    groups = extraction.groups
    assert [group.title for group in groups] == [
        "неотбеленные",
        "полотняного переплетения",
        "отбеленные",
        "полотняного переплетения",
    ]
    assert [group.dash_depth for group in groups] == [1, 2, 1, 2]
    assert groups[1].parent_title_hint == "неотбеленные"
    assert groups[1].hierarchy_hint == "dash_depth"
    assert groups[3].parent_title_hint == "отбеленные"


def test_5208_repeated_titles_are_nested_under_their_own_parent() -> None:
    extraction = _extract(
        "5208",
        [
            SourceRecord(
                "5208000000",
                "Ткани хлопчатобумажные: – неотбеленные:",
            ),
            SourceRecord(
                "5208110000",
                "– – полотна – – полотняного переплетения:",
            ),
            SourceRecord("5208120000", "– – прочие – отбеленные:"),
            SourceRecord(
                "5208210000",
                "– – полотна – – полотняного переплетения:",
            ),
            SourceRecord("5208220000", "– – прочие"),
        ],
    )

    tree = _assemble(extraction)
    top_groups = [
        node
        for node in tree.root.children
        if node.node_type == SemanticNodeType.CLASSIFICATION_GROUP
    ]

    assert [node.title for node in top_groups] == [
        "неотбеленные",
        "отбеленные",
    ]
    for parent in top_groups:
        subgroups = [
            node
            for node in parent.children
            if node.node_type == SemanticNodeType.CLASSIFICATION_SUBGROUP
        ]
        assert [node.title for node in subgroups] == [
            "полотняного переплетения"
        ]
        assert subgroups[0].metadata["nested_by"] == "dash_depth"

    assert set(tree.real_codes_in_tree()) == set(tree.expected_real_codes)
    validation = SemanticNavigationValidator().validate(
        tree,
        db_codes=tree.expected_real_codes,
    )
    assert not validation.has_critical
    assert not tree.nesting_fallbacks


def test_tuna_title_prefix_is_a_conservative_secondary_hint() -> None:
    extraction = _extract(
        "0303",
        [
            SourceRecord("0303000000", "Рыба мороженая: – тунец:"),
            SourceRecord(
                "0303110000",
                "– – первый товар – тунец синий:",
            ),
            SourceRecord(
                "0303120000",
                "– – второй товар – тунец тихоокеанский голубой:",
            ),
            SourceRecord("0303130000", "– – третий товар"),
        ],
    )

    assert extraction.groups[1].dash_depth == 1
    assert extraction.groups[1].hierarchy_hint == "title_prefix"
    assert extraction.groups[2].parent_title_hint == "тунец"

    tree = _assemble(extraction)
    tuna = _group(tree, "тунец")
    nested_titles = [
        node.title
        for node in tuna.children
        if node.node_type == SemanticNodeType.CLASSIFICATION_SUBGROUP
    ]
    assert nested_titles == [
        "тунец синий",
        "тунец тихоокеанский голубой",
    ]
    assert set(tree.real_codes_in_tree()) == set(tree.expected_real_codes)


def test_rejected_level_one_candidate_closes_parent_segment() -> None:
    extraction = _extract(
        "8517",
        [
            SourceRecord("8517000000", "Аппаратура связи: – аппаратура:"),
            SourceRecord("8517110000", "– – устройство – 10 ГГц:"),
            SourceRecord(
                "8517120000",
                "– – устройство – – аппаратура специальная:",
            ),
            SourceRecord("8517130000", "– – устройство"),
        ],
    )

    assert [candidate.title for candidate in extraction.rejected] == ["10 ГГц"]
    child = next(
        group for group in extraction.groups if group.title == "аппаратура специальная"
    )
    assert child.dash_depth == 2
    assert child.parent_title_hint is None

    tree = _assemble(extraction)
    assert all(
        node.node_type != SemanticNodeType.CLASSIFICATION_SUBGROUP
        for node in tree.group_nodes()
    )
    assert [item.reason for item in tree.nesting_fallbacks] == [
        "no_active_parent_hint"
    ]


def test_oversized_unsplit_subgroup_falls_back_to_flat_without_code_loss() -> None:
    heading = "9999"
    codes = [
        f"9999{index:06d}"
        for index in range(1, MAX_UNSPLIT_GROUP_CODES + 3)
    ]
    records = {
        code: SourceRecord(code, f"Тестовый товар {index}")
        for index, code in enumerate(codes, start=1)
    }
    extraction = ExtractionResult(
        heading=heading,
        pad_code=None,
        commodity_codes=codes,
        records_by_code=records,
        groups=[
            ExtractedGroup(
                title="родитель",
                raw="родитель",
                source_code="9999000000",
                after_code=None,
                confidence="high",
                reason="canonical_merged_header",
            ),
            ExtractedGroup(
                title="слишком широкая подгруппа",
                raw="– слишком широкая подгруппа",
                source_code=codes[0],
                after_code=codes[0],
                confidence="medium",
                reason="embedded_subheader",
                dash_depth=2,
                parent_title_hint="родитель",
                parent_source_code_hint="9999000000",
                hierarchy_hint="dash_depth",
            ),
        ],
    )

    tree = _assemble(extraction)
    wide = _group(tree, "слишком широкая подгруппа")

    assert wide.node_type == SemanticNodeType.CLASSIFICATION_GROUP
    assert wide.parent_id == tree.root.id
    assert len(tree.nesting_fallbacks) == 1
    assert tree.nesting_fallbacks[0].reason == "unsplit_span_exceeds_limit"
    assert (
        tree.nesting_fallbacks[0].real_code_count
        == MAX_UNSPLIT_GROUP_CODES + 1
    )
    assert set(tree.real_codes_in_tree()) == set(tree.expected_real_codes)
    validation = SemanticNavigationValidator().validate(
        tree,
        db_codes=tree.expected_real_codes,
    )
    assert not validation.has_critical
    assert "oversized_unsplit_group" in {
        issue.code for issue in validation.issues
    }


def test_depth_and_parent_links_are_refreshed_after_reparenting() -> None:
    extraction = _extract(
        "0303",
        [
            SourceRecord("0303000000", "Рыба: – тунец:"),
            SourceRecord("0303110000", "– – товар – – тунец синий:"),
            SourceRecord("0303120000", "– – товар"),
        ],
    )
    tree = _assemble(extraction)
    subgroup = _group(tree, "тунец синий")

    assert subgroup.depth == 2
    assert subgroup.parent_id == _group(tree, "тунец").id
    for node in subgroup.iter_descendants():
        parent = tree.nodes_by_id()[node.parent_id or ""]
        assert node.depth == parent.depth + 1


def test_aggregate_full_data_gate_checks_nested_targets_without_raw_output() -> None:
    def semantic(title: str, children: list[dict] | None = None) -> dict:
        return {
            "title": title,
            "role": "semantic_choice",
            "kind": "classification_subgroup",
            "code": None,
            "children": children or [],
        }

    tuna = semantic(
        "тунец",
        [
            semantic("тунец синий"),
            semantic("тунец тихоокеанский голубой"),
            {
                "title": "реальный код",
                "role": "declarable_code",
                "kind": "leaf",
                "code": "0303451200",
                "children": [],
            },
        ],
    )
    assert all(_hierarchy_checks("0303", [tuna]).values())

    finish_groups = [
        semantic(finish, [semantic("полотняного переплетения")])
        for finish in ("неотбеленные", "отбеленные", "окрашенные")
    ]
    assert all(_hierarchy_checks("5208", finish_groups).values())

    technical = semantic("10 ГГц")
    assert not all(_hierarchy_checks("8517", [technical]).values())
