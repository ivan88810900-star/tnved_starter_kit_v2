"""TreeParser — чтение SQLite → промежуточная модель (без построения дерева)."""

from __future__ import annotations

from sqlalchemy import inspect, or_
from sqlalchemy.orm import Session

from ...models import HsRate
from ...models.tnved import Commodity
from ..tnved_tree import (
    collect_chapter_notes,
    digits,
    exclude_obsolete_reserved,
    format_duty,
    node_level,
)
from .models import ParsedCommodityRecord, TreeParseResult

_LEAF_FLAG_CHUNK = 500


class TreeParser:
    """Загружает все DB-входы Canonical Builder без логики иерархии."""

    def parse(self, db: Session, *, limit: int = 2_000_000) -> TreeParseResult:
        self._ensure_read_snapshot(db)
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
        leaf_flags = self._load_leaf_flags(db, commodities)
        return TreeParseResult(
            commodities=commodities,
            chapter_notes=chapter_notes,
            db_codes=frozenset(db_codes),
            leaf_flags=leaf_flags,
        )

    @staticmethod
    def _load_leaf_flags(
        db: Session,
        commodities: list[ParsedCommodityRecord],
    ) -> dict[str, bool]:
        """Load leaf evidence for ambiguous L4/L6 nodes in the parser snapshot.

        This is the DB-backed equivalent of ``normative_store.is_leaf_hs_code``:
        terminal L4 requires an exact ``hs_rates`` key, while L6 accepts an exact
        or inherited 10→8→6→4→2 key. Compact Gate-2 databases may omit
        ``hs_prefix``; only columns present in the current schema are queried.
        """
        ambiguous = sorted(
            {
                record.code10
                for record in commodities
                if len(record.code10) == 10 and node_level(record.code10) in {4, 6}
            }
        )
        if not ambiguous:
            return {}

        prefixes_by_code: dict[str, set[str]] = {}
        all_prefixes: set[str] = set()
        for code in ambiguous:
            level = node_level(code)
            prefixes = (
                {code}
                if level == 4
                else {code[:length] for length in (10, 8, 6, 4, 2)}
            )
            prefixes_by_code[code] = prefixes
            all_prefixes.update(prefixes)

        rate_columns = [HsRate.hs_code]
        rate_inspector = inspect(db.get_bind())
        has_hs_prefix = (
            rate_inspector.has_table(HsRate.__tablename__)
            and any(
                column["name"] == "hs_prefix"
                for column in rate_inspector.get_columns(HsRate.__tablename__)
            )
        )
        if has_hs_prefix:
            rate_columns.append(HsRate.hs_prefix)

        existing_hs_codes: set[str] = set()
        existing_hs_prefixes: set[str] = set()
        prefix_list = sorted(all_prefixes)
        for index in range(0, len(prefix_list), _LEAF_FLAG_CHUNK):
            chunk = prefix_list[index : index + _LEAF_FLAG_CHUNK]
            rate_filters = [HsRate.hs_code.in_(chunk)]
            if has_hs_prefix:
                rate_filters.append(HsRate.hs_prefix.in_(chunk))
            rows = db.query(*rate_columns).filter(or_(*rate_filters)).all()
            for row in rows:
                if row[0]:
                    existing_hs_codes.add(row[0])
                if has_hs_prefix and row[1]:
                    existing_hs_prefixes.add(row[1])

        inherited_rate_keys = existing_hs_codes | existing_hs_prefixes
        return {
            code: (
                code in existing_hs_codes
                if node_level(code) == 4
                else bool(prefixes_by_code[code] & inherited_rate_keys)
            )
            for code in ambiguous
        }

    @staticmethod
    def _ensure_read_snapshot(db: Session) -> None:
        """Start a real SQLite read transaction before the first Parser query.

        Python's sqlite3 legacy transaction mode does not emit ``BEGIN`` for a
        ``SELECT``. SQLAlchemy can therefore report an active Session transaction
        while consecutive reads still observe different commits. An explicit
        ``BEGIN`` keeps all Parser inputs on one SQLite snapshot. PostgreSQL and an
        already active SQLite transaction retain their native transaction semantics.
        """
        bind = db.get_bind()
        if bind.dialect.name != "sqlite":
            return
        connection = db.connection()
        driver_connection = connection.connection.driver_connection
        if getattr(driver_connection, "in_transaction", None) is False:
            connection.exec_driver_sql("BEGIN")

    def parse_from_session_factory(self, session_factory) -> TreeParseResult:
        db = session_factory()
        try:
            return self.parse(db)
        finally:
            db.close()
