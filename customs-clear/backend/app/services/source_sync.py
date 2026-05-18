from __future__ import annotations

import hashlib
import os
import asyncio
from typing import Any

import httpx
from loguru import logger

from .normative_store import append_sync_log, upsert_hs_rate, upsert_source_status

# Парсеры официальных источников
from .ett_odata_parser import sync_all_odata
from .ett_pdf_parser import sync_ett_from_pdfs
from .tamdoc_sync import sync_tamdoc_archive, sync_tamdoc_documents, sync_tamdoc_targeted
from .trois_sync import sync_trois_sources

EEC_ETT_URL = "https://eec.eaeunion.org/comission/department/catr/ett/"
TRADE_DEFENSE_URL = "https://eec.eaeunion.org/comission/department/catr/trade-protect/"
NORMATIVE_FEED_URL = os.getenv("NORMATIVE_FEED_URL", "").strip()
NORMATIVE_CSV_URL = os.getenv("NORMATIVE_CSV_URL", "").strip()
NORMATIVE_BUNDLE_URL = os.getenv("NORMATIVE_BUNDLE_URL", "").strip()
# Макс. групп PDF для парсинга ЕТТ (0 = все, 3 = быстрый тест по умолчанию)
ETT_PDF_MAX_GROUPS = int(os.getenv("ETT_PDF_MAX_GROUPS", "3") or "0")
HTTP_MAX_ATTEMPTS = max(1, int(os.getenv("SYNC_HTTP_MAX_ATTEMPTS", "3") or "3"))
HTTP_RETRY_BASE_SEC = max(0.2, float(os.getenv("SYNC_HTTP_RETRY_BASE_SEC", "0.8") or "0.8"))
HTTP_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
HTTP_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
}


