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
_SEARCH_STOP_WORDS = frozenset({"and", "or", "not", "near"})
_RANKING_WORD_ENDINGS = (
    "иями", "ями", "ами", "ого", "его", "ому", "ему", "ыми", "ими",
    "ая", "яя", "ое", "ее", "ые", "ие", "ый", "ий", "ой", "ую", "юю",
    "ам", "ям", "ах", "ях", "ов", "ев", "ей", "а", "я", "о", "е", "ы", "и", "у", "ю", "ь",
)

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
        words = [word.lower() for word in tok.split() if word]
        if not tok or tok in seen or (words and all(word in _SEARCH_STOP_WORDS for word in words)):
            continue
        seen.add(tok)
        parts.append(f'"{tok}"*')
    return " OR ".join(parts)


def _normalise_search_text(value: str) -> str:
    cleaned = re.sub(r"[^\w\s]", " ", (value or "").lower().replace("ё", "е"), flags=re.UNICODE)
    return re.sub(r"\s+", " ", cleaned).strip()


def _search_words(value: str) -> list[str]:
    return [
        word
        for word in _normalise_search_text(value).split()
        if len(word) >= 2 and not word.isdigit() and word not in _SEARCH_STOP_WORDS
    ]


def _ranking_word_stem(word: str) -> str:
    for ending in _RANKING_WORD_ENDINGS:
        if word.endswith(ending) and len(word) - len(ending) >= 4:
            return word[: -len(ending)]
    return word


def _word_matches_description(word: str, description_words: list[str]) -> bool:
    if word in description_words:
        return True
    # Conservative morphology aid for ranking only; FTS candidate retrieval remains
    # the source of truth.
    root = _ranking_word_stem(word)
    return len(root) >= 4 and any(candidate.startswith(root) for candidate in description_words)


