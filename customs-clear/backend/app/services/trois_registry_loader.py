"""Загрузка брендов из БД ``trois_registry`` в runtime-кэш ``trois_service`` (#151)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from loguru import logger

from ..db import SessionLocal
from ..models.tnved import TroisRegistry
from .trois_fuzzy import normalize_brand_key


def _backend_data_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "data"


def export_db_brands_json(path: Path | None = None) -> int:
    """Экспорт уникальных брендов из БД в JSON для offline-кэша."""
    out_path = path or (_backend_data_dir() / "trois_brands_export.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    brands: list[dict[str, str]] = []
    seen: set[str] = set()
    with SessionLocal() as db:
        rows = (
            db.query(TroisRegistry)
            .filter(TroisRegistry.trademark.isnot(None))
            .limit(50000)
            .all()
        )
        for row in rows:
            for field in (row.trademark, row.brand):
                name = (field or "").strip()
                if not name:
                    continue
                key = normalize_brand_key(name)
                if not key or key in seen:
                    continue
                seen.add(key)
                brands.append(
                    {
                        "name": name,
                        "brand": row.brand or name,
                        "right_holder": row.right_holder or "—",
                        "goods": "—",
                        "reg_number": row.reg_number or "",
                    }
                )
    payload = {"brands": brands, "count": len(brands)}
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("trois_registry_loader: exported {} brands → {}", len(brands), out_path)
    return len(brands)


def count_db_brands() -> int:
    with SessionLocal() as db:
        return int(db.query(TroisRegistry).count())


def sync_db_to_local_cache(force: bool = False) -> int:
    """
    Подгружает бренды из ``trois_registry`` в in-memory кэш ``trois_service._LOCAL_CACHE``.
    Возвращает число добавленных ключей.
    """
    from . import trois_service

    db_count = count_db_brands()
    min_reload = int(os.getenv("TROIS_DB_RELOAD_MIN_ROWS", "200") or "200")
    if db_count < min_reload and not force:
        return 0

    added = 0
    seen_keys: set[str] = set()
    with SessionLocal() as db:
        rows = db.query(TroisRegistry).limit(50000).all()
        for row in rows:
            for raw_name in (row.trademark, row.brand):
                name = (raw_name or "").strip()
                if not name:
                    continue
                key = normalize_brand_key(name)
                if not key or key in seen_keys:
                    continue
                if key in trois_service._LOCAL_CACHE:
                    seen_keys.add(key)
                    continue
                holder = (row.right_holder or "—").strip()
                goods = (row.status or "—").strip()
                trois_service._LOCAL_CACHE[key] = trois_service._mk(name.upper(), holder, goods)
                seen_keys.add(key)
                added += 1
    if added:
        logger.info("trois_registry_loader: +{} brands from DB (total cache {})", added, len(trois_service._LOCAL_CACHE))
    return added


def search_db_registry(query: str, *, max_results: int = 10) -> list[dict[str, Any]]:
    """Поиск в БД через ``query_trois_matches_for_trademark``."""
    from .trois_registry_sync import normalize_trademark_for_registry, query_trois_matches_for_trademark

    tm = normalize_trademark_for_registry(query)
    if not tm:
        return []
    with SessionLocal() as db:
        rows = query_trois_matches_for_trademark(db, tm, max_results=max_results)
    out: list[dict[str, Any]] = []
    for row in rows:
        score = getattr(row, "_trois_match_score", None)
        out.append(
            {
                "brand": row.brand,
                "trademark": row.trademark,
                "right_holder": row.right_holder,
                "reg_number": row.reg_number,
                "status": row.status,
                "valid_until": row.valid_until,
                "match_score": score,
            }
        )
    return out
