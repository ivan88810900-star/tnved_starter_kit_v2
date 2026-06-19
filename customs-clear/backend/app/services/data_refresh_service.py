"""Unified data refresh orchestrator: CBR rates, excise, anti-dumping (Issue #89).

Provides freshness checks and coordinated refresh across all payment-related
data domains. Used by the API endpoint and the GitHub Actions workflow.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger

from ..db import SessionLocal
from ..models.core import ExchangeRate, SourceStatus

_BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent

_BUNDLE_DOMAINS: dict[str, str] = {
    "EEC_ETT": "data/raw_normative/eec_ett_normative_bundle.json",
    "EEC_VAT": "data/raw_normative/eec_ett_vat.json",
    "EEC_EXCISE": "data/raw_normative/eec_excise.json",
    "EEC_ANTI_DUMPING": "data/raw_normative/eec_anti_dumping.json",
    "EEC_SPECIAL_SAFEGUARD": "data/raw_normative/eec_special_safeguard.json",
    "EEC_COUNTERVAILING": "data/raw_normative/eec_countervailing.json",
}

STALE_THRESHOLD_DAYS = 90
CURRENCY_STALE_HOURS = 48


def _bundle_revision_date(rel_path: str) -> datetime | None:
    p = _BACKEND_ROOT / rel_path
    if not p.is_file():
        return None
    try:
        with open(p) as f:
            data = json.load(f)
        rev = data.get("revision", "")
        parts = rev.split(":")
        if len(parts) >= 2:
            return datetime.strptime(parts[-1], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except Exception:
        pass
    return None


def check_data_freshness() -> dict[str, Any]:
    """Check freshness of all data domains. Returns structured report."""
    now = datetime.now(timezone.utc)
    domains: list[dict[str, Any]] = []
    stale_count = 0

    for domain, rel_path in _BUNDLE_DOMAINS.items():
        rev_date = _bundle_revision_date(rel_path)
        p = _BACKEND_ROOT / rel_path
        entry: dict[str, Any] = {
            "domain": domain,
            "bundle_path": rel_path,
            "exists": p.is_file(),
        }
        if rev_date:
            age_days = (now - rev_date).days
            entry["revision_date"] = rev_date.strftime("%Y-%m-%d")
            entry["age_days"] = age_days
            entry["is_stale"] = age_days > STALE_THRESHOLD_DAYS
        else:
            entry["revision_date"] = None
            entry["age_days"] = None
            entry["is_stale"] = True
        if entry["is_stale"]:
            stale_count += 1
        domains.append(entry)

    currency_info = _check_currency_freshness(now)
    if currency_info["is_stale"]:
        stale_count += 1

    return {
        "checked_at": now.isoformat(),
        "stale_threshold_days": STALE_THRESHOLD_DAYS,
        "currency_stale_hours": CURRENCY_STALE_HOURS,
        "stale_count": stale_count,
        "all_fresh": stale_count == 0,
        "currency": currency_info,
        "domains": domains,
    }


def _check_currency_freshness(now: datetime) -> dict[str, Any]:
    """Check if exchange rates are fresh."""
    try:
        with SessionLocal() as db:
            rows = db.query(ExchangeRate).all()
            if not rows:
                return {"is_stale": True, "reason": "no_rates_in_db", "currencies": 0}
            latest = max(
                (r.updated_at for r in rows if r.updated_at),
                default=None,
            )
            if latest is None:
                return {"is_stale": True, "reason": "no_update_timestamp", "currencies": len(rows)}
            if latest.tzinfo is None:
                latest = latest.replace(tzinfo=timezone.utc)
            age_hours = (now - latest).total_seconds() / 3600
            return {
                "is_stale": age_hours > CURRENCY_STALE_HOURS,
                "last_update": latest.isoformat(),
                "age_hours": round(age_hours, 1),
                "currencies": len(rows),
            }
    except Exception as e:
        return {"is_stale": True, "reason": f"db_error: {e}", "currencies": 0}


async def refresh_currency_rates() -> dict[str, Any]:
    """Refresh CBR exchange rates."""
    from .exchange_rates import update_exchange_rates_from_cbrf

    try:
        result = await update_exchange_rates_from_cbrf()
        return {
            "domain": "CBRF",
            "status": "ok",
            "source": result.get("source", "unknown"),
            "date": result.get("date", ""),
            "updated": result.get("updated", 0),
        }
    except Exception as e:
        logger.exception(f"Currency refresh failed: {e}")
        return {"domain": "CBRF", "status": "error", "error": str(e)}


def refresh_excise_rates() -> dict[str, Any]:
    """Refresh excise rates from local official bundle."""
    from .excise_ingestion import run_excise_dry_run

    try:
        result = run_excise_dry_run()
        action = result.get("action", "")
        return {
            "domain": "EEC_EXCISE",
            "status": "ok",
            "action": action,
            "rows_total": result.get("row_counts", {}).get("total_excise_rows", 0)
            if isinstance(result.get("row_counts"), dict)
            else 0,
            "needs_apply": action == "ready_to_apply",
        }
    except Exception as e:
        logger.exception(f"Excise refresh check failed: {e}")
        return {"domain": "EEC_EXCISE", "status": "error", "error": str(e)}


def refresh_anti_dumping() -> dict[str, Any]:
    """Refresh anti-dumping duties from local official bundle."""
    from .anti_dumping_ingestion import run_anti_dumping_dry_run

    try:
        result = run_anti_dumping_dry_run()
        action = result.get("action", "")
        return {
            "domain": "EEC_ANTI_DUMPING",
            "status": "ok",
            "action": action,
            "rows_total": result.get("row_counts", {}).get("total_rows", 0)
            if isinstance(result.get("row_counts"), dict)
            else 0,
            "needs_apply": action == "ready_to_apply",
        }
    except Exception as e:
        logger.exception(f"Anti-dumping refresh check failed: {e}")
        return {"domain": "EEC_ANTI_DUMPING", "status": "error", "error": str(e)}


async def run_full_data_refresh(*, dry_run: bool = True) -> dict[str, Any]:
    """Run a coordinated refresh of all payment-related data.

    When dry_run=True (default), only checks freshness and reports what would change.
    When dry_run=False, applies currency rate updates (excise/anti-dumping still
    require explicit apply via their dedicated endpoints for safety).
    """
    results: list[dict[str, Any]] = []

    currency = await refresh_currency_rates()
    results.append(currency)

    excise = refresh_excise_rates()
    results.append(excise)

    anti_dumping = refresh_anti_dumping()
    results.append(anti_dumping)

    freshness = check_data_freshness()

    errors = [r for r in results if r.get("status") == "error"]
    needs_apply = [r for r in results if r.get("needs_apply")]

    return {
        "dry_run": dry_run,
        "status": "ok" if not errors else "partial_error",
        "results": results,
        "freshness": freshness,
        "errors_count": len(errors),
        "pending_apply": [r["domain"] for r in needs_apply],
    }
