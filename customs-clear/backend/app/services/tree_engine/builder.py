"""TreeBuilder — сборка типизированных узлов из recovery-результата.

ADR-0001 §6.3: Builder строит типизированные узлы напрямую (без делегирования в
legacy `build_tree`) с детерминированными `stable_id`. Recovery-логика вынесена в
`StructureNormalizer` (стадия Recovery); Builder отвечает за **сборку иерархии**
(stack/parent-children), материализацию синтетических листьев и pad-subheading-
group, и присвоение идентификаторов. legacy `build_tree()` остаётся production и
oracle до достижения parity.
"""

from __future__ import annotations

from ...db import SessionLocal
from ...models import HsRate
from ..tnved_tree import digits
from .canonical_model import CanonicalModel
from .models import (
    ClassificationGroupNode,
    CommodityNode,
    HeadingNode,
    TreeNode,
    TreeParseResult,
    assign_stable_ids,
    compute_snapshot_id,
)
from .recovery import RecoveredHeading, RecoveredNode, StructureNormalizer
from .validator import TreeValidator

_LEAF_FLAG_CHUNK = 500


class TreeBuilder:
    """Собирает TreeNode из RecoveredHeading (Parser → Recovery → Builder)."""

    def __init__(self, normalizer: StructureNormalizer | None = None) -> None:
        self._normalizer = normalizer or StructureNormalizer()

    def build(self, parse_result: TreeParseResult) -> list[TreeNode]:
        leaf_flags = self._compute_leaf_flags(parse_result)
        recovered = self._normalizer.normalize(
            parse_result.commodities,
            chapter_notes=parse_result.chapter_notes,
            leaf_flags=leaf_flags,
        )
        roots = [self._assemble(rh) for rh in recovered]
        snapshot_id = compute_snapshot_id(parse_result.db_codes)
        assign_stable_ids(roots, snapshot_id=snapshot_id)
        return roots

    def build_heading_map(self, parse_result: TreeParseResult) -> dict[str, TreeNode]:
        return {node.code or "": node for node in self.build(parse_result) if node.code}

    def build_model(
        self,
        parse_result: TreeParseResult,
        *,
        validate: bool = True,
        validator: TreeValidator | None = None,
    ) -> CanonicalModel:
        """Материализует иммутабельную CanonicalModel из результата `build`.

        Additive API: не меняет `build()` (по-прежнему `list[TreeNode]`), а
        оборачивает его в read-only модель с индексами. Перед freeze прогоняется
        validator gate (ADR-0001 §6.4); при `validate=True` проверка fake-кодов
        идёт по `parse_result.db_codes`. Модель к runtime не подключается.
        """
        roots = self.build(parse_result)
        snapshot_id = compute_snapshot_id(parse_result.db_codes)
        return CanonicalModel.from_roots(
            roots,
            snapshot_id=snapshot_id,
            parse_result=parse_result if validate else None,
            validator=validator,
        )

    # -- leaf-флаги (БД вне нормализатора, R2) -----------------------------

    def _compute_leaf_flags(self, parse_result: TreeParseResult) -> dict[str, bool]:
        """Предвычисляет leaf-признаки для неоднозначных «…0000» кодов.

        Повторяет предикат `normative_store.is_leaf_hs_code` (наличие строки в
        `hs_rates`) одним bulk-запросом. Держит БД-доступ ВНЕ `StructureNormalizer`.
        """
        ambiguous = sorted(
            {
                rec.code10
                for rec in parse_result.commodities
                if len(rec.code10) == 10 and rec.code10.endswith("0000")
            }
        )
        existing: set[str] = set()
        if ambiguous:
            with SessionLocal() as db:
                for i in range(0, len(ambiguous), _LEAF_FLAG_CHUNK):
                    chunk = ambiguous[i : i + _LEAF_FLAG_CHUNK]
                    rows = db.query(HsRate.hs_code).filter(HsRate.hs_code.in_(chunk)).all()
                    existing.update(code for (code,) in rows)
        return {code: (code in existing) for code in ambiguous}

    # -- сборка иерархии (assembly = Builder) ------------------------------

    def _assemble(self, rh: RecoveredHeading) -> TreeNode:
        heading = HeadingNode(
            title=rh.name,
            code=rh.code,
            level=4,
            metadata={
                "import_duty": "",
                "notes": rh.notes,
                "is_leaf": False,
                "is_codeless": False,
                "is_group": True,
                "display_code": rh.code,
            },
        )

        subheading_group: TreeNode | None = None
        if rh.use_subheading_group and rh.subheading_group is not None:
            subheading_group = self._make_node(rh.subheading_group)
            heading.add_child(subheading_group)

        stack: list[tuple[int, TreeNode]] = []
        for entry in rh.entries:
            lvl = entry.level
            node = self._make_node(entry)
            if (
                rh.use_subheading_group
                and subheading_group is not None
                and lvl == 6
                and entry.code not in rh.direct_l6
            ):
                stack.clear()
                parent = subheading_group
            else:
                while stack and stack[-1][0] >= lvl:
                    stack.pop()
                parent = stack[-1][1] if stack else heading
            parent.add_child(node)
            stack.append((lvl, node))
            if entry.synthetic_leaf is not None:
                node.add_child(self._make_node(entry.synthetic_leaf))

        self._sort_children(heading)

        if not heading.title:
            leaf_names: list[str] = []
            self._collect_leaf_names(heading, leaf_names)
            heading.title = self._normalizer.recover_group_name(leaf_names)

        return heading

    def _make_node(self, rn: RecoveredNode) -> TreeNode:
        metadata: dict[str, object] = {
            "import_duty": rn.import_duty or "",
            "notes": rn.notes or "",
            "is_leaf": rn.is_leaf,
            "is_codeless": rn.is_codeless,
            "is_group": rn.is_group,
            "display_code": rn.display_code or rn.code,
        }
        if rn.is_synthetic:
            metadata["is_synthetic"] = True

        if len(digits(rn.code)) <= 4:
            return HeadingNode(title=rn.name, code=rn.code, level=4, metadata=metadata)
        if rn.is_codeless or (rn.is_group and not rn.is_leaf):
            return ClassificationGroupNode(
                title=rn.name, code=rn.code or None, level=rn.level, metadata=metadata
            )
        return CommodityNode(title=rn.name, code=rn.code, level=rn.level, metadata=metadata)

    @staticmethod
    def _sort_children(node: TreeNode) -> None:
        node.children.sort(key=lambda ch: ch.code or "")
        for child in node.children:
            TreeBuilder._sort_children(child)

    @staticmethod
    def _collect_leaf_names(node: TreeNode, acc: list[str]) -> None:
        for child in node.children:
            if not child.children:
                acc.append(child.title)
            else:
                TreeBuilder._collect_leaf_names(child, acc)
