from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from jose import JWTError, jwt
from loguru import logger
import os


router = APIRouter()

def _required_env(name: str) -> str:
    value = (os.getenv(name) or "").strip()
    if not value:
        raise RuntimeError(
            f"{name} не задан. Укажите обязательный секрет в .env перед запуском приложения."
        )
    return value


SECRET_KEY = _required_env("SECRET_KEY")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "480"))
ACCESS_COOKIE_NAME = (os.getenv("AUTH_ACCESS_COOKIE_NAME") or "cc_access_token").strip() or "cc_access_token"
ACCESS_COOKIE_PATH = (os.getenv("AUTH_ACCESS_COOKIE_PATH") or "/").strip() or "/"
_cookie_samesite = (os.getenv("AUTH_ACCESS_COOKIE_SAMESITE") or "lax").strip().lower()
ACCESS_COOKIE_SAMESITE = _cookie_samesite if _cookie_samesite in {"lax", "strict", "none"} else "lax"
ACCESS_COOKIE_SECURE = (os.getenv("AUTH_ACCESS_COOKIE_SECURE") or "").strip().lower() in ("1", "true", "yes", "on")
ACCESS_COOKIE_DOMAIN = (os.getenv("AUTH_ACCESS_COOKIE_DOMAIN") or "").strip() or None

# В MVP список пользователей хранится в памяти
_USERS = {
    "admin": {
        "username": "admin",
        "password": _required_env("ADMIN_PASSWORD"),
        "role": "admin",
    },
    "viewer": {
        "username": "viewer",
        "password": _required_env("VIEWER_PASSWORD"),
        "role": "viewer",
    },
    "declarant": {
        "username": "declarant",
        "password": _required_env("DECLARANT_PASSWORD"),
        "role": "declarant",
    },
}


def authenticate_user(username: str, password: str) -> Optional[dict]:
    user = _USERS.get(username)
    if not user:
        return None
    if password != user["password"]:
        return None
    return user


def decode_access_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def _set_access_cookie(resp: JSONResponse, token: str) -> None:
    resp.set_cookie(
        key=ACCESS_COOKIE_NAME,
        value=token,
        max_age=max(60, int(ACCESS_TOKEN_EXPIRE_MINUTES) * 60),
        httponly=True,
        secure=ACCESS_COOKIE_SECURE,
        samesite=ACCESS_COOKIE_SAMESITE,
        path=ACCESS_COOKIE_PATH,
        domain=ACCESS_COOKIE_DOMAIN,
    )


def _clear_access_cookie(resp: JSONResponse) -> None:
    resp.delete_cookie(
        key=ACCESS_COOKIE_NAME,
        path=ACCESS_COOKIE_PATH,
        domain=ACCESS_COOKIE_DOMAIN,
    )


def _token_from_request(request: Request) -> str:
    auth = (request.headers.get("authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        tok = auth[7:].strip()
        if tok:
            return tok
    return (request.cookies.get(ACCESS_COOKIE_NAME) or "").strip()


@router.post("/login")
async def login(form_data: OAuth2PasswordRequestForm = Depends()) -> JSONResponse:
    """Авторизация пользователя, выдача JWT в HttpOnly cookie."""
    user = authenticate_user(form_data.username, form_data.password)
    if not user:
        logger.warning(f"Неудачная попытка входа для пользователя {form_data.username}")
        raise HTTPException(status_code=401, detail="Неверное имя пользователя или пароль")

    access_token = create_access_token(
        data={
            "sub": user["username"],
            "role": user.get("role") or "admin",
        }
    )
    logger.info(f"Пользователь {user['username']} успешно вошёл")
    resp = JSONResponse(
        {
            "status": "OK",
            "token_type": "cookie",
            "username": user["username"],
            "role": user.get("role") or "admin",
        }
    )
    _set_access_cookie(resp, access_token)
    return resp


@router.post("/logout")
async def logout() -> JSONResponse:
    resp = JSONResponse({"status": "OK"})
    _clear_access_cookie(resp)
    return resp


@router.get("/me")
async def me(request: Request) -> JSONResponse:
    token = _token_from_request(request)
    if not token:
        raise HTTPException(status_code=401, detail="Сессия не найдена")
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Недействительная сессия")
    return JSONResponse(
        {
            "status": "OK",
            "authenticated": True,
            "username": str(payload.get("sub") or ""),
            "role": str(payload.get("role") or "viewer"),
        }
    )

