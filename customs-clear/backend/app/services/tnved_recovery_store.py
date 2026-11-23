"""Read-only adapter for an isolated TN VED recovery SQLite.

The adapter exposes structural lookup/search only.  It never returns rates or a
claim that the recovered snapshot is legally active.
"""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
import re
import sqlite3
from typing import Any

from .tnved_presentation import PresentationIntegrityError


class SourceTextProvenanceError(RuntimeError):
    """The enabled source-text projection is internally incomplete."""


class TnvedRecoveryStore:
    def __init__(self, path: str | Path) -> None:
        uri = f"file:{Path(path).resolve()}?mode=ro"
        self._conn = sqlite3.connect(uri, uri=True)
        self._conn.row_factory = sqlite3.Row
        self.navigation_enabled = self._conn.execute("SELECT 1 FROM sqlite_master WHERE name='recovery_navigation'").fetchone() is not None
        self.source_text_enabled = self._conn.execute("SELECT 1 FROM sqlite_master WHERE name='recovery_source_text'").fetchone() is not None
        self.presentation_enabled = self._conn.execute("SELECT 1 FROM sqlite_master WHERE name='recovery_presentation_items'").fetchone() is not None

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
            "navigation_enabled": self.navigation_enabled,
            "source_text_enabled": self.source_text_enabled,
            "navigation_nodes": self._conn.execute("SELECT count(*) FROM recovery_navigation").fetchone()[0] if self.navigation_enabled else None,
            "presentation_enabled": self.presentation_enabled,
            "reserved_markers": self._conn.execute("SELECT count(*) FROM recovery_reserved_markers").fetchone()[0] if self.presentation_enabled else 0,
        }

    def sections(self) -> list[dict[str, Any]]:
        if self.navigation_enabled:
            return [dict(row) for row in self._conn.execute("SELECT id,code,label,kind,source_order FROM recovery_navigation WHERE kind='section' ORDER BY source_order")]
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
        if self.navigation_enabled:
            return [dict(row) for row in self._conn.execute("SELECT * FROM recovery_navigation WHERE parent_id=? AND kind='chapter' ORDER BY source_order", (section,))]
        return [dict(row) for row in self._conn.execute(
            "SELECT n.code,n.label FROM recovery_section_chapters c "
            "JOIN recovery_nodes n ON n.code=c.chapter_code "
            "WHERE c.section_roman=? ORDER BY n.code", (section,),
        )]

    def has_children(self, code: str) -> bool:
        if self.navigation_enabled:
            row = self._navigation_row(code)
            if row is None:
                return False
            return self._conn.execute("SELECT 1 FROM recovery_navigation WHERE parent_id=? LIMIT 1", (row["id"],)).fetchone() is not None or bool(self._container_markers(row))
        return self._conn.execute(
            "SELECT 1 FROM recovery_nodes WHERE parent_code=? LIMIT 1", (code,),
        ).fetchone() is not None

    def _navigation_row(self, value: str):
        value = re.sub(r"\s+", "", str(value))
        row = self._conn.execute("SELECT * FROM recovery_navigation WHERE id=?", (value,)).fetchone()
        if row is None:
            row = self._conn.execute("SELECT n.* FROM recovery_heading_aliases a JOIN recovery_navigation n ON n.id=a.node_id WHERE a.heading_code=?", (value,)).fetchone()
        return row

    def _with_source_text(self, row: dict) -> dict:
        if self.source_text_enabled:
            source = self._conn.execute("SELECT raw_label,raw_lines_json,dash_depth FROM recovery_source_text WHERE node_id=?", (row["id"],)).fetchone()
            if source is None:
                raise SourceTextProvenanceError("Missing source text provenance")
            row.update(raw_label=source["raw_label"], raw_lines=json.loads(source["raw_lines_json"]), dash_depth=source["dash_depth"])
        return row

    def lookup(self, code: str) -> dict[str, Any] | None:
        if self.navigation_enabled:
            row = self._navigation_row(code)
            if row is None:
                return self.marker(code)
            value = self._with_source_text(dict(row))
            value["presentation"] = self.presentation(row["id"])
            source = dict(self._conn.execute("SELECT url,sha256 FROM recovery_sources WHERE id=?", (row["source_id"],)).fetchone())
            edition = self._conn.execute("SELECT edition_id FROM recovery_nodes WHERE code=?", (row["chapter"],)).fetchone()
            parent = self._conn.execute("SELECT code FROM recovery_navigation WHERE id=?", (row["parent_id"],)).fetchone()
            requested = re.sub(r"\s+", "", str(code))
            value.update(node_id=row["id"], parent_code=parent[0] if parent else None,
                         edition_id=edition[0] if edition else None, path=json.loads(value.pop("path_json")), note_refs=[],
                         chain_status="unverified", valid_from=None, valid_to=None, complete=False,
                         source_url=source["url"], source_sha256=source["sha256"], rates=None,
                         requested_code=requested,
                         navigation_alias={"kind": "combined_printed_heading", "heading_code": requested, "printed_code": row["printed_code"], "resolved_code": row["code"]} if requested != row["id"] else None)
            return value
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
        if self.navigation_enabled:
            row = self._navigation_row(code)
            result, seen = [], set()
            marker = self.marker(code) if row is None else None
            if marker:
                result.append({"code": None, "node_id": marker['id'], "kind": 'reserved', "label": marker['label']})
                row = self._navigation_row(marker['parent_id'])
            while row is not None:
                if row["id"] in seen:
                    raise ValueError("cycle in navigation projection")
                seen.add(row["id"])
                result.append({"code": row["code"], "node_id": row["id"], "kind": row["kind"], "label": row["label"]})
                row = self._navigation_row(row["parent_id"]) if row["parent_id"] else None
            result.reverse()
            return result
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
        if self.navigation_enabled:
            parent = self._navigation_row(code)
            if parent is None:
                return []
            rows = self._conn.execute("SELECT * FROM recovery_navigation WHERE parent_id=? ORDER BY source_order LIMIT ?", (parent["id"], limit + 1)).fetchall()
            if len(rows) > limit:
                raise ValueError("child result exceeds limit; refusing partial result")
            values = [self._with_source_text({**dict(row), "path": json.loads(row["path_json"])}) for row in rows]
            for value in values:
                value.update(self.display_fields(value['id']))
            if self.presentation_enabled and parent['kind'] in ('chapter', 'caption'):
                markers = self._container_markers(parent)
                ordered = [(r['source_order'], 1, 0, r) for r in values] + [(r['before_order'], 0, r['marker_order'], r) for r in markers]
                values = [r[-1] for r in sorted(ordered, key=lambda r: r[:3])]
                if len(values) > limit:
                    raise ValueError('child result exceeds limit; refusing partial result')
            return values
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
        if len(str(query).strip()) < 2 or limit < 1:
            return []
        return self.search_page(query, limit=min(limit, 200))["results"]

    def search_page(self, query: str, *, cursor: str | None = None, limit: int = 40) -> dict[str, Any]:
        value = str(query).strip().casefold()
        if not 1 <= limit <= 200 or len(value) < 2:
            raise ValueError("invalid search page")
        scope = hashlib.sha256((self.status()["catalog_sha256"] + value + str(limit)).encode()).hexdigest()[:16]
        offset = 0
        if cursor:
            match = re.fullmatch(r"s1\.(\d+)\.([a-f0-9]{16})", cursor)
            if not match or match[2] != scope:
                raise ValueError("cursor belongs to another search/snapshot")
            offset = int(match[1])
        self._conn.create_function("unicode_casefold", 1, lambda text: str(text).casefold(), deterministic=True)
        numeric = re.fullmatch(r"[0-9\s]+", value) is not None
        digits = re.sub(r"\s", "", value)
        table = "recovery_navigation" if self.navigation_enabled else "recovery_nodes"
        where = "code LIKE ?" if numeric else "(instr(unicode_casefold(label),?)>0 OR instr(unicode_casefold(path_json),?)>0)"
        params = (digits + "%",) if numeric else (value, value)
        if self.navigation_enabled:
            where += " AND kind IN ('chapter','coded','codeless','caption')"
        total = self._conn.execute(f"SELECT count(*) FROM {table} WHERE {where}", params).fetchone()[0]
        if offset and (offset >= total or offset % limit):
            raise ValueError("invalid search page offset")
        order = "chapter,CASE WHEN kind='chapter' THEN -1 ELSE source_order END,id" if self.navigation_enabled else "code"
        rows = self._conn.execute(f"SELECT * FROM {table} WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?", (*params, limit, offset)).fetchall()
        def token(number):
            return f"s1.{number}.{scope}"
        return {
            "results": [{**dict(row), "path": json.loads(row["path_json"]), **self.display_fields(row['id'])} if self.navigation_enabled else {**dict(row), "path": json.loads(row["path_json"])} for row in rows],
            "total": total, "offset": offset, "limit": limit, "mode": "code_prefix" if numeric else "text",
            "has_more": offset + len(rows) < total,
            "next_cursor": token(offset + limit) if offset + limit < total else None,
            "previous_cursor": token(max(0, offset - limit)) if offset else None,
            "last_cursor": token(((total - 1) // limit) * limit) if total > limit else None,
        }

    def display_fields(self, node_id: str) -> dict:
        if not self.presentation_enabled:
            return {}
        row = self._conn.execute('SELECT notice FROM recovery_presentation_items WHERE node_id=?', (node_id,)).fetchone()
        return {'format_notice': row['notice'], 'source_fragment_url': f'/api/v1/tnved/{node_id}/source-fragments/0.png'} if row else {}

    def presentation(self, node_id: str) -> dict | None:
        if not self.presentation_enabled:
            return None
        row = self._conn.execute('SELECT p.*,s.url,s.sha256 FROM recovery_presentation_items p JOIN recovery_sources s ON s.id=p.source_id WHERE p.node_id=?', (node_id,)).fetchone()
        if row is None:
            return None
        fragments = [dict(r) for r in self._conn.execute('SELECT ordinal,page,bounds_json,sha256 FROM recovery_source_fragments WHERE node_id=? ORDER BY ordinal', (node_id,))]
        if not fragments:
            raise PresentationIntegrityError('Missing original source fragment')
        return {'notice': row['notice'], 'reasons': json.loads(row['reasons_json']), 'spacing_difference': json.loads(row['spacing_json']) if row['spacing_json'] else None,
                'source_url': row['url'], 'source_sha256': row['sha256'],
                'fragments': [{'url': f"/api/v1/tnved/{node_id}/source-fragments/{r['ordinal']}.png", 'page': r['page'], 'sha256': r['sha256'], 'bounds': json.loads(r['bounds_json'])} for r in fragments]}

    def source_fragment(self, node_id: str, ordinal: int) -> dict | None:
        if not self.presentation_enabled:
            return None
        row = self._conn.execute('SELECT f.png,f.sha256,s.sha256 AS source_sha256 FROM recovery_source_fragments f JOIN recovery_presentation_items p ON p.node_id=f.node_id JOIN recovery_sources s ON s.id=p.source_id WHERE f.node_id=? AND f.ordinal=?', (node_id, ordinal)).fetchone()
        if row is None:
            return None
        if hashlib.sha256(row['png']).hexdigest() != row['sha256']:
            raise PresentationIntegrityError('Original source fragment hash mismatch')
        return dict(row)

    def _container_markers(self, parent) -> list[dict]:
        if not self.presentation_enabled or parent['kind'] not in ('chapter', 'caption'):
            return []
        markers = (self.marker(r['id']) for r in self._conn.execute(
            'SELECT id FROM recovery_reserved_markers WHERE chapter=? ORDER BY before_order,marker_order',
            (parent['chapter'],),
        ))
        return [row for row in markers if row['parent_id'] == parent['id']]

    def _marker_parent(self, marker) -> sqlite3.Row:
        """Resolve the container open immediately BEFORE this printed position.

        before_order points to the next navigation row. That row can open a
        different caption, so use its predecessor and walk past commodity /
        codeless ancestors to the open caption or chapter. Consecutive marks
        share the position; marker_order supplies their separate stable order.
        Nothing is persisted and no reserved-code exceptions are needed.
        """
        row = self._conn.execute(
            "SELECT * FROM recovery_navigation WHERE chapter=? "
            "AND kind NOT IN ('section','chapter') AND source_order<? "
            "ORDER BY source_order DESC LIMIT 1",
            (marker['chapter'], marker['before_order']),
        ).fetchone()
        seen = set()
        while row is not None and row['kind'] not in ('chapter', 'caption'):
            if row['id'] in seen:
                raise PresentationIntegrityError('Cycle in reserved marker ancestry')
            seen.add(row['id'])
            row = self._navigation_row(row['parent_id'])
        parent = row if row is not None else self._navigation_row(marker['chapter'])
        if parent is None or parent['chapter'] != marker['chapter']:
            raise PresentationIntegrityError('Missing reserved marker container')
        return parent

    def marker(self, node_id: str) -> dict | None:
        if not self.presentation_enabled:
            return None
        row = self._conn.execute('SELECT m.*,p.source_id,s.url,s.sha256 FROM recovery_reserved_markers m JOIN recovery_presentation_items p ON p.node_id=m.id JOIN recovery_sources s ON s.id=p.source_id WHERE m.id=?', (node_id,)).fetchone()
        if row is None:
            return None
        parent = self._marker_parent(row)
        value = dict(row)
        value.update(code=None, node_id=row['id'], kind='reserved', label=row['printed_code'], parent_id=parent['id'], source_order=row['before_order'],
                     printed_code=row['printed_code'], path=json.loads(parent['path_json']) + [row['printed_code']], raw_label=row['printed_code'], raw_lines=[], dash_depth=None,
                     source_url=row['url'], source_sha256=row['sha256'], edition_id=None, chain_status='unverified', valid_from=None, valid_to=None, complete=False, rates=None,
                     presentation=self.presentation(node_id), **self.display_fields(node_id))
        return value

