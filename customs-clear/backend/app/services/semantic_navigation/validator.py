"""SemanticNavigationValidator — структурные проверки семантического дерева."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..tnved_tree.helpers import digits
from .models import (
    GROUP_NODE_TYPES,
    MAX_SEMANTIC_GROUP_LEVELS,
    MAX_UNSPLIT_GROUP_CODES,
    SemanticNavigationTree,
    SemanticNode,
    SemanticNodeType,
)

#: Уровни серьёзности.
CRITICAL = "critical"
WARNING = "warning"


@dataclass
class SemanticIssue:
    code: str
    severity: str
    message: str
    node_id: str | None = None


@dataclass
class SemanticValidationResult:
    issues: list[SemanticIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues

    @property
    def critical_issues(self) -> list[SemanticIssue]:
        return [i for i in self.issues if i.severity == CRITICAL]

    @property
    def has_critical(self) -> bool:
        return bool(self.critical_issues)


class SemanticNavigationValidator:
    """Проверяет целостность SemanticNavigationTree (offline QA, не в production)."""

    def validate(
        self,
        tree: SemanticNavigationTree,
        *,
        db_codes: frozenset[str] | set[str] | None = None,
    ) -> SemanticValidationResult:
        issues: list[SemanticIssue] = []
        nodes = tree.all_nodes()

        self._check_ids_and_cycles(tree, issues)
        self._check_groups_have_no_code(nodes, issues)
        self._check_semantic_hierarchy(tree, issues)
        self._check_leaves(nodes, issues)
        self._check_canonical_parent_containment(tree, issues)
        self._check_real_codes(tree, nodes, db_codes, issues)
        self._check_reachability(tree, issues)
        self._check_group_removal_invariance(tree, issues)

        return SemanticValidationResult(issues=issues)

    # -- checks ------------------------------------------------------------

    def _check_ids_and_cycles(
        self, tree: SemanticNavigationTree, issues: list[SemanticIssue]
    ) -> None:
        by_id: dict[str, SemanticNode] = {}

        def walk(node: SemanticNode, ancestors: set[str]) -> None:
            if node.id in ancestors:
                issues.append(
                    SemanticIssue(
                        code="cycle",
                        severity=CRITICAL,
                        message=f"Цикл: узел {node.id} в собственных предках",
                        node_id=node.id,
                    )
                )
                return
            if node.id in by_id:
                issues.append(
                    SemanticIssue(
                        code="duplicate_id",
                        severity=CRITICAL,
                        message=f"Дублирующийся id узла: {node.id}",
                        node_id=node.id,
                    )
                )
            by_id[node.id] = node
            for ch in node.children:
                if ch is node:
                    issues.append(
                        SemanticIssue(
                            code="self_child",
                            severity=CRITICAL,
                            message=f"Self-child: {node.code or node.title}",
                            node_id=node.id,
                        )
                    )
                    continue
                if ch.parent_id != node.id:
                    issues.append(
                        SemanticIssue(
                            code="bad_parent_link",
                            severity=WARNING,
                            message=f"parent_id ребёнка не указывает на родителя: {ch.id}",
                            node_id=ch.id,
                        )
                    )
                if ch.depth != node.depth + 1:
                    issues.append(
                        SemanticIssue(
                            code="bad_depth",
                            severity=WARNING,
                            message=(
                                "depth ребёнка не равен depth родителя + 1: "
                                f"{ch.id}"
                            ),
                            node_id=ch.id,
                        )
                    )
                walk(ch, ancestors | {node.id})

        walk(tree.root, set())

    def _check_groups_have_no_code(
        self, nodes: list[SemanticNode], issues: list[SemanticIssue]
    ) -> None:
        for n in nodes:
            if n.node_type in GROUP_NODE_TYPES and n.code:
                issues.append(
                    SemanticIssue(
                        code="group_has_code",
                        severity=CRITICAL,
                        message=f"Group-узел не должен иметь код: {n.node_type}={n.code}",
                        node_id=n.id,
                    )
                )
            if n.node_type in GROUP_NODE_TYPES and "import_duty" in n.metadata:
                issues.append(
                    SemanticIssue(
                        code="group_has_commodity_field",
                        severity=WARNING,
                        message=f"Group-узел содержит commodity-поле import_duty: {n.title}",
                        node_id=n.id,
                    )
                )

    def _check_semantic_hierarchy(
        self,
        tree: SemanticNavigationTree,
        issues: list[SemanticIssue],
    ) -> None:
        """Проверить допустимую форму controlled semantic-nesting."""

        def unsplit_real_codes(node: SemanticNode) -> int:
            count = 1 if node.carries_real_code and node.code else 0
            for child in node.children:
                if child.node_type in {
                    SemanticNodeType.CLASSIFICATION_GROUP,
                    SemanticNodeType.CLASSIFICATION_SUBGROUP,
                }:
                    continue
                count += unsplit_real_codes(child)
            return count

        def walk(
            node: SemanticNode,
            *,
            parent: SemanticNode | None,
            semantic_levels: int,
        ) -> None:
            is_semantic_group = node.node_type in {
                SemanticNodeType.CLASSIFICATION_GROUP,
                SemanticNodeType.CLASSIFICATION_SUBGROUP,
            }
            next_levels = semantic_levels + (1 if is_semantic_group else 0)

            if node.node_type == SemanticNodeType.CLASSIFICATION_GROUP:
                if parent is None or parent.node_type not in {
                    SemanticNodeType.HEADING,
                    SemanticNodeType.COMMODITY,
                }:
                    issues.append(
                        SemanticIssue(
                            code="classification_group_wrong_parent",
                            severity=CRITICAL,
                            message=(
                                "classification_group должен быть ребёнком heading "
                                "или code-branch: "
                                f"{node.title}"
                            ),
                            node_id=node.id,
                        )
                    )
            elif (
                node.node_type == SemanticNodeType.CLASSIFICATION_SUBGROUP
                and (
                    parent is None
                    or parent.node_type
                    not in {
                        SemanticNodeType.CLASSIFICATION_GROUP,
                        SemanticNodeType.COMMODITY,
                    }
                )
            ):
                issues.append(
                    SemanticIssue(
                        code="classification_subgroup_wrong_parent",
                        severity=CRITICAL,
                        message=(
                            "classification_subgroup должен быть ребёнком "
                            "classification_group или code-branch: "
                            f"{node.title}"
                        ),
                        node_id=node.id,
                    )
                )

            if is_semantic_group:
                if next_levels > MAX_SEMANTIC_GROUP_LEVELS:
                    issues.append(
                        SemanticIssue(
                            code="semantic_group_depth_exceeded",
                            severity=CRITICAL,
                            message=(
                                "Превышена допустимая глубина semantic-групп "
                                f"({MAX_SEMANTIC_GROUP_LEVELS}): {node.title}"
                            ),
                            node_id=node.id,
                        )
                    )
                unsplit = unsplit_real_codes(node)
                if unsplit > MAX_UNSPLIT_GROUP_CODES:
                    issues.append(
                        SemanticIssue(
                            code="oversized_unsplit_group",
                            severity=WARNING,
                            message=(
                                f"Semantic-сегмент {node.title!r} содержит "
                                f"{unsplit} кодов без дальнейшего смыслового "
                                f"разбиения (limit={MAX_UNSPLIT_GROUP_CODES})"
                            ),
                            node_id=node.id,
                        )
                    )

            for child in node.children:
                walk(
                    child,
                    parent=node,
                    semantic_levels=next_levels,
                )

        walk(tree.root, parent=None, semantic_levels=0)

    def _check_leaves(
        self, nodes: list[SemanticNode], issues: list[SemanticIssue]
    ) -> None:
        for n in nodes:
            if n.node_type == SemanticNodeType.LEAF and n.children:
                issues.append(
                    SemanticIssue(
                        code="leaf_has_children",
                        severity=CRITICAL,
                        message=f"Leaf не может иметь детей: {n.code}",
                        node_id=n.id,
                    )
                )
            if not n.carries_real_code or not n.code:
                continue
            evidence = n.metadata.get("leaf_evidence")
            actual_leaf = n.node_type == SemanticNodeType.LEAF
            if evidence is not None and actual_leaf != evidence:
                issues.append(
                    SemanticIssue(
                        code="leaf_role_mismatch",
                        severity=CRITICAL,
                        message=(
                            "Роль leaf расходится с Canonical evidence: "
                            f"{n.code}"
                        ),
                        node_id=n.id,
                    )
                )
            if evidence is False and not any(
                descendant.node_type == SemanticNodeType.LEAF
                for descendant in n.iter_descendants()
            ):
                issues.append(
                    SemanticIssue(
                        code="nonleaf_without_reachable_children",
                        severity=CRITICAL,
                        message=(
                            "Canonical non-leaf не ведёт к декларируемому коду: "
                            f"{n.code}"
                        ),
                        node_id=n.id,
                    )
                )

    def _check_real_codes(
        self,
        tree: SemanticNavigationTree,
        nodes: list[SemanticNode],
        db_codes: frozenset[str] | set[str] | None,
        issues: list[SemanticIssue],
    ) -> None:
        seen: dict[str, int] = {}
        for n in nodes:
            if not n.carries_real_code or not n.code:
                continue
            seen[n.code] = seen.get(n.code, 0) + 1
            if db_codes is not None and n.code not in db_codes:
                # 4-значная позиция реальна, если в БД есть её 10-значные коды
                # (tnved_commodities хранит только 10-значные строки, pad XXXX000000).
                d = digits(n.code)
                valid_prefix = len(d) == 4 and any(
                    c.startswith(d) for c in db_codes if len(digits(c)) >= 10
                )
                if not valid_prefix:
                    issues.append(
                        SemanticIssue(
                            code="fake_code",
                            severity=CRITICAL,
                            message=f"Код отсутствует в БД (fake): {n.code}",
                            node_id=n.id,
                        )
                    )
        for code, cnt in seen.items():
            if cnt > 1:
                issues.append(
                    SemanticIssue(
                        code="duplicate_code",
                        severity=CRITICAL,
                        message=f"Реальный код встречается {cnt} раз: {code}",
                    )
                )

    def _check_canonical_parent_containment(
        self,
        tree: SemanticNavigationTree,
        issues: list[SemanticIssue],
    ) -> None:
        """Every snapshot-projected code must keep its nearest code ancestor."""

        def walk(node: SemanticNode, nearest_code: str | None) -> None:
            next_nearest = nearest_code
            if node.carries_real_code and node.code:
                expected_parent = str(
                    node.metadata.get("canonical_parent_code") or ""
                )
                if expected_parent and nearest_code != expected_parent:
                    issues.append(
                        SemanticIssue(
                            code="canonical_parent_mismatch",
                            severity=CRITICAL,
                            message=(
                                "Ближайший кодовый предок расходится с "
                                f"Canonical snapshot: {node.code}"
                            ),
                            node_id=node.id,
                        )
                    )
                next_nearest = str(node.code)
            for child in node.children:
                walk(child, next_nearest)

        walk(tree.root, None)

    def _check_reachability(
        self, tree: SemanticNavigationTree, issues: list[SemanticIssue]
    ) -> None:
        present = {c for c in tree.real_codes_in_tree()}
        expected = set(tree.expected_real_codes)
        missing = expected - present
        for code in sorted(missing):
            issues.append(
                SemanticIssue(
                    code="unreachable_code",
                    severity=CRITICAL,
                    message=f"Реальный код heading недостижим в дереве: {code}",
                )
            )
        extra = present - expected
        for code in sorted(extra):
            issues.append(
                SemanticIssue(
                    code="unexpected_code",
                    severity=CRITICAL,
                    message=f"В дереве код вне ожидаемого набора heading: {code}",
                )
            )

    def _check_group_removal_invariance(
        self, tree: SemanticNavigationTree, issues: list[SemanticIssue]
    ) -> None:
        """Удаление group-узлов не должно менять набор реальных кодов."""
        with_groups = sorted(set(tree.real_codes_in_tree()))

        flat: list[str] = []

        def collect(node: SemanticNode) -> None:
            for ch in node.children:
                if ch.carries_real_code and ch.code:
                    flat.append(ch.code)
                collect(ch)

        collect(tree.root)
        if tree.root.carries_real_code and tree.root.code:
            flat.append(tree.root.code)

        without_groups = sorted(set(flat))
        if with_groups != without_groups:
            issues.append(
                SemanticIssue(
                    code="group_removal_changes_codes",
                    severity=CRITICAL,
                    message="Удаление group-узлов меняет набор реальных кодов",
                )
            )
