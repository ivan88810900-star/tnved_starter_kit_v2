"""Опциональная проверка JWT для экспорта (VED_EXPORT_MIN_ROLE)."""
from __future__ import annotations

import os
from typing import Optional

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .api import auth as auth_mod

ROLE_RANK = {"viewer": 1, "declarant": 2, "admin": 3}

_bearer = HTTPBearer(auto_error=False)


def ved_export_min_role() -> Optional[str]:
    v = (os.getenv("VED_EXPORT_MIN_ROLE") or "").strip().lower()
    if not v or v in ("0", "off", "false", "no", "none"):
        return None
    if v not in ROLE_RANK:
        return None
    return v


async def verify_ved_export_allowed(
    request: Request,
    cred: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> None:
    need = ved_export_min_role()
    if need is None:
        return
    token = (cred.credentials if cred else "") or ""
    token = token.strip() or (request.cookies.get(auth_mod.ACCESS_COOKIE_NAME) or "").strip()
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Для экспорта PDF нужна сессия (см. VED_EXPORT_MIN_ROLE). Выполните POST /api/auth/login.",
        )
    payload = auth_mod.decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Недействительный токен")
    role = str(payload.get("role") or "admin").strip().lower()
    if ROLE_RANK.get(role, 0) < ROLE_RANK.get(need, 99):
        raise HTTPException(
            status_code=403,
            detail=f"Недостаточно прав для экспорта (нужна роль не ниже «{need}», у вас «{role}»).",
        )
