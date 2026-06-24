"""Асинхронные задачи классификации пакинг-листов (Redis + in-memory fallback)."""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from loguru import logger
from starlette.background import BackgroundTasks

from .cache_layer import cache_get, cache_set
from .packing_list_export import export_classified_packing_list
from .packing_list_parser import parse_packing_list
from .smart_classifier import get_smart_classifier

TASK_PREFIX = "cc:packing:task:"
TASK_TTL = int(os.getenv("PACKING_TASK_TTL_SECONDS", str(24 * 3600)))
TASK_BASE_DIR = Path(os.getenv("PACKING_TASK_DIR", "/tmp/packing_tasks"))
AVG_ROW_SECONDS = float(os.getenv("PACKING_TASK_AVG_ROW_SECONDS", "25"))


def _now() -> float:
    return time.time()


def _task_dir(task_id: str) -> Path:
    return TASK_BASE_DIR / task_id


def _strip_heavy_fields(item: dict[str, Any]) -> dict[str, Any]:
    out = dict(item)
    out.pop("image_base64", None)
    return out


async def _save_task(task_id: str, payload: dict[str, Any]) -> None:
    await cache_set(TASK_PREFIX, task_id, payload, ttl=TASK_TTL)


async def get_task(task_id: str) -> dict[str, Any] | None:
    raw = await cache_get(TASK_PREFIX, task_id)
    return raw if isinstance(raw, dict) else None


def _eta_seconds(processed: int, total: int, started_at: float) -> int | None:
    if processed <= 0 or total <= 0:
        return int(total * AVG_ROW_SECONDS)
    elapsed = max(_now() - started_at, 0.1)
    rate = processed / elapsed
    remaining = max(total - processed, 0)
    return int(remaining / rate) if rate > 0 else None


def task_status_payload(task: dict[str, Any]) -> dict[str, Any]:
    processed = int(task.get("processed") or 0)
    total = int(task.get("total_rows") or 0)
    started_at = float(task.get("started_at") or _now())
    out: dict[str, Any] = {
        "task_id": task.get("task_id"),
        "status": task.get("status"),
        "processed": processed,
        "total": total,
        "original_filename": task.get("original_filename"),
        "meta": task.get("meta"),
    }
    if task.get("status") == "processing":
        out["eta_seconds"] = _eta_seconds(processed, total, started_at)
    if task.get("status") == "done":
        out["export_ready"] = bool(task.get("export_path"))
        out["rows_with_images"] = (task.get("meta") or {}).get("rows_with_images")
    if task.get("status") == "error":
        out["error"] = task.get("error")
    return out


async def create_packing_list_task(
    *,
    file_bytes: bytes,
    original_filename: str,
    background_tasks: BackgroundTasks,
    classify: bool = True,
    max_rows: int | None = None,
    start_row: int = 1,
) -> dict[str, Any]:
    task_id = uuid4().hex[:12]
    task_path = _task_dir(task_id)
    task_path.mkdir(parents=True, exist_ok=True)
    original_path = task_path / original_filename
    original_path.write_bytes(file_bytes)

    rows, meta = parse_packing_list(original_path)
    if not rows:
        shutil.rmtree(task_path, ignore_errors=True)
        raise ValueError("В файле не найдено строк данных")

    slice_start = max(0, start_row - 1)
    if max_rows is not None:
        rows = rows[slice_start : slice_start + max(1, min(max_rows, 500))]
    elif slice_start:
        rows = rows[slice_start:]

    total = len(rows)

    if not classify:
        results = [r.to_dict(include_image=False) for r in rows]
        payload = {
            "task_id": task_id,
            "status": "done",
            "total_rows": total,
            "processed": total,
            "started_at": _now(),
            "updated_at": _now(),
            "original_filename": original_filename,
            "original_path": str(original_path),
            "export_path": None,
            "meta": meta,
            "results": results,
            "error": None,
        }
        await _save_task(task_id, payload)
        return {
            "task_id": task_id,
            "status": "done",
            "total_rows": total,
            "meta": meta,
            "results": results,
        }

    payload: dict[str, Any] = {
        "task_id": task_id,
        "status": "processing",
        "total_rows": total,
        "processed": 0,
        "started_at": _now(),
        "updated_at": _now(),
        "original_filename": original_filename,
        "original_path": str(original_path),
        "export_path": None,
        "meta": meta,
        "results": [],
        "error": None,
        "_rows_snapshot": [
            {
                "row_num": r.row_num,
                "article": r.article,
                "name_cn": r.name_cn,
                "material": r.material,
                "box_count": r.box_count,
                "pcs_per_box": r.pcs_per_box,
                "total_qty": r.total_qty,
                "weight_gross": r.weight_gross,
                "weight_net": r.weight_net,
                "volume_cbm": r.volume_cbm,
                "value_usd": r.value_usd,
                "has_image": bool(r.image_path),
            }
            for r in rows
        ],
    }
    await _save_task(task_id, payload)
    background_tasks.add_task(_run_classification_task, task_id)
    return {
        "task_id": task_id,
        "status": "processing",
        "total_rows": total,
        "meta": meta,
    }


