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

        nesting_fallbacks = self._apply_controlled_nesting(root)
        self._restore_canonical_code_containment(root)
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
    def _detach_out_of_scope_children(
        node: SemanticNode,
    ) -> list[SemanticNode]:
        """Не позволить trailing-заголовку поглотить соседний кодовый диапазон."""

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
