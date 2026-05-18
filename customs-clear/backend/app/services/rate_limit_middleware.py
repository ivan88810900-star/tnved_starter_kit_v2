"""Простой rate limit по IP для /api/* (скользящее окно 60 с)."""
from __future__ import annotations

import time
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, per_minute: int) -> None:
        super().__init__(app)
        self.per_minute = max(1, int(per_minute))
        self._clients: dict[str, deque[float]] = defaultdict(deque)
        self._window_sec = 60.0

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path or ""
        if not path.startswith("/api/") or path.startswith("/api/health"):
            return await call_next(request)
        client = request.client.host if request.client else "unknown"
        now = time.time()
        dq = self._clients[client]
        while dq and dq[0] < now - self._window_sec:
            dq.popleft()
        if len(dq) >= self.per_minute:
            return JSONResponse(
                {"detail": "Превышен лимит запросов к API. Повторите позже."},
                status_code=429,
            )
        dq.append(now)
        return await call_next(request)