async def _http_get_with_retries(url: str, *, timeout: float) -> httpx.Response:
    last_exc: Exception | None = None
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=HTTP_BROWSER_HEADERS) as client:
        for attempt in range(1, HTTP_MAX_ATTEMPTS + 1):
            try:
                resp = await client.get(url)
                if resp.status_code in HTTP_RETRY_STATUSES and attempt < HTTP_MAX_ATTEMPTS:
                    delay = min(8.0, HTTP_RETRY_BASE_SEC * (2 ** (attempt - 1)))
                    logger.warning(
                        "HTTP retryable status={} for {}, retry {}/{} in {:.1f}s",
                        resp.status_code,
                        url,
                        attempt,
                        HTTP_MAX_ATTEMPTS,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                return resp
            except (httpx.TimeoutException, httpx.NetworkError, httpx.TransportError) as exc:
                last_exc = exc
                if attempt >= HTTP_MAX_ATTEMPTS:
                    break
                delay = min(8.0, HTTP_RETRY_BASE_SEC * (2 ** (attempt - 1)))
                logger.warning(
                    "HTTP error {} for {}, retry {}/{} in {:.1f}s",
                    type(exc).__name__,
                    url,
                    attempt,
                    HTTP_MAX_ATTEMPTS,
                    delay,
                )
                await asyncio.sleep(delay)
    if last_exc is not None:
        raise last_exc
    raise RuntimeError(f"GET {url} failed without explicit exception")


async def sync_eec_snapshot() -> dict[str, Any]:
    """Обновляет метаданные официального источника ЕЭК ТН ВЭД/ЕТТ.

    Ревизия фиксируется по хэшу страницы-индекса.
    """
    try:
        r = await _http_get_with_retries(EEC_ETT_URL, timeout=25.0)
        r.raise_for_status()
        digest = hashlib.sha256(r.text.encode("utf-8", errors="ignore")).hexdigest()[:16]
        upsert_source_status(
            source_code="EEC_ETT",
            source_name="ТН ВЭД и ЕТТ ЕАЭС",
            source_url=EEC_ETT_URL,
            revision=digest,
            is_stale=False,
            note="Ревизия определена по хэшу страницы ЕЭК.",
        )
        append_sync_log(
            source_code="EEC_ETT",
            status="OK",
            revision=digest,
            rows_affected=0,
            note="Страница ЕЭК доступна, хэш обновлён.",
        )
        return {"status": "OK", "source": "EEC_ETT", "revision": digest}
    except Exception as exc:
        upsert_source_status(
            source_code="EEC_ETT",
            source_name="ТН ВЭД и ЕТТ ЕАЭС",
            source_url=EEC_ETT_URL,
            revision="unavailable",
            is_stale=True,
            note=f"Ошибка синхронизации: {exc}",
        )
        append_sync_log(
            source_code="EEC_ETT",
            status="ERROR",
            revision="unavailable",
            rows_affected=0,
            note=str(exc),
        )
        logger.warning(f"EEC ETT sync failed: {exc}")
        return {"status": "ERROR", "source": "EEC_ETT", "error": str(exc)}


async def sync_trade_defense() -> dict[str, Any]:
    """Обновляет метаданные источника мер торговой защиты ЕЭК.

    В MVP фиксируем ревизию по хэшу страницы-индекса торговой защиты.
    Парсинг конкретных антидемпинговых мер требует отдельной реализации
    при наличии структурированного источника данных.
    """
    try:
        r = await _http_get_with_retries(TRADE_DEFENSE_URL, timeout=25.0)
        r.raise_for_status()
        digest = hashlib.sha256(r.text.encode("utf-8", errors="ignore")).hexdigest()[:16]
        upsert_source_status(
            source_code="TRADE_DEFENSE",
            source_name="Меры торговой защиты ЕАЭС",
            source_url=TRADE_DEFENSE_URL,
            revision=digest,
            is_stale=False,
            note="Ревизия определена по хэшу страницы торговой защиты ЕЭК.",
        )
        append_sync_log(
            source_code="TRADE_DEFENSE",
            status="OK",
            revision=digest,
            rows_affected=0,
            note="Страница мер торговой защиты ЕЭК доступна, хэш обновлён.",
        )
        return {"status": "OK", "source": "TRADE_DEFENSE", "revision": digest}
    except Exception as exc:
        upsert_source_status(
            source_code="TRADE_DEFENSE",
            source_name="Меры торговой защиты ЕАЭС",
            source_url=TRADE_DEFENSE_URL,
            revision="unavailable",
            is_stale=True,
            note=f"Ошибка синхронизации: {exc}",
        )
        append_sync_log(
            source_code="TRADE_DEFENSE",
            status="ERROR",
            revision="unavailable",
            rows_affected=0,
            note=str(exc),
        )
        logger.warning(f"TRADE_DEFENSE sync failed: {exc}")
        return {"status": "ERROR", "source": "TRADE_DEFENSE", "error": str(exc)}


async def sync_rates_feed() -> dict[str, Any]:
    """Синхронизация ставок из внешнего JSON-фида.

    Формат фида:
    {
      "revision": "...",
      "rows": [{ "hs_prefix": "...", "duty_rate": 0, "vat_import_rate": 22, ... }]
    }
    """
    if not NORMATIVE_FEED_URL:
        return {"status": "SKIPPED", "source": "NORMATIVE_FEED", "note": "NORMATIVE_FEED_URL is not set"}
    try:
        r = await _http_get_with_retries(NORMATIVE_FEED_URL, timeout=25.0)
        r.raise_for_status()
        data = r.json()
        revision = str(data.get("revision") or "unknown")
        rows = data.get("rows") or []
        count = 0
        for row in rows:
            if isinstance(row, dict):
                upsert_hs_rate(row)
                count += 1
        upsert_source_status(
            source_code="NORMATIVE_FEED",
            source_name="Нормативный фид ставок",
            source_url=NORMATIVE_FEED_URL,
            revision=revision,
            is_stale=False,
            note=f"Загружено строк: {count}",
        )
        append_sync_log(
            source_code="NORMATIVE_FEED",
            status="OK",
            revision=revision,
            rows_affected=count,
            note=f"Загружено/обновлено строк: {count}",
        )
        return {"status": "OK", "source": "NORMATIVE_FEED", "revision": revision, "rows": count}
    except Exception as exc:
        upsert_source_status(
            source_code="NORMATIVE_FEED",
            source_name="Нормативный фид ставок",
            source_url=NORMATIVE_FEED_URL,
            revision="unavailable",
            is_stale=True,
            note=f"Ошибка синхронизации: {exc}",
        )
        append_sync_log(
            source_code="NORMATIVE_FEED",
            status="ERROR",
            revision="unavailable",
            rows_affected=0,
            note=str(exc),
        )
        logger.warning(f"NORMATIVE_FEED sync failed: {exc}")
        return {"status": "ERROR", "source": "NORMATIVE_FEED", "error": str(exc)}


async def sync_csv_feed() -> dict[str, Any]:
    """Синхронизация ставок из внешнего CSV по URL.

    Формат: стандартный CSV с колонками hs_prefix, duty_rate, vat_import_rate и т.д.
    """
    if not NORMATIVE_CSV_URL:
        return {"status": "SKIPPED", "source": "NORMATIVE_CSV", "note": "NORMATIVE_CSV_URL is not set"}
    try:
        r = await _http_get_with_retries(NORMATIVE_CSV_URL, timeout=60.0)
        r.raise_for_status()
        content = r.content
        # Use source_import for parsing and upsert
        from .source_import import import_normative_file
        filename = NORMATIVE_CSV_URL.split("/")[-1] or "normative.csv"
        result = import_normative_file(
            filename,
            content,
            source_code="NORMATIVE_CSV",
            source_name="CSV-фид нормативных ставок",
        )
        append_sync_log(
            source_code="NORMATIVE_CSV",
            status="OK",
            revision=result.get("revision", "import-csv"),
            rows_affected=result.get("imported", 0),
            note=f"Загружено из {NORMATIVE_CSV_URL}, импортировано: {result.get('imported', 0)}",
        )
        return {
            "status": "OK",
            "source": "NORMATIVE_CSV",
            "revision": result.get("revision"),
            "imported": result.get("imported", 0),
        }
    except Exception as exc:
        upsert_source_status(
            source_code="NORMATIVE_CSV",
            source_name="CSV-фид нормативных ставок",
            source_url=NORMATIVE_CSV_URL,
            revision="unavailable",
            is_stale=True,
            note=f"Ошибка синхронизации: {exc}",
        )
        append_sync_log(
            source_code="NORMATIVE_CSV",
            status="ERROR",
            revision="unavailable",
            rows_affected=0,
            note=str(exc),
        )
        logger.warning(f"NORMATIVE_CSV sync failed: {exc}")
        return {"status": "ERROR", "source": "NORMATIVE_CSV", "error": str(exc)}


async def sync_normative_bundle_url() -> dict[str, Any]:
    """Загрузка единого JSON-пакета (ТН ВЭД + ставки + нетарифка + примечания) по URL."""
    if not NORMATIVE_BUNDLE_URL:
        return {
            "status": "SKIPPED",
            "source": "NORMATIVE_BUNDLE",
            "note": "NORMATIVE_BUNDLE_URL is not set",
        }
    try:
        r = await _http_get_with_retries(NORMATIVE_BUNDLE_URL, timeout=120.0)
        r.raise_for_status()
        from .normative_bundle import import_normative_bundle_bytes

        result = import_normative_bundle_bytes(
            r.content,
            filename=NORMATIVE_BUNDLE_URL.split("/")[-1] or "bundle.json",
            source_code="NORMATIVE_BUNDLE",
            source_name="Пакет нормативных данных (URL)",
        )
        return {
            "status": "OK",
            "source": "NORMATIVE_BUNDLE",
            "revision": result.get("revision"),
            "imported": result.get("imported"),
        }
    except Exception as exc:
        from .normative_store import append_sync_log, upsert_source_status

        upsert_source_status(
            source_code="NORMATIVE_BUNDLE",
            source_name="Пакет нормативных данных (URL)",
            source_url=NORMATIVE_BUNDLE_URL,
            revision="unavailable",
            is_stale=True,
            note=f"Ошибка: {exc}",
        )
        append_sync_log(
            source_code="NORMATIVE_BUNDLE",
            status="ERROR",
            revision="unavailable",
            rows_affected=0,
            note=str(exc),
        )
        logger.warning(f"NORMATIVE_BUNDLE sync failed: {exc}")
        return {"status": "ERROR", "source": "NORMATIVE_BUNDLE", "error": str(exc)}


async def sync_odata_sources() -> dict[str, Any]:
    """Парсинг OData портала ЕАЭС: классификатор льгот, попытка ЕТТ."""
    try:
        return await sync_all_odata()
    except Exception as exc:
        logger.warning(f"OData sync failed: {exc}")
        return {"status": "ERROR", "source": "ODATA", "error": str(exc)}


async def sync_ett_pdf() -> dict[str, Any]:
    """Прямой парсинг PDF ЕТТ с сайта ЕЭК."""
    try:
        return await sync_ett_from_pdfs(max_groups=ETT_PDF_MAX_GROUPS)
    except Exception as exc:
        logger.warning(f"ETT PDF sync failed: {exc}")
        return {"status": "ERROR", "source": "ETT_PDF", "error": str(exc)}


async def sync_all_sources() -> dict[str, Any]:
    """Пайплайн синхронизации: ЕЭК, торговая защита, OData, PDF ЕТТ, JSON-фид, CSV-фид, пакет ТН ВЭД."""
    eec = await sync_eec_snapshot()
    trade = await sync_trade_defense()
    odata = await sync_odata_sources()
    ett_pdf = await sync_ett_pdf()
    feed = await sync_rates_feed()
    csv_feed = await sync_csv_feed()
    bundle = await sync_normative_bundle_url()
    tamdoc = await sync_tamdoc_documents()
    tamdoc_targeted = await sync_tamdoc_targeted()
    tamdoc_archive = sync_tamdoc_archive(
        staging_only=os.getenv("TAMDOC_ARCHIVE_STAGING_ONLY", "1").lower() in ("1", "true", "yes"),
        include_non_tariff=os.getenv("TAMDOC_ARCHIVE_INCLUDE_NON_TARIFF", "1").lower() in ("1", "true", "yes"),
        auto_approve_pending=os.getenv("TAMDOC_ARCHIVE_AUTO_APPROVE", "0").lower() in ("1", "true", "yes"),
    )
    trois_sync = await sync_trois_sources()
    sources_result = [eec, trade, odata, ett_pdf, feed, csv_feed, bundle, tamdoc, tamdoc_targeted, tamdoc_archive, trois_sync]
    ok = all(x.get("status") in ("OK", "SKIPPED", "NOT_FOUND") for x in sources_result)
    return {"status": "OK" if ok else "WARNING", "sources": sources_result}