async def _run_classification_task(task_id: str) -> None:
    task = await get_task(task_id)
    if not task or task.get("status") != "processing":
        return

    original_path = Path(task["original_path"])
    meta = task.get("meta") or {}
    col_map = meta.get("detected_columns") or {}
    data_start = int(meta.get("data_start_row") or 2)
    rows_snapshot: list[dict] = list(task.get("_rows_snapshot") or [])

    try:
        images_by_row: dict[int, Any] = {}
        rows_full, _ = parse_packing_list(original_path)
        for r in rows_full:
            if r.image_base64 or r.image_path:
                images_by_row[r.row_num] = r

        results: list[dict] = []
        results_by_row: dict[int, dict] = {}
        classifier = get_smart_classifier()

        for idx, snap in enumerate(rows_snapshot):
            row_num = int(snap["row_num"])
            full = images_by_row.get(row_num)
            img_b64 = full.image_base64 if full else None

            desc_parts = [p for p in (snap.get("name_cn"), snap.get("material")) if p]
            item = dict(snap)
            item["image_path"] = str(full.image_path) if full and full.image_path else None

            try:
                clf = await classifier.classify(
                    description=" ".join(desc_parts) if desc_parts else None,
                    image_base64=img_b64,
                    article=snap.get("article"),
                )
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
            except Exception as exc:
                logger.warning(f"packing task {task_id} row {row_num}: {exc}")
                item["classify_status"] = "ERROR"
                item["classify_note"] = str(exc)

            clean = _strip_heavy_fields(item)
            results.append(clean)
            results_by_row[row_num] = clean

            task = await get_task(task_id) or task
            task["processed"] = idx + 1
            task["results"] = results
            task["updated_at"] = _now()
            task.pop("_rows_snapshot", None)
            await _save_task(task_id, task)

        safe_name = Path(task.get("original_filename") or "packing.xlsx").name
        export_path = Path(f"/tmp/classified_{task_id}_{safe_name}")
        export_classified_packing_list(
            original_path,
            results_by_row=results_by_row,
            col_map=col_map,
            data_start_row=data_start,
            output_path=export_path,
        )

        task = await get_task(task_id) or task
        task["status"] = "done"
        task["processed"] = len(results)
        task["export_path"] = str(export_path)
        task["updated_at"] = _now()
        task.pop("_rows_snapshot", None)
        await _save_task(task_id, task)
        logger.info(f"packing task {task_id} done: {len(results)} rows → {export_path}")
    except Exception as exc:
        logger.exception(f"packing task {task_id} failed")
        task = await get_task(task_id) or task
        task["status"] = "error"
        task["error"] = str(exc)
        task["updated_at"] = _now()
        task.pop("_rows_snapshot", None)
        await _save_task(task_id, task)


async def get_task_results(
    task_id: str,
    *,
    start: int = 0,
    limit: int = 50,
) -> dict[str, Any] | None:
    task = await get_task(task_id)
    if not task:
        return None
    start = max(0, int(start))
    limit = max(1, min(int(limit), 500))
    results = list(task.get("results") or [])
    return {
        "task_id": task_id,
        "status": task.get("status"),
        "processed": task.get("processed"),
        "total": task.get("total_rows"),
        "start": start,
        "limit": limit,
        "results": results[start : start + limit],
    }


async def get_task_export_path(task_id: str) -> Path | None:
    task = await get_task(task_id)
    if not task or task.get("status") != "done":
        return None
    path = task.get("export_path")
    if not path:
        return None
    p = Path(path)
    return p if p.is_file() else None
