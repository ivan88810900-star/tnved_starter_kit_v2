"""SemanticNavigationValidator — структурные проверки семантического дерева."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..tnved_tree.helpers import digits
from .models import (
    GROUP_NODE_TYPES,
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
        self._check_leaves(nodes, issues)
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
