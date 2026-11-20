from __future__ import annotations

from typing import Any, Optional

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .admin_token import require_admin_token as require_admin_token
from .api import auth as auth_mod

_bearer_optional = HTTPBearer(auto_error=False)

AUTHENTICATION_REQUIRED_DETAIL: dict[str, str] = {
    "error_code": "authentication_required",
    "message": "Требуется авторизация. Выполните POST /api/auth/login.",
}


def _raise_authentication_required() -> None:
    raise HTTPException(status_code=401, detail=dict(AUTHENTICATION_REQUIRED_DETAIL))


async def require_authenticated_user(
    request: Request,
    cred: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_optional),
) -> dict[str, Any]:
    """JWT из Authorization: Bearer … или HttpOnly-cookie (как у POST /api/auth/login)."""
    token = (cred.credentials if cred and cred.credentials else "").strip()
    if not token:
        token = (request.cookies.get(auth_mod.ACCESS_COOKIE_NAME) or "").strip()
    if not token:
        _raise_authentication_required()
    payload = auth_mod.decode_access_token(token)
    if not payload:
        _raise_authentication_required()
    username = str(payload.get("sub") or "").strip()
    if not username:
        _raise_authentication_required()
    role = str(payload.get("role") or "viewer").strip().lower()
    return {"username": username, "role": role, "payload": payload}
