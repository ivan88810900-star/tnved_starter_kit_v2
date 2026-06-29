"""TreeParser — чтение SQLite → промежуточная модель (без построения дерева)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from ...models.tnved import Commodity
from ..tnved_tree import collect_chapter_notes, digits, exclude_obsolete_reserved, format_duty
from .models import ParsedCommodityRecord, TreeParseResult


class TreeParser:
    """Загружает tnved_commodities и метаданные глав без логики иерархии."""

    def parse(self, db: Session, *, limit: int = 2_000_000) -> TreeParseResult:
        rows = (
            exclude_obsolete_reserved(db.query(Commodity).order_by(Commodity.code.asc()))
            .limit(limit)
            .all()
        )
        commodities: list[ParsedCommodityRecord] = []
        db_codes: set[str] = set()
        for row in rows:
            raw = (row.code or "").strip()
            d = digits(raw)
            if not d:
                continue
            if len(d) <= 4:
                code_key = d.zfill(4)
            else:
                code_key = d.zfill(10)[:10]
            db_codes.add(code_key)
            commodities.append(
                ParsedCommodityRecord(
                    code10=code_key,
                    description=(row.description or "").strip(),
                    raw_description=(row.description or "").strip(),
                    import_duty=format_duty(row.import_duty),
                    chapter_id=row.chapter_id,
                    unit=(row.unit or "").strip(),
                    supp_unit=(row.supp_unit or "").strip(),
                    weight_coeff=float(row.weight_coeff or 0),
                )
            )
        chapter_notes = collect_chapter_notes(db)
        return TreeParseResult(
            commodities=commodities,
            chapter_notes=chapter_notes,
            db_codes=frozenset(db_codes),
        )

    def parse_from_session_factory(self, session_factory) -> TreeParseResult:
        db = session_factory()
        try:
            return self.parse(db)
        finally:
            db.close()
