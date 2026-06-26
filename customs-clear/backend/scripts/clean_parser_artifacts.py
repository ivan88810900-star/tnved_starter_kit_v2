from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import inspect, text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")
load_dotenv()

from app.db import SessionLocal, engine
from app.models.tnved import NonTariffMeasure


URL_ARTIFACT_RE = re.compile(r"(file:///|https?://www\.alta\.ru)", re.IGNORECASE)
HEADER_DUP_RE = re.compile(
    r"^\s*код\s*тн\s*вэд\s+наименование\s+товара(?:\s+\d{4,10})?",
    re.IGNORECASE | re.MULTILINE,
)
TABLE_HEADER_BLOCK_RE = re.compile(
    r"Ставка\s+ввозной\s*\n+"
    r"\s*Код\s*\(в\s*процентах\s*\n+"
    r"\s*Наименование\s+позиции\s+ед\.\s*\n+"
    r"\s*ТН\s*ВЭД\s+от\s+таможенной\s*\n+"
    r"\s*изм\.\s*\n+"
    r"\s*стоимости\s+либо\s*\n+"
    r"\s*в\s+евро,\s*либо\s*\n+"
    r"\s*в\s+долларах\s+США\)?",
    re.IGNORECASE,
)
MANY_NEWLINES_RE = re.compile(r"\n{3,}")


@dataclass(frozen=True)
class NoteTarget:
    table: str
    column: str


def _text(value: str | None) -> str:
    return (value or "").strip()


def _is_url_artifact_row(description: str, document_required: str, regulatory_act: str) -> bool:
    return any(
        URL_ARTIFACT_RE.search(part or "")
        for part in (description, document_required, regulatory_act)
    )


def _is_system_stub_row(measure_type: str, regulatory_act: str) -> bool:
    if _text(measure_type).lower() != "tr_ts":
        return False
    return _text(regulatory_act) in {"ЕТТ ЕАЭС", "- 25"}


def _is_header_duplicate_row(description: str, document_required: str) -> bool:
    return bool(HEADER_DUP_RE.search(description or "") or HEADER_DUP_RE.search(document_required or ""))


def clean_non_tariff_measures(db) -> dict[str, int]:
    rows = (
        db.query(
            NonTariffMeasure.id,
            NonTariffMeasure.measure_type,
            NonTariffMeasure.description,
            NonTariffMeasure.document_required,
            NonTariffMeasure.regulatory_act,
        )
        .order_by(NonTariffMeasure.id.asc())
        .all()
    )

    ids_url: set[int] = set()
    ids_stub: set[int] = set()
    ids_header_dup: set[int] = set()

    for row in rows:
        if _is_url_artifact_row(row.description, row.document_required, row.regulatory_act):
            ids_url.add(int(row.id))
            continue
        if _is_system_stub_row(row.measure_type, row.regulatory_act):
            ids_stub.add(int(row.id))
            continue
        if _is_header_duplicate_row(row.description, row.document_required):
            ids_header_dup.add(int(row.id))

    ids_to_delete = ids_url | ids_stub | ids_header_dup
    deleted_total = 0
    if ids_to_delete:
        ids_sorted = sorted(ids_to_delete)
        chunk_size = 800  # SQLite имеет лимит параметров в одном выражении.
        for idx in range(0, len(ids_sorted), chunk_size):
            chunk = ids_sorted[idx : idx + chunk_size]
            deleted_total += int(
                db.query(NonTariffMeasure)
                .filter(NonTariffMeasure.id.in_(chunk))
                .delete(synchronize_session=False)
                or 0
            )

    return {
        "rows_scanned": len(rows),
        "deleted_total": deleted_total,
        "deleted_url_artifacts": len(ids_url),
        "deleted_system_stubs": len(ids_stub),
        "deleted_header_duplicates": len(ids_header_dup),
    }


def _clean_note_text(raw: str) -> tuple[str, int, bool]:
    text_in = (raw or "").replace("\r\n", "\n").replace("\r", "\n")
    header_blocks = len(TABLE_HEADER_BLOCK_RE.findall(text_in))
    text_out = TABLE_HEADER_BLOCK_RE.sub("", text_in)
    before_many_nl = len(MANY_NEWLINES_RE.findall(text_out))

    text_out = re.sub(r"\n[ \t]+\n", "\n\n", text_out)
    text_out = MANY_NEWLINES_RE.sub("\n\n", text_out)
    text_out = re.sub(r"[ \t]+\n", "\n", text_out)
    text_out = text_out.strip()

    changed = (text_out != text_in.strip()) or header_blocks > 0 or before_many_nl > 0
    return text_out, header_blocks, changed


def _existing_note_targets() -> list[NoteTarget]:
    inspector = inspect(engine)
    candidates = [
        ("tnved_notes", "body"),
        ("tnved_notes", "notes"),
        ("normative_notes", "body"),
        ("tnved_sections", "notes"),
        ("tnved_chapters", "notes"),
        ("tnved_commodities", "notes"),
    ]
    found: list[NoteTarget] = []
    seen: set[tuple[str, str]] = set()
    for table, column in candidates:
        if not inspector.has_table(table):
            continue
        cols = {c["name"] for c in inspector.get_columns(table)}
        if column not in cols:
            continue
        key = (table, column)
        if key in seen:
            continue
        seen.add(key)
        found.append(NoteTarget(table=table, column=column))
    return found


def clean_notes_tables(db) -> dict[str, int]:
    targets = _existing_note_targets()
    total_rows_scanned = 0
    total_rows_updated = 0
    total_headers_removed = 0
    tables_touched = 0

    for target in targets:
        select_sql = text(
            f"""
            SELECT id, {target.column} AS payload
            FROM {target.table}
            WHERE {target.column} IS NOT NULL
              AND TRIM({target.column}) <> ''
            """
        )
        rows = db.execute(select_sql).fetchall()
        if not rows:
            continue
        tables_touched += 1
        total_rows_scanned += len(rows)

        update_sql = text(
            f"""
            UPDATE {target.table}
            SET {target.column} = :payload
            WHERE id = :row_id
            """
        )
        for row in rows:
            cleaned, header_count, changed = _clean_note_text(str(row.payload or ""))
            if not changed:
                continue
            db.execute(update_sql, {"payload": cleaned, "row_id": row.id})
            total_rows_updated += 1
            total_headers_removed += int(header_count)

    return {
        "tables_found": len(targets),
        "tables_touched": tables_touched,
        "rows_scanned": total_rows_scanned,
        "rows_updated": total_rows_updated,
        "header_blocks_removed": total_headers_removed,
    }


def main() -> int:
    print("clean_parser_artifacts: старт")
    print(f"  dialect={engine.dialect.name}")

    with SessionLocal() as db:
        nt_stats = clean_non_tariff_measures(db)
        notes_stats = clean_notes_tables(db)
        db.commit()

    print("  [non_tariff_measures]")
    print(
        "    scanned={rows_scanned} deleted_total={deleted_total} "
        "deleted_url_artifacts={deleted_url_artifacts} "
        "deleted_system_stubs={deleted_system_stubs} "
        "deleted_header_duplicates={deleted_header_duplicates}".format(**nt_stats)
    )

    print("  [notes_cleanup]")
    print(
        "    tables_found={tables_found} tables_touched={tables_touched} "
        "rows_scanned={rows_scanned} rows_updated={rows_updated} "
        "header_blocks_removed={header_blocks_removed}".format(**notes_stats)
    )

    print("clean_parser_artifacts: успешно")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
