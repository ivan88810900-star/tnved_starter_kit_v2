"""Create a consistent, standalone SQLite snapshot for read-only staging."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote

REQUIRED_TABLES = {
    "alembic_version",
    "tnved_sections",
    "tnved_chapters",
    "tnved_commodities",
    "hs_rates",
    "non_tariff_measures",
    "ntm_measures_v2",
    "ntm_applicability_rules_v2",
    "tnved_fts",
}

REQUIRED_COLUMNS = {
    "tnved_sections": {"id", "roman_number", "title"},
    "tnved_chapters": {"id", "section_id", "code", "title"},
    "tnved_commodities": {"id", "chapter_id", "code", "description"},
    "hs_rates": {"id", "hs_code", "hs_prefix", "duty_rate", "vat_import_rate"},
    "non_tariff_measures": {"id", "commodity_code", "measure_type", "quality"},
    "ntm_measures_v2": {"id", "permit_type", "source_kind", "import_key"},
    "ntm_applicability_rules_v2": {
        "id",
        "measure_id",
        "hs_code",
        "applicability",
        "source_kind",
    },
    "tnved_fts": {"code", "description"},
}

CUSTOMS_CLEAR_ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = (
    CUSTOMS_CLEAR_ROOT / "backend" / "data" / "ntm_full_catalog_baseline.json"
)
ALEMBIC_VERSIONS_DIR = CUSTOMS_CLEAR_ROOT / "backend" / "alembic" / "versions"
BACKEND_ROOT = CUSTOMS_CLEAR_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.ntm_catalog_baseline import duty_rate_content_sha256  # noqa: E402


EXPECTED_FTS_TABLE_SQL = (
    "CREATE VIRTUAL TABLE tnved_fts USING fts5("
    "code, description, content='tnved_commodities', content_rowid='id', "
    "tokenize='unicode61 remove_diacritics 2', prefix='2 3 4')"
)
EXPECTED_FTS_TRIGGER_SQL = {
    "tnved_fts_ai": (
        "CREATE TRIGGER tnved_fts_ai AFTER INSERT ON tnved_commodities BEGIN "
        "INSERT INTO tnved_fts(rowid, code, description) "
        "VALUES (new.id, new.code, new.description); END"
    ),
    "tnved_fts_ad": (
        "CREATE TRIGGER tnved_fts_ad AFTER DELETE ON tnved_commodities BEGIN "
        "INSERT INTO tnved_fts(tnved_fts, rowid, code, description) "
        "VALUES ('delete', old.id, old.code, old.description); END"
    ),
    "tnved_fts_au": (
        "CREATE TRIGGER tnved_fts_au AFTER UPDATE ON tnved_commodities BEGIN "
        "INSERT INTO tnved_fts(tnved_fts, rowid, code, description) "
        "VALUES ('delete', old.id, old.code, old.description); "
        "INSERT INTO tnved_fts(rowid, code, description) "
        "VALUES (new.id, new.code, new.description); END"
    ),
}
FTS_DESCRIPTION_TOKEN_CHUNK_SIZE = 24


def _sha256_lines(lines: list[str]) -> str:
    digest = hashlib.sha256()
    for line in lines:
        digest.update(line.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _normalize_schema_sql(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().rstrip(";").casefold()


def _description_token_chunks(value: str) -> list[tuple[str, ...]]:
    """Return bounded overlapping phrase chunks covering every lexical token."""
    tokens = tuple(
        token.casefold()
        for token in re.findall(r"[^\W_]+", " ".join(value.split()), flags=re.UNICODE)
    )
    if not tokens:
        return []
    if len(tokens) <= FTS_DESCRIPTION_TOKEN_CHUNK_SIZE:
        return [tokens]
    chunks: list[tuple[str, ...]] = []
    # One-token overlap proves phrase order across chunk boundaries while each
    # individual MATCH expression remains bounded.
    step = FTS_DESCRIPTION_TOKEN_CHUNK_SIZE - 1
    for start in range(0, len(tokens), step):
        chunk = tokens[start : start + FTS_DESCRIPTION_TOKEN_CHUNK_SIZE]
        chunks.append(chunk)
        if start + len(chunk) >= len(tokens):
            break
    return chunks


def _alembic_heads() -> set[str]:
    revisions: set[str] = set()
    parents: set[str] = set()
    for path in ALEMBIC_VERSIONS_DIR.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        values: dict[str, object] = {}
        for node in tree.body:
            if isinstance(node, ast.Assign):
                targets = node.targets
                value_node = node.value
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
                value_node = node.value
            else:
                continue
            for target in targets:
                if not isinstance(target, ast.Name) or target.id not in {
                    "revision",
                    "down_revision",
                }:
                    continue
                try:
                    values[target.id] = ast.literal_eval(value_node)
                except (ValueError, TypeError):
                    pass
        revision = values.get("revision")
        if not isinstance(revision, str):
            continue
        revisions.add(revision)
        down_revision = values.get("down_revision")
        if isinstance(down_revision, str):
            parents.add(down_revision)
        elif isinstance(down_revision, (tuple, list)):
            parents.update(value for value in down_revision if isinstance(value, str))
    heads = revisions - parents
    if not heads:
        raise RuntimeError("cannot determine the repository Alembic head")
    return heads


def _validate_active_ett_rates(
    database: sqlite3.Connection,
    expected_ett: dict[str, object],
) -> dict[str, int | str]:
    rows = [
        (
            str(code or "").strip(),
            str(prefix or "").strip(),
            duty_rate,
        )
        for code, prefix, duty_rate in database.execute(
            "SELECT hs_code, hs_prefix, duty_rate FROM hs_rates"
        )
    ]
    expected_rows = int(expected_ett["unique_codes"])
    invalid_codes = [
        code for code, _, _ in rows if not (len(code) == 10 and code.isdigit())
    ]
    valid_codes = [code for code, _, _ in rows if len(code) == 10 and code.isdigit()]
    duplicate_rows = len(valid_codes) - len(set(valid_codes))
    exact_prefix_mismatches = [
        code
        for code, prefix, _ in rows
        if len(code) == 10 and code.isdigit() and prefix != code
    ]
    if len(rows) != expected_rows or invalid_codes or duplicate_rows:
        raise RuntimeError(
            "snapshot active ETT rows are not exact: "
            f"expected_total={expected_rows}, total={len(rows)}, "
            f"invalid={len(invalid_codes)}, duplicates={duplicate_rows}"
        )
    if exact_prefix_mismatches:
        raise RuntimeError(
            "snapshot exact ETT rows have broad hs_prefix values: "
            f"mismatches={len(exact_prefix_mismatches)}"
        )
    rate_codes = sorted(valid_codes)
    if _sha256_lines(rate_codes) != expected_ett["code_set_sha256"]:
        raise RuntimeError(
            "snapshot active ETT code set does not match the pinned baseline"
        )
    actual_duty_fingerprint = duty_rate_content_sha256(
        (code, duty_rate) for code, _, duty_rate in rows
    )
    if actual_duty_fingerprint != expected_ett["active_duty_rate_sha256"]:
        raise RuntimeError(
            "snapshot active ETT duty-rate content does not match the pinned baseline"
        )
    return {
        "rows": len(rows),
        "invalid_code_rows": len(invalid_codes),
        "duplicate_rows": duplicate_rows,
        "exact_prefix_mismatches": len(exact_prefix_mismatches),
        "duty_rate_sha256": actual_duty_fingerprint,
    }


def _validate_fts(database: sqlite3.Connection, expected_rows: int) -> int:
    table_definition = database.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='tnved_fts'"
    ).fetchone()
    if table_definition is None or _normalize_schema_sql(
        table_definition[0]
    ) != _normalize_schema_sql(EXPECTED_FTS_TABLE_SQL):
        raise RuntimeError("snapshot FTS virtual-table definition mismatch")

    actual_trigger_sql = {
        str(name): str(sql or "")
        for name, sql in database.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='trigger' "
            "AND name IN ('tnved_fts_ai', 'tnved_fts_ad', 'tnved_fts_au')"
        )
    }
    mismatched_triggers = sorted(
        name
        for name, expected_sql in EXPECTED_FTS_TRIGGER_SQL.items()
        if _normalize_schema_sql(actual_trigger_sql.get(name))
        != _normalize_schema_sql(expected_sql)
    )
    if mismatched_triggers:
        raise RuntimeError(
            "snapshot FTS trigger definition mismatch: "
            + ", ".join(mismatched_triggers)
        )

    commodity_rows = [
        (int(row_id), str(code or "").strip(), str(description or ""))
        for row_id, code, description in database.execute(
            "SELECT id, code, description FROM tnved_commodities ORDER BY id"
        )
    ]
    fts_rows = int(database.execute("SELECT COUNT(*) FROM tnved_fts").fetchone()[0])
    if len(commodity_rows) != expected_rows or fts_rows != expected_rows:
        raise RuntimeError(
            "snapshot FTS index is incomplete: "
            f"expected_rows={expected_rows}, commodities={len(commodity_rows)}, "
            f"reported_fts_rows={fts_rows}"
        )

    missing_code_matches = 0
    missing_description_matches = 0
    for row_id, code, description in commodity_rows:
        code_match = database.execute(
            "SELECT 1 FROM tnved_fts "
            "WHERE rowid = ? AND tnved_fts MATCH ? LIMIT 1",
            (row_id, f'code:"{code}"'),
        ).fetchone()
        if code_match is None:
            missing_code_matches += 1

        normalized_description = " ".join(description.split())
        if not normalized_description:
            continue
        token_chunks = _description_token_chunks(normalized_description)
        if not token_chunks:
            missing_description_matches += 1
            continue
        for token_chunk in token_chunks:
            # A column-scoped phrase proves that every token in the chunk is
            # present in source order. Overlap joins the complete normalized
            # description while keeping MATCH input bounded.
            phrase = " ".join(token_chunk).replace('"', '""')
            description_match = database.execute(
                "SELECT 1 FROM tnved_fts "
                "WHERE rowid = ? AND tnved_fts MATCH ? LIMIT 1",
                (row_id, f'description:"{phrase}"'),
            ).fetchone()
            if description_match is None:
                missing_description_matches += 1
                break

    if missing_code_matches or missing_description_matches:
        raise RuntimeError(
            "snapshot FTS postings are incomplete: "
            f"missing_code_matches={missing_code_matches}, "
            f"missing_description_matches={missing_description_matches}"
        )
    return fts_rows


def _validate_full_catalog(
    database: sqlite3.Connection,
    baseline_path: Path = BASELINE_PATH,
) -> dict[str, int]:
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    expected_catalog = baseline["catalog"]
    expected_ett = baseline["active_ett"]
    if (
        baseline.get("schema_version") == "1"
        and baseline.get("validation_mode") == "quarantine_only"
    ):
        raise RuntimeError(
            "pinned baseline schema v1 is quarantine-only; positive staging "
            "validation is impossible until a separate schema-v2 validator "
            "and decision are implemented"
        )
    raise RuntimeError("unsupported positive staging baseline schema")

    actual_versions = {
        str(row[0])
        for row in database.execute("SELECT version_num FROM alembic_version")
    }
    expected_versions = _alembic_heads()
    if actual_versions != expected_versions:
        raise RuntimeError(
            "snapshot schema is not at the repository Alembic head; "
            f"expected {sorted(expected_versions)}, got {sorted(actual_versions)}"
        )

    for table, expected_columns in REQUIRED_COLUMNS.items():
        actual_columns = {
            str(row[1]) for row in database.execute(f"PRAGMA table_info({table})")
        }
        missing_columns = sorted(expected_columns - actual_columns)
        if missing_columns:
            raise RuntimeError(
                f"snapshot table {table} is missing columns: {', '.join(missing_columns)}"
            )

    section_codes = sorted(
        str(row[0]).strip()
        for row in database.execute("SELECT roman_number FROM tnved_sections")
    )
    chapter_codes = sorted(
        str(row[0]).strip()
        for row in database.execute("SELECT code FROM tnved_chapters")
    )
    if section_codes != sorted(expected_catalog["section_codes"]):
        raise RuntimeError(
            "snapshot TN VED section set does not match the pinned baseline"
        )
    if chapter_codes != sorted(expected_catalog["chapter_codes"]):
        raise RuntimeError(
            "snapshot TN VED chapter set does not match the pinned baseline"
        )

    catalog_rows = sorted(
        (
            str(code or "").strip(),
            " ".join(str(description or "").split()),
        )
        for code, description in database.execute(
            "SELECT code, description FROM tnved_commodities"
        )
    )
    catalog_codes = [code for code, _ in catalog_rows]
    description_rows = sum(bool(description) for _, description in catalog_rows)
    catalog_checks = {
        "rows": len(catalog_rows),
        "unique_codes": len(set(catalog_codes)),
        "description_rows": description_rows,
        "code_set_sha256": _sha256_lines(sorted(set(catalog_codes))),
        "code_description_sha256": _sha256_lines(
            [f"{code}\t{description}" for code, description in catalog_rows]
        ),
    }
    for field, actual in catalog_checks.items():
        if actual != expected_catalog[field]:
            raise RuntimeError(
                f"snapshot TN VED baseline mismatch for {field}: "
                f"expected {expected_catalog[field]!r}, got {actual!r}"
            )

    rate_profile = _validate_active_ett_rates(database, expected_ett)
    fts_rows = _validate_fts(database, len(catalog_rows))

    return {
        "sections": len(section_codes),
        "chapters": len(chapter_codes),
        "commodities": len(catalog_rows),
        "active_ett_codes": int(rate_profile["rows"]),
        "fts_rows": fts_rows,
    }


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Copy a live SQLite database into a checkpointed read-only staging snapshot."
    )
    parser.add_argument("source", type=Path, help="source SQLite database")
    parser.add_argument(
        "output",
        type=Path,
        nargs="?",
        help="new snapshot path (must not exist)",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="validate source in place without creating a snapshot",
    )
    return parser.parse_args()


def _validate_database(database: sqlite3.Connection) -> dict[str, int]:
    database.execute("PRAGMA query_only=ON")
    quick_check = database.execute("PRAGMA quick_check").fetchone()
    if quick_check != ("ok",):
        raise RuntimeError(f"SQLite quick_check failed: {quick_check!r}")

    table_names = {
        row[0]
        for row in database.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    missing = sorted(REQUIRED_TABLES - table_names)
    if missing:
        raise RuntimeError(
            "snapshot is not a usable Tariff staging database; "
            f"missing tables: {', '.join(missing)}"
        )
    return _validate_full_catalog(database)


def main() -> int:
    args = _arguments()
    source = args.source.expanduser().resolve(strict=True)
    if args.validate_only:
        if args.output is not None:
            raise SystemExit("--validate-only does not accept an output path")
        source_uri = f"file:{quote(str(source), safe='/')}?mode=ro"
        with sqlite3.connect(source_uri, uri=True) as source_db:
            counts = _validate_database(source_db)
        print(
            f"Validated full read-only staging database: {source} "
            f"({counts['sections']} sections, {counts['chapters']} chapters, "
            f"{counts['commodities']} commodities, "
            f"{counts['active_ett_codes']} active ETT codes)"
        )
        return 0

    if args.output is None:
        raise SystemExit("output path is required unless --validate-only is used")
    output = args.output.expanduser().resolve()
    if source == output:
        raise SystemExit("source and output must be different files")
    if output.exists():
        raise SystemExit(f"refusing to overwrite existing output: {output}")

    output.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.", suffix=".tmp", dir=output.parent
    )
    os.close(handle)
    temporary = Path(temporary_name)

    source_uri = f"file:{quote(str(source), safe='/')}?mode=ro"
    try:
        with (
            sqlite3.connect(source_uri, uri=True) as source_db,
            sqlite3.connect(temporary) as output_db,
        ):
            source_db.backup(output_db)
            output_db.execute("PRAGMA journal_mode=DELETE")
            output_db.execute("PRAGMA optimize")
            counts = _validate_database(output_db)

        os.chmod(temporary, 0o444)
        os.link(temporary, output)
        print(
            f"Created read-only staging snapshot: {output} "
            f"({counts['sections']} sections, {counts['chapters']} chapters, "
            f"{counts['commodities']} commodities, "
            f"{counts['active_ett_codes']} active ETT codes)"
        )
        return 0
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
