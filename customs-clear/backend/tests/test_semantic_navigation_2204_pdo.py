"""Bounded 2204 PDO semantic slice regressions (TASK-SEMANTIC-006)."""

from __future__ import annotations

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
    BULK_2204_CONTEXT_SIGNATURE,
    BULK_2204_OTHER_ANCHOR_CODE,
    BULK_2204_OTHER_CODES,
    BULK_2204_OTHER_DEPTH,
    BULK_2204_OTHER_LEAF_COUNT,
    BULK_2204_OTHER_RAW,
    BULK_2204_OTHER_REASON,
    BULK_2204_OTHER_SCOPE_KIND,
    BULK_2204_OTHER_STOP_CODE,
    BULK_2204_PARENT_CODE,
    BULK_2204_PARENT_DESCRIPTION,
    BULK_2204_ROOT_ANCHOR_CODE,
    BULK_2204_ROOT_ANCHOR_DESCRIPTION,
    PDO_2204_COLOUR_SIGNATURE,
    PDO_2204_OTHER_ANCHOR_CODE,
    PDO_2204_OTHER_CODES,
    PDO_2204_OTHER_DEPTH,
    PDO_2204_OTHER_LEAF_COUNT,
    PDO_2204_OTHER_RAW,
    PDO_2204_OTHER_REASON,
    PDO_2204_OTHER_SCOPE_KIND,
)
from app.services.tree_engine import (
    CanonicalModel,
    ClassificationGroupNode,
    CommodityNode,
    HeadingNode,
    ParsedCommodityRecord,
    assign_stable_ids,
    compute_snapshot_id,
)

PARENT_CODE = "2204210000"
ANCHOR_CODE = "2204210900"
STOP_CODE = "2204217800"
AFTER_STOP_CODE = "2204217900"
PDO_TITLE = "вина с защищенным наименованием по происхождению"
PDO_OFFICIAL_HEADER = (
    "вина с защищенным наименованием по происхождению "
    "(Protected Designation of Origin, PDO)"
)
PGI_TITLE = "вина с защищенным географическим указанием"
PGI_OFFICIAL_HEADER = (
    "вина с защищенным географическим указанием "
    "(Protected Geographical Indication, PGI)"
)
PDO_CODES = (
    "2204211100",
    "2204211200",
    "2204211300",
    "2204211700",
    "2204211800",
    "2204211900",
    "2204212200",
    "2204212300",
    "2204212400",
    "2204212600",
    "2204212700",
    "2204212800",
    "2204213200",
    "2204213400",
    "2204213600",
    "2204213700",
    "2204213800",
    "2204214200",
    "2204214300",
    "2204214400",
    "2204214600",
    "2204214700",
    "2204214800",
    "2204216200",
    "2204216600",
    "2204216700",
    "2204216800",
    "2204216900",
    "2204217100",
    "2204217400",
    "2204217600",
    "2204217700",
    STOP_CODE,
)

ANCHOR_DESCRIPTION = (
    "– – – – прочее – – – прочие: "
    "– – – – произведенные в Европейском союзе: "
    "– – – – – с фактической концентрацией спирта не более 15 об.%: "
    f"– – – – – – {PDO_OFFICIAL_HEADER}:"
)
STOP_DESCRIPTION = (
    "– – – – – – – – прочие "
    f"– – – – – – {PGI_OFFICIAL_HEADER}:"
)
PDO_SOURCE_DESCRIPTIONS = {
    code: description
    for code, _parent, _is_leaf, description in PDO_2204_COLOUR_SIGNATURE
}


def _records() -> list[SourceRecord]:
    records = [
        SourceRecord(
            code="2204",
            description="Вина виноградные натуральные",
            is_leaf=False,
        ),
        SourceRecord(
            code=PARENT_CODE,
            description="– – в сосудах емкостью 2 л или менее",
            is_leaf=False,
        ),
        SourceRecord(
            code=ANCHOR_CODE,
            description=ANCHOR_DESCRIPTION,
            is_leaf=True,
            parent_code=PARENT_CODE,
        ),
    ]
    records.extend(
        SourceRecord(
            code=code,
            description=PDO_SOURCE_DESCRIPTIONS[code],
            is_leaf=True,
            parent_code=PARENT_CODE,
        )
        for code in PDO_CODES
    )
    records.append(
        SourceRecord(
            code=AFTER_STOP_CODE,
            description="– – – – – – – белые",
            is_leaf=True,
            parent_code=PARENT_CODE,
        )
    )
    return records