def _search_once(query: str, limit: int, *, corrected: bool = False) -> list[dict[str, Any]] | None:
    from .normative_store import _expand_query_terms  # local import: avoids a module cycle

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
    text_terms.extend(_search_words(q))

    # De-duplicate dictionary prefixes while preserving their intentional order.
    code_terms = list(dict.fromkeys(code_terms))
    text_terms = list(dict.fromkeys(text_terms))

    candidates: dict[str, dict[str, Any]] = {}
    raw_rank = 0

    def add(
        code: str | None,
        desc: str | None,
        *,
        source: str,
        dictionary_prefix: str | None = None,
    ) -> None:
        nonlocal raw_rank
        code_value = (code or "").strip()
        desc_value = (desc or "").strip()
        if not code_value or desc_value.startswith("Товарная позиция"):
            return
        row = candidates.get(code_value)
        if row is None:
            row = {
                "code": code_value,
                "description": desc_value,
                "sources": set(),
                "dictionary_prefixes": set(),
                "raw_rank": raw_rank,
            }
            candidates[code_value] = row
            raw_rank += 1
        row["sources"].add(source)
        if dictionary_prefix:
            row["dictionary_prefixes"].add(dictionary_prefix)

    try:
        with engine.begin() as conn:
            # 1) Точный префикс кода из самого запроса — максимальная релевантность.
            if qd and len(qd) >= 2:
                for code, desc in conn.execute(
                    text(f"SELECT code, description FROM {_SOURCE_TABLE} "
                         f"WHERE code LIKE :p AND {_OBSOLETE_RESERVED_DESC_SQL} ORDER BY code LIMIT :l"),
                    {"p": f"{qd}%", "l": limit},
                ):
                    add(code, desc, source="code")

            # 2) Curated domain dictionary prefixes.  These must be candidates
            # before generic BM25 rows: otherwise "ноутбук" ranked a computer
            # tomography device above the intended 8471 family.
            per_prefix_limit = max(12, min(limit * 2, 60))
            for code_term in code_terms:
                for code, desc in conn.execute(
                    text(
                        f"SELECT code, description FROM {_SOURCE_TABLE} "
                        f"WHERE code LIKE :p AND {_OBSOLETE_RESERVED_DESC_SQL} ORDER BY code LIMIT :l"
                    ),
                    {"p": f"{code_term}%", "l": per_prefix_limit},
                ):
                    add(code, desc, source="dictionary", dictionary_prefix=code_term)

            # 3) Full-text candidates.  BM25 supplies a stable raw order; final
            # ranking below combines it with direct-text and dictionary evidence.
            match = _build_match(text_terms)
            if match:
                rows = conn.execute(
                    text(f"SELECT c.code, c.description FROM {_FTS_TABLE} f "
                         f"JOIN {_SOURCE_TABLE} c ON c.id = f.rowid "
                         f"WHERE {_FTS_TABLE} MATCH :m AND {_OBSOLETE_RESERVED_DESC_SQL_C} "
                         f"ORDER BY bm25({_FTS_TABLE}) LIMIT :l"),
                    {"m": match, "l": max(100, min(limit * 6, 400))},
                )
                for code, desc in rows:
                    add(code, desc, source="text")
    except Exception as exc:
        logger.warning("tnved_fts: ошибка FTS-поиска, fallback на LIKE: %s", exc)
        return None

    query_norm = _normalise_search_text(q)
    query_words = _search_words(q)

    def rank(row: dict[str, Any]) -> tuple[int, int, str]:
        code = str(row["code"])
        description_norm = _normalise_search_text(str(row["description"]))
        description_words = _search_words(description_norm)
        sources: set[str] = row["sources"]
        dictionary_prefixes: set[str] = row["dictionary_prefixes"]
        matched_dictionary_prefixes = {
            prefix for prefix in code_terms if code.startswith(prefix)
        } | dictionary_prefixes
        score = 0

        direct_code = bool(qd and len(qd) >= 2 and code.startswith(qd))
        direct_phrase = bool(query_norm and f" {query_norm} " in f" {description_norm} ")
        direct_word_hits = sum(
            1 for word in query_words if _word_matches_description(word, description_words)
        )
        dictionary_hit = bool(matched_dictionary_prefixes)

        if direct_code:
            score += 100_000
            if code == qd:
                score += 8_000
        if direct_phrase:
            score += 70_000
        if query_words and direct_word_hits == len(query_words):
            score += 60_000
        elif direct_word_hits:
            score += direct_word_hits * 6_000
        if dictionary_hit:
            score += 45_000
            if code in matched_dictionary_prefixes:
                score += 8_000
            elif len(code) == 4:
                score += 3_000
        if "text" in sources:
            score += 5_000

        if direct_code:
            reason = "code_prefix"
        elif corrected:
            reason = "typo_correction"
        elif direct_phrase or (query_words and direct_word_hits == len(query_words)):
            reason = "name_match"
        elif dictionary_hit:
            reason = "domain_dictionary"
        else:
            reason = "full_text"
        row["match_reason"] = reason
        return (-score, int(row["raw_rank"]), code)

    ranked = sorted(candidates.values(), key=rank)
    return [
        {
            "code": row["code"],
            "description": row["description"],
            "match_reason": row["match_reason"],
        }
        for row in ranked[:limit]
    ]


def search_commodities_smart(query: str, limit: int = 40) -> dict[str, Any]:
    """Hybrid lexical search with curated semantics and conservative typo recovery."""
    q = (query or "").strip()
    if len(q) < 2:
        return {
            "results": [],
            "corrected_query": None,
            "effective_query": q,
            "strategy": "hybrid_fts",
        }
    if not ensure_fts_index():
        return {
            "results": None,
            "corrected_query": None,
            "effective_query": q,
            "strategy": "fts_unavailable",
        }

    results = _search_once(q, limit) or []
    corrected_query: str | None = None
    if not results:
        from .normative_store import suggest_search_correction

        corrected_query = suggest_search_correction(q)
        if corrected_query:
            corrected_results = _search_once(corrected_query, limit, corrected=True)
            if corrected_results:
                results = corrected_results
            else:
                corrected_query = None

    return {
        "results": results,
        "corrected_query": corrected_query,
        "effective_query": corrected_query or q,
        "strategy": "hybrid_fts_typo" if corrected_query else "hybrid_fts",
    }


def search_commodities_fts(query: str, limit: int = 40) -> list[dict[str, Any]] | None:
    """Backward-compatible result list for existing service consumers."""
    return search_commodities_smart(query, limit=limit)["results"]
