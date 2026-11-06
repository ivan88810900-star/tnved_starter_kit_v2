"""Read-only adapter for an isolated TN VED recovery SQLite.

The adapter exposes structural lookup/search only.  It never returns rates or a
claim that the recovered snapshot is legally active.
"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any


class TnvedRecoveryStore:
    def __init__(self, path: str | Path) -> None:
        uri = f"file:{Path(path).resolve()}?mode=ro"
        self._conn = sqlite3.connect(uri, uri=True)
        self._conn.row_factory = sqlite3.Row

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "TnvedRecoveryStore":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def status(self) -> dict[str, Any]:
        metadata = dict(self._conn.execute("SELECT key,value FROM recovery_metadata"))
        return {
            "catalog_id": metadata["catalog_id"],
            "catalog_sha256": metadata["catalog_sha256"],
            "legal_status": metadata["legal_status"],
            "rates_present": metadata["rates_present"] == "true",
            "nodes": self._conn.execute("SELECT count(*) FROM recovery_nodes").fetchone()[0],
        }

    def sections(self) -> list[dict[str, Any]]:
        rows = [dict(row) for row in self._conn.execute(
            "SELECT roman_number AS code,title AS label FROM recovery_sections "
            "ORDER BY roman_number"
        )]
        order = "I II III IV V VI VII VIII IX X XI XII XIII XIV XV XVI XVII XVIII XIX XX XXI".split()
        return sorted(rows, key=lambda row: order.index(row["code"]))

    def section_for(self, code: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT s.roman_number AS code,s.title AS label FROM recovery_sections s "
            "JOIN recovery_section_chapters c ON c.section_roman=s.roman_number "
            "WHERE c.chapter_code=?", (code[:2],),
        ).fetchone()
        return dict(row) if row else None

    def chapters(self, section: str) -> list[dict[str, Any]]:
        return [dict(row) for row in self._conn.execute(
            "SELECT n.code,n.label FROM recovery_section_chapters c "
            "JOIN recovery_nodes n ON n.code=c.chapter_code "
            "WHERE c.section_roman=? ORDER BY n.code", (section,),
        )]

    def has_children(self, code: str) -> bool:
        return self._conn.execute(
            "SELECT 1 FROM recovery_nodes WHERE parent_code=? LIMIT 1", (code,),
        ).fetchone() is not None

    def lookup(self, code: str) -> dict[str, Any] | None:
        normalized = "".join(ch for ch in str(code) if ch.isdigit())
        row = self._conn.execute(
            """SELECT n.*, e.chain_status,e.valid_from,e.valid_to,e.complete,
                      s.url AS source_url,s.sha256 AS source_sha256
                 FROM recovery_nodes n
                 JOIN recovery_editions e ON e.id=n.edition_id
                 JOIN recovery_sources s ON s.id=n.source_id
                WHERE n.code=?""",
            (normalized,),
        ).fetchone()
        if row is None:
            return None
        value = dict(row)
        value["path"] = json.loads(value.pop("path_json"))
        value["note_refs"] = json.loads(value.pop("note_refs_json"))
        value["complete"] = bool(value["complete"])
        value["rates"] = None
        return value

    def breadcrumb(self, code: str) -> list[dict[str, Any]]:
        item = self.lookup(code)
        if item is None:
            return []
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        current = item
        while current is not None:
            if current["code"] in seen:
                raise ValueError("cycle in recovery database")
            seen.add(current["code"])
            rows.append({"code": current["code"], "label": current["label"]})
            current = self.lookup(current["parent_code"]) if current["parent_code"] else None
        rows.reverse()
        rows[-1]["path"] = item["path"]
        return rows

    def children(self, code: str, *, limit: int = 200) -> list[dict[str, Any]]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
            raise ValueError("limit must be an integer between 1 and 200")
        normalized = "".join(ch for ch in str(code) if ch.isdigit())
        if not normalized:
            return []
        rows = self._conn.execute(
            """SELECT code,label,path_json,edition_id,source_id
                 FROM recovery_nodes
                WHERE parent_code=?
                ORDER BY length(code), code
                LIMIT ?""",
            (normalized, limit + 1),
        ).fetchall()
        if len(rows) > limit:
            raise ValueError("child result exceeds limit; refusing partial result")
        return [{**dict(row), "path": json.loads(row["path_json"])} for row in rows]

    def search(self, query: str, *, limit: int = 40) -> list[dict[str, Any]]:
        value = str(query).strip().casefold()
        if len(value) < 2 or limit < 1:
            return []
        digits = "".join(ch for ch in value if ch.isdigit())
        pattern = f"%{value}%"
        # SQLite's built-in lower() only handles ASCII. Casefold both sides for
        # Russian catalog labels without rebuilding or writing a search index.
        self._conn.create_function("unicode_casefold", 1, lambda text: str(text).casefold(), deterministic=True)
        rows = self._conn.execute(
            """SELECT code,label,path_json,edition_id,source_id
                 FROM recovery_nodes
                WHERE unicode_casefold(label) LIKE ? OR unicode_casefold(path_json) LIKE ? OR (? <> '' AND code LIKE ?)
                ORDER BY CASE WHEN code=? THEN 0 WHEN code LIKE ? THEN 1 ELSE 2 END, length(code), code
                LIMIT ?""",
            (pattern, pattern, digits, f"{digits}%", digits, f"{digits}%", min(limit, 200)),
        ).fetchall()
        return [{**dict(row), "path": json.loads(row["path_json"])} for row in rows]