def _bulk_records() -> list[SourceRecord]:
    records = [
        SourceRecord(
            code="2204",
            description="Вина виноградные натуральные",
            is_leaf=False,
        ),
        SourceRecord(
            code=BULK_2204_PARENT_CODE,
            description=BULK_2204_PARENT_DESCRIPTION,
            is_leaf=False,
        ),
        SourceRecord(
            code=BULK_2204_ROOT_ANCHOR_CODE,
            description=BULK_2204_ROOT_ANCHOR_DESCRIPTION,
            is_leaf=True,
            parent_code=BULK_2204_PARENT_CODE,
        ),
    ]
    records.extend(
        SourceRecord(
            code=code,
            description=description,
            is_leaf=is_leaf,
            parent_code=parent,
        )
        for code, parent, is_leaf, description in BULK_2204_CONTEXT_SIGNATURE
    )
    records.append(
        SourceRecord(
            code="2204227900",
            description="– – – – – – – – прочий товар",
            is_leaf=True,
            parent_code=BULK_2204_PARENT_CODE,
        )
    )
    return records


def _pdo_group(tree):
    return next(
        node
        for node in tree.group_nodes()
        if node.metadata.get("reason") == "bounded_2204_official_pdo_chain"
    )


def _pdo_other_group(tree):
    return next(
        node
        for node in tree.group_nodes()
        if node.metadata.get("reason") == PDO_2204_OTHER_REASON
    )


def _bulk_other_group(tree):
    return next(
        node
        for node in tree.group_nodes()
        if node.metadata.get("reason") == BULK_2204_OTHER_REASON
    )


def _canonical_model() -> CanonicalModel:
    records = _records()
    root = HeadingNode(title="Вина виноградные натуральные", code="2204")
    parent = ClassificationGroupNode(
        title="в сосудах емкостью 2 л или менее",
        code=PARENT_CODE,
        level=6,
        metadata={
            "display_code": "220421",
            "is_leaf": False,
            "is_codeless": True,
            "is_group": True,
        },
    )
    root.add_child(parent)
    for record in records:
        if record.code in {"2204", PARENT_CODE}:
            continue
        parent.add_child(
            CommodityNode(
                title=f"Товар {record.code}",
                code=record.code,
                level=10,
                metadata={
                    "display_code": record.code,
                    "is_leaf": True,
                    "is_codeless": False,
                    "is_group": False,
                },
            )
        )
    roots = [root]
    assign_stable_ids(roots)
    snapshot_id = compute_snapshot_id(roots)
    source_records = [
        ParsedCommodityRecord(
            code10=record.code,
            description=record.description,
            raw_description=record.description,
            import_duty=record.import_duty,
        )
        for record in records
    ]
    return CanonicalModel.from_roots(
        roots,
        snapshot_id=snapshot_id,
        source_records=source_records,
    )


def test_exact_later_packed_header_and_same_depth_boundary_are_accepted() -> None:
    extraction = SemanticStructureExtractor().extract("2204", _records())
    pdo = next(
        group
        for group in extraction.groups
        if group.reason == "bounded_2204_official_pdo_chain"
    )
    pgi = next(
        group
        for group in extraction.groups
        if group.source_code == STOP_CODE and group.title == PGI_TITLE
    )

    assert pdo.title == PDO_TITLE
    assert pdo.raw == f"– – – – – – {PDO_OFFICIAL_HEADER}:"
    assert pdo.source_code == ANCHOR_CODE
    assert pdo.after_code == ANCHOR_CODE
    assert pdo.dash_depth == pgi.dash_depth == 6
    assert pdo.confidence == "high"
    assert pdo.verified_scope_kind == "canonical_sibling_leaf_interval"
    assert pdo.verified_scope_start_exclusive == ANCHOR_CODE
    assert pdo.verified_scope_end_inclusive == STOP_CODE
    assert pdo.verified_scope_parent_code == PARENT_CODE
    assert pdo.verified_scope_leaf_count == 33


