"""
HTTP для синхронизации реестров (госсайты): короткий таймаут и повторы при 5xx/сетевых сбоях.
"""

from __future__ import annotations

from typing import Any

import requests
from loguru import logger
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

# Госресурсы часто «висят» — не держим соединение долго.
REGISTRY_HTTP_TIMEOUT_SEC: float = 15.0
REGISTRY_HTTP_MAX_ATTEMPTS: int = 5


def _before_sleep_log(retry_state: Any) -> None:
    exc: BaseException | None = None
    try:
        out = getattr(retry_state, "outcome", None)
        if out is not None and getattr(out, "failed", False):
            exc = out.exception()
    except Exception:
        pass
    n = getattr(retry_state, "attempt_number", 0)
    logger.warning("registry_http_get: пауза перед повтором (попытка {}/{}): {!r}", n, REGISTRY_HTTP_MAX_ATTEMPTS, exc)


def _is_retryable_exception(exc: BaseException) -> bool:
    if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
        return True
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        return exc.response.status_code in (500, 502, 503, 504)
    return False


@retry(
    stop=stop_after_attempt(REGISTRY_HTTP_MAX_ATTEMPTS),
    wait=wait_exponential(multiplier=1, min=1, max=30),
    retry=retry_if_exception(_is_retryable_exception),
    before_sleep=_before_sleep_log,
    reraise=True,
)
def registry_http_get(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float | None = None,
) -> requests.Response:
    """
    GET с ``timeout`` по умолчанию :data:`REGISTRY_HTTP_TIMEOUT_SEC`.
    Повтор при Timeout/ConnectionError и при HTTP 500/502/503/504.
    """
    to = float(timeout if timeout is not None else REGISTRY_HTTP_TIMEOUT_SEC)
    r = requests.get(url, headers=headers or {}, timeout=to)
    if r.status_code in (500, 502, 503, 504):
        r.raise_for_status()
    r.raise_for_status()
    return r


def registry_http_get_text(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float | None = None,
) -> str:
    """GET и тело ответа как str (кодировка из ответа или UTF-8)."""
    r = registry_http_get(url, headers=headers, timeout=timeout)
    if not r.encoding or r.encoding == "ISO-8859-1":
        r.encoding = r.apparent_encoding or "utf-8"
    return r.text
