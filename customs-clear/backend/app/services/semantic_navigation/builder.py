"""SemanticNavigationBuilder — экспериментальное semantic-tree для одного heading.

Строит навигацию вида:

    0302  (heading)
      classification_group: лососевые
        classification_subgroup: лосось тихоокеанский
          commodity: 0302130000
      classification_group: камбалообразные
        ...

Не меняет обычное production-дерево. Guided runtime передаёт immutable records из
выбранного CanonicalModel snapshot; отдельный DB entrypoint сохранён для offline
диагностики и изолированных тестов.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import inspect
from sqlalchemy.exc import NoInspectionAvailable, SQLAlchemyError
from sqlalchemy.orm import Session

from ...models.core import HsRate
from ...models.tnved import Commodity
from ..tnved_tree.data_access import exclude_obsolete_reserved
from ..tnved_tree.helpers import digits, node_level, strip_leading_dashes
from .bounded_slices import (
    BULK_2204_CONTEXT_CODES,
    BULK_2204_CONTEXT_SIGNATURE,
    BULK_2204_OTHER_ANCHOR_CODE,
    BULK_2204_OTHER_CODES,
    BULK_2204_OTHER_DEPTH,
    BULK_2204_OTHER_LEAF_COUNT,
    BULK_2204_OTHER_RAW,
    BULK_2204_OTHER_REASON,
    BULK_2204_OTHER_SCOPE_KIND,
    BULK_2204_OTHER_STOP_CODE,
    BULK_2204_OTHER_TITLE,
    BULK_2204_PARENT_CODE,
    BULK_2204_PARENT_DESCRIPTION,
    BULK_2204_ROOT_ANCHOR_CODE,
    BULK_2204_ROOT_ANCHOR_DESCRIPTION,
    Bounded0406GroupSpec,
    Bounded0304GroupSpec,
    CHEESE_0406_AFTER_CODE,
    CHEESE_0406_AFTER_DESCRIPTION,
    CHEESE_0406_ANCHOR_CODE,
    CHEESE_0406_ANCHOR_DESCRIPTION,
    CHEESE_0406_GROUPS,
    CHEESE_0406_HEADING,
    CHEESE_0406_MIDDLE_ANCHOR_CODE,
    CHEESE_0406_MIDDLE_DESCRIPTION,
    CHEESE_0406_PAD_CODE,
    CHEESE_0406_PARENT_CODE,
    CHEESE_0406_REASON,
    CHEESE_0406_SCOPE_KIND,
    CHEESE_0406_STOP_CODE,
    CHEESE_0406_STOP_DESCRIPTION,
    PDO_2204_ANCHOR_CODE,
    PDO_2204_ANCHOR_DESCRIPTION,
    PDO_2204_CODES,
    PDO_2204_COLOUR_SIGNATURE,
    PDO_2204_LEAF_COUNT,
    PDO_2204_OTHER_ANCHOR_CODE,
    PDO_2204_OTHER_CODES,
    PDO_2204_OTHER_DEPTH,
    PDO_2204_OTHER_LEAF_COUNT,
    PDO_2204_OTHER_RAW,
    PDO_2204_OTHER_REASON,
    PDO_2204_OTHER_SCOPE_KIND,
    PDO_2204_OTHER_TITLE,
    PDO_2204_PARENT_CODE,
    PDO_2204_REASON,
    PDO_2204_SCOPE_KIND,
    PDO_2204_STOP_CODE,
    PDO_2204_TITLE,
    STATE_0304_PAD_CODE,
    STATE_0304_REAL_SIGNATURE,
    STATE_0304_GROUPS,
    STATE_0304_HEADING,
    STATE_0304_REASON,
    STATE_0304_SCOPE_KIND,
)
from .extractor import ExtractionResult, SemanticStructureExtractor
from .models import (
    MAX_SEMANTIC_GROUP_LEVELS,
    MAX_UNSPLIT_GROUP_CODES,
    NestingFallback,
    SemanticNavigationTree,
    SemanticNode,
    SemanticNodeType,
    SourceRecord,
)


class SemanticNavigationBuilder:
    """Собирает SemanticNavigationTree для одной 4-значной позиции."""

    def __init__(self, extractor: SemanticStructureExtractor | None = None) -> None:
        self.extractor = extractor or SemanticStructureExtractor()

    # -- public ------------------------------------------------------------

    def build_heading(self, db: Session, heading: str) -> SemanticNavigationTree:
        heading4 = digits(heading).zfill(4)[:4]
        records = self._load_records(db, heading4)
        return self.build_heading_from_records(heading4, records)

    def build_heading_from_records(
        self,
        heading: str,
        records: Iterable[SourceRecord],
    ) -> SemanticNavigationTree:
        """Build the semantic overlay from an already captured source snapshot."""

        heading4 = digits(heading).zfill(4)[:4]
        scoped_records = sorted(
            (
                record
                for record in records
                if digits(record.code).zfill(4)[:4] == heading4
            ),
            key=lambda record: record.code,
        )
        heading_title = self._heading_title(heading4, scoped_records)
        extraction = self.extractor.extract(heading4, scoped_records)
        return self._assemble(heading4, heading_title, extraction)

    # -- data access -------------------------------------------------------

    def _load_records(self, db: Session, heading4: str) -> list[SourceRecord]:
        rows = (
            exclude_obsolete_reserved(
                db.query(Commodity).filter(Commodity.code.like(f"{heading4}%"))
            )
            .order_by(Commodity.code.asc())
            .all()
        )
        pad_code = heading4 + "000000"
        normalized_codes = [
            code_digits.zfill(10)[:10]
            for row in rows
            if len(code_digits := digits(str(row.code or ""))) > 4
        ]
        terminal_pad = pad_code in normalized_codes and not any(
            code != pad_code for code in normalized_codes
        )
        try:
            has_hs_rates = terminal_pad and inspect(db.get_bind()).has_table(
                HsRate.__tablename__
            )
        except (AttributeError, NoInspectionAvailable, SQLAlchemyError, TypeError):
            has_hs_rates = False
        exact_terminal_pad = bool(
            has_hs_rates
            and db.query(HsRate.hs_code)
            .filter(HsRate.hs_code == pad_code)
            .first()
        )
        return [
            SourceRecord(
                code=str(r.code or ""),
                description=(r.description or "").strip(),
                import_duty=(r.import_duty or "").strip(),
                is_leaf=(
                    True
                    if exact_terminal_pad
                    and digits(str(r.code or "")).zfill(10)[:10] == pad_code
                    else None
                ),
            )
            for r in rows
        ]

    def _heading_title(self, heading4: str, records: list[SourceRecord]) -> str:
        for rec in records:
            if (
                digits(rec.code).zfill(4)[:4] == heading4
                and len(digits(rec.code)) <= 4
                and rec.description
            ):
                return rec.description
        pad = heading4 + "000000"
        for rec in records:
            if digits(rec.code).zfill(10)[:10] == pad:
                if rec.is_leaf:
                    return strip_leading_dashes(rec.description)
                return self.extractor.main_title(rec.description)
        return ""

    # -- assembling --------------------------------------------------------

    def _assemble(
        self,
        heading4: str,
        heading_title: str,
        extraction: ExtractionResult,
    ) -> SemanticNavigationTree:
        root = SemanticNode(
            node_type=SemanticNodeType.HEADING,
            title=heading_title,
            code=heading4,
            depth=0,
            source="tnved_commodities",
            metadata={"pad_code": extraction.pad_code},
        )

        # Первый проход сохраняет безопасную плоскую модель этапа 2. Controlled
        # nesting выполняется только вторым проходом и только по явной подсказке
        # экстрактора; поэтому сомнительный кандидат всегда может остаться sibling.
        position = {code: i for i, code in enumerate(extraction.commodity_codes)}
        activations: dict[int, list] = {}
        for grp in extraction.groups:
            idx = 0 if grp.after_code is None else position.get(grp.after_code, -1) + 1
            activations.setdefault(idx, []).append(grp)

        current_group: SemanticNode | None = None
        commodity_stack: list[tuple[int, SemanticNode]] = []  # (node_level, node)
        ungrouped: list[str] = []

        def open_groups(idx: int) -> None:
            nonlocal current_group, commodity_stack
            for grp in activations.get(idx, []):
                metadata = {
                    "raw": grp.raw,
                    "extracted_from": grp.source_code,
                    "confidence": grp.confidence,
                    "reason": grp.reason,
                    "activation_index": idx,
                    "dash_depth": grp.dash_depth,
                    "parent_title_hint": grp.parent_title_hint,
                    "parent_source_code_hint": grp.parent_source_code_hint,
                    "hierarchy_hint": grp.hierarchy_hint,
                }
                if grp.verified_scope_kind is not None:
                    metadata.update(
                        {
                            "verified_scope_kind": grp.verified_scope_kind,
                            "verified_scope_start_exclusive": (
                                grp.verified_scope_start_exclusive
                            ),
                            "verified_scope_end_inclusive": (
                                grp.verified_scope_end_inclusive
                            ),
                            "verified_scope_parent_code": (
                                grp.verified_scope_parent_code
                            ),
                            "verified_scope_leaf_count": (
                                grp.verified_scope_leaf_count
                            ),
                        }
                    )
                gnode = SemanticNode(
                    node_type=SemanticNodeType.CLASSIFICATION_GROUP,
                    title=grp.title,
                    code=None,
                    source="semantic_extraction",
                    metadata=metadata,
                )
                root.add_child(gnode)
                current_group = gnode
                commodity_stack = []

        for i, code10 in enumerate(extraction.commodity_codes):
            open_groups(i)
            rec = extraction.records_by_code[code10]
            lvl = node_level(code10)

            while commodity_stack and commodity_stack[-1][0] >= lvl:
                commodity_stack.pop()
            if commodity_stack:
                parent = commodity_stack[-1][1]
            elif current_group is not None:
                parent = current_group
            else:
                parent = root
                ungrouped.append(code10)

            cnode = SemanticNode(
                node_type=SemanticNodeType.COMMODITY,
                title=(
                    strip_leading_dashes(rec.description)
                    if code10 == extraction.pad_code and rec.is_leaf
                    else self.extractor.main_title(rec.description)
                ),
                code=code10,
                source="tnved_commodities",
                metadata={
                    "raw_description": rec.description,
                    "import_duty": rec.import_duty,
                    "node_level": lvl,
                    "leaf_evidence": rec.is_leaf,
                    "canonical_parent_code": rec.parent_code,
                },
            )
            parent.add_child(cnode)
            commodity_stack.append((lvl, cnode))

        # группы, открытые последним кодом (без последующих товаров) — пустые заголовки
        open_groups(len(extraction.commodity_codes))

        self._arrange_or_unwrap_bounded_2204_other(root, extraction)
        nesting_fallbacks = self._apply_controlled_nesting(root)
        self._verify_or_unwrap_bounded_0304_state(root, extraction)
        self._arrange_or_unwrap_bounded_0406_moisture(root, extraction)
        self._restore_canonical_code_containment(root)
        self._finalize_bounded_2204_other(root, extraction)
        self._finalize_bounded_2204_bulk_other(root, extraction)
        self._finalize_bounded_0406_moisture(root, extraction)
        self._refresh_links(root)
        self._mark_leaves(root)

        expected = {heading4, *extraction.commodity_codes}
        return SemanticNavigationTree(
            heading=heading4,
            root=root,
            expected_real_codes=frozenset(expected),
            ungrouped_codes=ungrouped,
            pad_code=extraction.pad_code,
            rejected_candidates=[
                (rc.title, rc.reason, rc.source_code) for rc in extraction.rejected
            ],
            nesting_fallbacks=nesting_fallbacks,
        )

    @staticmethod
    def _apply_controlled_nesting(root: SemanticNode) -> list[NestingFallback]:
        """Вложить только доказанные и ограниченные semantic-подгруппы.

        Источником доказательства служит ``parent_*_hint`` экстрактора. Родитель
        дополнительно обязан быть текущим level-1 сегментом: это не позволяет
        подгруппе перепрыгнуть через соседний заголовок. При любом сомнении узел
        остаётся top-level sibling — ровно как в безопасной flat-модели.
        """

        fallbacks: list[NestingFallback] = []
        top_level: list[SemanticNode] = []
        current_parent: SemanticNode | None = None

        def fallback(
            node: SemanticNode,
            reason: str,
            *,
            parent: SemanticNode | None = None,
            real_code_count: int = 0,
        ) -> None:
            fallbacks.append(
                NestingFallback(
                    title=node.title,
                    source_code=str(node.metadata.get("extracted_from") or ""),
                    reason=reason,
                    parent_title=parent.title if parent is not None else None,
                    real_code_count=real_code_count,
                )
            )

        for node in root.children:
            if node.node_type != SemanticNodeType.CLASSIFICATION_GROUP:
                top_level.append(node)
                continue

            spillover = SemanticNavigationBuilder._detach_out_of_scope_children(node)
            dash_depth = int(node.metadata.get("dash_depth") or 1)
            parent_title_hint = node.metadata.get("parent_title_hint")
            parent_source_hint = node.metadata.get("parent_source_code_hint")
            hierarchy_hint = node.metadata.get("hierarchy_hint")
            wants_nesting = bool(parent_title_hint and hierarchy_hint)

            if not wants_nesting:
                top_level.append(node)
                top_level.extend(spillover)
                if dash_depth == 1:
                    current_parent = node
                else:
                    fallback(node, "no_active_parent_hint")
                    current_parent = None
                continue

            parent_matches = (
                current_parent is not None
                and current_parent.title == parent_title_hint
                and str(current_parent.metadata.get("extracted_from") or "")
                == str(parent_source_hint or "")
            )
            if not parent_matches:
                top_level.append(node)
                top_level.extend(spillover)
                fallback(node, "parent_segment_not_active", parent=current_parent)
                continue

            parent_scope = (
                SemanticNavigationBuilder._semantic_scope_prefix(current_parent)
                if current_parent is not None
                else None
            )
            source_code = digits(str(node.metadata.get("extracted_from") or "")).zfill(
                10
            )[:10]
            if parent_scope and not source_code.startswith(parent_scope):
                top_level.append(node)
                top_level.extend(spillover)
                fallback(node, "outside_parent_code_scope", parent=current_parent)
                continue

            unsplit_codes = SemanticNavigationBuilder._unsplit_real_code_count(node)
            if unsplit_codes > MAX_UNSPLIT_GROUP_CODES:
                top_level.append(node)
                top_level.extend(spillover)
                fallback(
                    node,
                    "unsplit_span_exceeds_limit",
                    parent=current_parent,
                    real_code_count=unsplit_codes,
                )
                continue

            node.node_type = SemanticNodeType.CLASSIFICATION_SUBGROUP
            node.metadata["nested_by"] = hierarchy_hint
            existing = next(
                (
                    child
                    for child in current_parent.children
                    if (
                        child.node_type == SemanticNodeType.CLASSIFICATION_SUBGROUP
                        and SemanticNavigationBuilder._normalise_group_title(
                            child.title
                        )
                        == SemanticNavigationBuilder._normalise_group_title(node.title)
                    )
                ),
                None,
            )
            if existing is None:
                current_parent.children.append(node)
            else:
                variants = existing.metadata.setdefault("merged_variants", [])
                if not variants:
                    variants.append(
                        {
                            "raw": existing.metadata.get("raw"),
                            "extracted_from": existing.metadata.get("extracted_from"),
                        }
                    )
                variants.append(
                    {
                        "raw": node.metadata.get("raw"),
                        "extracted_from": node.metadata.get("extracted_from"),
                    }
                )
                existing.children.extend(node.children)
            current_parent.children.extend(spillover)

        root.children = top_level
        return fallbacks

    @staticmethod
    def _normalise_group_title(value: str) -> str:
        return " ".join((value or "").casefold().split())

    @staticmethod
    def _bounded_0304_candidate(
        node: SemanticNode,
    ) -> Bounded0304GroupSpec | None:
        """Map a group sourced from one of the five audited anchor records."""

        source_code = str(node.metadata.get("extracted_from") or "")
        for spec in STATE_0304_GROUPS:
            if source_code == spec.anchor_code:
                return spec
        return None

    @staticmethod
    def _matches_exact_0304_raw_header(raw: object, title: str) -> bool:
        """Accept one dash separator plus the exact audited title and colon."""

        source = str(raw or "").strip()
        if not source or source[0] not in "–—-":
            return False
        remainder = source[1:].lstrip()
        if remainder.startswith(("–", "—", "-")):
            return False
        return remainder == f"{title}:"

    @staticmethod
    def _verified_0304_group_signature(
        node: SemanticNode,
        spec: Bounded0304GroupSpec,
    ) -> bool:
        """Check the complete post-nesting wrapper and Canonical topology."""

        metadata = node.metadata
        identity = (
            node.node_type == SemanticNodeType.CLASSIFICATION_GROUP,
            node.code is None,
            node.source == "semantic_extraction",
            node.title == spec.title,
            str(metadata.get("extracted_from") or "") == spec.anchor_code,
            metadata.get("confidence") == "high",
            metadata.get("reason") == STATE_0304_REASON,
            metadata.get("dash_depth") == 1,
            metadata.get("verified_scope_kind") == STATE_0304_SCOPE_KIND,
            str(metadata.get("verified_scope_start_exclusive") or "")
            == spec.anchor_code,
            str(metadata.get("verified_scope_end_inclusive") or "")
            == spec.last_code,
            metadata.get("verified_scope_leaf_count") == spec.leaf_count,
            SemanticNavigationBuilder._matches_exact_0304_raw_header(
                metadata.get("raw"),
                spec.title,
            ),
        )
        if not all(identity):
            return False

        actual_signature = tuple(
            (
                str(descendant.code),
                str(descendant.metadata.get("canonical_parent_code") or ""),
                descendant.metadata.get("leaf_evidence"),
            )
            for descendant in node.iter_descendants()
            if descendant.carries_real_code and descendant.code
        )
        return actual_signature == spec.signature

    @staticmethod
    def _verify_or_unwrap_bounded_0304_state(
        root: SemanticNode,
        extraction: ExtractionResult,
    ) -> None:
        """Publish the five official states atomically or remove all wrappers.

        Verification deliberately runs after controlled subgroup nesting, so
        the exact signature includes code nodes hidden behind preserved generic
        subgroups.  It runs before Canonical containment restoration, which can
        then reparent code branches without weakening the bounded proof.
        """

        all_nodes = [root, *root.iter_descendants()]
        anchor_candidates = [
            (node, spec)
            for node in all_nodes
            if node.is_group
            if (spec := SemanticNavigationBuilder._bounded_0304_candidate(node))
            is not None
        ]
        state_labeled = [
            node
            for node in all_nodes
            if node.is_group
            and (
                node.metadata.get("reason") == STATE_0304_REASON
                or node.metadata.get("verified_scope_kind")
                == STATE_0304_SCOPE_KIND
            )
        ]
        override_anchors = {
            spec.anchor_code
            for spec in STATE_0304_GROUPS
            if spec.generic_disposition == "rejected"
        }
        chain_signal = bool(
            state_labeled
            or any(
                str(node.metadata.get("extracted_from") or "")
                in override_anchors
                for node, _ in anchor_candidates
            )
        )
        if not chain_signal:
            return

        by_key: dict[str, list[SemanticNode]] = {
            spec.key: [] for spec in STATE_0304_GROUPS
        }
        for node, spec in anchor_candidates:
            by_key[spec.key].append(node)
        expected_frontier: tuple[str, ...] = (
            "0304310000",
            "0304320000",
            "0304330000",
            "0304390000",
            "A",
            "B",
            "0304610000",
            "0304620000",
            "0304630000",
            "0304690000",
            "C",
            "D",
            "E",
        )

        def frontier_token(node: SemanticNode) -> str:
            if node.carries_real_code and node.code:
                return str(node.code)
            spec = SemanticNavigationBuilder._bounded_0304_candidate(node)
            return spec.key if spec is not None else ""

        pad_record = extraction.records_by_code.get(STATE_0304_PAD_CODE)
        actual_real_signature = tuple(
            (
                code,
                str(extraction.records_by_code[code].parent_code or ""),
                extraction.records_by_code[code].is_leaf,
            )
            for code in extraction.commodity_codes
            if code in extraction.records_by_code
        )
        source_projection_valid = bool(
            extraction.heading == STATE_0304_HEADING
            and extraction.pad_code == STATE_0304_PAD_CODE
            and pad_record is not None
            and pad_record.code == STATE_0304_PAD_CODE
            and pad_record.is_leaf is False
            and pad_record.parent_code is None
            and tuple(extraction.commodity_codes)
            == tuple(code for code, _, _ in STATE_0304_REAL_SIGNATURE)
            and actual_real_signature == STATE_0304_REAL_SIGNATURE
            and set(extraction.records_by_code)
            == {
                STATE_0304_PAD_CODE,
                *(code for code, _, _ in STATE_0304_REAL_SIGNATURE),
            }
        )
        valid = bool(
            source_projection_valid
            and len(anchor_candidates) == len(STATE_0304_GROUPS)
            and len(state_labeled) == len(STATE_0304_GROUPS)
            and all(len(by_key[spec.key]) == 1 for spec in STATE_0304_GROUPS)
            and tuple(frontier_token(node) for node in root.children)
            == expected_frontier
            and all(
                by_key[spec.key][0] in root.children
                and SemanticNavigationBuilder._verified_0304_group_signature(
                    by_key[spec.key][0],
                    spec,
                )
                for spec in STATE_0304_GROUPS
            )
        )
        if valid:
            return

        # A partial semantic promise is worse than a flat route.  Splice every
        # recognizable bounded wrapper out as one operation.  Its generic
        # subgroups and real-code nodes remain intact for Canonical restoration.
        candidate_ids = {id(node) for node, _ in anchor_candidates}
        candidate_ids.update(id(node) for node in state_labeled)
        candidate_ids.update(
            id(node)
            for node in root.children
            if node.node_type == SemanticNodeType.CLASSIFICATION_GROUP
        )

        def unwrap(parent: SemanticNode) -> None:
            retained: list[SemanticNode] = []
            for child in parent.children:
                unwrap(child)
                if id(child) in candidate_ids:
                    retained.extend(child.children)
                else:
                    retained.append(child)
            parent.children = retained

        unwrap(root)

    @staticmethod
    def _bounded_0406_candidate(
        node: SemanticNode,
    ) -> Bounded0406GroupSpec | None:
        """Map a recognizable wrapper to one audited 0406 group spec."""

        source = str(node.metadata.get("extracted_from") or "")
        stop = str(node.metadata.get("verified_scope_end_inclusive") or "")
        for spec in CHEESE_0406_GROUPS:
            if source == spec.anchor_code and stop == spec.stop_code:
                return spec
        return None

    @staticmethod
    def _exact_bounded_raw_header(
        raw: object,
        *,
        title: str,
        dash_depth: int,
    ) -> bool:
        expected = f"{'– ' * dash_depth}{title}:"
        return str(raw or "").strip() == expected

    @staticmethod
    def _0406_source_projection_valid(extraction: ExtractionResult) -> bool:
        """Recheck exact source/topology evidence independently in Builder."""

        records = extraction.records_by_code
        try:
            pad = records[CHEESE_0406_PAD_CODE]
            parent = records[CHEESE_0406_PARENT_CODE]
            anchor = records[CHEESE_0406_ANCHOR_CODE]
            middle = records[CHEESE_0406_MIDDLE_ANCHOR_CODE]
            stop = records[CHEESE_0406_STOP_CODE]
            after = records[CHEESE_0406_AFTER_CODE]
        except KeyError:
            return False
        if not (
            extraction.heading == CHEESE_0406_HEADING
            and extraction.pad_code == CHEESE_0406_PAD_CODE
            and pad.is_leaf is False
            and pad.parent_code is None
            and parent.is_leaf is False
            and parent.parent_code == CHEESE_0406_HEADING
            and anchor.description == CHEESE_0406_ANCHOR_DESCRIPTION
            and middle.description == CHEESE_0406_MIDDLE_DESCRIPTION
            and stop.description == CHEESE_0406_STOP_DESCRIPTION
            and after.description == CHEESE_0406_AFTER_DESCRIPTION
        ):
            return False
        for spec in CHEESE_0406_GROUPS:
            actual = tuple(
                (
                    code,
                    str(records[code].parent_code or ""),
                    records[code].is_leaf,
                )
                for code in extraction.commodity_codes
                if spec.anchor_code < code <= spec.stop_code
                and code in records
            )
            if actual != spec.signature:
                return False
        return True

    @staticmethod
    def _0406_wrapper_identity(
        node: SemanticNode,
        spec: Bounded0406GroupSpec,
    ) -> bool:
        metadata = node.metadata
        return all(
            (
                node.code is None,
                node.source == "semantic_extraction",
                node.title == spec.title,
                str(metadata.get("extracted_from") or "") == spec.anchor_code,
                metadata.get("confidence") == "high",
                metadata.get("reason") == CHEESE_0406_REASON,
                metadata.get("dash_depth") == spec.dash_depth,
                metadata.get("verified_scope_kind") == CHEESE_0406_SCOPE_KIND,
                str(metadata.get("verified_scope_start_exclusive") or "")
                == spec.anchor_code,
                str(metadata.get("verified_scope_end_inclusive") or "")
                == spec.stop_code,
                str(metadata.get("verified_scope_parent_code") or "")
                == CHEESE_0406_PARENT_CODE,
                metadata.get("verified_scope_leaf_count") == spec.leaf_count,
                SemanticNavigationBuilder._exact_bounded_raw_header(
                    metadata.get("raw"),
                    title=spec.title,
                    dash_depth=spec.dash_depth,
                ),
            )
        )

    @staticmethod
    def _real_signature(node: SemanticNode) -> tuple[tuple[str, str, object], ...]:
        return tuple(
            (
                str(descendant.code),
                str(descendant.metadata.get("canonical_parent_code") or ""),
                descendant.metadata.get("leaf_evidence"),
            )
            for descendant in node.iter_descendants()
            if descendant.carries_real_code and descendant.code
        )

    @staticmethod
    def _unwrap_bounded_0406(root: SemanticNode) -> None:
        """Remove all recognizable 0406 wrappers without dropping real nodes."""

        def unwrap(parent: SemanticNode) -> None:
            retained: list[SemanticNode] = []
            for child in parent.children:
                unwrap(child)
                if (
                    child.is_group
                    and (
                        child.metadata.get("reason") == CHEESE_0406_REASON
                        or child.metadata.get("verified_scope_kind")
                        == CHEESE_0406_SCOPE_KIND
                        or "verified_scope_kind" in child.metadata
                        or SemanticNavigationBuilder._bounded_0406_candidate(child)
                        is not None
                    )
                ):
                    retained.extend(child.children)
                else:
                    retained.append(child)
            parent.children = retained

        unwrap(root)

    @staticmethod
    def _0406_signals(root: SemanticNode) -> list[SemanticNode]:
        return [
            node
            for node in [root, *root.iter_descendants()]
            if node.is_group
            and (
                node.metadata.get("reason") == CHEESE_0406_REASON
                or node.metadata.get("verified_scope_kind")
                == CHEESE_0406_SCOPE_KIND
                or "verified_scope_kind" in node.metadata
                or SemanticNavigationBuilder._bounded_0406_candidate(node)
                is not None
            )
        ]

    @staticmethod
    def _arrange_or_unwrap_bounded_0406_moisture(
        root: SemanticNode,
        extraction: ExtractionResult,
    ) -> None:
        """Assemble the exact two-level moisture chain before containment."""

        if extraction.heading != CHEESE_0406_HEADING:
            return
        signals = SemanticNavigationBuilder._0406_signals(root)
        if not signals:
            return

        by_key: dict[str, list[SemanticNode]] = {
            spec.key: [] for spec in CHEESE_0406_GROUPS
        }
        for node in [root, *root.iter_descendants()]:
            if not node.is_group:
                continue
            spec = SemanticNavigationBuilder._bounded_0406_candidate(node)
            if spec is not None:
                by_key[spec.key].append(node)

        valid = bool(
            SemanticNavigationBuilder._0406_source_projection_valid(extraction)
            and len(signals) == len(CHEESE_0406_GROUPS)
            and all(len(by_key[spec.key]) == 1 for spec in CHEESE_0406_GROUPS)
            and all(
                SemanticNavigationBuilder._0406_wrapper_identity(
                    by_key[spec.key][0], spec
                )
                for spec in CHEESE_0406_GROUPS
            )
        )
        if not valid:
            SemanticNavigationBuilder._unwrap_bounded_0406(root)
            return

        top = by_key["top"][0]
        low = by_key["low"][0]
        middle = by_key["middle"][0]
        if not all(node in root.children for node in (top, low, middle)):
            SemanticNavigationBuilder._unwrap_bounded_0406(root)
            return
        if (
            top.children
            or SemanticNavigationBuilder._real_signature(low)
            != CHEESE_0406_GROUPS[1].signature
        ):
            SemanticNavigationBuilder._unwrap_bounded_0406(root)
            return

        middle_codes = {code for code, _, _ in CHEESE_0406_GROUPS[2].signature}
        selected: list[SemanticNode] = []
        high: list[SemanticNode] = []
        spillover: list[SemanticNode] = []
        for child in middle.children:
            first_code = SemanticNavigationBuilder._first_real_code(child)
            if first_code in middle_codes:
                selected.append(child)
            elif first_code == CHEESE_0406_STOP_CODE:
                high.append(child)
            else:
                spillover.append(child)
        middle.children = selected
        if (
            SemanticNavigationBuilder._real_signature(middle)
            != CHEESE_0406_GROUPS[2].signature
            or len(high) != 1
            or high[0].code != CHEESE_0406_STOP_CODE
            or high[0].metadata.get("leaf_evidence") is not True
            or str(high[0].metadata.get("canonical_parent_code") or "")
            != CHEESE_0406_PARENT_CODE
        ):
            middle.children.extend(high)
            middle.children.extend(spillover)
            SemanticNavigationBuilder._unwrap_bounded_0406(root)
            return

        top.node_type = SemanticNodeType.CLASSIFICATION_GROUP
        low.node_type = SemanticNodeType.CLASSIFICATION_SUBGROUP
        middle.node_type = SemanticNodeType.CLASSIFICATION_SUBGROUP
        top.children = [low, middle, high[0]]

        rebuilt: list[SemanticNode] = []
        for child in root.children:
            if child is top:
                rebuilt.append(top)
                rebuilt.extend(spillover)
            elif child is low or child is middle:
                continue
            else:
                rebuilt.append(child)
        root.children = rebuilt
        if (
            SemanticNavigationBuilder._real_signature(top)
            != CHEESE_0406_GROUPS[0].signature
        ):
            SemanticNavigationBuilder._unwrap_bounded_0406(root)

    @staticmethod
    def _finalize_bounded_0406_moisture(
        root: SemanticNode,
        extraction: ExtractionResult,
    ) -> None:
        """Verify final Canonical containment or atomically restore flat safety."""

        if extraction.heading != CHEESE_0406_HEADING:
            return
        signals = SemanticNavigationBuilder._0406_signals(root)
        if not signals:
            return
        by_key: dict[str, list[SemanticNode]] = {
            spec.key: [] for spec in CHEESE_0406_GROUPS
        }
        for node in signals:
            spec = SemanticNavigationBuilder._bounded_0406_candidate(node)
            if spec is not None:
                by_key[spec.key].append(node)
        all_nodes = [root, *root.iter_descendants()]
        code_parent = next(
            (
                node
                for node in all_nodes
                if node.carries_real_code
                and node.code == CHEESE_0406_PARENT_CODE
            ),
            None,
        )
        valid = bool(
            SemanticNavigationBuilder._0406_source_projection_valid(extraction)
            and code_parent is not None
            and len(signals) == len(CHEESE_0406_GROUPS)
            and all(len(by_key[spec.key]) == 1 for spec in CHEESE_0406_GROUPS)
        )
        if valid:
            top = by_key["top"][0]
            low = by_key["low"][0]
            middle = by_key["middle"][0]
            high = [
                child
                for child in top.children
                if child.carries_real_code
                and child.code == CHEESE_0406_STOP_CODE
            ]
            valid = bool(
                top in code_parent.children
                and top.node_type == SemanticNodeType.CLASSIFICATION_GROUP
                and low.node_type == SemanticNodeType.CLASSIFICATION_SUBGROUP
                and middle.node_type == SemanticNodeType.CLASSIFICATION_SUBGROUP
                and len(high) == 1
                and top.children == [low, middle, high[0]]
                and all(
                    SemanticNavigationBuilder._0406_wrapper_identity(
                        by_key[spec.key][0], spec
                    )
                    and SemanticNavigationBuilder._real_signature(
                        by_key[spec.key][0]
                    )
                    == spec.signature
                    for spec in CHEESE_0406_GROUPS
                )
            )
        if valid:
            return
        SemanticNavigationBuilder._unwrap_bounded_0406(root)

    @staticmethod
    def _source_signature(
        extraction: ExtractionResult,
        expected_codes: tuple[str, ...],
    ) -> tuple[tuple[str, str, bool | None, str], ...]:
        records = extraction.records_by_code
        return tuple(
            (
                code,
                str(records[code].parent_code or ""),
                records[code].is_leaf,
                records[code].description,
            )
            for code in extraction.commodity_codes
            if code in expected_codes and code in records
        )

    @staticmethod
    def _2204_colour_source_projection_valid(
        extraction: ExtractionResult,
    ) -> bool:
        records = extraction.records_by_code
        parent = records.get(PDO_2204_PARENT_CODE)
        anchor = records.get(PDO_2204_ANCHOR_CODE)
        return bool(
            extraction.heading == "2204"
            and parent is not None
            and parent.is_leaf is False
            and anchor is not None
            and anchor.is_leaf is True
            and anchor.parent_code == PDO_2204_PARENT_CODE
            and anchor.description == PDO_2204_ANCHOR_DESCRIPTION
            and SemanticNavigationBuilder._source_signature(
                extraction,
                PDO_2204_CODES,
            )
            == PDO_2204_COLOUR_SIGNATURE
        )

    @staticmethod
    def _2204_other_identity(node: SemanticNode) -> bool:
        metadata = node.metadata
        return all(
            (
                node.code is None,
                node.source == "semantic_extraction",
                node.title == PDO_2204_OTHER_TITLE,
                str(metadata.get("raw") or "") == PDO_2204_OTHER_RAW,
                str(metadata.get("extracted_from") or "")
                == PDO_2204_OTHER_ANCHOR_CODE,
                metadata.get("confidence") == "high",
                metadata.get("reason") == PDO_2204_OTHER_REASON,
                metadata.get("dash_depth") == PDO_2204_OTHER_DEPTH,
                metadata.get("verified_scope_kind")
                == PDO_2204_OTHER_SCOPE_KIND,
                str(metadata.get("verified_scope_start_exclusive") or "")
                == PDO_2204_OTHER_ANCHOR_CODE,
                str(metadata.get("verified_scope_end_inclusive") or "")
                == PDO_2204_STOP_CODE,
                str(metadata.get("verified_scope_parent_code") or "")
                == PDO_2204_PARENT_CODE,
                metadata.get("verified_scope_leaf_count")
                == PDO_2204_OTHER_LEAF_COUNT,
            )
        )

    @staticmethod
    def _2204_other_signals(root: SemanticNode) -> list[SemanticNode]:
        return [
            node
            for node in [root, *root.iter_descendants()]
            if SemanticNavigationBuilder._is_2204_other_signal(node)
        ]

    @staticmethod
    def _is_2204_other_signal(node: SemanticNode) -> bool:
        metadata = node.metadata
        return bool(
            node.is_group
            and (
                metadata.get("reason") == PDO_2204_OTHER_REASON
                or metadata.get("verified_scope_kind")
                == PDO_2204_OTHER_SCOPE_KIND
                or (
                    str(metadata.get("extracted_from") or "")
                    == PDO_2204_OTHER_ANCHOR_CODE
                    and "verified_scope_start_exclusive" in metadata
                )
            )
        )

    @staticmethod
    def _splice_group(parent: SemanticNode, group: SemanticNode) -> bool:
        if group not in parent.children:
            return False
        rebuilt: list[SemanticNode] = []
        for child in parent.children:
            if child is group:
                rebuilt.extend(group.children)
            else:
                rebuilt.append(child)
        parent.children = rebuilt
        return True

    @staticmethod
    def _unwrap_bounded_2204_other(root: SemanticNode) -> None:
        def unwrap(parent: SemanticNode) -> None:
            for child in list(parent.children):
                unwrap(child)
            for child in list(parent.children):
                if SemanticNavigationBuilder._is_2204_other_signal(child):
                    SemanticNavigationBuilder._splice_group(parent, child)

        unwrap(root)

    @staticmethod
    def _arrange_or_unwrap_bounded_2204_other(
        root: SemanticNode,
        extraction: ExtractionResult,
    ) -> None:
        """Nest the retained PDO colour boundary, or keep all 33 leaves flat."""

        signals = SemanticNavigationBuilder._2204_other_signals(root)
        if not signals:
            return
        pdo_candidates = [
            node
            for node in root.children
            if node.is_group
            and SemanticNavigationBuilder._verified_2204_pdo_interval(node)
            is not None
        ]
        expected_white = tuple(
            (code, PDO_2204_PARENT_CODE, True)
            for code in PDO_2204_CODES[: -PDO_2204_OTHER_LEAF_COUNT]
        )
        expected_other = tuple(
            (code, PDO_2204_PARENT_CODE, True)
            for code in PDO_2204_OTHER_CODES
        )
        valid = bool(
            SemanticNavigationBuilder._2204_colour_source_projection_valid(
                extraction
            )
            and len(signals) == 1
            and len(pdo_candidates) == 1
        )
        if valid:
            pdo = pdo_candidates[0]
            other = signals[0]
            valid = bool(
                other in root.children
                and root.children.index(pdo) + 1 == root.children.index(other)
                and SemanticNavigationBuilder._2204_other_identity(other)
                and SemanticNavigationBuilder._real_signature(pdo)
                == expected_white
                and SemanticNavigationBuilder._real_signature(other)
                == expected_other
                and all(child.carries_real_code for child in pdo.children)
                and all(child.carries_real_code for child in other.children)
            )
        if valid:
            other.node_type = SemanticNodeType.CLASSIFICATION_SUBGROUP
            other.metadata["nested_by"] = "bounded_exact_source_topology"
            pdo.children.append(other)
            root.children = [child for child in root.children if child is not other]
            return

        # When only the new wrapper is malformed, retain the already-proven
        # PDO question and return its leaves to the original direct order.
        if len(pdo_candidates) == 1 and len(signals) == 1:
            pdo = pdo_candidates[0]
            other = signals[0]
            if (
                pdo in root.children
                and other in root.children
                and root.children.index(pdo) < root.children.index(other)
                and SemanticNavigationBuilder._real_signature(pdo)
                + SemanticNavigationBuilder._real_signature(other)
                == tuple(
                    (code, PDO_2204_PARENT_CODE, True)
                    for code in PDO_2204_CODES
                )
            ):
                pdo.children.extend(other.children)
                root.children = [
                    child for child in root.children if child is not other
                ]
                return
        SemanticNavigationBuilder._unwrap_bounded_2204_other(root)

    @staticmethod
    def _finalize_bounded_2204_other(
        root: SemanticNode,
        extraction: ExtractionResult,
    ) -> None:
        signals = SemanticNavigationBuilder._2204_other_signals(root)
        if not signals:
            return
        all_nodes = [root, *root.iter_descendants()]
        pdo_candidates = [
            node
            for node in all_nodes
            if node.is_group
            and SemanticNavigationBuilder._verified_2204_pdo_interval(node)
            is not None
        ]
        code_parents = [
            node
            for node in all_nodes
            if node.carries_real_code and node.code == PDO_2204_PARENT_CODE
        ]
        valid = bool(
            SemanticNavigationBuilder._2204_colour_source_projection_valid(
                extraction
            )
            and len(signals) == 1
            and len(pdo_candidates) == 1
            and len(code_parents) == 1
        )
        if valid:
            other = signals[0]
            pdo = pdo_candidates[0]
            direct_codes = tuple(
                str(child.code)
                for child in pdo.children
                if child.carries_real_code and child.code
            )
            valid = bool(
                pdo in code_parents[0].children
                and other in pdo.children
                and other.node_type == SemanticNodeType.CLASSIFICATION_SUBGROUP
                and SemanticNavigationBuilder._2204_other_identity(other)
                and len(pdo.children) == 18
                and direct_codes
                == PDO_2204_CODES[: -PDO_2204_OTHER_LEAF_COUNT]
                and SemanticNavigationBuilder._real_signature(other)
                == tuple(
                    (code, PDO_2204_PARENT_CODE, True)
                    for code in PDO_2204_OTHER_CODES
                )
                and SemanticNavigationBuilder._real_signature(pdo)
                == tuple(
                    (code, PDO_2204_PARENT_CODE, True)
                    for code in PDO_2204_CODES
                )
            )
        if valid:
            return
        SemanticNavigationBuilder._unwrap_bounded_2204_other(root)

    @staticmethod
    def _2204_bulk_source_projection_valid(
        extraction: ExtractionResult,
    ) -> bool:
        records = extraction.records_by_code
        parent = records.get(BULK_2204_PARENT_CODE)
        anchor = records.get(BULK_2204_ROOT_ANCHOR_CODE)
        return bool(
            extraction.heading == "2204"
            and parent is not None
            and parent.is_leaf is False
            and parent.description == BULK_2204_PARENT_DESCRIPTION
            and anchor is not None
            and anchor.is_leaf is True
            and anchor.parent_code == BULK_2204_PARENT_CODE
            and anchor.description == BULK_2204_ROOT_ANCHOR_DESCRIPTION
            and SemanticNavigationBuilder._source_signature(
                extraction,
                BULK_2204_CONTEXT_CODES,
            )
            == BULK_2204_CONTEXT_SIGNATURE
        )

    @staticmethod
    def _2204_bulk_other_identity(node: SemanticNode) -> bool:
        metadata = node.metadata
        return all(
            (
                node.code is None,
                node.source == "semantic_extraction",
                node.title == BULK_2204_OTHER_TITLE,
                str(metadata.get("raw") or "") == BULK_2204_OTHER_RAW,
                str(metadata.get("extracted_from") or "")
                == BULK_2204_OTHER_ANCHOR_CODE,
                metadata.get("confidence") == "high",
                metadata.get("reason") == BULK_2204_OTHER_REASON,
                metadata.get("dash_depth") == BULK_2204_OTHER_DEPTH,
                metadata.get("verified_scope_kind")
                == BULK_2204_OTHER_SCOPE_KIND,
                str(metadata.get("verified_scope_start_exclusive") or "")
                == BULK_2204_OTHER_ANCHOR_CODE,
                str(metadata.get("verified_scope_end_inclusive") or "")
                == BULK_2204_OTHER_STOP_CODE,
                str(metadata.get("verified_scope_parent_code") or "")
                == BULK_2204_PARENT_CODE,
                metadata.get("verified_scope_leaf_count")
                == BULK_2204_OTHER_LEAF_COUNT,
            )
        )

    @staticmethod
    def _2204_bulk_other_signals(root: SemanticNode) -> list[SemanticNode]:
        return [
            node
            for node in [root, *root.iter_descendants()]
            if SemanticNavigationBuilder._is_2204_bulk_other_signal(node)
        ]

    @staticmethod
    def _is_2204_bulk_other_signal(node: SemanticNode) -> bool:
        metadata = node.metadata
        return bool(
            node.is_group
            and (
                metadata.get("reason") == BULK_2204_OTHER_REASON
                or metadata.get("verified_scope_kind")
                == BULK_2204_OTHER_SCOPE_KIND
                or (
                    str(metadata.get("extracted_from") or "")
                    == BULK_2204_OTHER_ANCHOR_CODE
                    and "verified_scope_start_exclusive" in metadata
                )
            )
        )

    @staticmethod
    def _unwrap_bounded_2204_bulk_other(root: SemanticNode) -> None:
        def unwrap(parent: SemanticNode) -> None:
            for child in list(parent.children):
                unwrap(child)
            for child in list(parent.children):
                if SemanticNavigationBuilder._is_2204_bulk_other_signal(child):
                    SemanticNavigationBuilder._splice_group(parent, child)

        unwrap(root)

    @staticmethod
    def _finalize_bounded_2204_bulk_other(
        root: SemanticNode,
        extraction: ExtractionResult,
    ) -> None:
        signals = SemanticNavigationBuilder._2204_bulk_other_signals(root)
        if not signals:
            return
        all_nodes = [root, *root.iter_descendants()]
        code_parents = [
            node
            for node in all_nodes
            if node.carries_real_code and node.code == BULK_2204_PARENT_CODE
        ]
        valid = bool(
            SemanticNavigationBuilder._2204_bulk_source_projection_valid(
                extraction
            )
            and len(signals) == 1
            and len(code_parents) == 1
        )
        if valid:
            group = signals[0]
            valid = bool(
                group in code_parents[0].children
                and group.node_type == SemanticNodeType.CLASSIFICATION_GROUP
                and SemanticNavigationBuilder._2204_bulk_other_identity(group)
                and len(group.children) == BULK_2204_OTHER_LEAF_COUNT
                and all(child.carries_real_code for child in group.children)
                and SemanticNavigationBuilder._real_signature(group)
                == tuple(
                    (code, BULK_2204_PARENT_CODE, True)
                    for code in BULK_2204_OTHER_CODES
                )
            )
        if valid:
            return
        SemanticNavigationBuilder._unwrap_bounded_2204_bulk_other(root)

    @staticmethod
    def _detach_out_of_scope_children(
        node: SemanticNode,
    ) -> list[SemanticNode]:
        """Не позволить trailing-заголовку поглотить соседний кодовый диапазон."""

        # TASK-SEMANTIC-008 verifies and assembles all three 0406 wrappers as
        # one chain after controlled nesting.  Prefix heuristics would split
        # its explicit 17-sibling allowlist, so leave it untouched here.
        if (
            node.metadata.get("reason") == CHEESE_0406_REASON
            or node.metadata.get("verified_scope_kind")
            == CHEESE_0406_SCOPE_KIND
        ):
            return []

        is_bounded_2204_bulk = (
            SemanticNavigationBuilder._is_2204_bulk_other_signal(node)
        )
        if is_bounded_2204_bulk:
            original_children = list(node.children)
            complete_scope = bool(
                SemanticNavigationBuilder._2204_bulk_other_identity(node)
                and len(node.children) == BULK_2204_OTHER_LEAF_COUNT
                and all(child.carries_real_code for child in node.children)
                and SemanticNavigationBuilder._real_signature(node)
                == tuple(
                    (code, BULK_2204_PARENT_CODE, True)
                    for code in BULK_2204_OTHER_CODES
                )
            )
            if complete_scope:
                return []
            node.children = []
            return original_children

        verified_interval = (
            SemanticNavigationBuilder._verified_2204_pdo_interval(node)
        )
        is_bounded_2204_pdo = (
            node.metadata.get("reason") == PDO_2204_REASON
        )
        if is_bounded_2204_pdo and verified_interval is None:
            original_children = list(node.children)
            node.children = []
            return original_children
        if verified_interval is not None:
            (
                start_exclusive,
                _first_code,
                end_inclusive,
                parent_code,
                expected_count,
            ) = verified_interval
            original_children = list(node.children)
            kept: list[SemanticNode] = []
            spillover: list[SemanticNode] = []
            kept_codes: list[str] = []
            for child in node.children:
                child_real_nodes = [
                    descendant
                    for descendant in [child, *child.iter_descendants()]
                    if descendant.carries_real_code and descendant.code
                ]
                child_codes = tuple(
                    digits(str(descendant.code)).zfill(10)[:10]
                    for descendant in child_real_nodes
                )
                is_verified_branch = bool(
                    child_real_nodes
                    and all(
                        start_exclusive < code <= end_inclusive
                        and descendant.metadata.get("leaf_evidence") is True
                        and str(
                            descendant.metadata.get("canonical_parent_code")
                            or ""
                        )
                        == parent_code
                        for descendant, code in zip(
                            child_real_nodes,
                            child_codes,
                            strict=True,
                        )
                    )
                )
                if is_verified_branch:
                    kept.append(child)
                    kept_codes.extend(child_codes)
                else:
                    spillover.append(child)
            complete_scope = bool(
                len(kept_codes) == expected_count
                and tuple(kept_codes) == PDO_2204_CODES
            )
            if not complete_scope:
                # Never publish a partial semantic promise.  The group becomes
                # empty (and is pruned by Guided), while every code falls back
                # to its ordinary flat/canonical placement.
                node.children = []
                return original_children
            node.children = kept
            return spillover

        scope = SemanticNavigationBuilder._semantic_scope_prefix(node)
        if not scope:
            return []

        kept: list[SemanticNode] = []
        spillover: list[SemanticNode] = []
        for child in node.children:
            child_code = SemanticNavigationBuilder._first_real_code(child)
            if child_code and not child_code.startswith(scope):
                spillover.append(child)
            else:
                kept.append(child)
        node.children = kept
        return spillover

    @staticmethod
    def _verified_2204_pdo_interval(
        node: SemanticNode,
    ) -> tuple[str, str, str, str, int] | None:
        """Recognize only the exact TASK-SEMANTIC-006 verified scope."""

        metadata = node.metadata
        signature = (
            node.code is None,
            node.source == "semantic_extraction",
            " ".join(node.title.casefold().split())
            == PDO_2204_TITLE,
            str(metadata.get("extracted_from") or "") == PDO_2204_ANCHOR_CODE,
            metadata.get("reason") == PDO_2204_REASON,
            metadata.get("verified_scope_kind")
            == PDO_2204_SCOPE_KIND,
            str(metadata.get("verified_scope_start_exclusive") or "")
            == PDO_2204_ANCHOR_CODE,
            str(metadata.get("verified_scope_end_inclusive") or "")
            == PDO_2204_STOP_CODE,
            str(metadata.get("verified_scope_parent_code") or "")
            == PDO_2204_PARENT_CODE,
            metadata.get("verified_scope_leaf_count") == PDO_2204_LEAF_COUNT,
        )
        if not all(signature):
            return None
        return (
            PDO_2204_ANCHOR_CODE,
            PDO_2204_CODES[0],
            PDO_2204_STOP_CODE,
            PDO_2204_PARENT_CODE,
            PDO_2204_LEAF_COUNT,
        )

    @staticmethod
    def _semantic_scope_prefix(node: SemanticNode) -> str | None:
        """Вернуть официальный кодовый диапазон level-1 semantic-группы.

        Бескодовый заголовок из официального текста обычно занимает нечётный
        промежуточный уровень: перед несколькими L6-кодами это 5-значный
        диапазон, перед L8 — 7-значный и т. д. Первое реальное кодовое поддерево
        плоского прохода надёжно задаёт этот диапазон. Проверка не даёт
        оставшейся активной группе («тунец») поглотить более поздний соседний
        диапазон («мерлуза»), даже если у его trailing-заголовка больше тире.
        """

        code = SemanticNavigationBuilder._first_real_code(node)
        if not code:
            return None
        level = node_level(code)
        if level <= 4:
            return None
        return code[: level - 1]

    @staticmethod
    def _first_real_code(node: SemanticNode) -> str | None:
        if node.carries_real_code and node.code:
            return digits(node.code).zfill(10)[:10]
        for child in node.children:
            if child.is_group:
                continue
            found = SemanticNavigationBuilder._first_real_code(child)
            if found:
                return found
        return None

    @staticmethod
    def _unsplit_real_code_count(node: SemanticNode) -> int:
        """Число кодов в сегменте до любой дальнейшей semantic-подгруппы."""

        count = 1 if node.carries_real_code and node.code else 0
        for child in node.children:
            if child.is_group:
                continue
            count += SemanticNavigationBuilder._unsplit_real_code_count(child)
        return count

    @staticmethod
    def _restore_canonical_code_containment(root: SemanticNode) -> None:
        """Restore snapshot-proven code ancestry without discarding semantics.

        Controlled semantic nesting is intentionally applied first.  A semantic
        wrapper is moved as a unit only when every real-code node on its frontier
        has the same Canonical parent and the two-level semantic limit remains
        valid.  That keeps safe group/subgroup wrappers and their kinds intact.
        Any remaining misplaced code node is then reparented directly; no node
        is copied or synthesized here.
        """

        all_nodes = [root, *root.iter_descendants()]
        original_order = {id(node): index for index, node in enumerate(all_nodes)}
        baseline_children = {id(node): list(node.children) for node in all_nodes}
        code_nodes: dict[str, SemanticNode] = {
            str(node.code): node
            for node in all_nodes
            if node.carries_real_code and node.code
        }

        def structural_parents() -> dict[int, SemanticNode]:
            return {
                id(child): node
                for node in [root, *root.iter_descendants()]
                for child in node.children
            }

        def contains(ancestor: SemanticNode, candidate: SemanticNode) -> bool:
            return ancestor is candidate or any(
                descendant is candidate for descendant in ancestor.iter_descendants()
            )

        def nearest_code_ancestor(
            node: SemanticNode,
            parents: dict[int, SemanticNode],
        ) -> SemanticNode | None:
            cursor = parents.get(id(node))
            seen: set[int] = set()
            while cursor is not None and id(cursor) not in seen:
                seen.add(id(cursor))
                if cursor.carries_real_code and cursor.code:
                    return cursor
                cursor = parents.get(id(cursor))
            return None

        def semantic_frontier(node: SemanticNode) -> list[SemanticNode]:
            frontier: list[SemanticNode] = []

            def walk(current: SemanticNode) -> None:
                for child in current.children:
                    if child.carries_real_code and child.code:
                        frontier.append(child)
                    else:
                        walk(child)

            walk(node)
            return frontier

        def semantic_ancestor_count(
            node: SemanticNode,
            parents: dict[int, SemanticNode],
        ) -> int:
            count = 0
            cursor: SemanticNode | None = node
            seen: set[int] = set()
            while cursor is not None and id(cursor) not in seen:
                seen.add(id(cursor))
                count += int(cursor.is_group)
                cursor = parents.get(id(cursor))
            return count

        def semantic_subtree_depth(node: SemanticNode, current: int = 0) -> int:
            level = current + int(node.is_group)
            return max(
                [level]
                + [semantic_subtree_depth(child, level) for child in node.children]
            )

        def move(node: SemanticNode, target: SemanticNode) -> bool:
            parents = structural_parents()
            current = parents.get(id(node))
            if current is None or current is target or contains(node, target):
                return False
            current.children = [child for child in current.children if child is not node]
            if all(child is not node for child in target.children):
                target.children.append(node)
            return True

        groups_with_depth: list[tuple[int, SemanticNode]] = []

        def collect_groups(node: SemanticNode, depth: int) -> None:
            if node.is_group:
                groups_with_depth.append((depth, node))
            for child in node.children:
                collect_groups(child, depth + 1)

        collect_groups(root, 0)
        ordered_groups = sorted(
            groups_with_depth,
            key=lambda item: (item[0], original_order.get(id(item[1]), 0)),
        )

        def canonical_depth(node: SemanticNode) -> int:
            depth = 0
            code = str(node.code or "")
            seen: set[str] = set()
            while code and code not in seen:
                seen.add(code)
                current = code_nodes.get(code)
                if current is None:
                    break
                parent_code = str(
                    current.metadata.get("canonical_parent_code") or ""
                )
                if not parent_code or parent_code == code:
                    break
                depth += 1
                code = parent_code
            return depth

        real_nodes = [
            node
            for node in all_nodes
            if node.carries_real_code and node.code and node is not root
        ]
        ordered_real_nodes = sorted(
            real_nodes,
            key=lambda item: (
                canonical_depth(item),
                original_order.get(id(item), 0),
            ),
        )

        def restore_order(node: SemanticNode) -> None:
            node.children.sort(key=lambda child: original_order.get(id(child), 10**9))
            for child in node.children:
                restore_order(child)

        def execute(excluded_groups: set[int]) -> set[int]:
            for node in all_nodes:
                node.children = list(baseline_children[id(node)])

            moved_groups: set[int] = set()
            # Settle shallow semantic ancestry first.  A deeper wrapper is
            # accepted only against the already-established semantic frontier.
            for _, group in ordered_groups:
                if id(group) in excluded_groups:
                    continue
                frontier = semantic_frontier(group)
                parent_codes = {
                    str(node.metadata.get("canonical_parent_code") or "")
                    for node in frontier
                }
                if not frontier or "" in parent_codes or len(parent_codes) != 1:
                    continue
                target = code_nodes.get(next(iter(parent_codes)))
                if target is None or contains(group, target):
                    continue
                parents = structural_parents()
                if nearest_code_ancestor(group, parents) is target:
                    continue
                if (
                    semantic_ancestor_count(target, parents)
                    + semantic_subtree_depth(group)
                    > MAX_SEMANTIC_GROUP_LEVELS
                ):
                    continue
                if move(group, target):
                    moved_groups.add(id(group))

            for node in ordered_real_nodes:
                parent_code = str(
                    node.metadata.get("canonical_parent_code") or ""
                )
                target = code_nodes.get(parent_code)
                if (
                    not parent_code
                    or target is None
                    or target is node
                    or contains(node, target)
                ):
                    continue
                parents = structural_parents()
                if nearest_code_ancestor(node, parents) is target:
                    continue
                move(node, target)

            restore_order(root)
            return moved_groups

        def depth_breaking_moves(moved_groups: set[int]) -> set[int]:
            excluded: set[int] = set()

            def walk(
                node: SemanticNode,
                semantic_levels: int,
                moved_path: tuple[int, ...],
            ) -> None:
                next_levels = semantic_levels + int(node.is_group)
                next_path = (
                    (*moved_path, id(node))
                    if node.is_group and id(node) in moved_groups
                    else moved_path
                )
                if next_levels > MAX_SEMANTIC_GROUP_LEVELS and next_path:
                    excluded.add(next_path[-1])
                for child in node.children:
                    walk(child, next_levels, next_path)

            walk(root, 0, ())
            return excluded

        excluded_groups: set[int] = set()
        for _ in range(len(ordered_groups) + 1):
            moved_groups = execute(excluded_groups)
            new_exclusions = depth_breaking_moves(moved_groups) - excluded_groups
            if not new_exclusions:
                break
            excluded_groups.update(new_exclusions)

    @staticmethod
    def _refresh_links(
        node: SemanticNode,
        *,
        parent_id: str | None = None,
        depth: int = 0,
    ) -> None:
        """После reparenting синхронизировать parent_id/depth всего поддерева."""

        node.parent_id = parent_id
        node.depth = depth
        for child in node.children:
            SemanticNavigationBuilder._refresh_links(
                child,
                parent_id=node.id,
                depth=depth + 1,
            )

    @staticmethod
    def _mark_leaves(node: SemanticNode) -> None:
        for ch in node.children:
            SemanticNavigationBuilder._mark_leaves(ch)
        if node.node_type == SemanticNodeType.COMMODITY:
            evidence = node.metadata.get("leaf_evidence")
            has_code_descendants = any(
                descendant.carries_real_code and descendant.code
                for descendant in node.iter_descendants()
            )
            if evidence is True or (evidence is None and not has_code_descendants):
                node.node_type = SemanticNodeType.LEAF
