"""Tree Model v2 — типизированные узлы дерева ТН ВЭД (параллельный контур)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import uuid4


class NodeType(str, Enum):
    """Семантический тип узла (не путать с API is_codeless)."""

    HEADING = "heading"  # 4-значная товарная позиция
    CLASSIFICATION_GROUP = "classification_group"  # промежуточная группа / субпозиция
    COMMODITY = "commodity"  # декларируемый или терминальный код


def _new_id() -> str:
    return uuid4().hex


@dataclass
class TreeNode:
    """Базовый узел дерева Tree Model v2."""

    title: str
    level: int
    node_type: NodeType
    id: str = field(default_factory=_new_id)
    code: str | None = None
    parent: TreeNode | None = field(default=None, repr=False)
    children: list[TreeNode] = field(default_factory=list, repr=False)
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_child(self, child: TreeNode) -> TreeNode:
        child.parent = self
        self.children.append(child)
        return child


@dataclass
class HeadingNode(TreeNode):
    """4-значная товарная позиция (XXXX)."""

    def __init__(
        self,
        *,
        title: str,
        code: str,
        level: int = 4,
        id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            id=id or _new_id(),
            title=title,
            level=level,
            node_type=NodeType.HEADING,
            code=code,
            metadata=metadata or {},
        )


@dataclass
class ClassificationGroupNode(TreeNode):
    """Промежуточная классификационная группа (субпозиция / подзаголовок)."""

    def __init__(
        self,
        *,
        title: str,
        code: str | None,
        level: int,
        id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            id=id or _new_id(),
            title=title,
            level=level,
            node_type=NodeType.CLASSIFICATION_GROUP,
            code=code,
            metadata=metadata or {},
        )


@dataclass
class CommodityNode(TreeNode):
    """Терминальный товарный код (лист или декларируемая позиция)."""

    def __init__(
        self,
        *,
        title: str,
        code: str,
        level: int,
        id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            id=id or _new_id(),
            title=title,
            level=level,
            node_type=NodeType.COMMODITY,
            code=code,
            metadata=metadata or {},
        )


@dataclass
class ParsedCommodityRecord:
    """Плоская запись из БД — промежуточная модель Parser."""

    code10: str
    description: str
    raw_description: str
    import_duty: str
    chapter_id: int | None = None
    unit: str = ""
    supp_unit: str = ""
    weight_coeff: float = 0.0


@dataclass
class TreeParseResult:
    """Результат TreeParser — без построенного дерева."""

    commodities: list[ParsedCommodityRecord]
    chapter_notes: dict[str, str]
    db_codes: frozenset[str]
