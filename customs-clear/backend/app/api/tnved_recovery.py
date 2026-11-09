"""HTTP projections of the existing recovery store; no ORM or rate fallbacks."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import re

from fastapi import APIRouter, HTTPException, Query

from ..services.tnved_recovery_store import SourceTextProvenanceError, TnvedRecoveryStore


def recovery_router(database: Path, snapshot_sha256: str) -> APIRouter:
    router = APIRouter()
    identity = database.stat()

    def unchanged():
        try:
            current = database.stat()
        except OSError as exc:
            raise HTTPException(503, "Снимок недоступен") from exc
        if (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns, current.st_ctime_ns) != (
            identity.st_dev, identity.st_ino, identity.st_size, identity.st_mtime_ns, identity.st_ctime_ns
        ):
            raise HTTPException(503, "Снимок изменился; требуется повторная проверка SHA-256")

    @contextmanager
    def open_store():
        unchanged()
        try:
            with TnvedRecoveryStore(database) as store:
                yield store
        except SourceTextProvenanceError as exc:
            raise HTTPException(503, "В снимке отсутствует исходный текст узла; требуется проверить целостность набора") from exc
        unchanged()

    def normalized(code: str) -> str:
        if re.fullmatch(r"u-[a-f0-9]{24}", code):
            return code
        value = re.sub(r"\s+", "", code).upper()
        if not (re.fullmatch(r"[IVX]+", value) or re.fullmatch(r"[0-9]{2,10}", value)):
            raise HTTPException(422, "Некорректный код")
        return value

    def item(store, row, *, section=False):
        node_id = row.get("id") or row["code"]
        code = row["code"] or ""
        children = bool(store.chapters(node_id)) if section else store.has_children(node_id)
        return {
            "code": node_id if section else code, "node_id": node_id,
            "display_code": row.get("printed_code") or code or (node_id if section else ""), "name": row["label"],
            "level": "section" if section else f"code{len(code)}",
            "is_leaf": not section and len(code) == 10 and not children,
            "is_codeless": row.get("kind") in ("codeless", "caption"), "is_group": children, "has_children": children,
            "kind": row.get("kind"), "dash_depth": row.get("dash_depth"),
            **({"source_order": row["source_order"], "source_row_id": row.get("source_row_id")} if "source_order" in row else {}),
            "import_duty": None, "duty_rate": None, "vat_rate": None,
        }

    def children(store, code):
        if not code:
            return [item(store, row, section=True) for row in store.sections()]
        if re.fullmatch(r"[IVX]+", code):
            rows = store.chapters(code)
            if not rows:
                raise HTTPException(404, "Раздел не найден")
        else:
            if store.lookup(code) is None:
                raise HTTPException(404, "Код не найден")
            try:
                rows = store.children(code)
            except ValueError as exc:
                raise HTTPException(422, "Список дочерних узлов превышает допустимый размер") from exc
        return [item(store, row) for row in rows]

    def breadcrumb(store, code):
        rows = store.breadcrumb(code)
        if not rows:
            raise HTTPException(404, "Код не найден")
        if store.navigation_enabled:
            return [{"hs_code": row["code"] or (row["node_id"] if row["kind"] == "section" else ""), "node_id": row["node_id"], "title": row["label"], "level": index, "is_codeless": row["kind"] in ("codeless", "caption")} for index, row in enumerate(rows)]
        section = store.section_for(code)
        return ([{"hs_code": section["code"], "title": section["label"], "level": 0}] if section else []) + [
            {"hs_code": row["code"], "title": row["label"], "level": len(row["code"])} for row in rows
        ]

    @router.get("/api/v1/tnved/search")
    def search(q: str = Query(min_length=2, max_length=200), cursor: str | None = Query(default=None, max_length=100), limit: int = Query(default=40, ge=1, le=200)):
        with open_store() as store:
            try:
                page = store.search_page(q, cursor=cursor, limit=limit)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            page["results"] = [{**item(store, row), "path": row["path"]} for row in page["results"]]
            return {"status": "OK", "snapshot_sha256": snapshot_sha256, **page}

    @router.get("/api/tnved/children")
    @router.get("/api/tnved/children/{code}")
    def get_children(code: str = "", depth: str = Query(default="direct", pattern="^direct$")):
        code = normalized(code) if code else ""
        with open_store() as store:
            return {"status": "OK", "code": code, "depth": depth, "items": children(store, code), "snapshot_sha256": snapshot_sha256}

    @router.get("/api/tnved/breadcrumb/{code}")
    def get_breadcrumb(code: str):
        with open_store() as store:
            return {"status": "OK", "breadcrumb": breadcrumb(store, normalized(code)), "snapshot_sha256": snapshot_sha256}

    @router.get("/api/v1/tnved/{code}")
    def detail(code: str):
        code = normalized(code)
        with open_store() as store:
            row = store.lookup(code)
            if row is None:
                raise HTTPException(404, "Код не найден")
            return {
                "status": "OK", "code": row["code"] or "", "name": row["label"], "path": row["path"],
                "breadcrumb": breadcrumb(store, code), "children": children(store, code),
                "source_url": row["source_url"], "source_sha256": row["source_sha256"],
                "edition_id": row["edition_id"], "page": row["page"],
                "legal_status": row["chain_status"], "valid_from": row["valid_from"],
                "valid_to": row["valid_to"], "complete": row["complete"], "rates": None,
                "snapshot_sha256": snapshot_sha256,
                "node_id": row.get("node_id", code), "printed_code": row.get("printed_code", code),
                "requested_code": row.get("requested_code", code), "navigation_alias": row.get("navigation_alias"),
                "kind": row.get("kind"), "dash_depth": row.get("dash_depth"),
                "raw_name": row.get("raw_label", row["label"]), "source_lines": row.get("raw_lines", []),
            }

    return router
