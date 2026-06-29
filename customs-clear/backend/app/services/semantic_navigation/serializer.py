"""SemanticNavigationSerializer — внутренний debug-формат (не публичный API)."""

from __future__ import annotations

from typing import Any

from .models import SemanticNavigationTree, SemanticNode


class SemanticNavigationSerializer:
    """Сериализует семантическое дерево в debug-словарь. Контракт API не затрагивается."""

    def to_debug_dict(self, tree: SemanticNavigationTree) -> dict[str, Any]:
        return {
            "heading": tree.heading,
            "pad_code": tree.pad_code,
            "ungrouped_codes": list(tree.ungrouped_codes),
            "items": [self._node(ch) for ch in tree.root.children],
            "root": self._node(tree.root),
        }

    def _node(self, node: SemanticNode) -> dict[str, Any]:
        return {
            "id": node.id,
            "node_type": node.node_type.value,
            "title": node.title,
            "code": node.code,
            "depth": node.depth,
            "source": node.source,
            "children": [self._node(ch) for ch in node.children],
        }

    def to_text(self, tree: SemanticNavigationTree) -> str:
        """Человекочитаемое дерево с отступами (для диагностики)."""
        lines: list[str] = []

        def walk(node: SemanticNode, indent: int) -> None:
            prefix = "  " * indent
            code = f" [{node.code}]" if node.code else ""
            lines.append(f"{prefix}{node.node_type.value}: {node.title}{code}")
            for ch in node.children:
                walk(ch, indent + 1)

        walk(tree.root, 0)
        return "\n".join(lines)
