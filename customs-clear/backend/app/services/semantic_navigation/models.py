"""Semantic Navigation v1 — доменные модели смыслового дерева ТН ВЭД.

Отдельный экспериментальный слой. Не связан с production API и _build_tree().
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterator
from uuid import uuid4


class SemanticNodeType(str, Enum):
    """Тип узла семантической навигации."""

    SECTION = "section"
    CHAPTER = "chapter"
    HEADING = "heading"
    CLASSIFICATION_GROUP = "classification_group"
    CLASSIFICATION_SUBGROUP = "classification_subgroup"
    COMMODITY = "commodity"
    LEAF = "leaf"


#: Узлы-навигаторы (НЕ товары) — не несут реального кода ТН ВЭД.
GROUP_NODE_TYPES: frozenset[SemanticNodeType] = frozenset(
    {
        SemanticNodeType.SECTION,
        SemanticNodeType.CHAPTER,
        SemanticNodeType.CLASSIFICATION_GROUP,
        SemanticNodeType.CLASSIFICATION_SUBGROUP,
    }
)

#: Узлы, несущие реальный код из БД.
REAL_CODE_NODE_TYPES: frozenset[SemanticNodeType] = frozenset(
    {
        SemanticNodeType.HEADING,
        SemanticNodeType.COMMODITY,
        SemanticNodeType.LEAF,
    }
)


def _new_id() -> str:
    return uuid4().hex


@dataclass
class SourceRecord:
    """Сырая запись из tnved_commodities (read-only вход экстрактора)."""

    code: str
    description: str
    import_duty: str = ""


@dataclass
class SemanticNode:
    """Узел семантического дерева навигации."""

    node_type: SemanticNodeType
    title: str
    id: str = field(default_factory=_new_id)
    code: str | None = None
    parent_id: str | None = None
    children: list[SemanticNode] = field(default_factory=list, repr=False)
    depth: int = 0
    source: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_group(self) -> bool:
        return self.node_type in GROUP_NODE_TYPES

    @property
    def carries_real_code(self) -> bool:
        return self.node_type in REAL_CODE_NODE_TYPES

    def add_child(self, child: SemanticNode) -> SemanticNode:
        child.parent_id = self.id
        child.depth = self.depth + 1
        self.children.append(child)
        return child

    def iter_descendants(self) -> Iterator[SemanticNode]:
        for ch in self.children:
            yield ch
            yield from ch.iter_descendants()


@dataclass
class SemanticNavigationTree:
    """Результат построения семантической навигации для одного heading."""

    heading: str
    root: SemanticNode
    expected_real_codes: frozenset[str]
    ungrouped_codes: list[str] = field(default_factory=list)
    pad_code: str | None = None
    #: Отбракованные кандидаты в группы (confidence=low): (title, reason, source_code).
    rejected_candidates: list[tuple[str, str, str]] = field(default_factory=list)

    def all_nodes(self) -> list[SemanticNode]:
        return [self.root, *self.root.iter_descendants()]

    def nodes_by_id(self) -> dict[str, SemanticNode]:
        return {n.id: n for n in self.all_nodes()}

    def real_codes_in_tree(self) -> list[str]:
        """Все реальные коды, достижимые в дереве (в порядке обхода)."""
        return [n.code for n in self.all_nodes() if n.carries_real_code and n.code]

    def group_nodes(self) -> list[SemanticNode]:
        return [n for n in self.all_nodes() if n.is_group]
