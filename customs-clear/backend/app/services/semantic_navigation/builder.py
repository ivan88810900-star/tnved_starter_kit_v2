"""SemanticNavigationBuilder — экспериментальное semantic-tree для одного heading.

Строит навигацию вида:

    0302  (heading)
      classification_group: лососевые
        commodity: 0302110000
        commodity: 0302130000
      classification_group: камбалообразные
        ...

НЕ влияет на production API и текущее дерево. Реальные коды берутся только из БД.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ...models.tnved import Commodity
from ..tnved_tree.data_access import exclude_obsolete_reserved
from ..tnved_tree.helpers import digits, node_level
from .extractor import SemanticStructureExtractor
from .models import (
    SemanticNavigationTree,
    SemanticNode,
    SemanticNodeType,
    SourceRecord,
)


class SemanticNavigationBuilder:
    """Собирает SemanticNavigationTree для одной 4-значной позиции."""

    def __init__(self, extractor: SemanticStructureExtractor | None = None) -> None:
        self.extractor = extractor or SemanticStructureExtractor()

    # -- public ------------------------------------------------------------

    def build_heading(self, db: Session, heading: str) -> SemanticNavigationTree:
        heading4 = digits(heading).zfill(4)[:4]
        records = self._load_records(db, heading4)
        heading_title = self._heading_title(db, heading4, records)
        extraction = self.extractor.extract(heading4, records)
        return self._assemble(heading4, heading_title, extraction)

    # -- data access -------------------------------------------------------

    def _load_records(self, db: Session, heading4: str) -> list[SourceRecord]:
        rows = (
            exclude_obsolete_reserved(
                db.query(Commodity).filter(Commodity.code.like(f"{heading4}%"))
            )
            .order_by(Commodity.code.asc())
            .all()
        )
        return [
            SourceRecord(
                code=str(r.code or ""),
                description=(r.description or "").strip(),
                import_duty=(r.import_duty or "").strip(),
            )
            for r in rows
        ]

    def _heading_title(
        self, db: Session, heading4: str, records: list[SourceRecord]
    ) -> str:
        for rec in records:
            if digits(rec.code).zfill(4)[:4] == heading4 and len(digits(rec.code)) <= 4:
                if rec.description:
                    return rec.description
        pad = heading4 + "000000"
        for rec in records:
            if digits(rec.code).zfill(10)[:10] == pad:
                return self.extractor.main_title(rec.description)
        return ""

    # -- assembling --------------------------------------------------------

    def _assemble(
        self,
        heading4: str,
        heading_title: str,
        extraction,
    ) -> SemanticNavigationTree:
        root = SemanticNode(
            node_type=SemanticNodeType.HEADING,
            title=heading_title,
            code=heading4,
            depth=0,
            source="tnved_commodities",
            metadata={"pad_code": extraction.pad_code},
        )

        # Плоская группировка: каждая принятая группа — sibling под heading.
        # Это сознательное решение этапа 2: исходные «прилипшие» заголовки не несут
        # надёжной информации о вложенности, поэтому вложенные группы (напр. «тунец
        # синий» внутри «тунец», но и «мерлуза» рядом) не строим — иначе одна группа
        # поглощает соседние. Вложенность товаров сохраняется по node_level кода.
        position = {code: i for i, code in enumerate(extraction.commodity_codes)}
        activations: dict[int, list] = {}
        for grp in extraction.groups:
            idx = 0 if grp.after_code is None else position.get(grp.after_code, -1) + 1
            activations.setdefault(idx, []).append(grp)

        current_group: SemanticNode | None = None
        commodity_stack: list[tuple[int, SemanticNode]] = []  # (node_level, node)
        ungrouped: list[str] = []

        def open_groups(idx: int) -> None:
            nonlocal current_group, commodity_stack
            for grp in activations.get(idx, []):
                gnode = SemanticNode(
                    node_type=SemanticNodeType.CLASSIFICATION_GROUP,
                    title=grp.title,
                    code=None,
                    source="semantic_extraction",
                    metadata={
                        "raw": grp.raw,
                        "extracted_from": grp.source_code,
                        "confidence": grp.confidence,
                        "reason": grp.reason,
                    },
                )
                root.add_child(gnode)
                current_group = gnode
                commodity_stack = []

        for i, code10 in enumerate(extraction.commodity_codes):
            open_groups(i)
            rec = extraction.records_by_code[code10]
            lvl = node_level(code10)

            while commodity_stack and commodity_stack[-1][0] >= lvl:
                commodity_stack.pop()
            if commodity_stack:
                parent = commodity_stack[-1][1]
            elif current_group is not None:
                parent = current_group
            else:
                parent = root
                ungrouped.append(code10)

            cnode = SemanticNode(
                node_type=SemanticNodeType.COMMODITY,
                title=self.extractor.main_title(rec.description),
                code=code10,
                source="tnved_commodities",
                metadata={
                    "raw_description": rec.description,
                    "import_duty": rec.import_duty,
                    "node_level": lvl,
                },
            )
            parent.add_child(cnode)
            commodity_stack.append((lvl, cnode))

        # группы, открытые последним кодом (без последующих товаров) — пустые заголовки
        open_groups(len(extraction.commodity_codes))

        self._mark_leaves(root)

        expected = {heading4, *extraction.commodity_codes}
        return SemanticNavigationTree(
            heading=heading4,
            root=root,
            expected_real_codes=frozenset(expected),
            ungrouped_codes=ungrouped,
            pad_code=extraction.pad_code,
            rejected_candidates=[
                (rc.title, rc.reason, rc.source_code) for rc in extraction.rejected
            ],
        )

    @staticmethod
    def _mark_leaves(node: SemanticNode) -> None:
        for ch in node.children:
            SemanticNavigationBuilder._mark_leaves(ch)
        if node.node_type == SemanticNodeType.COMMODITY:
            has_code_children = any(
                c.node_type in (SemanticNodeType.COMMODITY, SemanticNodeType.LEAF)
                for c in node.children
            )
            if not has_code_children:
                node.node_type = SemanticNodeType.LEAF
