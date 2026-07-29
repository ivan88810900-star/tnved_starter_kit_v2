"""Deterministic product-description entry into Guided TN VED navigation."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Any

from .tree_engine import CanonicalModel, get_canonical_model

logger = logging.getLogger(__name__)

_DIGITS_RE = re.compile(r"\D")
_LETTER_RE = re.compile(r"[A-Za-zА-Яа-яЁё]")

ModelLoader = Callable[[], CanonicalModel | None]

_MATCH_REASON_PRIORITY = {
    "code_prefix": 5,
    "name_match": 4,
    "domain_dictionary": 3,
    "typo_correction": 2,
    "full_text": 1,
}


def _digits(value: object) -> str:
    return _DIGITS_RE.sub("", str(value or ""))


def _anchor_payload(model: CanonicalModel, node: object) -> dict[str, Any] | None:
    anchor = model.anchor(node)  # type: ignore[arg-type]
    if anchor is None:
        return None
    return {
        "stable_id": anchor.stable_id,
        "snapshot_id": anchor.snapshot_id,
        "code": anchor.code,
        "node_type": anchor.node_type.value,
    }


def build_guided_search_routes(
    query: str,
    search_results: list[dict[str, Any]],
    *,
    limit: int = 4,
    model_loader: ModelLoader = get_canonical_model,
) -> list[dict[str, Any]]:
    """Group lexical hits into Canonical headings that can open Guided navigation.

    Search remains the candidate generator. This helper never classifies a product
    by itself and never calls an external model. Numeric/code-only lookup is kept
    unchanged because the user has already supplied a structural identifier.
    """

    if not _LETTER_RE.search(query or "") or not search_results:
        return []

    try:
        model = model_loader()
    except Exception:
        logger.exception("Guided search entry: CanonicalModel unavailable")
        return []
    if model is None:
        return []

    route_limit = max(1, min(int(limit), 8))
    routes_by_heading: dict[str, dict[str, Any]] = {}
    for rank, result in enumerate(search_results):
        code = _digits(result.get("code"))
        if len(code) < 4:
            continue
        heading = code[:4]
        route = routes_by_heading.get(heading)
        raw_match_reason = str(result.get("match_reason") or "full_text")
        match_reason = (
            raw_match_reason
            if raw_match_reason in _MATCH_REASON_PRIORITY
            else "full_text"
        )
        match_priority = _MATCH_REASON_PRIORITY.get(match_reason, 0)
        if route is not None:
            route["candidate_count"] += 1
            if match_priority > route["_match_priority"]:
                route["best_match_reason"] = match_reason
                route["_match_priority"] = match_priority
            continue

        heading_node = (
            model.get_by_code(heading)
            or model.get_by_display_code(heading)
        )
        if heading_node is None:
            continue
        anchor = _anchor_payload(model, heading_node)
        if anchor is None:
            continue

        routes_by_heading[heading] = {
            "heading": heading,
            "title": heading_node.title,
            "candidate_count": 1,
            "best_match_reason": match_reason,
            "first_result_rank": rank + 1,
            "canonical_anchor": anchor,
            "guided_href": f"/api/v1/tnved/guided/{heading}",
            "_match_priority": match_priority,
        }

    ranked = sorted(
        routes_by_heading.values(),
        key=lambda route: (
            -int(route["_match_priority"]),
            -int(route["candidate_count"]),
            int(route["first_result_rank"]),
            str(route["heading"]),
        ),
    )
    for route in ranked:
        route.pop("_match_priority", None)
    return ranked[:route_limit]