def test_exact_retained_pdo_other_boundary_is_accepted() -> None:
    extraction = SemanticStructureExtractor().extract("2204", _records())
    other = next(
        group
        for group in extraction.groups
        if group.reason == PDO_2204_OTHER_REASON
    )

    assert other.title == "прочие"
    assert other.raw == PDO_2204_OTHER_RAW
    assert other.source_code == PDO_2204_OTHER_ANCHOR_CODE
    assert other.after_code == PDO_2204_OTHER_ANCHOR_CODE
    assert other.dash_depth == PDO_2204_OTHER_DEPTH == 7
    assert other.confidence == "high"
    assert other.verified_scope_kind == PDO_2204_OTHER_SCOPE_KIND
    assert other.verified_scope_start_exclusive == PDO_2204_OTHER_ANCHOR_CODE
    assert other.verified_scope_end_inclusive == STOP_CODE
    assert other.verified_scope_parent_code == PARENT_CODE
    assert other.verified_scope_leaf_count == PDO_2204_OTHER_LEAF_COUNT == 16


def test_exact_retained_220422_other_boundary_is_accepted() -> None:
    extraction = SemanticStructureExtractor().extract("2204", _bulk_records())
    other = next(
        group
        for group in extraction.groups
        if group.reason == BULK_2204_OTHER_REASON
    )

    assert other.title == "прочие"
    assert other.raw == BULK_2204_OTHER_RAW
    assert other.source_code == BULK_2204_OTHER_ANCHOR_CODE
    assert other.after_code == BULK_2204_OTHER_ANCHOR_CODE
    assert other.dash_depth == BULK_2204_OTHER_DEPTH == 7
    assert other.confidence == "high"
    assert other.verified_scope_kind == BULK_2204_OTHER_SCOPE_KIND
    assert other.verified_scope_start_exclusive == BULK_2204_OTHER_ANCHOR_CODE
    assert other.verified_scope_end_inclusive == BULK_2204_OTHER_STOP_CODE
    assert other.verified_scope_parent_code == BULK_2204_PARENT_CODE
    assert other.verified_scope_leaf_count == BULK_2204_OTHER_LEAF_COUNT == 7


def test_builder_places_exact_220422_other_group_under_canonical_parent() -> None:
    tree = SemanticNavigationBuilder().build_heading_from_records(
        "2204",
        _bulk_records(),
    )
    other = _bulk_other_group(tree)
    parent = next(
        node for node in tree.all_nodes() if node.code == BULK_2204_PARENT_CODE
    )

    assert other.node_type == SemanticNodeType.CLASSIFICATION_GROUP
    assert other.parent_id == parent.id
    assert tuple(node.code for node in other.children) == BULK_2204_OTHER_CODES
    assert len(other.children) == BULK_2204_OTHER_LEAF_COUNT == 7
    assert set(tree.real_codes_in_tree()) == set(tree.expected_real_codes)
    validation = SemanticNavigationValidator().validate(
        tree,
        db_codes=tree.expected_real_codes,
    )
    assert not validation.has_critical
    assert all(issue.code != "oversized_unsplit_group" for issue in validation.issues)


def test_builder_keeps_exact_33_leaf_boundary_with_retained_other_step() -> None:
    tree = SemanticNavigationBuilder().build_heading_from_records("2204", _records())
    pdo = _pdo_group(tree)
    other = _pdo_other_group(tree)
    parent = next(node for node in tree.all_nodes() if node.code == PARENT_CODE)
    code_nodes = [node for node in pdo.iter_descendants() if node.code]

    assert pdo.title == PDO_TITLE
    assert pdo.code is None
    assert pdo.source == "semantic_extraction"
    assert pdo.parent_id == parent.id
    assert pdo.metadata["extracted_from"] == ANCHOR_CODE
    assert pdo.metadata["raw"] == f"– – – – – – {PDO_OFFICIAL_HEADER}:"
    assert tuple(node.code for node in code_nodes) == PDO_CODES
    assert len(pdo.children) == 18
    assert sum(child.carries_real_code for child in pdo.children) == 17
    assert other.node_type == SemanticNodeType.CLASSIFICATION_SUBGROUP
    assert other.parent_id == pdo.id
    assert tuple(node.code for node in other.children) == PDO_2204_OTHER_CODES
    assert len(other.children) == PDO_2204_OTHER_LEAF_COUNT == 16
    assert all(node.node_type == SemanticNodeType.LEAF for node in code_nodes)
    assert STOP_CODE in {str(node.code) for node in code_nodes}
    assert AFTER_STOP_CODE not in {str(node.code) for node in code_nodes}
    assert set(tree.real_codes_in_tree()) == set(tree.expected_real_codes)

    validation = SemanticNavigationValidator().validate(
        tree,
        db_codes=tree.expected_real_codes,
    )
    assert not validation.has_critical
    assert validation.issues == []


