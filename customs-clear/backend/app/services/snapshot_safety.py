"""Fail-closed validation shared by full-snapshot regulatory importers."""

from __future__ import annotations

import os
import re
from typing import Any


def _env_key(source_id: str, suffix: str) -> str:
    token = re.sub(r"[^A-Z0-9]+", "_", source_id.upper()).strip("_")
    return f"REGULATORY_{token}_{suffix}"


def configured_minimum_rows(source_id: str, default: int) -> int:
    raw = (os.getenv(_env_key(source_id, "MIN_ROWS")) or "").strip()
    try:
        return max(1, int(raw)) if raw else max(1, int(default))
    except ValueError:
        return max(1, int(default))


def configured_max_shrink_fraction(source_id: str, default: float = 0.35) -> float:
    raw = (os.getenv(_env_key(source_id, "MAX_SHRINK_FRACTION")) or "").strip()
    try:
        value = float(raw) if raw else float(default)
    except ValueError:
        value = float(default)
    return min(0.95, max(0.0, value))


def validate_full_snapshot(
    *,
    source_id: str,
    candidate_count: int,
    existing_count: int,
    minimum_rows: int,
    reported_total: int | None = None,
    fetched_count: int | None = None,
    max_shrink_fraction: float | None = None,
) -> dict[str, Any]:
    """Reject empty, incomplete and implausibly shrunken full snapshots.

    A large legitimate deletion is routed to review by failing the automatic
    adapter; operators can adjust the per-source threshold only after checking
    the official artifact.
    """
    candidate_count = max(0, int(candidate_count))
    existing_count = max(0, int(existing_count))
    minimum_rows = max(1, int(minimum_rows))
    shrink_limit = (
        configured_max_shrink_fraction(source_id)
        if max_shrink_fraction is None
        else min(0.95, max(0.0, float(max_shrink_fraction)))
    )

    errors: list[str] = []
    if candidate_count < minimum_rows:
        errors.append(
            f"candidate_rows={candidate_count} below minimum_rows={minimum_rows}"
        )
    if reported_total is not None and fetched_count is not None:
        if int(fetched_count) != int(reported_total):
            errors.append(
                f"fetched_rows={int(fetched_count)} does not match reported_total={int(reported_total)}"
            )
    if existing_count >= minimum_rows:
        minimum_after_shrink = int(existing_count * (1.0 - shrink_limit))
        if candidate_count < minimum_after_shrink:
            errors.append(
                f"candidate_rows={candidate_count} shrank more than "
                f"{shrink_limit:.0%} from existing_rows={existing_count}"
            )

    result = {
        "source_id": source_id,
        "candidate_rows": candidate_count,
        "existing_rows": existing_count,
        "minimum_rows": minimum_rows,
        "max_shrink_fraction": shrink_limit,
        "reported_total": reported_total,
        "fetched_rows": fetched_count,
        "valid": not errors,
        "errors": errors,
    }
    if errors:
        raise RuntimeError(
            f"{source_id} full snapshot rejected; live data preserved: "
            + "; ".join(errors)
        )
    return result
