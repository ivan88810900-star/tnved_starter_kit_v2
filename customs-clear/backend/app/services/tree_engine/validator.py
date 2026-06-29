"""TreeValidator — структурные проверки дерева (не используется в production)."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..tnved_tree import (
    digits,
    is_direct_position_subheading,
    needs_pad_subheading_group,
    node_level,
)
from .models import NodeType, TreeNode, TreeParseResult


@dataclass
class ValidationIssue:
    code: str
    message: str
    node_id: str | None = None


@dataclass
class ValidationResult:
    ok: bool
    issues: list[ValidationIssue] = field(default_factory=list)


class TreeValidator:
    """Проверяет целостность TreeNode-дерева."""

    def validate(
        self,
        roots: list[TreeNode],
        *,
        parse_result: TreeParseResult | None = None,
    ) -> ValidationResult:
        issues: list[ValidationIssue] = []
        seen_ids: set[str] = set()
        codes_seen: dict[str, str] = {}
        db_codes = set(parse_result.db_codes) if parse_result else None

        def walk(node: TreeNode, stack: list[str]) -> None:
            if node.id in stack:
                issues.append(
                    ValidationIssue(
                        code="cycle",
                        message=f"Цикл: узел {node.id} встречен повторно в цепочке предков",
                        node_id=node.id,
                    )
                )
                return
            if node.id in seen_ids:
                issues.append(
                    ValidationIssue(
                        code="duplicate_id",
                        message=f"Дублирующийся id узла: {node.id}",
                        node_id=node.id,
                    )
                )
            seen_ids.add(node.id)

            if node in node.children:
                issues.append(
                    ValidationIssue(
                        code="self_child",
                        message=f"Узел является собственным ребёнком: {node.code or node.id}",
                        node_id=node.id,
                    )
                )

            if node.code:
                prev = codes_seen.get(node.code)
                if prev and prev != node.id:
                    allowed_dup = (
                        node.metadata.get("is_leaf")
                        and node.parent is not None
                        and node.parent.code == node.code
                        and node.parent.metadata.get("is_codeless")
                    )
                    if not allowed_dup:
                        issues.append(
                            ValidationIssue(
                                code="duplicate_code",
                                message=f"Дублирующийся code={node.code}",
                                node_id=node.id,
                            )
                        )
                else:
                    codes_seen[node.code] = node.id

                if db_codes is not None and node.code not in db_codes:
                    d = digits(node.code)
                    is_valid_prefix = len(d) == 4 and any(
                        c.startswith(d) for c in db_codes if len(digits(c)) >= 4
                    )
                    if not is_valid_prefix and not node.metadata.get("is_synthetic"):
                        issues.append(
                            ValidationIssue(
                                code="fake_code",
                                message=f"Код отсутствует в БД: {node.code}",
                                node_id=node.id,
                            )
                        )

            if node.node_type == NodeType.COMMODITY and node.metadata.get("is_leaf") and node.children:
                issues.append(
                    ValidationIssue(
                        code="leaf_has_children",
                        message=f"Лист не должен иметь детей: {node.code}",
                        node_id=node.id,
                    )
                )

            if node.parent is None and node not in roots:
                issues.append(
                    ValidationIssue(
                        code="orphan",
                        message=f"Узел без parent вне корней: {node.code or node.id}",
                        node_id=node.id,
                    )
                )

            for child in node.children:
                if child.parent is not node:
                    issues.append(
                        ValidationIssue(
                            code="orphan",
                            message=f"Ребёнок ссылается на другого parent: {child.code or child.id}",
                            node_id=child.id,
                        )
                    )
                walk(child, stack + [node.id])

            if node.node_type == NodeType.HEADING:
                self._check_pad_swallowing(node, issues)

        for root in roots:
            walk(root, [])

        return ValidationResult(ok=not issues, issues=issues)

    def _check_pad_swallowing(self, heading: TreeNode, issues: list[ValidationIssue]) -> None:
        """Pad-узел XXXX000000 допустим только при паттерне 0101 (needs_pad_subheading_group)."""
        if not heading.code or len(heading.children) != 1:
            return
        only = heading.children[0]
        if only.node_type != NodeType.CLASSIFICATION_GROUP:
            return
        if not only.metadata.get("is_codeless"):
            return
        pad_code = f"{heading.code}000000"
        if (only.code or "") != pad_code:
            return

        level6_codes: list[str] = []

        def collect_l6(node: TreeNode) -> None:
            code = node.code or ""
            d = digits(code)
            if len(d) == 10 and node_level(d) == 6:
                level6_codes.append(d)
            for ch in node.children:
                collect_l6(ch)

        for ch in heading.children:
            collect_l6(ch)

        if not needs_pad_subheading_group(
            only.title,
            level6_codes,
        ):
            issues.append(
                ValidationIssue(
                    code="pad_swallowing",
                    message=(
                        f"Подозрительный pad-узел {pad_code} под {heading.code}: "
                        "группа не требуется по needs_pad_subheading_group"
                    ),
                    node_id=only.id,
                )
            )

    @staticmethod
    def collect_level6_under_heading(heading: TreeNode) -> list[str]:
        out: list[str] = []
        for child in heading.children:
            code = child.code or ""
            d = digits(code)
            if len(d) == 10 and node_level(d) == 6:
                out.append(d)
            for grand in child.children:
                gd = digits(grand.code or "")
                if len(gd) == 10 and node_level(gd) == 6:
                    out.append(gd)
        return out

    @staticmethod
    def has_direct_l6(level6_codes: list[str]) -> bool:
        return any(is_direct_position_subheading(c) for c in level6_codes)
