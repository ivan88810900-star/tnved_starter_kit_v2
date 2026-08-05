"""CanonicalModel — иммутабельная Source-of-Truth модель поверх TreeBuilder.

ADR-0001 §3/§5: Canonical TNVED Model — единая авторитетная, детерминированная и
**иммутабельная** модель номенклатуры с устойчивыми `stable_id`, отношениями
parent/children и адресуемостью по коду. Этот модуль материализует результат
`TreeBuilder.build(...)` (list[TreeNode]) в read-only объект с индексами
достижимости (`code → node`, `display_code → node`, `stable_id → node`) и
навигацией (parent/children/path/descendants).

TASK-CANONICAL-010 усиливает publication boundary: после identity stamping и
validator gate замораживаются не только индексы/корни модели, но и каждый
`TreeNode`, его `children`, `parent` и рекурсивные standard metadata-контейнеры.
Builder и recovery до публикации остаются mutable; legacy `build_tree()` не
меняется.

Validator gate (ADR-0001 §4, §6.4): перед созданием модели прогоняется
`TreeValidator`. Если валидатор нашёл ошибки — модель **не создаётся**
(`CanonicalModelValidationError`), старое дерево/oracle остаётся истиной.

ADR-0003 разделяет два понятия: provider source revision решает, когда перестраивать
модель, а `snapshot_id` хеширует детерминированный Canonical output и идентифицирует
то, что было построено. `stable_id` при этом не зависит от snapshot-контента.
"""

from __future__ import annotations

from collections.abc import Iterable
from types import MappingProxyType
from typing import Mapping

from .models import (
    CanonicalAnchor,
    CanonicalSourceRecord,
    ParsedCommodityRecord,
    TreeNode,
    compute_snapshot_id,
    freeze_tree_nodes,
    stamp_snapshot_id,
)
from .validator import TreeValidator, ValidationIssue


_PUBLICATION_TOKEN = object()


def _reject_published_nodes(roots: Iterable[TreeNode]) -> None:
    """Fail before validation/stamping if any reachable node is already published."""

    pending = list(roots)
    seen: set[int] = set()
    while pending:
        node = pending.pop()
        identity = id(node)
        if identity in seen:
            continue
        seen.add(identity)
        if node.is_frozen:
            raise ValueError(
                "published roots cannot be republished and published descendants "
                "cannot be attached to a new Canonical graph without retained inputs"
            )
        pending.extend(node.children)


class CanonicalModelValidationError(RuntimeError):
    """Validator gate не пройден — CanonicalModel не создаётся (ADR-0001 §6.4)."""

    def __init__(self, issues: list[ValidationIssue]) -> None:
        self.issues: list[ValidationIssue] = list(issues)
        preview = "; ".join(f"{i.code}:{i.message}" for i in self.issues[:5])
        super().__init__(
            f"CanonicalModel validation failed ({len(self.issues)} issue(s)): {preview}"
        )


