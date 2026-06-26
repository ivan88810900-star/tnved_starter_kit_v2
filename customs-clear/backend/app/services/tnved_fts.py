"""Полнотекстовый поиск по номенклатуре ТН ВЭД (FTS5 над tnved_commodities).

Индекс производный и перестраиваемый, поэтому создаётся идемпотентно в рантайме
(по аналогии с ``_sqlite_patch_non_tariff_columns``), вне Alembic: это поисковый
индекс, а не бизнес-схема. Источник данных — официальные русские описания в
``tnved_commodities.description`` + код в ``tnved_commodities.code``.

Особенность номенклатуры: официальные описания не содержат разговорных слов
("ноутбук", "планшет"), поэтому запрос расширяется синонимами и стеммингом через
``normative_store._expand_query_terms`` (разговорное → официальные термины + коды
глав), а морфология добирается префиксным матчингом FTS5 (term*).
"""

from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy import text

from ..db import engine

logger = logging.getLogger(__name__)

_FTS_TABLE = "tnved_fts"
_SOURCE_TABLE = "tnved_commodities"
_OBSOLETE_RESERVED_DESC_SQL = "description NOT LIKE 'Товарная позиция%'"
_OBSOLETE_RESERVED_DESC_SQL_C = "c.description NOT LIKE 'Товарная позиция%'"

# Кэш доступности FTS5 в текущей сборке SQLite (None — ещё не проверяли).
_fts_ready: bool | None = None


def _is_sqlite() -> bool:
    return str(engine.url).startswith("sqlite")


def _create_triggers(conn) -> None:
    """Синхронизация FTS с tnved_commodities (external-content FTS5)."""
    conn.execute(text(
        f"CREATE TRIGGER IF NOT EXISTS {_FTS_TABLE}_ai AFTER INSERT ON {_SOURCE_TABLE} BEGIN "
        f"INSERT INTO {_FTS_TABLE}(rowid, code, description) "
        f"VALUES (new.id, new.code, new.description); END;"
    ))
    conn.execute(text(
        f"CREATE TRIGGER IF NOT EXISTS {_FTS_TABLE}_ad AFTER DELETE ON {_SOURCE_TABLE} BEGIN "
        f"INSERT INTO {_FTS_TABLE}({_FTS_TABLE}, rowid, code, description) "
        f"VALUES ('delete', old.id, old.code, old.description); END;"
    ))
    conn.execute(text(
        f"CREATE TRIGGER IF NOT EXISTS {_FTS_TABLE}_au AFTER UPDATE ON {_SOURCE_TABLE} BEGIN "
        f"INSERT INTO {_FTS_TABLE}({_FTS_TABLE}, rowid, code, description) "
        f"VALUES ('delete', old.id, old.code, old.description); "
        f"INSERT INTO {_FTS_TABLE}(rowid, code, description) "
        f"VALUES (new.id, new.code, new.description); END;"
    ))


def ensure_fts_index(*, rebuild: bool = False) -> bool:
    """Идемпотентно создаёт/наполняет FTS5-индекс. Возвращает доступность FTS."""
    global _fts_ready
    if not _is_sqlite():
        _fts_ready = False
        return False
    if _fts_ready and not rebuild:
        return True
    try:
        with engine.begin() as conn:
            exists = conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name=:n"),
                {"n": _FTS_TABLE},
            ).fetchone()
            if not exists:
                conn.execute(text(
                    f"CREATE VIRTUAL TABLE {_FTS_TABLE} USING fts5("
                    f"code, description, content='{_SOURCE_TABLE}', content_rowid='id', "
                    f"tokenize='unicode61 remove_diacritics 2', prefix='2 3 4')"
                ))
                _create_triggers(conn)
                conn.execute(text(f"INSERT INTO {_FTS_TABLE}({_FTS_TABLE}) VALUES('rebuild')"))
            else:
                _create_triggers(conn)
                if rebuild:
                    conn.execute(text(f"INSERT INTO {_FTS_TABLE}({_FTS_TABLE}) VALUES('rebuild')"))
                else:
                    cnt = conn.execute(text(f"SELECT count(*) FROM {_FTS_TABLE}")).scalar() or 0
                    if cnt == 0:
                        conn.execute(text(f"INSERT INTO {_FTS_TABLE}({_FTS_TABLE}) VALUES('rebuild')"))
        _fts_ready = True
        return True
    except Exception as exc:  # fts5 может отсутствовать в сборке SQLite
        logger.warning("tnved_fts: FTS5 недоступен, поиск работает через LIKE-fallback: %s", exc)
        _fts_ready = False
        return False


