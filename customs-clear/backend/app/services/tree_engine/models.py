"""Tree Model v2 — типизированные узлы дерева ТН ВЭД (параллельный контур).

ADR-0001 (Canonical TNVED Model): canonical path **детерминирован** — никаких
`uuid4()`. Идентификаторы узлов (`id` / `stable_id`) присваиваются Builder'ом как
чистая функция от структуры (см. `assign_stable_ids`).
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
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
    """Все явные входы Builder, собранные TreeParser из одного DB snapshot."""

    commodities: list[ParsedCommodityRecord]
    chapter_notes: dict[str, str]
    db_codes: frozenset[str]
    leaf_flags: dict[str, bool] = field(default_factory=dict)


@dataclass(frozen=True)
class CanonicalAnchor:
    """Additive internal reference to one node in one Canonical snapshot."""

    stable_id: str
    snapshot_id: str
    code: str | None
    node_type: NodeType

    @classmethod
    def from_node(cls, node: TreeNode) -> "CanonicalAnchor":
        return cls(
            stable_id=node.stable_id,
            snapshot_id=node.snapshot_id,
            code=node.code,
            node_type=node.node_type,
        )


# ---------------------------------------------------------------------------
# Canonical TNVED Model — детерминированные идентификаторы (ADR-0001, этап 1)
# ---------------------------------------------------------------------------

#: Версионированные контракты ADR-0003 / TASK-CANONICAL-005.
SNAPSHOT_PREFIX = "snap-v2"
STABLE_ID_PREFIX = "node"
STABLE_ID_VERSION = "stable-id-v1"
SNAPSHOT_VERSION = "canonical-snapshot-v2"


def _normalize_identity_text(value: object) -> str:
    """Cross-engine hash normalization: Unicode NFC + outer trim only."""
    return unicodedata.normalize("NFC", str(value or "")).strip()


def _snapshot_node_payload(node: TreeNode) -> dict[str, object]:
    metadata = node.metadata
    return {
        "children": [_snapshot_node_payload(child) for child in node.children],
        "code": _normalize_identity_text(node.code),
        "display_code": _normalize_identity_text(metadata.get("display_code") or node.code),
        "import_duty": _normalize_identity_text(metadata.get("import_duty")),
        "is_codeless": bool(metadata.get("is_codeless")),
        "is_group": bool(metadata.get("is_group")),
        "is_leaf": bool(metadata.get("is_leaf")),
        "is_synthetic": bool(metadata.get("is_synthetic")),
        "level": int(node.level),
        "node_type": node.node_type.value,
        "notes": _normalize_identity_text(metadata.get("notes")),
        "title": _normalize_identity_text(node.title),
    }


def compute_snapshot_id(roots: Iterable[TreeNode]) -> str:
    """Hash the deterministic Canonical output, not raw storage identifiers."""
    payload = [_snapshot_node_payload(root) for root in roots]
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    digest = hashlib.sha256()
    digest.update(f"{SNAPSHOT_VERSION}\n".encode("ascii"))
    digest.update(encoded)
    return f"{SNAPSHOT_PREFIX}-{digest.hexdigest()[:32]}"


def _local_key(node: TreeNode) -> str:
    """Локальный ключ узла, уникальный среди соседей и детерминированный.

    Для кодовых узлов — display_code (различает codeless-заголовок L6/L8 и его
    синтетический лист с тем же 10-значным кодом). Для бескодовых групп — title.
    """
    if node.code:
        display = node.metadata.get("display_code") or node.code
        return _normalize_identity_text(display)
    return f"grp:{_normalize_identity_text(node.title)}"


def assign_stable_ids(
    roots: list[TreeNode],
    *,
    snapshot_id: str | None = None,
) -> None:
    """Присваивает детерминированный `stable_id` (и `id`) каждому узлу.

    `stable_id = sha1(version + canonical_json(path_segments))`, где каждый
    segment — пара `(node_type, local_key)`. JSON исключает коллизии разделителя.
    Чистая функция структуры: не зависит от времени/случайности (ADR I3/I4).
    `snapshot_id` хранится отдельно, чтобы stable_id оставался устойчивым между
    снапшотами при неизменной структуре.
    """

    def walk(node: TreeNode, parent_path: tuple[tuple[str, str], ...]) -> None:
        path = (*parent_path, (node.node_type.value, _local_key(node)))
        encoded_path = json.dumps(
            path,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        digest = hashlib.sha1(
            f"{STABLE_ID_VERSION}\n".encode("ascii") + encoded_path
        ).hexdigest()
        node.stable_id = f"{STABLE_ID_PREFIX}-{digest[:24]}"
        if snapshot_id is not None:
            node.snapshot_id = snapshot_id
        node.id = node.stable_id
        for child in node.children:
            walk(child, path)

    for root in roots:
        walk(root, ())


def stamp_snapshot_id(roots: Iterable[TreeNode], snapshot_id: str) -> None:
    """Stamp one output version on every node after the snapshot hash is known."""

    def walk(node: TreeNode) -> None:
        node.snapshot_id = snapshot_id
        for child in node.children:
            walk(child)

    for root in roots:
        walk(root)