class CanonicalModel:
    """Иммутабельная модель дерева ТН ВЭД с индексами и навигацией.

    Read-only на всех опубликованных ссылках: `roots` и `children(...)` возвращают
    `tuple`, индексы — `MappingProxyType`, а сами узлы и standard metadata
    containers deep-frozen.
    """

    __slots__ = (
        "_roots",
        "_snapshot_id",
        "_node_by_stable_id",
        "_node_by_code",
        "_node_by_display_code",
        "_parent_by_stable_id",
        "_children_by_stable_id",
        "_source_records_by_heading",
        "_frozen",
    )

    def __init__(
        self,
        roots: list[TreeNode],
        snapshot_id: str,
        *,
        source_records: Iterable[ParsedCommodityRecord] = (),
        _publication_token: object | None = None,
    ) -> None:
        if _publication_token is not _PUBLICATION_TOKEN:
            raise TypeError(
                "CanonicalModel must be published through CanonicalModel.from_roots"
            )
        roots_tuple: tuple[TreeNode, ...] = tuple(roots)

        node_by_stable_id: dict[str, TreeNode] = {}
        node_by_code: dict[str, TreeNode] = {}
        node_by_display_code: dict[str, TreeNode] = {}
        parent_by_stable_id: dict[str, TreeNode | None] = {}
        children_by_stable_id: dict[str, tuple[TreeNode, ...]] = {}

        def walk(node: TreeNode, parent: TreeNode | None) -> None:
            sid = node.stable_id
            node_by_stable_id.setdefault(sid, node)
            parent_by_stable_id[sid] = parent
            children_by_stable_id[sid] = tuple(node.children)
            if node.code:
                self._register_code(node_by_code, node.code, node)
            display = node.metadata.get("display_code") or node.code
            if display:
                self._register_code(node_by_display_code, str(display), node)
            for child in node.children:
                walk(child, node)

        for root in roots_tuple:
            walk(root, None)

        source_records_by_heading: dict[str, list[CanonicalSourceRecord]] = {}
        for record in source_records:
            code = str(record.code10 or "").strip()
            if len(code) not in {4, 10} or not code.isdigit():
                continue
            canonical_node = node_by_code.get(code) or node_by_display_code.get(code)
            parent_code: str | None = None
            if canonical_node is not None:
                # A synthetic leaf can have a same-code codeless wrapper.  The
                # semantic overlay represents one source code once, so retain
                # the nearest *distinct* real-code ancestor for containment.
                parent = parent_by_stable_id.get(canonical_node.stable_id)
                seen: set[str] = set()
                while parent is not None and parent.stable_id not in seen:
                    seen.add(parent.stable_id)
                    candidate = str(parent.code or "").strip()
                    omitted_nonleaf_pad = bool(
                        len(candidate) == 10
                        and candidate.endswith("000000")
                        and not parent.metadata.get("is_leaf")
                    )
                    if candidate and candidate != code and not omitted_nonleaf_pad:
                        parent_code = candidate
                        break
                    parent = parent_by_stable_id.get(parent.stable_id)
            heading = code[:4]
            source_records_by_heading.setdefault(heading, []).append(
                CanonicalSourceRecord(
                    code=code,
                    description=(
                        record.raw_description or record.description or ""
                    ).strip(),
                    import_duty=(record.import_duty or "").strip(),
                    is_leaf=bool(
                        canonical_node
                        and canonical_node.metadata.get("is_leaf")
                    ),
                    parent_code=parent_code,
                )
            )
        frozen_source_records = MappingProxyType(
            {
                heading: tuple(sorted(records, key=lambda record: record.code))
                for heading, records in source_records_by_heading.items()
            }
        )
        roots_tuple = freeze_tree_nodes(roots_tuple)

        object.__setattr__(self, "_roots", roots_tuple)
        object.__setattr__(self, "_snapshot_id", snapshot_id)
        object.__setattr__(self, "_node_by_stable_id", MappingProxyType(node_by_stable_id))
        object.__setattr__(self, "_node_by_code", MappingProxyType(node_by_code))
        object.__setattr__(self, "_node_by_display_code", MappingProxyType(node_by_display_code))
        object.__setattr__(self, "_parent_by_stable_id", MappingProxyType(parent_by_stable_id))
        object.__setattr__(self, "_children_by_stable_id", MappingProxyType(children_by_stable_id))
        object.__setattr__(
            self,
            "_source_records_by_heading",
            frozen_source_records,
        )
        object.__setattr__(self, "_frozen", True)

    # -- construction ------------------------------------------------------

    @classmethod
    def from_roots(
        cls,
        roots: list[TreeNode],
        *,
        snapshot_id: str | None = None,
        parse_result=None,
        validator: TreeValidator | None = None,
        source_records: Iterable[ParsedCommodityRecord] | None = None,
    ) -> "CanonicalModel":
        """Собирает CanonicalModel после обязательного validator gate.

        Перед freeze прогоняется `TreeValidator`; при наличии ошибок модель не
        создаётся (`CanonicalModelValidationError`). `parse_result` (если передан)
        включает проверку fake-кодов по `db_codes`. `snapshot_id` по умолчанию
        берётся с уже размеченных узлов (`assign_stable_ids`).
        """
        roots_list = list(roots)
        _reject_published_nodes(roots_list)
        gate = (validator or TreeValidator()).validate(roots_list, parse_result=parse_result)
        if not gate.ok:
            raise CanonicalModelValidationError(gate.issues)
        if snapshot_id is None:
            snapshot_id = roots_list[0].snapshot_id if roots_list else compute_snapshot_id(())
        stamp_snapshot_id(roots_list, snapshot_id)
        retained_records = (
            source_records
            if source_records is not None
            else (parse_result.commodities if parse_result is not None else ())
        )
        return cls(
            roots_list,
            snapshot_id,
            source_records=retained_records,
            _publication_token=_PUBLICATION_TOKEN,
        )

    @staticmethod
    def _register_code(index: dict[str, TreeNode], code: str, node: TreeNode) -> None:
        """Индекс по коду с разрешением коллизий.

        Единственная допустимая коллизия кода — бескодовый L6/L8-заголовок и его
        синтетический лист с тем же 10-значным кодом (ADR-0001 I11). Приоритет
        отдаётся реальному листу (декларируемому коду), а не заголовку-обёртке.
        """
        existing = index.get(code)
        if existing is None:
            index[code] = node
            return
        if not existing.metadata.get("is_leaf") and node.metadata.get("is_leaf"):
            index[code] = node

    # -- read-only guards --------------------------------------------------

    def __setattr__(self, name: str, value) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError(
                f"CanonicalModel is read-only (frozen); cannot set {name!r}"
            )
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        raise AttributeError(
            f"CanonicalModel is read-only (frozen); cannot delete {name!r}"
        )

    # -- properties (immutable views) --------------------------------------

    @property
    def roots(self) -> tuple[TreeNode, ...]:
        return self._roots

    @property
    def snapshot_id(self) -> str:
        return self._snapshot_id

    @property
    def node_by_stable_id(self) -> Mapping[str, TreeNode]:
        return self._node_by_stable_id

    @property
    def node_by_code(self) -> Mapping[str, TreeNode]:
        return self._node_by_code

    @property
    def node_by_display_code(self) -> Mapping[str, TreeNode]:
        return self._node_by_display_code

    @property
    def parent_by_stable_id(self) -> Mapping[str, TreeNode | None]:
        return self._parent_by_stable_id

    @property
    def children_by_stable_id(self) -> Mapping[str, tuple[TreeNode, ...]]:
        return self._children_by_stable_id

    @property
    def source_records_by_heading(
        self,
    ) -> Mapping[str, tuple[CanonicalSourceRecord, ...]]:
        """Official descriptions retained from the Parser snapshot by heading."""

        return self._source_records_by_heading

    # -- lookups -----------------------------------------------------------

    def get(self, stable_id: str) -> TreeNode | None:
        return self._node_by_stable_id.get(stable_id)

    def get_by_code(self, code: str) -> TreeNode | None:
        return self._node_by_code.get(code)

    def get_by_display_code(self, display_code: str) -> TreeNode | None:
        return self._node_by_display_code.get(display_code)

    def source_records_for_heading(
        self,
        heading: str,
    ) -> tuple[CanonicalSourceRecord, ...]:
        """Return immutable semantic inputs from this model's own Parser snapshot."""

        key = "".join(
            character for character in str(heading or "") if character.isdigit()
        )
        if len(key) != 4:
            return ()
        return self._source_records_by_heading.get(key, ())

    def anchor(self, node_or_id: TreeNode | str) -> CanonicalAnchor | None:
        """Return an internal stable/versioned reference without changing API JSON."""
        node = self._node_by_stable_id.get(self._resolve_id(node_or_id))
        return CanonicalAnchor.from_node(node) if node is not None else None

    # -- navigation --------------------------------------------------------

    def parent(self, node_or_id: TreeNode | str) -> TreeNode | None:
        return self._parent_by_stable_id.get(self._resolve_id(node_or_id))

    def children(self, node_or_id: TreeNode | str) -> tuple[TreeNode, ...]:
        return self._children_by_stable_id.get(self._resolve_id(node_or_id), ())

    def path(self, node_or_id: TreeNode | str) -> tuple[TreeNode, ...]:
        """Путь от корня до узла включительно (breadcrumb)."""
        node = self._node_by_stable_id.get(self._resolve_id(node_or_id))
        if node is None:
            return ()
        chain: list[TreeNode] = []
        seen: set[str] = set()
        cursor: TreeNode | None = node
        while cursor is not None and cursor.stable_id not in seen:
            seen.add(cursor.stable_id)
            chain.append(cursor)
            cursor = self._parent_by_stable_id.get(cursor.stable_id)
        return tuple(reversed(chain))

    def descendants(self, node_or_id: TreeNode | str) -> tuple[TreeNode, ...]:
        """Все потомки узла в pre-order (без самого узла)."""
        node = self._node_by_stable_id.get(self._resolve_id(node_or_id))
        if node is None:
            return ()
        out: list[TreeNode] = []
        stack: list[TreeNode] = list(reversed(self._children_by_stable_id.get(node.stable_id, ())))
        while stack:
            current = stack.pop()
            out.append(current)
            children = self._children_by_stable_id.get(current.stable_id, ())
            stack.extend(reversed(children))
        return tuple(out)

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _resolve_id(node_or_id: TreeNode | str) -> str:
        if isinstance(node_or_id, TreeNode):
            return node_or_id.stable_id
        return str(node_or_id)

    def __len__(self) -> int:
        return len(self._node_by_stable_id)

    def __contains__(self, node_or_id: TreeNode | str) -> bool:
        return self._resolve_id(node_or_id) in self._node_by_stable_id

    def __repr__(self) -> str:
        return (
            f"CanonicalModel(snapshot_id={self._snapshot_id!r}, "
            f"roots={len(self._roots)}, nodes={len(self._node_by_stable_id)})"
        )
