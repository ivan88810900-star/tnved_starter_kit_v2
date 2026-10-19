#!/usr/bin/env python3
"""Build a disposable classification-inventory database for regression tests.

The normal application startup intentionally does not load the large historical
classification seeds.  Some dataset regression tests do require that inventory,
however.  This helper creates a *new* SQLite database, copies the canonical TN
VED catalogue committed in this repository, and loads the existing curated/test
classification seed scripts into that database.

Safety properties:

* the target path must not exist;
* only SQLite targets are supported;
* the source catalogue is opened read-only and its SHA-256 is pinned;
* this helper never connects to or mutates an existing application database.

The resulting database is test evidence only.  It is not a synchronized legal or
production snapshot and must not be used to claim regulatory completeness.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CATALOG = BACKEND_ROOT / "customs.db.backup_before_pdf_import"
CATALOG_SHA256 = "53847cb00ebc53f6315042325bc416d13d65cf020a10530a4ce7dde848ed1ff2"
sys.path.insert(0, str(BACKEND_ROOT))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _open_immutable(path: Path) -> sqlite3.Connection:
    """Open the committed catalogue without creating SQLite WAL sidecars."""
    return sqlite3.connect(f"{path.as_uri()}?mode=ro&immutable=1", uri=True)


def _validate_paths(target: Path, source: Path) -> tuple[Path, Path]:
    target = target.expanduser().resolve()
    source = source.expanduser().resolve()
    if target.exists():
        raise SystemExit(f"refusing existing target database: {target}")
    if target == source:
        raise SystemExit("target database must differ from the read-only catalogue source")
    if not source.is_file():
        raise SystemExit(f"catalogue source does not exist: {source}")
    actual_hash = _sha256(source)
    if actual_hash != CATALOG_SHA256:
        raise SystemExit(
            "catalogue source fingerprint mismatch: "
            f"expected {CATALOG_SHA256}, got {actual_hash}"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    return target, source


def _catalogue_counts(source: Path) -> dict[str, int]:
    connection = _open_immutable(source)
    try:
        counts = {
            table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in ("tnved_sections", "tnved_chapters", "tnved_commodities")
        }
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        connection.close()
    if integrity != "ok":
        raise SystemExit(f"catalogue source failed integrity_check: {integrity}")
    if counts["tnved_commodities"] < 13_900:
        raise SystemExit(f"catalogue source is incomplete: {counts}")
    return counts


def _copy_catalogue(source: Path, target: Path) -> dict[str, int]:
    """Copy the pinned catalogue, resolving legacy duplicate codes deterministically."""
    source_connection = _open_immutable(source)
    target_connection = sqlite3.connect(target)
    try:
        target_connection.execute("PRAGMA foreign_keys = OFF")
        target_connection.execute("DELETE FROM tnved_commodities")
        target_connection.execute("DELETE FROM tnved_chapters")
        target_connection.execute("DELETE FROM tnved_sections")
        target_connection.executemany(
            "INSERT INTO tnved_sections (id, roman_number, title, notes) VALUES (?, ?, ?, ?)",
            source_connection.execute(
                "SELECT id, roman_number, title, notes FROM tnved_sections ORDER BY id"
            ).fetchall(),
        )
        target_connection.executemany(
            "INSERT INTO tnved_chapters (id, section_id, code, title, notes) "
            "VALUES (?, ?, ?, ?, ?)",
            source_connection.execute(
                "SELECT id, section_id, code, title, notes FROM tnved_chapters ORDER BY id"
            ).fetchall(),
        )
        # The historical source contains 39 duplicated codes.  The application
        # schema correctly enforces unique codes, so retain the lowest stable id.
        target_connection.executemany(
            "INSERT INTO tnved_commodities "
            "(id, chapter_id, code, description, unit, import_duty) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            source_connection.execute(
                "SELECT c.id, c.chapter_id, c.code, c.description, c.unit, c.import_duty "
                "FROM tnved_commodities c "
                "JOIN (SELECT code, MIN(id) AS keep_id FROM tnved_commodities GROUP BY code) d "
                "ON d.keep_id = c.id ORDER BY c.id"
            ).fetchall(),
        )
        target_connection.commit()
        target_connection.execute("PRAGMA foreign_keys = ON")
        return {
            table: int(target_connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in ("tnved_sections", "tnved_chapters", "tnved_commodities")
        }
    finally:
        source_connection.close()
        target_connection.close()


def bootstrap(target: Path, source: Path = DEFAULT_CATALOG) -> dict[str, object]:
    """Create and populate one new disposable SQLite database."""
    if "app.db" in sys.modules:
        raise SystemExit(
            "bootstrap must run in a fresh Python interpreter; app.db is already loaded"
        )
    target, source = _validate_paths(target, source)
    source_counts = _catalogue_counts(source)

    # Import app modules only after binding them to the new disposable target.
    os.environ["DATABASE_URL"] = f"sqlite:///{target}"
    os.environ["TNVED_SOURCE_DB"] = str(source)

    from app.services.normative_store import init_db
    from scripts import expand_classification_rulings
    from scripts import seed_classification_rulings
    from scripts import seed_fts_classification_letters

    init_db()
    copied_counts = _copy_catalogue(source, target)
    letters = seed_fts_classification_letters.seed()
    formal = seed_classification_rulings.seed()
    reference = expand_classification_rulings.expand(
        target=520,
        per_chapter=8,
        dry_run=False,
    )

    connection = sqlite3.connect(target)
    try:
        counts = {
            "fts_letters": int(
                connection.execute(
                    "SELECT COUNT(*) FROM regulatory_documents "
                    "WHERE agency = 'FTS' AND doc_type = 'letter' "
                    "AND doc_number LIKE '06-73/%'"
                ).fetchone()[0]
            ),
            "classification_decisions": int(
                connection.execute("SELECT COUNT(*) FROM classification_decisions").fetchone()[0]
            ),
            "official_rulings": int(
                connection.execute(
                    "SELECT COUNT(*) FROM classification_rulings WHERE is_official = 1"
                ).fetchone()[0]
            ),
            "reference_rulings": int(
                connection.execute(
                    "SELECT COUNT(*) FROM classification_rulings "
                    "WHERE agency = 'ТНВЭД-REF' AND is_official = 0"
                ).fetchone()[0]
            ),
        }
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        connection.close()

    minimums = {
        "fts_letters": 200,
        "classification_decisions": 190,
        "official_rulings": 50,
        "reference_rulings": 500,
    }
    short = {name: (counts[name], minimum) for name, minimum in minimums.items() if counts[name] < minimum}
    if short:
        raise SystemExit(f"classification inventory is incomplete: {short}")
    if integrity != "ok":
        raise SystemExit(f"target failed integrity_check: {integrity}")

    return {
        "database": str(target),
        "catalogue_sha256": CATALOG_SHA256,
        "catalogue_counts": source_counts,
        "copied_catalogue_counts": copied_counts,
        "inventory_counts": counts,
        "seed_reports": {
            "letters": letters,
            "formal_rulings": formal,
            "reference_rulings": reference,
        },
        "scope": "disposable-test-inventory-not-legal-completeness",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", type=Path, help="path for a new disposable SQLite database")
    parser.add_argument(
        "--catalogue",
        type=Path,
        default=DEFAULT_CATALOG,
        help="pinned repository TN VED catalogue source",
    )
    args = parser.parse_args()
    report = bootstrap(args.target, args.catalogue)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