def test_rule_requires_canonical_evidence_and_exact_heading() -> None:
    offline_records = [
        SourceRecord(
            code=record.code,
            description=record.description,
            import_duty=record.import_duty,
        )
        for record in _records()
    ]

    for heading in ("2204", "2205"):
        extraction = SemanticStructureExtractor().extract(heading, offline_records)
        assert all(
            group.reason != "bounded_2204_official_pdo_chain"
            for group in extraction.groups
        )


def test_shuffled_source_records_build_the_same_verified_slice() -> None:
    records = _records()
    expected = SemanticNavigationBuilder().build_heading_from_records(
        "2204",
        records,
    )
    shuffled = SemanticNavigationBuilder().build_heading_from_records(
        "2204",
        list(reversed(records)),
    )

    assert tuple(
        node.code for node in _pdo_group(expected).iter_descendants() if node.code
    ) == PDO_CODES
    assert tuple(
        node.code for node in _pdo_group(shuffled).iter_descendants() if node.code
    ) == PDO_CODES


@pytest.mark.parametrize(
    "drift",
    ("other_anchor_product_text", "other_boundary_colon", "other_leaf_text"),
)
def test_pdo_other_source_drift_keeps_original_pdo_flat(drift: str) -> None:
    records = _records()
    by_code = {record.code: record for record in records}
    if drift == "other_anchor_product_text":
        by_code[PDO_2204_OTHER_ANCHOR_CODE].description = by_code[
            PDO_2204_OTHER_ANCHOR_CODE
        ].description.replace(
            "прочие – – – – – – – прочие:",
            "прочие (редакция) – – – – – – – прочие:",
        )
    elif drift == "other_boundary_colon":
        by_code[PDO_2204_OTHER_ANCHOR_CODE].description = by_code[
            PDO_2204_OTHER_ANCHOR_CODE
        ].description.removesuffix(":")
    else:
        by_code[PDO_2204_OTHER_CODES[0]].description += " (редакция источника)"

    extraction = SemanticStructureExtractor().extract("2204", records)
    assert all(group.reason != PDO_2204_OTHER_REASON for group in extraction.groups)
    tree = SemanticNavigationBuilder().build_heading_from_records("2204", records)
    pdo = _pdo_group(tree)

    assert all(
        group.metadata.get("reason") != PDO_2204_OTHER_REASON
        for group in tree.group_nodes()
    )
    assert len(pdo.children) == len(PDO_CODES) == 33
    assert tuple(node.code for node in pdo.children) == PDO_CODES
    assert set(tree.real_codes_in_tree()) == set(tree.expected_real_codes)


@pytest.mark.parametrize(
    "drift",
    ("parent_text", "root_anchor_text", "other_boundary_text", "leaf_text"),
)
def test_220422_other_source_drift_fails_flat_without_code_loss(drift: str) -> None:
    records = _bulk_records()
    by_code = {record.code: record for record in records}
    if drift == "parent_text":
        by_code[BULK_2204_PARENT_CODE].description += " (редакция)"
    elif drift == "root_anchor_text":
        by_code[BULK_2204_ROOT_ANCHOR_CODE].description += " (редакция)"
    elif drift == "other_boundary_text":
        by_code[BULK_2204_OTHER_ANCHOR_CODE].description = by_code[
            BULK_2204_OTHER_ANCHOR_CODE
        ].description.replace("– – – – – – – прочие:", "– – – – – – – иные:")
    else:
        by_code[BULK_2204_OTHER_CODES[0]].description += " (редакция)"

    extraction = SemanticStructureExtractor().extract("2204", records)
    assert all(group.reason != BULK_2204_OTHER_REASON for group in extraction.groups)
    tree = SemanticNavigationBuilder().build_heading_from_records("2204", records)
    assert all(
        group.metadata.get("reason") != BULK_2204_OTHER_REASON
        for group in tree.group_nodes()
    )
    assert set(tree.real_codes_in_tree()) == set(tree.expected_real_codes)


