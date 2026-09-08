"""Единый APScheduler: безопасные обновления реестров и мониторинг источников."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

_scheduler: AsyncIOScheduler | None = None

_REGULATORY_JOB_IDS: tuple[tuple[str, str], ...] = (
    ("daily", "regulatory_sources_daily"),
    ("weekly", "regulatory_sources_weekly"),
    ("monthly", "regulatory_sources_monthly"),
)


def get_scheduler() -> AsyncIOScheduler | None:
    return _scheduler


def is_scheduler_running() -> bool:
    sch = _scheduler
    return sch is not None and sch.running


def regulatory_job_next_run_iso() -> str | None:
    """Backward-compatible next daily run used by the legacy sync status API."""
    sch = _scheduler
    if sch is None:
        return None
    job = sch.get_job("regulatory_sources_daily")
    if job is None or job.next_run_time is None:
        return None
    nr = job.next_run_time
    if nr.tzinfo is None:
        return nr.replace(tzinfo=timezone.utc).isoformat()
    return nr.isoformat()


def regulatory_jobs_status() -> dict[str, dict[str, str | None]]:
    """Return scheduler state for every regulatory update cadence."""
    sch = _scheduler
    rows: dict[str, dict[str, str | None]] = {}
    for cadence, job_id in _REGULATORY_JOB_IDS:
        next_run: str | None = None
        if sch is not None:
            job = sch.get_job(job_id)
            if job is not None and job.next_run_time is not None:
                value = job.next_run_time
                if value.tzinfo is None:
                    value = value.replace(tzinfo=timezone.utc)
                next_run = value.isoformat()
        rows[cadence] = {"job_id": job_id, "next_run_at": next_run}
    return rows


def start_apscheduler() -> None:
    """Старт планировщика вместе с приложением (lifespan)."""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        return

    jobs: list[str] = []

    regulatory_on = os.getenv("REGULATORY_SYNC_SCHEDULER_ENABLED", "true").lower() in ("1", "true", "yes")
    legacy_on = os.getenv("SCHEDULER_ENABLED", "").lower() in ("1", "true", "yes")

    if regulatory_on and legacy_on:
        raise RuntimeError(
            "REGULATORY_SYNC_SCHEDULER_ENABLED and legacy SCHEDULER_ENABLED "
            "must not be enabled in the same process"
        )

    if not regulatory_on and not legacy_on:
        logger.info("APScheduler: все задачи отключены (REGULATORY_SYNC_SCHEDULER_ENABLED и SCHEDULER_ENABLED)")
        return

    sch = AsyncIOScheduler()
    _scheduler = sch

    if regulatory_on:
        async def _run_source_updates(cadence: str) -> None:
            try:
                from .regulatory_source_updates import run_regulatory_update_cycle

                result = await run_regulatory_update_cycle(cadence, apply_safe=True)  # type: ignore[arg-type]
                if result.get("status") not in {"ok", "review_required"}:
                    raise RuntimeError(
                        f"regulatory update cycle returned {result.get('status')}: "
                        f"{result.get('error') or result.get('errors') or 'adapter failure'}"
                    )
                log = logger.warning if result.get("status") == "review_required" else logger.info
                log(
                    "Regulatory source updates {}: status={}, adapters={}, pending_reviews={}",
                    cadence,
                    result.get("status"),
                    len(result.get("results") or []),
                    len(result.get("review_required_source_ids") or []),
                )
            except Exception as e:
                logger.exception("Regulatory source updates {} failed: {}", cadence, e)
                raise

        tz_name = os.getenv("REGULATORY_SYNC_TZ", "Europe/Moscow").strip() or "Europe/Moscow"
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            logger.warning(f"REGULATORY_SYNC_TZ={tz_name!r} недоступен, используем Europe/Moscow")
            tz = ZoneInfo("Europe/Moscow")

        sch.add_job(
            _run_source_updates,
            CronTrigger(hour=3, minute=0, timezone=tz),
            args=["daily"],
            id="regulatory_sources_daily",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )
        jobs.append("regulatory_sources_daily@03:00")

        # Daily adapters have a bounded default worst case of three hours.
        # Keeping the weekly pass five hours later prevents normal calendar
        # overlap; the cross-process file lock in run_regulatory_update_cycle
        # remains the fail-closed guard if an upstream source stalls longer.
        sch.add_job(
            _run_source_updates,
            CronTrigger(day_of_week="sun", hour=8, minute=0, timezone=tz),
            args=["weekly"],
            id="regulatory_sources_weekly",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )
        jobs.append("regulatory_sources_weekly@Sun 08:00")

        # Monthly is a reconciliation/review-due pass. It is deliberately
        # separated from both data-writing windows, including when the first
        # day of a month is Sunday.
        sch.add_job(
            _run_source_updates,
            CronTrigger(day=1, hour=13, minute=0, timezone=tz),
            args=["monthly"],
            id="regulatory_sources_monthly",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )
        jobs.append("regulatory_sources_monthly@day 1 13:00")

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
