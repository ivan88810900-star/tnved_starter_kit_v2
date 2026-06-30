"""Tree Model v2 — типизированные узлы дерева ТН ВЭД (параллельный контур).

ADR-0001 (Canonical TNVED Model): canonical path **детерминирован** — никаких
`uuid4()`. Идентификаторы узлов (`id` / `stable_id`) присваиваются Builder'ом как
чистая функция от структуры (см. `assign_stable_ids`).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable


class NodeType(str, Enum):
    """Семантический тип узла (не путать с API is_codeless)."""

    HEADING = "heading"  # 4-значная товарная позиция
    CLASSIFICATION_GROUP = "classification_group"  # промежуточная группа / субпозиция
    COMMODITY = "commodity"  # декларируемый или терминальный код


@dataclass
class TreeNode:
    """Базовый узел дерева Tree Model v2.

    `id` / `stable_id` пусты при конструировании и заполняются детерминированно
    в Builder (`assign_stable_ids`). Это исключает `uuid4()` из canonical path.
    """

    title: str
    level: int
    node_type: NodeType
    id: str = ""
    code: str | None = None
    stable_id: str = ""
    snapshot_id: str = ""
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
            id=id or "",
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
            id=id or "",
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
            id=id or "",
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


# ---------------------------------------------------------------------------
# Canonical TNVED Model — детерминированные идентификаторы (ADR-0001, этап 1)
# ---------------------------------------------------------------------------

#: Префикс snapshot-id. Skeleton: содержательный хеш набора кодов БД.
#: Полный provenance (sections/chapters/revision) — TASK-CANONICAL-002.
SNAPSHOT_PREFIX = "snap"
STABLE_ID_PREFIX = "node"


def compute_snapshot_id(db_codes: Iterable[str]) -> str:
    """Детерминированный snapshot_id из набора кодов БД (skeleton).

    Воспроизводим: один и тот же снапшот → один и тот же id. Это **не** полный
    provenance из ADR §3.2 (sections/chapters/revision) — расширение в
    TASK-CANONICAL-002.
    """
    joined = "\n".join(sorted(db_codes))
    digest = hashlib.sha1(joined.encode("utf-8")).hexdigest()
    return f"{SNAPSHOT_PREFIX}-{digest[:16]}"


def _local_key(node: TreeNode) -> str:
    """Локальный ключ узла, уникальный среди соседей и детерминированный.

    Для кодовых узлов — display_code (различает codeless-заголовок L6/L8 и его
    синтетический лист с тем же 10-значным кодом). Для бескодовых групп — title.
    """
    if node.code:
        display = node.metadata.get("display_code") or node.code
        return str(display)
    return f"grp:{node.title}"


def assign_stable_ids(roots: list[TreeNode], *, snapshot_id: str) -> None:
    """Присваивает детерминированный `stable_id` (и `id`) каждому узлу.

    `stable_id = sha1(path)`, где path — цепочка `node_type:local_key` от корня.
    Чистая функция структуры: не зависит от времени/случайности (ADR I3/I4).
    `snapshot_id` хранится отдельно, чтобы stable_id оставался устойчивым между
    снапшотами при неизменной структуре.
    """

    def walk(node: TreeNode, parent_path: str) -> None:
        segment = f"{node.node_type.value}:{_local_key(node)}"
        path = f"{parent_path}/{segment}" if parent_path else segment
        digest = hashlib.sha1(path.encode("utf-8")).hexdigest()
        node.stable_id = f"{STABLE_ID_PREFIX}-{digest[:24]}"
        node.snapshot_id = snapshot_id
        node.id = node.stable_id
        for child in node.children:
            walk(child, path)

    for root in roots:
        walk(root, "")
