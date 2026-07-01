"""CanonicalModel — иммутабельная Source-of-Truth модель поверх TreeBuilder.

ADR-0001 §3/§5: Canonical TNVED Model — единая авторитетная, детерминированная и
**иммутабельная** модель номенклатуры с устойчивыми `stable_id`, отношениями
parent/children и адресуемостью по коду. Этот модуль материализует результат
`TreeBuilder.build(...)` (list[TreeNode]) в read-only объект с индексами
достижимости (`code → node`, `display_code → node`, `stable_id → node`) и
навигацией (parent/children/path/descendants).

Границы этого этапа (см. TASK — Canonical Model Materialization):
- модель **не подключается** к API / runtime / lifespan;
- **нет** feature flag;
- legacy `build_tree()` остаётся production и oracle;
- freeze — на уровне **интерфейса** (индексы и `roots`/`children` возвращаются
  как immutable view / tuple; переустановка атрибутов модели запрещена).
  Глубокая физическая иммутабельность каждого `TreeNode` (заморозка `children`
  и `metadata` самих узлов) **не** входит в этот этап и зафиксирована как
  известное ограничение.

Validator gate (ADR-0001 §4, §6.4): перед созданием модели прогоняется
`TreeValidator`. Если валидатор нашёл ошибки — модель **не создаётся**
(`CanonicalModelValidationError`), старое дерево/oracle остаётся истиной.

Known debt (не решается в этой задаче, см. `.ai/CURRENT_STATE.md` §8):
`snapshot_id` считается от `db_codes` и **не** учитывает все входы (в частности
`hs_rates`/leaf-флаги, `import_duty`, примечания глав). Кэш/инвалидация по такому
`snapshot_id` пока ненадёжны — расширение входов вынесено в отдельный derisking-этап.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping

from .models import TreeNode
from .validator import TreeValidator, ValidationIssue


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

    Read-only на уровне интерфейса: `roots` и `children(...)` возвращают `tuple`,
    индексы — `MappingProxyType`; переустановка/удаление атрибутов запрещены.
    """

    __slots__ = (
        "_roots",
        "_snapshot_id",
        "_node_by_stable_id",
        "_node_by_code",
        "_node_by_display_code",
        "_parent_by_stable_id",
        "_children_by_stable_id",
        "_frozen",
    )

    def __init__(self, roots: list[TreeNode], snapshot_id: str) -> None:
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

        object.__setattr__(self, "_roots", roots_tuple)
        object.__setattr__(self, "_snapshot_id", snapshot_id)
        object.__setattr__(self, "_node_by_stable_id", MappingProxyType(node_by_stable_id))
        object.__setattr__(self, "_node_by_code", MappingProxyType(node_by_code))
        object.__setattr__(self, "_node_by_display_code", MappingProxyType(node_by_display_code))
        object.__setattr__(self, "_parent_by_stable_id", MappingProxyType(parent_by_stable_id))
        object.__setattr__(self, "_children_by_stable_id", MappingProxyType(children_by_stable_id))
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
    ) -> "CanonicalModel":
        """Собирает CanonicalModel после обязательного validator gate.

        Перед freeze прогоняется `TreeValidator`; при наличии ошибок модель не
        создаётся (`CanonicalModelValidationError`). `parse_result` (если передан)
        включает проверку fake-кодов по `db_codes`. `snapshot_id` по умолчанию
        берётся с уже размеченных узлов (`assign_stable_ids`).
        """
        roots_list = list(roots)
        gate = (validator or TreeValidator()).validate(roots_list, parse_result=parse_result)
        if not gate.ok:
            raise CanonicalModelValidationError(gate.issues)
        if snapshot_id is None:
            snapshot_id = roots_list[0].snapshot_id if roots_list else ""
        return cls(roots_list, snapshot_id)

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

    # -- lookups -----------------------------------------------------------

    def get(self, stable_id: str) -> TreeNode | None:
        return self._node_by_stable_id.get(stable_id)

    def get_by_code(self, code: str) -> TreeNode | None:
        return self._node_by_code.get(code)

    def get_by_display_code(self, display_code: str) -> TreeNode | None:
        return self._node_by_display_code.get(display_code)

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
