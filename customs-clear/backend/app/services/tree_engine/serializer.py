"""TreeSerializer — TreeNode → JSON-структура legacy _build_tree (контракт API)."""

from __future__ import annotations

from typing import Any

from .models import TreeNode


class TreeSerializer:
    """Сериализует TreeNode в dict, совместимый с _build_tree / list_tnved_children."""

    def to_legacy_dict(self, node: TreeNode) -> dict[str, Any]:
        md = node.metadata
        code = node.code or ""
        return {
            "code": code,
            "name": node.title,
            "import_duty": md.get("import_duty") or "",
            "notes": md.get("notes") or "",
            "is_leaf": bool(md.get("is_leaf")),
            "is_codeless": bool(md.get("is_codeless")),
            "is_group": bool(md.get("is_group")),
            "display_code": md.get("display_code") or code,
            "children": [self.to_legacy_dict(ch) for ch in node.children],
        }

    def serialize_roots(self, roots: list[TreeNode]) -> list[dict[str, Any]]:
        return [self.to_legacy_dict(root) for root in roots]

    @staticmethod
    def structure_fingerprint(node: dict[str, Any]) -> tuple[Any, ...]:
        """Компактный отпечаток иерархии: (code, child_count, nested...)."""
        children = node.get("children") or []
        return (
            node.get("code") or "",
            len(children),
            tuple(
                TreeSerializer.structure_fingerprint(ch)
                for ch in children
            ),
        )
