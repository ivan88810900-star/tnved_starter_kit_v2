"""Create a consistent, standalone SQLite snapshot for read-only staging."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import sqlite3
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
}

REQUIRED_COLUMNS = {
    "tnved_sections": {"id", "roman_number", "title"},
    "tnved_chapters": {"id", "section_id", "code", "title"},
    "tnved_commodities": {"id", "chapter_id", "code", "description"},
    "hs_rates": {"id", "hs_code", "duty_rate", "vat_import_rate"},
    "non_tariff_measures": {"id", "commodity_code", "measure_type", "quality"},
    "ntm_measures_v2": {"id", "permit_type", "source_kind", "import_key"},
    "ntm_applicability_rules_v2": {
        "id",
        "measure_id",
        "hs_code",
        "applicability",
        "source_kind",
    },
}

CUSTOMS_CLEAR_ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = (
    CUSTOMS_CLEAR_ROOT / "backend" / "data" / "ntm_full_catalog_baseline.json"
)
ALEMBIC_VERSIONS_DIR = CUSTOMS_CLEAR_ROOT / "backend" / "alembic" / "versions"


def _sha256_lines(lines: list[str]) -> str:
    digest = hashlib.sha256()
    for line in lines:
        digest.update(line.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


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


def _validate_full_catalog(database: sqlite3.Connection) -> dict[str, int]:
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    expected_catalog = baseline["catalog"]
    expected_ett = baseline["active_ett"]

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

    rate_codes = sorted(
        {
            str(row[0]).strip()
            for row in database.execute("SELECT hs_code FROM hs_rates")
            if str(row[0] or "").strip().isdigit()
            and len(str(row[0] or "").strip()) == 10
        }
    )
    if len(rate_codes) != expected_ett["unique_codes"]:
        raise RuntimeError(
            "snapshot active ETT code count does not match the pinned baseline: "
            f"expected {expected_ett['unique_codes']}, got {len(rate_codes)}"
        )
    rate_fingerprint = _sha256_lines(rate_codes)
    if rate_fingerprint != expected_ett["code_set_sha256"]:
        raise RuntimeError(
            "snapshot active ETT code set does not match the pinned baseline"
        )

    return {
        "sections": len(section_codes),
        "chapters": len(chapter_codes),
        "commodities": len(catalog_rows),
        "active_ett_codes": len(rate_codes),
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
