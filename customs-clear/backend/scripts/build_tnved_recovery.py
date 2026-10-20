#!/usr/bin/env python3
"""Build a deterministic, isolated TN VED structural recovery SQLite.

The input is a pinned, unverified structural snapshot.  This tool deliberately
does not import rates, infer legal dates, or touch the application database.
"""

from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sqlite3
import sys
from typing import Any, Iterable

CATALOG_SHA256 = "c7e4e5bb52b103d8b13554b4e25bf12ea0d09b4d67494e236a55cc276a173d41"
INDEX_SHA256 = "2465cd548ccc4b9b9f9cfb05e504cf79774ab49a513ae63fda203f1b7bfc0bdc"
EXPECTED_CHAPTERS = tuple(f"{n:02d}" for n in range(1, 98) if n != 77)
EXPECTED_COUNTS = {"sources": 99, "editions": 96, "nodes": 18014, "notes": 107, "ten_digit": 13294}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def _roman(raw: str) -> str:
    # The saved EEC index spells XII and XIV with Cyrillic Х.  Preserve the
    # source spelling separately and normalize only the structural key.
    normalized = re.sub(r"\s+", "", raw.upper()).replace("Х", "X")
    _require(bool(normalized) and not re.search(r"[^IVX]", normalized), f"invalid section numeral: {raw!r}")
    return normalized