@pytest.mark.parametrize("drift", ("leaf_count", "identity", "raw"))
def test_builder_unwraps_malformed_pdo_other_but_keeps_all_33_pdo_leaves(
    drift: str,
) -> None:
    extraction = SemanticStructureExtractor().extract("2204", _records())
    other = next(
        group
        for group in extraction.groups
        if group.reason == PDO_2204_OTHER_REASON
    )
    if drift == "leaf_count":
        other.verified_scope_leaf_count -= 1
    elif drift == "identity":
        other.reason = "tampered"
        other.verified_scope_kind = "tampered"
    else:
        other.raw += " "

    tree = SemanticNavigationBuilder()._assemble(
        "2204",
        "Вина виноградные натуральные",
        extraction,
    )
    pdo = _pdo_group(tree)

    assert all(
        group.metadata.get("reason") != PDO_2204_OTHER_REASON
        for group in tree.group_nodes()
    )
    assert tuple(node.code for node in pdo.children) == PDO_CODES
    assert set(tree.real_codes_in_tree()) == set(tree.expected_real_codes)


def test_builder_rechecks_parent_role_before_publishing_pdo_other() -> None:
    extraction = SemanticStructureExtractor().extract("2204", _records())
    extraction.records_by_code[PARENT_CODE].is_leaf = True

    tree = SemanticNavigationBuilder()._assemble(
        "2204",
        "Вина виноградные натуральные",
        extraction,
    )
    pdo = _pdo_group(tree)

    assert all(
        group.metadata.get("reason") != PDO_2204_OTHER_REASON
        for group in tree.group_nodes()
    )
    assert tuple(node.code for node in pdo.children) == PDO_CODES
    assert set(tree.real_codes_in_tree()) == set(tree.expected_real_codes)


@pytest.mark.parametrize("drift", ("leaf_count", "identity", "raw"))
def test_builder_unwraps_malformed_220422_other_without_code_loss(
    drift: str,
) -> None:
    extraction = SemanticStructureExtractor().extract("2204", _bulk_records())
    other = next(
        group
        for group in extraction.groups
        if group.reason == BULK_2204_OTHER_REASON
    )
    if drift == "leaf_count":
        other.verified_scope_leaf_count -= 1
    elif drift == "identity":
        other.reason = "tampered"
        other.verified_scope_kind = "tampered"
    else:
        other.raw += " "

    tree = SemanticNavigationBuilder()._assemble(
        "2204",
        "Вина виноградные натуральные",
        extraction,
    )

    assert all(
        group.metadata.get("reason") != BULK_2204_OTHER_REASON
        for group in tree.group_nodes()
    )
    assert set(tree.real_codes_in_tree()) == set(tree.expected_real_codes)


@pytest.mark.parametrize(
    "drift",
    (
        "anchor_text",
        "anchor_same_depth_predecessor",
        "accepted_boundary_title",
        "hidden_same_depth_boundary",
        "hidden_shallower_boundary",
        "interior_substitution",
        "stop_depth",
        "stop_tail",
        "missing_first",
        "nonleaf",
        "wrong_parent",
    ),
)
def test_source_or_canonical_drift_fails_closed_without_code_loss(drift: str) -> None:
    records = _records()
    by_code = {record.code: record for record in records}
    if drift == "anchor_text":
        by_code[ANCHOR_CODE].description = by_code[ANCHOR_CODE].description.replace(
            "Protected Designation of Origin, PDO",
            "Protected Designation of Origin, PDX",
        )
    elif drift == "anchor_same_depth_predecessor":
        by_code[ANCHOR_CODE].description = by_code[ANCHOR_CODE].description.replace(
            f"– – – – – – {PDO_OFFICIAL_HEADER}",
            "– – – – – – новая официальная категория: "
            f"– – – – – – {PDO_OFFICIAL_HEADER}",
        )
    elif drift == "accepted_boundary_title":
        by_code[STOP_CODE].description = (
            "– – – – – – – – прочие "
            "– – – – – – иные защищенные вина: "
            f"– – – – – – {PGI_OFFICIAL_HEADER}:"
        )
    elif drift == "hidden_same_depth_boundary":
        by_code["2204213800"].description = (
            "– – – – – – – – прочие "
            "– – – – – – – прочие: "
            "– – – – – – новая официальная категория:"
        )
    elif drift == "hidden_shallower_boundary":
        by_code["2204213800"].description = (
            "– – – – – – – – прочие "
            "– – – – – – – прочие: "
            "– – – – – новая официальная категория:"
        )
    elif drift == "interior_substitution":
        records.remove(by_code["2204212200"])
        records.append(
            SourceRecord(
                code="2204212100",
                description="– – – – – – – – подмененный внутренний товар",
                is_leaf=True,
                parent_code=PARENT_CODE,
            )
        )
    elif drift == "stop_depth":
        by_code[STOP_CODE].description = by_code[STOP_CODE].description.replace(
            f"– – – – – – {PGI_OFFICIAL_HEADER}",
            f"– – – – – {PGI_OFFICIAL_HEADER}",
        )
    elif drift == "stop_tail":
        by_code[STOP_CODE].description += " – – – – – – прочие сортовые вина:"
    elif drift == "missing_first":
        records.remove(by_code[PDO_CODES[0]])
    elif drift == "nonleaf":
        by_code[PDO_CODES[10]].is_leaf = False
    else:
        by_code[PDO_CODES[10]].parent_code = "2204220000"

    extraction = SemanticStructureExtractor().extract("2204", records)
    assert all(
        group.reason != "bounded_2204_official_pdo_chain"
        for group in extraction.groups
    )

    tree = SemanticNavigationBuilder().build_heading_from_records("2204", records)
    assert all(
        group.metadata.get("reason") != "bounded_2204_official_pdo_chain"
        for group in tree.group_nodes()
    )
    assert set(tree.real_codes_in_tree()) == set(tree.expected_real_codes)


