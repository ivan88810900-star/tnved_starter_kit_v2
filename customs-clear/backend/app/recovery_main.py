"""Explicit local read-only profile. Never imports normal app startup or .env."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .api.tnved_recovery import recovery_router
from .services.tnved_recovery_store import TnvedRecoveryStore


def create_recovery_app(database: Path, expected_sha256: str, frontend: Path | None = None) -> FastAPI:
    database = database.resolve(strict=True)
    if not database.is_file() or not re.fullmatch(r"[a-f0-9]{64}", expected_sha256):
        raise ValueError("An existing snapshot and explicit SHA-256 pin are required")
    if any(Path(str(database) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
        raise ValueError("Recovery snapshot must not have database sidecars")
    with database.open("rb") as source:
        actual = hashlib.file_digest(source, "sha256").hexdigest()
    if actual != expected_sha256:
        raise ValueError("Recovery snapshot SHA-256 mismatch")
    with TnvedRecoveryStore(database) as store:
        status = store.status()
    if status["legal_status"] != "unverified" or status["rates_present"]:
        raise ValueError("This profile requires an unverified structural snapshot without rates")
    app = FastAPI(title="Tariff — восстановленный справочник (только чтение)")
    identity = database.stat()

    @app.middleware("http")
    async def require_unchanged_snapshot(request, call_next):
        if request.url.path.startswith("/api/"):
            try:
                current = database.stat()
                valid = all(getattr(current, key) == getattr(identity, key) for key in (
                    "st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns"
                )) and not any(
                    Path(str(database) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")
                )
            except OSError:
                valid = False
            if not valid:
                return JSONResponse({"detail": "Снимок изменился или недоступен; проверьте SHA-256 и перезапустите локальный профиль"}, status_code=503)
        return await call_next(request)

    app.include_router(recovery_router(database, actual))

    @app.get("/api/health/ready")
    def ready():
        return {
            "status": "ready", "database": True, "redis": None, "assistant_llm_configured": False,
            "recovered_catalog": {**status, "snapshot_sha256": actual},
        }

    if frontend is not None:
        frontend = frontend.resolve(strict=True)
        index = frontend / "index.html"
        if not index.is_file():
            raise ValueError("Build the existing frontend before serving it")
        app.mount("/assets", StaticFiles(directory=frontend / "assets"), name="assets")

        @app.get("/")
        def home():
            return RedirectResponse("/tnved")

        @app.get("/{path:path}")
        def spa(path: str):
            if path.startswith("api/"):
                raise HTTPException(404)
            return FileResponse(index)
    return app


def create_app() -> FastAPI:
    return create_recovery_app(
        Path(os.environ["TNVED_RECOVERY_DB"]),
        os.environ["TNVED_RECOVERY_SQLITE_SHA256"],
        Path(os.environ["TNVED_RECOVERY_FRONTEND"]) if os.environ.get("TNVED_RECOVERY_FRONTEND") else None,
    )
