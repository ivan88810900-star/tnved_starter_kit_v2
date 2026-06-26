"""Единый APScheduler (AsyncIO): ежедневная нормативная синхронизация и опционально полный sync источников."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler | None:
    return _scheduler


def is_scheduler_running() -> bool:
    sch = _scheduler
    return sch is not None and sch.running


def regulatory_job_next_run_iso() -> str | None:
    sch = _scheduler
    if sch is None:
        return None
    job = sch.get_job("sync_daily_regulatory_data")
    if job is None or job.next_run_time is None:
        return None
    nr = job.next_run_time
    if nr.tzinfo is None:
        return nr.replace(tzinfo=timezone.utc).isoformat()
    return nr.isoformat()


def start_apscheduler() -> None:
    """Старт планировщика вместе с приложением (lifespan)."""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        return

    jobs: list[dict[str, Any]] = []

    regulatory_on = os.getenv("REGULATORY_SYNC_SCHEDULER_ENABLED", "true").lower() in ("1", "true", "yes")
    legacy_on = os.getenv("SCHEDULER_ENABLED", "").lower() in ("1", "true", "yes")

    if not regulatory_on and not legacy_on:
        logger.info("APScheduler: все задачи отключены (REGULATORY_SYNC_SCHEDULER_ENABLED и SCHEDULER_ENABLED)")
        return

    sch = AsyncIOScheduler()
    _scheduler = sch

    if regulatory_on:

        async def _sync_daily_regulatory_data() -> None:
            try:
                from .sync_engine import sync_daily_regulatory_data

                await sync_daily_regulatory_data(trigger="scheduled")
            except Exception as e:
                logger.exception(f"sync_daily_regulatory_data: {e}")

        async def _refresh_currency_rates() -> None:
            try:
                from .exchange_rates import update_exchange_rates_from_cbrf

                result = await update_exchange_rates_from_cbrf()
                logger.info(f"Currency refresh: source={result.get('source')}, updated={result.get('updated')}")
            except Exception as e:
                logger.exception(f"Currency refresh failed: {e}")

        tz_name = os.getenv("REGULATORY_SYNC_TZ", "Europe/Moscow").strip() or "Europe/Moscow"
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            logger.warning(f"REGULATORY_SYNC_TZ={tz_name!r} недоступен, используем Europe/Moscow")
            tz = ZoneInfo("Europe/Moscow")

        sch.add_job(
            _sync_daily_regulatory_data,
            CronTrigger(hour=3, minute=0, timezone=tz),
            id="sync_daily_regulatory_data",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        jobs.append("sync_daily_regulatory_data@03:00")

        sch.add_job(
            _refresh_currency_rates,
            CronTrigger(hour=9, minute=0, timezone=tz),
            id="refresh_currency_rates_daily",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        jobs.append("refresh_currency_rates@09:00")

    if legacy_on:
        from .source_sync import sync_all_sources

        hours = float(os.getenv("SCHEDULER_SYNC_INTERVAL_HOURS", "24"))

        async def _normative_full_sync() -> None:
            try:
                logger.info("Планировщик: запуск sync_all_sources")
                await sync_all_sources()
            except Exception as e:
                logger.exception(f"Планировщик: ошибка sync_all_sources: {e}")

        sch.add_job(
            _normative_full_sync,
            "interval",
            hours=hours,
            id="normative_full_sync",
            replace_existing=True,
        )
        jobs.append(f"normative_full_sync каждые {hours} ч")

    sch.start()
    logger.info(f"APScheduler запущен: {', '.join(jobs)}")


def shutdown_apscheduler() -> None:
    global _scheduler
    if _scheduler is None:
        return
    try:
        _scheduler.shutdown(wait=False)
    except Exception:
        pass
    _scheduler = None


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