def test_builder_drops_partial_verified_group_and_spills_every_code() -> None:
    extraction = SemanticStructureExtractor().extract("2204", _records())
    extraction.records_by_code[PDO_CODES[10]].parent_code = "2204220000"

    tree = SemanticNavigationBuilder()._assemble(
        extraction.heading,
        "Вина виноградные натуральные",
        extraction,
    )
    pdo = _pdo_group(tree)

    assert pdo.children == []
    assert set(tree.real_codes_in_tree()) == set(tree.expected_real_codes)
    assert GuidedTnvedNavigationService._prune_empty_groups(tree) == 1
    assert all(
        group.metadata.get("reason") != "bounded_2204_official_pdo_chain"
        for group in tree.group_nodes()
    )


def test_builder_rejects_same_count_interior_code_substitution() -> None:
    extraction = SemanticStructureExtractor().extract("2204", _records())
    removed_code = "2204212200"
    substitute_code = "2204212100"
    extraction.commodity_codes.remove(removed_code)
    extraction.commodity_codes.append(substitute_code)
    extraction.commodity_codes.sort()
    extraction.records_by_code.pop(removed_code)
    extraction.records_by_code[substitute_code] = SourceRecord(
        code=substitute_code,
        description="– – – – – – – – подмененный внутренний товар",
        is_leaf=True,
        parent_code=PARENT_CODE,
    )

    tree = SemanticNavigationBuilder()._assemble(
        extraction.heading,
        "Вина виноградные натуральные",
        extraction,
    )
    pdo = _pdo_group(tree)

    assert pdo.children == []
    assert substitute_code in tree.real_codes_in_tree()
    assert removed_code not in tree.real_codes_in_tree()
    assert set(tree.real_codes_in_tree()) == set(tree.expected_real_codes)


def test_service_prunes_malformed_verified_scope_and_stays_complete() -> None:
    class MalformedScopeBuilder(SemanticNavigationBuilder):
        def build_heading_from_records(self, heading, records):  # noqa: ANN001
            scoped_records = sorted(records, key=lambda record: record.code)
            extraction = self.extractor.extract(heading, scoped_records)
            pdo = next(
                group
                for group in extraction.groups
                if group.reason == "bounded_2204_official_pdo_chain"
            )
            pdo.verified_scope_leaf_count = 32
            return self._assemble(
                heading,
                "Вина виноградные натуральные",
                extraction,
            )

    model = _canonical_model()
    service = GuidedTnvedNavigationService(
        builder=MalformedScopeBuilder(),
        model_loader=lambda: model,
    )
    result = service.build(object(), "2204")

    assert result["status"] == "OK"
    assert result["integrity"]["complete"] is True
    assert result["integrity"]["pruned_empty_groups"] == 1
    assert result["integrity"]["expected_real_codes"] == result["integrity"][
        "reachable_real_codes"
    ]
    serialized_titles: list[str] = []

    def collect_titles(nodes: list[dict]) -> None:
        for node in nodes:
            serialized_titles.append(str(node.get("title") or ""))
            collect_titles(list(node.get("children") or []))

    collect_titles(result["choices"])
    assert PDO_TITLE not in serialized_titles
