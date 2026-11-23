"""Local reference profile for pinned, previously prepared SQLite batches."""
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Path as PathParam, Query

from .recovery_main import create_recovery_app


PINS = json.loads((Path(__file__).resolve().parents[1] / "data/local_pilot_pins.json").read_text())


def file_identity(path):
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def require_unchanged(path, identity):
    if file_identity(path) != identity or any(Path(str(path) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
        raise OSError("Snapshot changed")


def verify(path, digest):
    if any(Path(str(path) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
        raise ValueError(f"Unexpected database sidecar for {path.name}")
    identity = file_identity(path)
    with path.open("rb") as stream:
        allowed = digest if isinstance(digest, list) else [digest]
        if hashlib.file_digest(stream, "sha256").hexdigest() not in allowed or identity != file_identity(path):
            raise ValueError(f"Snapshot mismatch for {path.name}")
    return identity


def create_app():
    data = Path(os.environ["TARIFF_PILOT_DATA"]).resolve(strict=True)
    catalog_path = data / "catalog.sqlite"
    catalog_identity = file_identity(catalog_path)
    catalog = create_recovery_app(catalog_path, PINS["catalog"], Path(os.environ["TNVED_RECOVERY_FRONTEND"]))
    identities = {chapter: verify(data / (chapter + ".sqlite"), entry["sha256"])
                  for chapter, entry in PINS["chapters"].items()}
    # The production reader sets SQLite WAL pragmas. Give it its own disposable
    # copy of the public registry table, without job tables, users or client data.
    registry = data / "public-acts.sqlite"
    scratch = tempfile.TemporaryDirectory(prefix="tariff-public-acts-")
    local_registry = Path(scratch.name) / registry.name
    shutil.copyfile(registry, local_registry)
    verify(local_registry, PINS["public_acts"])
    os.environ["DATABASE_URL"] = "sqlite:///" + str(local_registry)
    from .db import engine
    if engine.url.database != str(local_registry) or engine.url.drivername != "sqlite":
        raise RuntimeError("Start the pilot in a dedicated process")
    from .local_pilot_payments import pilot_payment_router
    from .services.normative_store import list_tr_ts_acts

    app = FastAPI(title="Tariff — локальная справочная карточка")
    app.state.registry_tempdir = scratch
    app.include_router(pilot_payment_router(catalog_path, lambda: require_unchanged(catalog_path, catalog_identity), local_registry))

    @app.middleware("http")
    async def local_resources_only(request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; connect-src 'self'; img-src 'self' data:; "
            "style-src 'self' 'unsafe-inline'; font-src 'self' data:; "
            "object-src 'none'; frame-ancestors 'none'; form-action 'self'"
        )
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.get("/api/local-ett/{code}")
    def saved_rate(code: Annotated[str, PathParam(pattern=r"^[0-9]{10}$")]):
        chapter = code[:2]
        if chapter not in identities:
            return {"rate": None}
        path = data / (chapter + ".sqlite")
        try:
            require_unchanged(path, identities[chapter])
            with closing(sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
                db.row_factory = sqlite3.Row
                rows = db.execute(
                    """SELECT n.hs_code, n.original_duty_text, n.original_supplementary_unit,
                              n.syntax_status, n.ambiguity_reason, n.legal_status, n.source_revision,
                              n.page_number, n.line_number, s.source_url, s.sha256 AS pdf_sha256
                       FROM ett_normalization_results n
                       JOIN source_objects s ON s.source_id = n.source_id
                       JOIN ett_collected_rows r ON r.source_id=n.source_id AND r.row_sha256=n.raw_row_sha256
                       WHERE n.hs_code=? AND n.verified=0 AND n.admitted=0 AND n.legal_status='UNVERIFIED'""",
                    (code,),
                ).fetchall()
                if len(rows) > 1:
                    raise ValueError("Multiple candidates")
                return {"rate": dict(rows[0]) if rows else None}
        except (OSError, sqlite3.Error, ValueError) as error:
            raise HTTPException(503, "Требуется проверить локальную копию партии ЕТТ") from error

    @app.get("/api/non_tariff/tr-ts-registry")
    def registry_lookup(q: str = Query(default="", max_length=160), limit: int = Query(200, ge=1, le=500)):
        # The pinned public snapshot contains nine acts. Filter the same rows
        # returned to the card, including the subject in the full title.
        needle = q.strip().casefold()
        items = [
            act for act in list_tr_ts_acts(limit=500)
            if any(needle in act[field].casefold() for field in ("act_code", "short_name", "full_title"))
        ]
        return {"status": "OK", "items": items[:limit]}

    @app.post("/api/non_tariff/normative-block")
    def protected_service_unavailable():
        raise HTTPException(503, "Защищённый нормативный сервис не подключён к локальному профилю")

    # Mount after the additional endpoints so the existing SPA keeps its routes.
    app.mount("/", catalog)
    return app
