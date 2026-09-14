"""Admin-only, read-only ETT candidate previews. No upload/approve/apply API."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
import os
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_validator
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..db import SessionLocal
from ..models.ett import ETTSnapshot
from ..security import require_authenticated_user
from ..services.ett_artifacts import LocalArtifactStore
from ..services.ett_repository import candidate_readiness, load_candidate
from ..services.ett_resolver import resolve_rate


async def _admin(user: dict = Depends(require_authenticated_user)) -> None:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Administrator access required")


router = APIRouter(dependencies=[Depends(_admin)])
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


def candidate_db():
    with SessionLocal() as db:
        yield db


def _store() -> LocalArtifactStore:
    configured = os.getenv("ETT_CANDIDATE_STORE", "")
    if not configured:
        raise HTTPException(status_code=503, detail="ETT candidate storage is not configured")
    return LocalArtifactStore(Path(configured), create=False)


class ETTPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(pattern=r"^[0-9]{10}$")
    as_of: date
    destination: str = Field(pattern=r"^(AM|BY|KZ|KG|RU)$")
    facts: dict[str, StrictStr | StrictInt | StrictBool | None] = Field(default_factory=dict, max_length=256)

    @field_validator("as_of", mode="before")
    @classmethod
    def exact_date(cls, value):
        if type(value) is date:
            return value
        if type(value) is str and len(value) == 10:
            parsed = date.fromisoformat(value)
            if parsed.isoformat() == value:
                return parsed
        raise ValueError("as_of must be an explicit YYYY-MM-DD date")

    @field_validator("facts")
    @classmethod
    def bounded_facts(cls, values):
        if any(len(key) > 128 or (isinstance(value, str) and len(value) > 2048) for key, value in values.items()):
            raise ValueError("Fact exceeds the size limit")
        return values


@router.get("")
def list_candidates(limit: int = Query(50, ge=1, le=100), db: Session = Depends(candidate_db)) -> dict[str, Any]:
    try:
        rows = db.scalars(select(ETTSnapshot).order_by(ETTSnapshot.staged_at.desc(), ETTSnapshot.manifest_sha256).limit(limit)).all()
        return {"mode": "candidate_preview", "production_ready": False, "candidates": [
            {"manifest_sha256": row.manifest_sha256, "snapshot_id": row.snapshot_id,
             "coverage_from": row.coverage_from, "coverage_to_exclusive": row.coverage_to,
             "integrity_checked": False, "status": "candidate"} for row in rows
        ]}
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="ETT candidate database is unavailable") from None


def _load(db: Session, digest: str):
    try:
        return load_candidate(db, _store(), digest)
    except (ValueError, OSError, SQLAlchemyError):
        # Never leak local paths, database URLs, raw evidence or parser exceptions.
        raise HTTPException(status_code=409, detail="ETT candidate is missing or failed integrity verification") from None


@router.get("/{digest}/readiness")
def readiness(digest: Digest, db: Session = Depends(candidate_db)) -> dict[str, Any]:
    return candidate_readiness(_load(db, digest))


@router.post("/{digest}/preview")
def preview(digest: Digest, request: ETTPreviewRequest, db: Session = Depends(candidate_db)) -> dict[str, Any]:
    manifest = _load(db, digest)
    try:
        result = resolve_rate(manifest, request.code, request.as_of, request.destination, request.facts)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid ETT preview facts") from None
    return jsonable_encoder(result, custom_encoder={Decimal: str})
