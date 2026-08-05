"""Canonical leaf-role and code-containment regressions for Guided TN VED."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.core import HsRate
from app.models.tnved import Chapter, Commodity, Section
from app.services.guided_tnved_navigation import GuidedTnvedNavigationService
from app.services.semantic_navigation import (
    SemanticNavigationBuilder,
    SemanticNavigationValidator,
    SemanticNodeType,
    SourceRecord,
)
from app.services.tree_engine import ParsedCommodityRecord, TreeBuilder, TreeParseResult


PARENT_CODE = "0302350000"
CHILD_CODES = (
    "0302351100",
    "0302351900",
    "0302359100",
    "0302359900",
)


def _record(code: str, description: str, duty: str = "") -> ParsedCommodityRecord:
    return ParsedCommodityRecord(
        code10=code,
        description=description,
        raw_description=description,
        import_duty=duty,
    )


def _bluefin_model():
    records = [
        _record("0302000000", "Рыба свежая: – тунец:"),
        _record(
            PARENT_CODE,
            "– – тунец синий и тихоокеанский голубой: – – тунец синий:",
        ),
        _record(CHILD_CODES[0], "– – – – для промышленного производства"),
        _record(
            CHILD_CODES[1],
            "– – – – прочий – – тунец тихоокеанский голубой:",
        ),
        _record(CHILD_CODES[2], "– – – – для промышленного производства"),
        _record(CHILD_CODES[3], "– – – – прочий"),
    ]
    return TreeBuilder().build_model(
        TreeParseResult(
            commodities=records,
            chapter_notes={},
            db_codes=frozenset(record.code10 for record in records),
            leaf_flags={
                "0302000000": False,
                PARENT_CODE: False,
                **{code: True for code in CHILD_CODES},
            },
        )
    )


def _walk_choices(nodes: list[dict]):
    for node in nodes:
        yield node
        yield from _walk_choices(list(node.get("children") or []))


def test_nonleaf_code_branch_retains_semantic_subgroups_and_four_true_leaves() -> None:
    model = _bluefin_model()
    frozen = {record.code: record for record in model.source_records_for_heading("0302")}

    assert frozen[PARENT_CODE].is_leaf is False
    assert frozen[PARENT_CODE].parent_code == "0302"
    assert all(frozen[code].is_leaf is True for code in CHILD_CODES)
    assert all(frozen[code].parent_code == PARENT_CODE for code in CHILD_CODES)

    result = GuidedTnvedNavigationService(model_loader=lambda: model).build(
        object(), "0302"
    )

    assert result["status"] == "OK"
    assert result["integrity"]["critical_issues"] == []
    assert result["integrity"]["source_code_nodes"] == 5
    assert result["integrity"]["canonical_declarable_leaves"] == 4
    assert result["integrity"]["declarable_leaf_codes"] == 4
    assert result["integrity"]["semantic_max_depth"] == 2

    choices = list(_walk_choices(result["choices"]))
    branch = next(node for node in choices if node.get("code") == PARENT_CODE)
    assert branch["role"] == "code_branch"
    assert branch["is_leaf"] is False
    assert branch["result_count"] == 4
    subgroups = [
        child
        for child in branch["children"]
        if child["kind"] == "classification_subgroup"
    ]
    assert len(subgroups) == 2
    descendants = list(_walk_choices(branch["children"]))
    assert {node.get("code") for node in descendants if node.get("code")} == set(
        CHILD_CODES
    )
    assert all(
        node["role"] == "declarable_code"
        for node in descendants
        if node.get("code")
    )


def test_published_nodes_reject_metadata_mutation_and_source_evidence_stays_frozen() -> None:
    model = _bluefin_model()
    before = model.source_records_for_heading("0302")

    with pytest.raises(TypeError):
        model.get_by_code(PARENT_CODE).metadata["is_leaf"] = True
    with pytest.raises(TypeError):
        model.get_by_code(CHILD_CODES[0]).metadata["is_leaf"] = False

    assert model.source_records_for_heading("0302") == before
    evidence = {record.code: record for record in before}
    assert evidence[PARENT_CODE].is_leaf is False
    assert evidence[CHILD_CODES[0]].is_leaf is True

    result = GuidedTnvedNavigationService(model_loader=lambda: model).build(
        object(), "0302"
    )
    branch = next(
        node
        for node in _walk_choices(result["choices"])
        if node.get("code") == PARENT_CODE
    )
    assert result["status"] == "OK"
    assert branch["role"] == "code_branch"
    assert branch["result_count"] == 4


def test_validator_rejects_childless_explicit_nonleaf_and_leaf_role_mismatch() -> None:
    tree = SemanticNavigationBuilder().build_heading_from_records(
        "9999",
        [
            SourceRecord(
                "9999110000",
                "Тестовая недекларируемая ветвь",
                is_leaf=False,
                parent_code="9999",
            )
        ],
    )
    validator = SemanticNavigationValidator()

    first = validator.validate(tree, db_codes=tree.expected_real_codes)
    assert "nonleaf_without_reachable_children" in {
        issue.code for issue in first.critical_issues
    }

    branch = next(node for node in tree.all_nodes() if node.code == "9999110000")
    branch.node_type = SemanticNodeType.LEAF
    second = validator.validate(tree, db_codes=tree.expected_real_codes)
    assert "leaf_role_mismatch" in {issue.code for issue in second.critical_issues}


def test_validator_rejects_wrong_nearest_canonical_code_ancestor() -> None:
    tree = SemanticNavigationBuilder().build_heading_from_records(
        "9999",
        [
            SourceRecord(
                "9999110000",
                "Тестовый лист",
                is_leaf=True,
                parent_code="9998",
            )
        ],
    )

    result = SemanticNavigationValidator().validate(
        tree,
        db_codes=tree.expected_real_codes,
    )

    assert "canonical_parent_mismatch" in {
        issue.code for issue in result.critical_issues
    }


def _offline_session(*, include_hs_rates: bool):
    engine = create_engine("sqlite://")
    tables = [Section.__table__, Chapter.__table__, Commodity.__table__]
    if include_hs_rates:
        tables.append(HsRate.__table__)
    Base.metadata.create_all(engine, tables=tables)
    return sessionmaker(bind=engine)()


def _seed_terminal_l4(db, *, with_exact_rate: bool) -> None:
    section = Section(roman_number="I", title="Test", notes="")
    db.add(section)
    db.flush()
    chapter = Chapter(section_id=section.id, code="04", title="Test", notes="")
    db.add(chapter)
    db.flush()
    title = "Мед натуральный"
    db.add_all(
        [
            Commodity(chapter_id=chapter.id, code="0409", description=title),
            Commodity(
                chapter_id=chapter.id,
                code="0409000000",
                description=title,
                import_duty="12%",
            ),
        ]
    )
    if with_exact_rate:
        db.add(HsRate(hs_code="0409000000", hs_prefix="0409", duty_rate="12"))
    db.commit()


def test_offline_builder_keeps_exact_terminal_l4_with_explicit_heading_row() -> None:
    db = _offline_session(include_hs_rates=True)
    try:
        _seed_terminal_l4(db, with_exact_rate=True)
        tree = SemanticNavigationBuilder().build_heading(db, "0409")
    finally:
        db.close()

    assert tree.root.code == "0409"
    assert tree.root.title == "Мед натуральный"
    assert len(tree.root.children) == 1
    leaf = tree.root.children[0]
    assert leaf.code == "0409000000"
    assert leaf.node_type == SemanticNodeType.LEAF
    assert leaf.metadata["leaf_evidence"] is True
    assert leaf.metadata["import_duty"] == "12%"


def test_offline_builder_is_safe_when_minimal_db_has_no_hs_rates_table() -> None:
    db = _offline_session(include_hs_rates=False)
    try:
        _seed_terminal_l4(db, with_exact_rate=False)
        tree = SemanticNavigationBuilder().build_heading(db, "0409")
    finally:
        db.close()

    assert tree.root.code == "0409"
    assert tree.root.children == []
