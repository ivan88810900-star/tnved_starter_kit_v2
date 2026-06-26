"""Кэш с TTL: память процесса + опционально Redis (ФСА, ТРОИС)."""
from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any, Optional

from loguru import logger

REDIS_URL = os.getenv("REDIS_URL", "").strip()
DEFAULT_TTL = int(os.getenv("CACHE_TTL_SECONDS", "3600"))

PERMITS_PREFIX = "cc:perm:"
TROIS_PREFIX = "cc:trois:"

_mem: dict[str, tuple[float, str]] = {}
_lock = asyncio.Lock()
_redis_client: Any = None


async def _get_redis():
    global _redis_client
    if not REDIS_URL:
        return None
    if _redis_client is None:
        try:
            import redis.asyncio as redis_async

            _redis_client = redis_async.from_url(REDIS_URL, decode_responses=True)
        except ImportError:
            logger.warning("Пакет redis не установлен — только in-memory кэш")
            return None
        except Exception as e:
            logger.warning(f"Redis URL задан, подключение не удалось: {e}")
            return None
    return _redis_client


async def cache_get(prefix: str, key: str) -> Optional[Any]:
    full = f"{prefix}{key}"
    now = time.time()
    async with _lock:
        if full in _mem:
            exp, raw = _mem[full]
            if now < exp:
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    del _mem[full]
            else:
                del _mem[full]
    r = await _get_redis()
    if r:
        try:
            raw = await r.get(full)
            if raw:
                return json.loads(raw)
        except Exception as e:
            logger.debug(f"redis get {full}: {e}")
    return None


async def cache_set(prefix: str, key: str, value: Any, ttl: int | None = None) -> None:
    if ttl is None:
        ttl = DEFAULT_TTL
    full = f"{prefix}{key}"
    raw = json.dumps(value, default=str, ensure_ascii=False)
    async with _lock:
        _mem[full] = (time.time() + ttl, raw)
    r = await _get_redis()
    if r:
        try:
            await r.setex(full, ttl, raw)
        except Exception as e:
            logger.debug(f"redis setex {full}: {e}")


async def purge_prefix(prefix: str) -> None:
    async with _lock:
        for k in list(_mem):
            if k.startswith(prefix):
                del _mem[k]
    r = await _get_redis()
    if r:
        try:
            async for k in r.scan_iter(match=f"{prefix}*"):
                await r.delete(k)
        except Exception as e:
            logger.warning(f"redis purge {prefix}: {e}")


async def redis_ping() -> bool | None:
    """True если ответили, False ошибка, None — Redis не настроен."""
    if not REDIS_URL:
        return None
    r = await _get_redis()
    if not r:
        return False
    try:
        pong = await r.ping()
        return bool(pong)
    except Exception:
        return False