def _build_match(text_terms: list[str]) -> str:
    """Собирает безопасное FTS5 MATCH-выражение: OR префиксных токенов."""
    parts: list[str] = []
    seen: set[str] = set()
    for term in text_terms:
        # Оставляем буквы/цифры/пробел (в т.ч. кириллицу), убираем спецсимволы FTS.
        tok = re.sub(r"[^\w\s]", " ", term, flags=re.UNICODE).strip()
        tok = re.sub(r"\s+", " ", tok)
        if not tok or tok in seen:
            continue
        seen.add(tok)
        parts.append(f'"{tok}"*')
    return " OR ".join(parts)


def search_commodities_fts(query: str, limit: int = 40) -> list[dict[str, Any]] | None:
    """Релевантный поиск по номенклатуре. None — если FTS недоступен (fallback)."""
    if not ensure_fts_index():
        return None

    from .normative_store import _expand_query_terms  # локальный импорт: избегаем цикла

    q = (query or "").strip()
    if len(q) < 2:
        return []

    qd = re.sub(r"\D", "", q)
    text_terms: list[str] = []
    code_terms: list[str] = []
    for t in _expand_query_terms(q):
        if t.isdigit():
            if len(t) >= 2:
                code_terms.append(t)
        else:
            text_terms.append(t)

    results: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(code: str | None, desc: str | None) -> None:
        code = (code or "").strip()
        if code and code not in seen and not (desc or "").strip().startswith("Товарная позиция"):
            seen.add(code)
            results.append({"code": code, "description": (desc or "").strip()})

    try:
        with engine.begin() as conn:
            # 1) Точный префикс кода из самого запроса — максимальная релевантность.
            if qd and len(qd) >= 2:
                for code, desc in conn.execute(
                    text(f"SELECT code, description FROM {_SOURCE_TABLE} "
                         f"WHERE code LIKE :p AND {_OBSOLETE_RESERVED_DESC_SQL} ORDER BY code LIMIT :l"),
                    {"p": f"{qd}%", "l": limit},
                ):
                    add(code, desc)

            # 2) Полнотекстовый поиск по описанию, ранжирование bm25.
            match = _build_match(text_terms)
            if match and len(results) < limit:
                rows = conn.execute(
                    text(f"SELECT c.code, c.description FROM {_FTS_TABLE} f "
                         f"JOIN {_SOURCE_TABLE} c ON c.id = f.rowid "
                         f"WHERE {_FTS_TABLE} MATCH :m AND {_OBSOLETE_RESERVED_DESC_SQL_C} "
                         f"ORDER BY bm25({_FTS_TABLE}) LIMIT :l"),
                    {"m": match, "l": limit * 3},
                )
                for code, desc in rows:
                    if len(results) >= limit:
                        break
                    add(code, desc)

            # 3) Коды глав из синонимов (например, ноутбук → 8471).
            for ct in code_terms:
                if len(results) >= limit:
                    break
                for code, desc in conn.execute(
                    text(f"SELECT code, description FROM {_SOURCE_TABLE} "
                         f"WHERE code LIKE :p AND {_OBSOLETE_RESERVED_DESC_SQL} ORDER BY code LIMIT :l"),
                    {"p": f"{ct}%", "l": limit},
                ):
                    if len(results) >= limit:
                        break
                    add(code, desc)
    except Exception as exc:
        logger.warning("tnved_fts: ошибка FTS-поиска, fallback на LIKE: %s", exc)
        return None

    return results[:limit]
