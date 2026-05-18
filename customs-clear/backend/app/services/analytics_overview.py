"""Сводная аналитика для дашборда: БД, ИИ, журналы, ФСА — одним запросом."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List

from sqlalchemy import text

from ..db import engine
from .calculation_history_service import summarize_calculation_history
from .decision_history import compute_journal_stats
from .embedding_service import embeddings_stats
from .normative_store import (
    get_integrated_data_stats,
    get_normative_data_hints,
    list_source_status,
)
from .permits_jobs import permits_verify_jobs_counts_by_status
from .ved_intel_jobs import ved_intel_jobs_counts_by_status
from .permits_metrics import get_permits_metrics
from .trois_service import get_trois_local_cache_stats


def _normative_sync_summary() -> dict[str, Any]:
    rows = list_source_status()
    times: list[str] = []
    for r in rows:
        sa = r.get("synced_at")
        if isinstance(sa, str) and sa.strip():
            times.append(sa)
    latest = max(times) if times else None
    stale = sum(1 for r in rows if r.get("fallback"))
    return {
        "sources_count": len(rows),
        "latest_sync_iso": latest,
        "stale_or_fallback_count": stale,
    }


def _ai_configuration() -> dict[str, Any]:
    try:
        from .onnx_hs_classifier import is_onnx_classifier_configured

        onnx_hs = bool(is_onnx_classifier_configured())
    except Exception:
        onnx_hs = False
    return {
        "gemini_configured": bool(
            (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
        ),
        "anthropic_configured": bool(os.getenv("ANTHROPIC_API_KEY", "").strip()),
        "openai_embeddings_configured": bool(os.getenv("OPENAI_API_KEY", "").strip()),
        "onnx_hs_classifier_configured": onnx_hs,
        "custom_classifier_enabled": os.getenv("CUSTOM_CLASSIFIER_ENABLED", "").lower()
        in ("1", "true", "yes")
        and bool(os.getenv("CUSTOM_CLASSIFIER_URL", "").strip()),
        "redis_url_set": bool(os.getenv("REDIS_URL", "").strip()),
        "scheduler_enabled": os.getenv("SCHEDULER_ENABLED", "").lower() in ("1", "true", "yes"),
        "rag_docs_dir_set": bool(os.getenv("RAG_DOCS_DIR", "").strip()),
        "fsa_proxy_configured": bool(os.getenv("FSA_EXTERNAL_API_URL", "").strip()),
    }


def _database_ok() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def _build_narrative_brief_ru(
    *,
    stats: dict[str, Any],
    hints: list[dict[str, Any]],
    ai: dict[str, Any],
) -> list[str]:
    """Короткие пункты для сводки; детальные счётчики — на фронте в «Расширенной диагностике»."""
    out: list[str] = []

    if not ai.get("gemini_configured") and not ai.get("anthropic_configured"):
        out.append(
            "ИИ (LLM) не настроен: в backend/.env задайте GEMINI_API_KEY или GOOGLE_API_KEY, либо ANTHROPIC_API_KEY."
        )
    else:
        parts = []
        if ai.get("gemini_configured"):
            parts.append("Gemini")
        if ai.get("anthropic_configured"):
            parts.append("Claude")
        out.append("ИИ: " + ", ".join(parts) + ".")

    if ai.get("onnx_hs_classifier_configured"):
        out.append("Локальный ONNX-классификатор ТН ВЭД включён.")
    if ai.get("custom_classifier_enabled"):
        out.append("Внешний HTTP-классификатор включён.")

    ns = stats.get("normative_sync_summary") if isinstance(stats, dict) else None
    if isinstance(ns, dict) and int(ns.get("stale_or_fallback_count") or 0) > 0:
        out.append(
            f"Нормативка: {ns.get('stale_or_fallback_count')} источник(ов) с пометкой fallback/устаревание."
        )

    if stats.get("tnved_entries_count", 0) == 0:
        out.append(
            "Справочник ТН ВЭД в базе пуст — импортируйте пакет данных (см. NORMATIVE_PIPELINE.md)."
        )

    if stats.get("hs_rates_count", 0) < 30:
        out.append("В hs_rates мало строк — для платежей загрузите актуальные ставки ЕТТ.")

    for h in hints:
        if h.get("level") == "warning" and h.get("text"):
            out.append(str(h["text"]))

    if ai.get("scheduler_enabled"):
        out.append("Планировщик синхронизации нормативки включён (SCHEDULER_ENABLED).")

    if not ai.get("redis_url_set"):
        out.append("Без REDIS_URL кэш только в памяти процесса.")

    if not out:
        out.append("Ключевые подсистемы в рабочем состоянии.")
    return out


def build_analytics_overview() -> dict[str, Any]:
    """Синхронная сборка (БД-запросы внутри); вызывать из async-роута через asyncio.to_thread при необходимости."""
    integrated_stats = get_integrated_data_stats()
    normative_sync_summary = _normative_sync_summary()
    normative_sources_preview = list_source_status()[:40]
    stats_for_narrative = {**integrated_stats, "normative_sync_summary": normative_sync_summary}
    hints = get_normative_data_hints()
    hist_summary = summarize_calculation_history()
    journal = compute_journal_stats()
    ai = _ai_configuration()
    permits_m = get_permits_metrics()
    job_counts = permits_verify_jobs_counts_by_status()
    ved_job_counts = ved_intel_jobs_counts_by_status()
    trois = get_trois_local_cache_stats()
    emb = embeddings_stats()
    narrative = _build_narrative_brief_ru(stats=stats_for_narrative, hints=hints, ai=ai)
    now = datetime.now(timezone.utc)
    return {
        "status": "OK",
        "generated_at": now.isoformat(),
        "database_reachable": _database_ok(),
        "integrated_stats": integrated_stats,
        "normative_sync_summary": normative_sync_summary,
        "normative_sources_preview": normative_sources_preview,
        "normative_hints": hints,
        "calculation_history_summary": hist_summary,
        "decisions_journal": journal,
        "ai_configuration": ai,
        "permits_metrics": permits_m,
        "permits_async_jobs_by_status": job_counts,
        "ved_intel_async_jobs_by_status": ved_job_counts,
        "trois": trois,
        "embeddings": emb,
        "narrative_brief_ru": narrative,
    }