class _TableRows(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_tr = False
        self.in_td = False
        self.cells: list[str] = []
        self.parts: list[str] = []
        self.rows: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self.in_tr, self.cells = True, []
        elif tag in {"td", "th"} and self.in_tr:
            self.in_td, self.parts = True, []
        elif tag == "br" and self.in_td:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self.in_td:
            self.cells.append(" ".join("".join(self.parts).split()))
            self.in_td = False
        elif tag == "tr" and self.in_tr:
            if self.cells:
                self.rows.append(self.cells)
            self.in_tr = False

    def handle_data(self, data: str) -> None:
        if self.in_td:
            self.parts.append(data)


def parse_sections(index_raw: bytes) -> list[dict[str, Any]]:
    parser = _TableRows()
    parser.feed(index_raw.decode("utf-8"))
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    seen_chapters: set[str] = set()
    for cells in parser.rows:
        first = cells[0] if cells else ""
        second = cells[1] if len(cells) > 1 else ""
        section_match = re.search(r"РАЗДЕЛ\s+([IVXХ]+)", first, re.I)
        if section_match:
            raw_roman = section_match.group(1).upper()
            current = {"roman": _roman(raw_roman), "rawRoman": raw_roman, "title": second.strip(), "chapters": []}
            _require(current["title"] != "", f"section {raw_roman} has no title")
            sections.append(current)
            continue
        chapter_match = re.search(r"Группа\s+(\d{2})", first, re.I)
        if chapter_match:
            chapter = chapter_match.group(1)
            if chapter == "77":
                continue
            _require(current is not None, f"chapter {chapter} occurs before a section")
            _require(chapter not in seen_chapters, f"duplicate chapter in index: {chapter}")
            current["chapters"].append(chapter)
            seen_chapters.add(chapter)
    _require(len(sections) == 21, f"expected 21 sections, found {len(sections)}")
    _require(tuple(sorted(seen_chapters)) == EXPECTED_CHAPTERS, "section/chapter coverage differs from 96-chapter inventory")
    _require(tuple(s["roman"] for s in sections) == tuple(_to_roman(i) for i in range(1, 22)), "section order/numerals invalid")
    return sections


def _to_roman(value: int) -> str:
    mapping = ((10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"))
    out = ""
    for number, symbol in mapping:
        while value >= number:
            out += symbol
            value -= number
    return out


SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE recovery_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID;
CREATE TABLE recovery_sources (
  id TEXT PRIMARY KEY, url TEXT NOT NULL, title TEXT NOT NULL, sha256 TEXT NOT NULL,
  retrieved_at TEXT, media_type TEXT NOT NULL, raw_path TEXT NOT NULL
) WITHOUT ROWID;
CREATE TABLE recovery_editions (
  id TEXT PRIMARY KEY, valid_from TEXT, valid_to TEXT, chain_status TEXT NOT NULL,
  complete INTEGER NOT NULL CHECK(complete IN (0,1)), chapters_json TEXT NOT NULL,
  source_ids_json TEXT NOT NULL, limitations_json TEXT NOT NULL
) WITHOUT ROWID;
CREATE TABLE recovery_notes (
  id TEXT PRIMARY KEY, title TEXT NOT NULL, source_id TEXT NOT NULL,
  page INTEGER, text TEXT, url TEXT,
  FOREIGN KEY(source_id) REFERENCES recovery_sources(id)
) WITHOUT ROWID;
CREATE TABLE recovery_sections (
  roman_number TEXT PRIMARY KEY, raw_roman_number TEXT NOT NULL, title TEXT NOT NULL,
  source_id TEXT NOT NULL, FOREIGN KEY(source_id) REFERENCES recovery_sources(id)
) WITHOUT ROWID;
CREATE TABLE recovery_section_chapters (
  chapter_code TEXT PRIMARY KEY, section_roman TEXT NOT NULL,
  FOREIGN KEY(section_roman) REFERENCES recovery_sections(roman_number)
) WITHOUT ROWID;
CREATE TABLE recovery_nodes (
  edition_id TEXT NOT NULL, code TEXT NOT NULL, label TEXT NOT NULL,
  parent_code TEXT, source_id TEXT NOT NULL, page INTEGER NOT NULL,
  path_json TEXT NOT NULL, note_refs_json TEXT NOT NULL, change_symbol TEXT NOT NULL,
  PRIMARY KEY(edition_id, code),
  FOREIGN KEY(edition_id) REFERENCES recovery_editions(id),
  FOREIGN KEY(source_id) REFERENCES recovery_sources(id),
  FOREIGN KEY(edition_id, parent_code) REFERENCES recovery_nodes(edition_id, code) DEFERRABLE INITIALLY DEFERRED
) WITHOUT ROWID;
CREATE UNIQUE INDEX recovery_nodes_code_unique ON recovery_nodes(code);
CREATE INDEX recovery_nodes_parent_idx ON recovery_nodes(edition_id, parent_code);
CREATE INDEX recovery_nodes_label_idx ON recovery_nodes(label);
CREATE TABLE recovery_node_notes (
  edition_id TEXT NOT NULL, code TEXT NOT NULL, position INTEGER NOT NULL, note_id TEXT NOT NULL,
  PRIMARY KEY(edition_id, code, position),
  FOREIGN KEY(edition_id, code) REFERENCES recovery_nodes(edition_id, code),
  FOREIGN KEY(note_id) REFERENCES recovery_notes(id)
) WITHOUT ROWID;
-- Compatibility projection for the existing TnvedEntry-shaped read path.
-- source_revision remains the unverified edition id; no rate/status admission occurs.
CREATE TABLE tnved_entries (
  id INTEGER PRIMARY KEY, hs_code TEXT NOT NULL UNIQUE, parent_hs TEXT NOT NULL,
  level INTEGER NOT NULL, title TEXT NOT NULL, description TEXT NOT NULL,
  chapter TEXT NOT NULL, source_url TEXT NOT NULL, source_revision TEXT NOT NULL
);
CREATE INDEX ix_tnved_entries_hs_code ON tnved_entries(hs_code);
CREATE INDEX ix_tnved_entries_parent_hs ON tnved_entries(parent_hs);
CREATE INDEX ix_tnved_entries_chapter ON tnved_entries(chapter);
"""


def validate_catalog(catalog: dict[str, Any]) -> None:
    _require(catalog.get("schemaVersion") == 1, "unsupported catalog schemaVersion")
    for key, expected in EXPECTED_COUNTS.items():
        if key == "ten_digit":
            actual = sum(len(str(n.get("code", ""))) == 10 for n in catalog.get("nodes", []))
        else:
            actual = len(catalog.get(key, []))
        _require(actual == expected, f"{key}: expected {expected}, got {actual}")
    coverage = catalog.get("importCoverage", {})
    _require(tuple(coverage.get("acceptedChapters", [])) == EXPECTED_CHAPTERS, "accepted chapter order/coverage invalid")
    _require(not coverage.get("failedChapters"), "catalog contains failed chapters")
    source_ids = {s["id"] for s in catalog["sources"]}
    note_ids = {n["id"] for n in catalog["notes"]}
    _require(len(source_ids) == EXPECTED_COUNTS["sources"], "duplicate source ids")
    _require(len(note_ids) == EXPECTED_COUNTS["notes"], "duplicate note ids")
    editions = {e["id"]: e for e in catalog["editions"]}
    for edition in editions.values():
        _require(edition.get("validFrom") is None and edition.get("validTo") is None, "edition validity must stay unknown")
        _require(edition.get("chainStatus") == "unverified" and edition.get("complete") is False, "edition must stay unverified/incomplete")
        _require(set(edition.get("sourceIds", [])) <= source_ids, "edition references unknown source")
    keys: set[tuple[str, str]] = set()
    global_codes: set[str] = set()
    parent: dict[tuple[str, str], str | None] = {}
    for node in catalog["nodes"]:
        code, edition_id = node.get("code"), node.get("editionId")
        _require(isinstance(code, str) and code.isdigit() and len(code) in {2, 4, 6, 8, 9, 10}, f"invalid code {code!r}")
        _require(edition_id in editions, f"unknown edition for {code}")
        key = (edition_id, code)
        _require(key not in keys and code not in global_codes, f"duplicate node {key}")
        keys.add(key); global_codes.add(code); parent[key] = node.get("parentCode")
        _require(node.get("sourceId") in source_ids, f"unknown source for {code}")
        _require(isinstance(node.get("path"), list) and node["path"], f"missing path for {code}")
        _require(set(node.get("noteRefs", [])) <= note_ids, f"unknown note for {code}")
    for key, parent_code in parent.items():
        if parent_code is not None:
            _require((key[0], parent_code) in keys, f"orphan parent {parent_code} for {key}")
    for key in keys:
        seen: set[tuple[str, str]] = set()
        current: tuple[str, str] | None = key
        while current is not None:
            _require(current not in seen, f"parent cycle at {key}")
            seen.add(current)
            p = parent[current]
            current = None if p is None else (current[0], p)


def _logical_digest(conn: sqlite3.Connection) -> str:
    digest = hashlib.sha256()
    tables = ("recovery_metadata", "recovery_sources", "recovery_editions", "recovery_notes", "recovery_sections", "recovery_section_chapters", "recovery_nodes", "recovery_node_notes", "tnved_entries")
    for table in tables:
        digest.update((table + "\n").encode())
        columns = [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
        order = ",".join(str(i + 1) for i in range(len(columns)))
        for row in conn.execute(f"SELECT * FROM {table} ORDER BY {order}"):
            digest.update((_json(list(row)) + "\n").encode())
    return digest.hexdigest()


def build(catalog_path: Path, index_path: Path, output_path: Path, manifest_path: Path | None = None) -> dict[str, Any]:
    catalog_raw, index_raw = catalog_path.read_bytes(), index_path.read_bytes()
    _require(_sha(catalog_raw) == CATALOG_SHA256, "catalog bytes do not match approved input")
    _require(_sha(index_raw) == INDEX_SHA256, "EEC index bytes do not match approved input")
    catalog = json.loads(catalog_raw)
    validate_catalog(catalog)
    sections = parse_sections(index_raw)
    source_by_id = {s["id"]: s for s in catalog["sources"]}
    _require(source_by_id["eec-ett-index"]["sha256"] == INDEX_SHA256, "catalog/index provenance mismatch")
    _require(not output_path.exists(), f"refusing to overwrite existing recovery output: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    building_path = output_path.with_name(f".{output_path.name}.building")
    _require(not building_path.exists(), f"refusing to reuse incomplete recovery output: {building_path}")
    conn = sqlite3.connect(building_path)
    try:
        # The database is assembled at a private temporary path.  Disabling
        # journalling here prevents a successful build from depending on a
        # transferable rollback sidecar; only the verified closed database is
        # atomically exposed at output_path.
        conn.execute("PRAGMA journal_mode=OFF")
        conn.executescript(SCHEMA)
        with conn:
            metadata = {
                "schema_version": "1",
                "catalog_sha256": CATALOG_SHA256,
                "index_sha256": INDEX_SHA256,
                "catalog_id": str(catalog["id"]),
                "legal_status": "unverified",
                "rates_present": "false",
                "generated_at_source": str(catalog.get("generatedAt") or ""),
            }
            conn.executemany("INSERT INTO recovery_metadata VALUES (?,?)", sorted(metadata.items()))
            conn.executemany(
                "INSERT INTO recovery_sources VALUES (?,?,?,?,?,?,?)",
                [(s["id"], s["url"], s["title"], s["sha256"], s.get("retrievedAt"), s.get("mediaType", ""), s.get("rawPath", "")) for s in sorted(catalog["sources"], key=lambda x: x["id"])],
            )
            conn.executemany(
                "INSERT INTO recovery_editions VALUES (?,?,?,?,?,?,?,?)",
                [(e["id"], e.get("validFrom"), e.get("validTo"), e["chainStatus"], int(e["complete"]), _json(e.get("chapters", [])), _json(e.get("sourceIds", [])), _json(e.get("limitations", []))) for e in sorted(catalog["editions"], key=lambda x: x["id"])],
            )
            conn.executemany(
                "INSERT INTO recovery_notes VALUES (?,?,?,?,?,?)",
                [(n["id"], n.get("title", ""), n["sourceId"], n.get("page"), n.get("text"), n.get("url")) for n in sorted(catalog["notes"], key=lambda x: x["id"])],
            )
            conn.executemany("INSERT INTO recovery_sections VALUES (?,?,?,?)", [(s["roman"], s["rawRoman"], s["title"], "eec-ett-index") for s in sections])
            conn.executemany("INSERT INTO recovery_section_chapters VALUES (?,?)", [(ch, s["roman"]) for s in sections for ch in s["chapters"]])
            nodes = sorted(catalog["nodes"], key=lambda n: (n["editionId"], n["code"]))
            conn.executemany(
                "INSERT INTO recovery_nodes VALUES (?,?,?,?,?,?,?,?,?)",
                [(n["editionId"], n["code"], n["label"], n.get("parentCode"), n["sourceId"], int(n["page"]), _json(n["path"]), _json(n.get("noteRefs", [])), n.get("changeSymbol", "")) for n in nodes],
            )
            conn.executemany(
                "INSERT INTO recovery_node_notes VALUES (?,?,?,?)",
                [(n["editionId"], n["code"], pos, note) for n in nodes for pos, note in enumerate(n.get("noteRefs", []))],
            )
            compat = []
            for idx, n in enumerate(sorted(catalog["nodes"], key=lambda n: n["code"]), 1):
                source = source_by_id[n["sourceId"]]
                compat.append((idx, n["code"], n.get("parentCode") or "", len(n["code"]), n["label"], _json(n["path"]), n["code"][:2], source["url"], n["editionId"]))
            conn.executemany("INSERT INTO tnved_entries VALUES (?,?,?,?,?,?,?,?,?)", compat)
        conn.execute("VACUUM")
    finally:
        conn.close()
    for suffix in ("-journal", "-wal", "-shm"):
        _require(not Path(f"{building_path}{suffix}").exists(), f"unexpected SQLite sidecar after close: {suffix}")
    # Validate and digest a freshly reopened file.  This is deliberately after
    # closing the writer so the manifest can never describe buffered or
    # pre-VACUUM bytes instead of the transferable artifact.
    with closing(sqlite3.connect(f"file:{building_path.resolve()}?mode=ro&immutable=1", uri=True)) as check:
        _require(check.execute("PRAGMA foreign_key_check").fetchall() == [], "foreign key check failed")
        _require(check.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "SQLite integrity check failed")
        logical_sha = _logical_digest(check)
    building_path.replace(output_path)
    _require(not building_path.exists(), "temporary recovery file remains after atomic publish")
    for suffix in ("-journal", "-wal", "-shm"):
        _require(not Path(f"{output_path}{suffix}").exists(), f"unexpected published SQLite sidecar: {suffix}")
    with closing(sqlite3.connect(f"file:{output_path.resolve()}?mode=ro&immutable=1", uri=True)) as published:
        _require(published.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "published SQLite integrity check failed")
    result = {
        "schemaVersion": 1,
        "catalogSha256": CATALOG_SHA256,
        "indexSha256": INDEX_SHA256,
        "sqlitePath": str(output_path),
        "sqliteBytes": output_path.stat().st_size,
        "sqliteSha256": _sha(output_path.read_bytes()),
        "logicalSha256": logical_sha,
        "counts": {**EXPECTED_COUNTS, "sections": 21, "chapters": 96},
        "integrityCheck": "ok",
        "legalStatus": "unverified",
        "ratesPresent": False,
    }
    if manifest_path is not None:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    return result


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--ett-index", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args(argv)
    print(json.dumps(build(args.catalog, args.ett_index, args.output, args.manifest), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
