"""SemanticNavigationBuilder — экспериментальное semantic-tree для одного heading.

Строит навигацию вида:

    0302  (heading)
      classification_group: лососевые
        classification_subgroup: лосось тихоокеанский
          commodity: 0302130000
      classification_group: камбалообразные
        ...

НЕ влияет на production API и текущее дерево. Реальные коды берутся только из БД.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ...models.tnved import Commodity
from ..tnved_tree.data_access import exclude_obsolete_reserved
from ..tnved_tree.helpers import digits, node_level
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
        heading_title = self._heading_title(db, heading4, records)
        extraction = self.extractor.extract(heading4, records)
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
        return [
            SourceRecord(
                code=str(r.code or ""),
                description=(r.description or "").strip(),
                import_duty=(r.import_duty or "").strip(),
            )
            for r in rows
        ]

    def _heading_title(
        self, db: Session, heading4: str, records: list[SourceRecord]
    ) -> str:
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
                gnode = SemanticNode(
                    node_type=SemanticNodeType.CLASSIFICATION_GROUP,
                    title=grp.title,
                    code=None,
                    source="semantic_extraction",
                    metadata={
                        "raw": grp.raw,
                        "extracted_from": grp.source_code,
                        "confidence": grp.confidence,
                        "reason": grp.reason,
                        "activation_index": idx,
                        "dash_depth": grp.dash_depth,
                        "parent_title_hint": grp.parent_title_hint,
                        "parent_source_code_hint": grp.parent_source_code_hint,
                        "hierarchy_hint": grp.hierarchy_hint,
                    },
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
                title=self.extractor.main_title(rec.description),
                code=code10,
                source="tnved_commodities",
                metadata={
                    "raw_description": rec.description,
                    "import_duty": rec.import_duty,
                    "node_level": lvl,
                },
            )
            parent.add_child(cnode)
            commodity_stack.append((lvl, cnode))

        # группы, открытые последним кодом (без последующих товаров) — пустые заголовки
        open_groups(len(extraction.commodity_codes))

        nesting_fallbacks = self._apply_controlled_nesting(root)
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

            dash_depth = int(node.metadata.get("dash_depth") or 1)
            parent_title_hint = node.metadata.get("parent_title_hint")
            parent_source_hint = node.metadata.get("parent_source_code_hint")
            hierarchy_hint = node.metadata.get("hierarchy_hint")
            wants_nesting = bool(parent_title_hint and hierarchy_hint)

            if not wants_nesting:
                top_level.append(node)
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
                fallback(node, "parent_segment_not_active", parent=current_parent)
                continue

            if (
                hierarchy_hint == "dash_depth"
                and dash_depth > MAX_SEMANTIC_GROUP_LEVELS
            ):
                top_level.append(node)
                fallback(node, "semantic_depth_exceeds_limit", parent=current_parent)
                continue

            unsplit_codes = SemanticNavigationBuilder._unsplit_real_code_count(node)
            if unsplit_codes > MAX_UNSPLIT_GROUP_CODES:
                top_level.append(node)
                fallback(
                    node,
                    "unsplit_span_exceeds_limit",
                    parent=current_parent,
                    real_code_count=unsplit_codes,
                )
                continue

            node.node_type = SemanticNodeType.CLASSIFICATION_SUBGROUP
            node.metadata["nested_by"] = hierarchy_hint
            current_parent.children.append(node)

        root.children = top_level
        return fallbacks

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
            has_code_children = any(
                c.node_type in (SemanticNodeType.COMMODITY, SemanticNodeType.LEAF)
                for c in node.children
            )
            if not has_code_children:
                node.node_type = SemanticNodeType.LEAF
