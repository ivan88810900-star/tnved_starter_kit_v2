#!/usr/bin/env python3
"""
Единый планировщик фоновых краулеров (Law.TKS, нетарифка TKS, IFCG, курсы ЦБ, реестры ФСБ/РЭС, СГР).

Запуск из каталога ``customs-clear/backend``::

  python3 scripts/auto_updater.py

Переменные окружения (``.env`` / shell) пробрасываются в дочерние процессы;
дополнительно выставляется ``PYTHONPATH`` на корень backend.
"""

from __future__ import annotations

import argparse
import logging
import os
import shlex
import subprocess
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = BACKEND_ROOT / "scripts"
LOG_DIR = BACKEND_ROOT / "logs"
LOG_FILE = LOG_DIR / "updater.log"

# Главы ТН ВЭД 01–97 для ежемесячной докачки IFCG, кроме 77 (резервная пустая глава).
IFCG_MONTHLY_CHAPTERS = [f"{i:02d}" for i in range(1, 98) if i != 77]
IFCG_MAX_CODES_PER_CHAPTER = 500


def _child_env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(BACKEND_ROOT)
    return env


def _setup_logging() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("auto_updater")
    log.setLevel(logging.INFO)
    log.handlers.clear()

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    fh = RotatingFileHandler(
        LOG_FILE,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    fh.setFormatter(fmt)
    log.addHandler(fh)

    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    log.addHandler(ch)

    return log


LOG = _setup_logging()


def _stream_output(pipe, prefix: str) -> None:
    try:
        for line in iter(pipe.readline, ""):
            if not line:
                break
            line = line.rstrip("\n\r")
            LOG.info("%s %s", prefix, line)
            print(f"{prefix} {line}", flush=True)
    finally:
        pipe.close()


def run_subprocess(
    script: str,
    args: list[str],
    *,
    job_id: str,
    timeout_sec: float | None = None,
) -> int:
    """
    Запуск ``python <script>`` в изолированном процессе.
    stdout/stderr дочернего процесса дублируются в лог и консоль.
    """
    script_path = SCRIPTS_DIR / script
    if not script_path.is_file():
        LOG.error("Файл скрипта не найден: %s", script_path)
        return 127

    cmd = [sys.executable, str(script_path), *args]
    cmd_display = " ".join(shlex.quote(c) for c in cmd)
    LOG.info("[%s] START cwd=%s", job_id, BACKEND_ROOT)
    LOG.info("[%s] CMD %s", job_id, cmd_display)

    proc = subprocess.Popen(
        cmd,
        cwd=str(BACKEND_ROOT),
        env=_child_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    t = threading.Thread(
        target=_stream_output,
        args=(proc.stdout, f"[{job_id}]"),
        daemon=True,
    )
    t.start()

    try:
        rc = proc.wait(timeout=timeout_sec)
    except subprocess.TimeoutExpired:
        LOG.error("[%s] timeout после %.0f с, завершаю процесс", job_id, timeout_sec or 0)
        proc.kill()
        proc.wait(timeout=60)
        return 124

    t.join(timeout=5)
    if rc == 0:
        LOG.info("[%s] DONE exit=0", job_id)
    else:
        LOG.error("[%s] DONE exit=%s", job_id, rc)
    return int(rc)


def job_sync_law_full() -> None:
    run_subprocess("sync_law_full.py", [], job_id="law_daily")


def job_sync_tks_nontariff() -> None:
    run_subprocess(
        "sync_tks_nontariff.py",
        ["--all-chapters", "--workers", "4"],
        job_id="nontariff_weekly",
    )


def job_update_rates() -> None:
    run_subprocess("update_rates.py", [], job_id="rates_daily", timeout_sec=600)


def job_sync_eco_fees() -> None:
    run_subprocess("sync_eco_fees.py", [], job_id="eco_fees_monthly", timeout_sec=3600)


def job_sync_state_registries() -> None:
    run_subprocess("sync_state_registries.py", [], job_id="state_registries_weekly", timeout_sec=3600)


def job_sync_sgr_registry() -> None:
    run_subprocess("sync_sgr_registry.py", [], job_id="sgr_registry_weekly", timeout_sec=7200)


def job_sync_ifcg_monthly() -> None:
    """
    1-го числа: по очереди главы 01–97 (без 77), каждая в своём subprocess.
    """
    for ch in IFCG_MONTHLY_CHAPTERS:
        jid = f"ifcg_monthly_{ch}"
        run_subprocess(
            "sync_ifcg_examples.py",
            ["--chapter", ch, "--max-codes", str(IFCG_MAX_CODES_PER_CHAPTER)],
            job_id=jid,
        )


def build_scheduler() -> BlockingScheduler:
    sch = BlockingScheduler(timezone=os.environ.get("TZ", "Europe/Moscow"))

    # Ежедневно 02:00 — законы TKS
    sch.add_job(
        job_sync_law_full,
        CronTrigger(hour=2, minute=0),
        id="sync_law_full_daily",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )

    # Воскресенье 03:00 — нетарифные меры по всем главам
    sch.add_job(
        job_sync_tks_nontariff,
        CronTrigger(day_of_week="sun", hour=3, minute=0),
        id="sync_tks_nontariff_weekly",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )

    # 1-го числа 04:00 — примеры IFCG (не пересекается с воскресным 03:00 по смыслу)
    sch.add_job(
        job_sync_ifcg_monthly,
        CronTrigger(day=1, hour=4, minute=0),
        id="sync_ifcg_monthly",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )

    # 1-го числа 05:30 — тарифы экосбора (РОП), в т.ч. под новый год после публикации ПП
    sch.add_job(
        job_sync_eco_fees,
        CronTrigger(day=1, hour=5, minute=30),
        id="sync_eco_fees_monthly",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )

    # Ежедневно 09:00 — курсы валют (ЦБ РФ)
    sch.add_job(
        job_update_rates,
        CronTrigger(hour=9, minute=0),
        id="update_rates_daily",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )

    # Понедельник 06:30 — нотификации ФСБ и реестр РЭС (CSV по URL из .env или пропуск)
    sch.add_job(
        job_sync_state_registries,
        CronTrigger(day_of_week="mon", hour=6, minute=30),
        id="sync_state_registries_weekly",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )

    # Воскресенье 04:30 — реестр СГР (OData/CSV; объём большой — отдельный subprocess)
    sch.add_job(
        job_sync_sgr_registry,
        CronTrigger(day_of_week="sun", hour=4, minute=30),
        id="sync_sgr_registry_weekly",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )

    return sch


def main() -> int:
    ap = argparse.ArgumentParser(description="Планировщик краулеров backend")
    ap.add_argument(
        "--run-once",
        choices=("law", "nontariff", "ifcg", "rates", "ifcg-one", "eco", "registries", "sgr"),
        help="Один прогон выбранной задачи и выход (без расписания)",
    )
    ap.add_argument(
        "--ifcg-chapter",
        type=str,
        default="64",
        metavar="NN",
        help="С --run-once ifcg-one: одна глава для проверки",
    )
    args = ap.parse_args()

    if args.run_once == "law":
        return run_subprocess("sync_law_full.py", [], job_id="law_once")
    if args.run_once == "nontariff":
        return run_subprocess(
            "sync_tks_nontariff.py",
            ["--all-chapters", "--workers", "4"],
            job_id="nontariff_once",
        )
    if args.run_once == "ifcg":
        job_sync_ifcg_monthly()
        return 0
    if args.run_once == "ifcg-one":
        return run_subprocess(
            "sync_ifcg_examples.py",
            [
                "--chapter",
                args.ifcg_chapter,
                "--max-codes",
                str(IFCG_MAX_CODES_PER_CHAPTER),
            ],
            job_id=f"ifcg_once_{args.ifcg_chapter}",
        )
    if args.run_once == "rates":
        return run_subprocess("update_rates.py", [], job_id="rates_once", timeout_sec=600)
    if args.run_once == "eco":
        return run_subprocess("sync_eco_fees.py", [], job_id="eco_once", timeout_sec=3600)
    if args.run_once == "registries":
        return run_subprocess("sync_state_registries.py", [], job_id="registries_once", timeout_sec=3600)
    if args.run_once == "sgr":
        return run_subprocess("sync_sgr_registry.py", [], job_id="sgr_once", timeout_sec=7200)

    LOG.info("Планировщик стартовал; лог: %s", LOG_FILE)
    LOG.info(
        "Расписание: law 02:00 daily | nontariff Sun 03:00 | sgr Sun 04:30 | IFCG 1st 04:00 | eco fees 1st 05:30 | registries Mon 06:30 | rates 09:00 (timezone=%s)",
        os.environ.get("TZ", "Europe/Moscow"),
    )
    sch = build_scheduler()
    try:
        sch.start()
    except (KeyboardInterrupt, SystemExit):
        LOG.info("Останов по сигналу пользователя")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
