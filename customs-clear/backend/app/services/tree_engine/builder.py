"""TreeBuilder — построение TreeNode из промежуточной модели (зеркало build_tree)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..tnved_tree import build_tree, digits, node_level
from .models import (
    ClassificationGroupNode,
    CommodityNode,
    HeadingNode,
    ParsedCommodityRecord,
    TreeNode,
    TreeParseResult,
)


@dataclass
class _CommodityRowAdapter:
    """Минимальный адаптер ParsedCommodityRecord → объект для build_tree."""

    code: str
    description: str
    import_duty: str


class TreeBuilder:
    """Строит TreeNode, делегируя иерархию существующему build_tree()."""

    def build(self, parse_result: TreeParseResult) -> list[TreeNode]:
        rows = [
            _CommodityRowAdapter(
                code=rec.code10,
                description=rec.description,
                import_duty=rec.import_duty,
            )
            for rec in parse_result.commodities
        ]
        legacy_tree = build_tree(rows, parse_result.chapter_notes)
        return [self._from_legacy_dict(node) for node in legacy_tree]

    def build_heading_map(self, parse_result: TreeParseResult) -> dict[str, TreeNode]:
        return {node.code or "": node for node in self.build(parse_result) if node.code}

    def _from_legacy_dict(self, node: dict[str, Any]) -> TreeNode:
        code = (node.get("code") or "").strip()
        display = node.get("display_code") or digits(code)
        is_leaf = bool(node.get("is_leaf"))
        is_codeless = bool(node.get("is_codeless"))
        is_group = bool(node.get("is_group"))
        metadata: dict[str, Any] = {
            "import_duty": node.get("import_duty") or "",
            "notes": node.get("notes") or "",
            "is_leaf": is_leaf,
            "is_codeless": is_codeless,
            "is_group": is_group,
            "display_code": display,
        }
        title = (node.get("name") or "").strip()
        level = node_level(code) if len(digits(code)) >= 10 else 4

        if len(digits(code)) <= 4:
            tree_node: TreeNode = HeadingNode(
                title=title,
                code=code,
                level=4,
                metadata=metadata,
            )
        elif is_codeless or (is_group and not is_leaf):
            tree_node = ClassificationGroupNode(
                title=title,
                code=code or None,
                level=level,
                metadata=metadata,
            )
        else:
            tree_node = CommodityNode(
                title=title,
                code=code,
                level=level,
                metadata=metadata,
            )

        for child in node.get("children") or []:
            tree_node.add_child(self._from_legacy_dict(child))
        return tree_node
