"""Оптимизированная пакетная классификация строк пакинг-листа."""

from __future__ import annotations

import asyncio
import os
from typing import Any, Callable, Awaitable

from loguru import logger

from .packing_list_parser import PackingRow
from .smart_classifier import ClassifyResult, SmartClassifier, get_smart_classifier

ProgressCallback = Callable[[int, int], Awaitable[None] | None]

DEFAULT_CONCURRENCY = int(os.getenv("PACKING_CLASSIFY_CONCURRENCY", "8"))


def _group_key(snap: dict[str, Any]) -> tuple[str, str]:
    return (
        (snap.get("name_cn") or "").strip(),
        (snap.get("material") or "").strip(),
    )


def _desc_for_row(snap: dict[str, Any]) -> str:
    parts = [p for p in (snap.get("name_cn"), snap.get("material")) if p]
    return " ".join(parts)


def _classify_result_to_item(
    snap: dict[str, Any],
    full: PackingRow | None,
    clf: ClassifyResult,
) -> dict[str, Any]:
    item = dict(snap)
    item["image_path"] = str(full.image_path) if full and full.image_path else None
    api = clf.to_api_dict()
    item["translation_used"] = api.get("translation_used") or ""
    item["visual_analysis"] = api.get("visual_analysis")
    item["classify_status"] = api.get("status")
    top = (api.get("results") or [{}])[0] if api.get("results") else {}
    item["hs_code"] = top.get("hs_code")
    item["hs_confidence"] = top.get("confidence")
    item["hs_description"] = top.get("description")
    item["hs_rationale"] = top.get("rationale")
    item["classify_results"] = api.get("results") or []
    if api.get("note"):
        item["classify_note"] = api.get("note")
    return item


async def _invoke_progress(cb: ProgressCallback | None, done: int, total: int) -> None:
    if cb is None:
        return
    maybe = cb(done, total)
    if asyncio.iscoroutine(maybe):
        await maybe


async def classify_packing_rows_optimized(
    rows_snapshot: list[dict[str, Any]],
    images_by_row: dict[int, PackingRow],
    *,
    classifier: SmartClassifier | None = None,
    max_concurrent: int | None = None,
    on_progress: ProgressCallback | None = None,
) -> list[dict[str, Any]]:
    """
    Батч-перевод, dedupe Vision/классификации по (name_cn, material),
    параллельная обработка групп с ограничением concurrency.
    """
    if not rows_snapshot:
        return []

    clf = classifier or get_smart_classifier()
    concurrency = max(1, min(max_concurrent or DEFAULT_CONCURRENCY, 20))
    semaphore = asyncio.Semaphore(concurrency)

    descriptions = [_desc_for_row(s) for s in rows_snapshot]
    await clf.prepare_translations(descriptions)

    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for snap in rows_snapshot:
        groups.setdefault(_group_key(snap), []).append(snap)

    total_rows = len(rows_snapshot)
    results_by_row: dict[int, dict[str, Any]] = {}
    done_rows = 0

    async def _process_group(key: tuple[str, str], snaps: list[dict[str, Any]]) -> None:
        nonlocal done_rows
        async with semaphore:
            leader = snaps[0]
            row_num = int(leader["row_num"])
            full = images_by_row.get(row_num)
            img_b64 = full.image_base64 if full else None
            desc = _desc_for_row(leader)
            translated = await clf.translate_cached(desc)

            try:
                visual = await clf.get_or_analyze_vision(
                    key,
                    image_base64=img_b64,
                    description=translated,
                )
                group_result = await clf.get_or_classify_group(
                    key,
                    description=desc,
                    translated=translated,
                    visual_context=visual,
                    article=leader.get("article"),
                )
            except Exception as exc:
                logger.warning(f"packing group {key}: {exc}")
                group_result = ClassifyResult(
                    results=[],
                    translation_used=translated,
                    status="ERROR",
                    note=str(exc),
                )
                visual = None

            for snap in snaps:
                rn = int(snap["row_num"])
                row_full = images_by_row.get(rn) or full
                item = _classify_result_to_item(snap, row_full, group_result)
                if visual and not item.get("visual_analysis"):
                    item["visual_analysis"] = visual
                results_by_row[rn] = item

            done_rows += len(snaps)
            await _invoke_progress(on_progress, done_rows, total_rows)

    await asyncio.gather(*[_process_group(k, v) for k, v in groups.items()])

    ordered: list[dict[str, Any]] = []
    for snap in rows_snapshot:
        rn = int(snap["row_num"])
        ordered.append(results_by_row[rn])
    return ordered
