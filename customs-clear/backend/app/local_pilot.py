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


def verified_rate_parts(data):
    parts = {}
    for directory, chapters in (
        (data, PINS["chapters"]),
        (os.environ.get("TARIFF_PILOT_ADDITIONAL_RATES"), PINS["additional_chapters"]),
    ):
        if directory:
            root = Path(directory).resolve(strict=True)
            for chapter, entry in chapters.items():
                path = root / (chapter + ".sqlite")
                parts[chapter] = [(chapter + "00000000", chapter + "99999999", path, verify(path, entry["sha256"]))]

    directory = os.environ.get("TARIFF_PILOT_PARTITIONED_RATES")
    if directory:
        root = Path(directory).resolve(strict=True)
        # The original partitioned snapshot contains chapter 38 only.
        chapters = os.environ.get("TARIFF_PILOT_PARTITIONED_CHAPTERS", "38").split(",")
        for chapter in chapters:
            entry = PINS["partitioned_chapters"].get(chapter)
            if entry is None:
                raise ValueError("Unknown partitioned tariff chapter")
            if chapter in parts:
                raise ValueError("Duplicate tariff chapter")
            intervals = []
            for part in entry["parts"]:
                first, last = part["first"], part["last"]
                if (len(first) != 10 or len(last) != 10 or not first.isdigit() or not last.isdigit()
                        or not first.startswith(chapter) or not last.startswith(chapter)
                        or first > last or (intervals and first <= intervals[-1][1])):
                    raise ValueError("Invalid tariff partition bounds")
                path = root / part["file"]
                intervals.append((first, last, path, verify(path, part["sha256"])))
            if not intervals:
                raise ValueError("Missing tariff partitions")
            parts[chapter] = intervals
    return parts


def create_app():
    data = Path(os.environ["TARIFF_PILOT_DATA"]).resolve(strict=True)
    catalog_path = data / "catalog.sqlite"
    catalog_identity = file_identity(catalog_path)
    catalog = create_recovery_app(catalog_path, PINS["catalog"], Path(os.environ["TNVED_RECOVERY_FRONTEND"]))
    rate_parts = verified_rate_parts(data)
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
    from .local_pilot_payments import catalog_code_issue, pilot_catalog_reader, pilot_payment_router
    from .services.normative_store import list_tr_ts_acts

    app = FastAPI(title="Tariff — локальная справочная карточка")
    app.state.registry_tempdir = scratch

    def check_catalog_snapshot():
        require_unchanged(catalog_path, catalog_identity)

    app.include_router(pilot_payment_router(catalog_path, check_catalog_snapshot, local_registry))

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
        batch = next(((path, identity) for first, last, path, identity in rate_parts.get(code[:2], ())
                      if first <= code <= last), None)
        if batch is None:
            return {"rate": None}
        path, identity = batch
        try:
            require_unchanged(path, identity)
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

    login_enabled = os.environ.get("TARIFF_PILOT_LOGIN") == "1"

    @app.get("/api/local-invoice/profile")
    def invoice_profile():
        return {"enabled": login_enabled}

    if login_enabled:
        from .api.local_pilot_invoice import pilot_invoice_router
        from .api.auth import router as auth_router
        from .api.non_tariff import non_tariff_normative_block, normative_position_checker
        from .services.local_pilot_ntm import archive_normative_block

        async def check_local_position(hs_code, description, country, permits):
            code = hs_code.strip().replace(" ", "")
            with pilot_catalog_reader(catalog_path, check_catalog_snapshot) as store:
                issue = catalog_code_issue(store, code)
                if issue:
                    raise HTTPException(422, issue["message"])
                return archive_normative_block(code, description, country=country, permits=permits)

        app.include_router(auth_router, prefix="/api/auth")
        app.include_router(pilot_invoice_router(catalog_path, check_catalog_snapshot, Path(scratch.name)))
        if prior_drafts := os.environ.pop("TARIFF_PILOT_RESUME_DRAFTS", None):
            from .local_pilot_profile import restore_local_drafts

            restore_local_drafts(Path(prior_drafts), Path(scratch.name) / "invoice-drafts.sqlite")
        app.dependency_overrides[normative_position_checker] = lambda: check_local_position
        app.add_api_route("/api/non_tariff/normative-block", non_tariff_normative_block, methods=["POST"])
    else:
        @app.post("/api/non_tariff/normative-block")
        def protected_service_unavailable():
            raise HTTPException(503, "Защищённый нормативный сервис не подключён к локальному профилю")

    # Mount after the additional endpoints so the existing SPA keeps its routes.
    app.mount("/", catalog)
    return app
