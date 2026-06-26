"""
RAG-контекст для классификации товара: прецеденты ФТС, предварительные решения и примеры декларирования (ifcg),
нетарифка, выжимки из Law.TKS (regulatory_ai_extracts).
"""

from __future__ import annotations

import math
import os
import re
from difflib import SequenceMatcher

from loguru import logger
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..models.core import (
    ClassificationDecision,
    CustomsCaseLaw,
    DeclarationExample,
    PreliminaryDecision,
    RegulatoryAiExtract,
    TnvedEntry,
    TnvedEntryEmbedding,
)
from ..models.tnved import NonTariffMeasure
from .gemini_embedding_service import embed_texts_gemini

try:
    import numpy as np
except Exception:  # pragma: no cover - fallback для окружений без numpy
    np = None

# ~4000 токенов при грубой оценке 4 символа на токен (подстраховка для лимитов API).
MAX_RAG_CONTEXT_CHARS = 16_000
_DEFAULT_SEMANTIC_MIN_SCORE = 0.40

RAG_CLASSIFICATION_MANDATE = (
    "КРИТИЧЕСКИ ВАЖНО: При классификации товара и определении мер нетарифного регулирования, "
    "ты ОБЯЗАН опираться ИСКЛЮЧИТЕЛЬНО на данные из блока «ОФИЦИАЛЬНАЯ БАЗА ЗНАНИЙ». "
    "Обоснование кода ТН ВЭД выполняй строго по ОПИ 1-6 по порядку и явно отражай применённые правила. "
    "Запрещено выдумывать сертификаты, которых нет в базе. Если в базе сказано «Маркировка», укажи маркировку. "
    "Если база пуста по этому коду, так и напиши, но не придумывай лишнего. "
    "### ЭТАЛОННЫЕ ПРЕЦЕДЕНТЫ (EXACT MATCH) — ВЫСШИЙ ПРИОРИТЕТ ###\n"
    "Если в блоке «ОФИЦИАЛЬНАЯ БАЗА ЗНАНИЙ» присутствует раздел [ЭТАЛОННЫЙ ПРЕЦЕДЕНТ (EXACT MATCH)] — "
    "в нём уже лежит ПОДТВЕРЖДЁННОЕ экспертом или таможней соответствие «описание товара → 10-значный код». "
    "Ты ОБЯЗАН использовать этот код ТН ВЭД как финальный ответ (поле suggested_hs_code) и явно сослаться на "
    "этот прецедент в opi_reasoning_steps (тип совпадения и score). Отклонение от этого кода допустимо ТОЛЬКО "
    "если из инвойса/фото достоверно следует, что товар отличается по материалу/назначению/функции; "
    "в этом случае опиши различие и обоснуй другой выбор. Никогда не переписывай код «по интуиции».\n\n"
    "Раздел [ОФИЦИАЛЬНЫЕ ПРЕДВАРИТЕЛЬНЫЕ РЕШЕНИЯ ТАМОЖНИ (ВЫСШИЙ ПРИОРИТЕТ)] при наличии подходящей строки "
    "имеет приоритет над примерами декларирования: выбранный 10-значный код ТН ВЭД должен согласоваться с ним. "
    "Раздел [ПРИМЕРЫ ИЗ ПРАКТИКИ] — обезличенная статистика формулировок; используй как вспомогательный материал "
    "по стилю и терминологии, если подходящих предварительных решений в базе нет или они не подходят по описанию товара. "
    "Обоснуй код ТН ВЭД, опираясь на эти прецеденты и ОПИ 1-6."
)


def _env_float(name: str, default: float) -> float:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except Exception:
        return default


RAG_SEMANTIC_MIN_SCORE = max(0.0, min(0.99, _env_float("RAG_SEMANTIC_MIN_SCORE", _DEFAULT_SEMANTIC_MIN_SCORE)))
SEMANTIC_EMBEDDING_ALLOWED_SOURCES = {
    "regulatory_ai_extracts",
    "declaration_examples",
    "classification_decisions",  # сохраняем обратную совместимость старых индексов
}


def _normalize_hs_prefix(raw: str) -> str:
    return re.sub(r"\D", "", (raw or "").strip())[:6]


def _semantic_rank_prefix(raw: str) -> str:
    d = _normalize_hs_prefix(raw)
    if len(d) >= 4:
        return d[:4]
    if len(d) >= 2:
        return d[:2]
    return ""


def _chapter_from_hs(raw: str) -> str:
    d = re.sub(r"\D", "", (raw or "").strip())
    return d[:2] if len(d) >= 2 else ""


def _semantic_bucket(candidate_hs: str, rank_prefix: str) -> int:
    """
    Меньше bucket -> выше приоритет:
    0: совпадение 4-значной позиции (или 2-значной, если доступна только глава),
    1: совпадение по главе (2 знака),
    2: смежная глава (например 84/85),
    3: прочие.
    """
    p = _semantic_rank_prefix(rank_prefix)
    hs = re.sub(r"\D", "", str(candidate_hs or ""))[:10]
    if not p or len(hs) < 2:
        return 3
    if len(p) >= 4 and hs.startswith(p[:4]):
        return 0
    if hs.startswith(p[:2]):
        return 1 if len(p) >= 4 else 0
    ch_hs = _chapter_from_hs(hs)
    ch_p = _chapter_from_hs(p)
    if ch_hs and ch_p:
        try:
            if abs(int(ch_hs) - int(ch_p)) == 1:
                return 2
        except Exception:
            pass
    return 3


def _semantic_weight(bucket: int) -> float:
    if bucket <= 0:
        return 1.32
    if bucket == 1:
        return 1.22
    if bucket == 2:
        return 0.88
    return 0.70


def _truncate_block(text: str, max_chars: int) -> str:
    t = (text or "").strip()
    if len(t) <= max_chars:
        return t
    return t[: max_chars - 120] + "\n\n[…контекст обрезан по лимиту длины для API (~4000 токенов)…]\n"


def _tokenize_keywords(text: str) -> list[str]:
    raw = re.findall(r"[a-zA-Zа-яА-Я0-9]{3,}", (text or "").lower())
    if not raw:
        return []
    stop = {
        "для",
        "или",
        "это",
        "the",
        "and",
        "with",
        "товар",
        "модель",
        "brand",
        "model",
        "item",
        "code",
        "код",
    }
    uniq: list[str] = []
    seen: set[str] = set()
    for tok in raw:
        if tok in stop or tok in seen:
            continue
        seen.add(tok)
        uniq.append(tok)
        if len(uniq) >= 18:
            break
    return uniq


def _safe_embedding(raw: object) -> list[float]:
    if not isinstance(raw, list):
        return []
    out: list[float] = []
    for v in raw:
        try:
            out.append(float(v))
        except Exception:
            return []
    return out


def _parse_precedent_embedding_row(desc: str) -> tuple[str, str, str]:
    """SOURCE_TABLE / REAL_HS / TEXT из synthetic записи tnved_entries."""
    text = str(desc or "")
    src = "precedent"
    real_hs = ""
    frag = text
    m_src = re.search(r"SOURCE_TABLE=([^;]+)", text)
    m_hs = re.search(r"REAL_HS=([^;]+)", text)
    if m_src:
        src = (m_src.group(1) or "").strip() or src
    if m_hs:
        real_hs = re.sub(r"\D", "", str(m_hs.group(1) or ""))[:10]
    if "TEXT=" in text:
        frag = text.split("TEXT=", 1)[1]
    return src, real_hs, frag


def _cosine_similarity_np(a: object, b: object) -> float:
    if np is None:
        if not isinstance(a, list) or not isinstance(b, list):
            return 0.0
        return _cosine_similarity(a, b)
    if not isinstance(a, np.ndarray) or not isinstance(b, np.ndarray):
        return 0.0
    if a.size == 0 or b.size == 0 or a.shape != b.shape:
        return 0.0
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def get_semantic_legal_context(
    item_description: str,
    db_session: Session,
    *,
    top_k: int = 3,
    hs_code_prefix: str | None = None,
) -> list[str]:
    """
    Возвращает Top-K семантически релевантных прецедентов из ``tnved_entry_embeddings``.

    Источник векторов: synthetic записи (source_revision=precedent_embeddings_v1),
    сформированные из ``regulatory_ai_extracts`` и ``declaration_examples``
    (а также из ``classification_decisions`` для обратной совместимости).
    """
    query = (item_description or "").strip()
    if len(query) < 3:
        return []
    try:
        _model, vectors = embed_texts_gemini([query], batch_size=1)
        qv_raw = vectors[0] if vectors else []
        if np is not None:
            qv: object = np.asarray(qv_raw, dtype=np.float32)
        else:
            qv = [float(x) for x in qv_raw]
    except Exception as e:
        logger.warning("get_semantic_legal_context: embedding query failed: {}", e)
        return []
    if (np is not None and isinstance(qv, np.ndarray) and qv.size == 0) or (
        np is None and isinstance(qv, list) and not qv
    ):
        return []

    try:
        rows = (
            db_session.query(TnvedEntryEmbedding, TnvedEntry)
            .join(TnvedEntry, TnvedEntry.id == TnvedEntryEmbedding.tnved_entry_id)
            .filter(TnvedEntryEmbedding.embedding.isnot(None))
            .filter(TnvedEntry.source_revision == "precedent_embeddings_v1")
            .all()
        )
    except Exception as e:
        logger.warning("get_semantic_legal_context: DB query failed: {}", e)
        return []

    rank_prefix = _semantic_rank_prefix(hs_code_prefix or "")
    scored: list[tuple[float, float, int, str]] = []
    for emb_row, ent in rows:
        rv_raw = _safe_embedding(emb_row.embedding)
        if not rv_raw:
            continue
        if np is not None and isinstance(qv, np.ndarray):
            rv: object = np.asarray(rv_raw, dtype=np.float32)
            if not isinstance(rv, np.ndarray) or rv.shape != qv.shape:
                continue
        else:
            rv = rv_raw
        score = _cosine_similarity_np(qv, rv)
        if score <= 0.0:
            continue
        src, real_hs, frag = _parse_precedent_embedding_row(str(ent.description or ""))
        if src not in SEMANTIC_EMBEDDING_ALLOWED_SOURCES:
            continue
        title = (ent.title or "").strip().replace("\n", " ")[:160]
        snippet = (frag or "").strip().replace("\n", " ")[:520]
        hs = real_hs or re.sub(r"\D", "", str(ent.parent_hs or ""))[:10] or "—"
        bucket = _semantic_bucket(hs, rank_prefix)
        score_adj = score * _semantic_weight(bucket)
        if score_adj <= 0.0:
            continue
        line = f"[{src}] код {hs} | score={score_adj:.3f} | {title or '—'} | {snippet or '—'}"
        scored.append((score_adj, score, bucket, line))

    if not scored:
        return []
    total = len(scored)
    if rank_prefix:
        best_bucket = min(s[2] for s in scored)
        scored = [s for s in scored if s[2] == best_bucket]
    scored = [s for s in scored if s[0] >= RAG_SEMANTIC_MIN_SCORE]
    if not scored:
        logger.debug(
            "semantic_context: all matches filtered (prefix={!r}, raw_candidates={}, threshold={})",
            rank_prefix,
            total,
            RAG_SEMANTIC_MIN_SCORE,
        )
        return []

    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)

    out: list[str] = []
    seen: set[str] = set()
    for _, _, _, line in scored:
        if line in seen:
            continue
        seen.add(line)
        out.append(line)
        if len(out) >= max(1, int(top_k)):
            break
    return out


def _vector_precedent_matches(
    db_session: Session,
    hs_code_prefix: str,
    product_text: str,
    *,
    max_results: int = 5,
) -> list[tuple[float, TnvedEntry, str, str, str]]:
    query = (product_text or "").strip()
    if len(query) < 3:
        return []
    prefix = _normalize_hs_prefix(hs_code_prefix)
    rank_prefix = _semantic_rank_prefix(prefix)
    terms = _tokenize_keywords(query)

    qv: list[float] = []
    try:
        _model, vectors = embed_texts_gemini([query], batch_size=1)
        qv = vectors[0] if vectors else []
    except Exception as e:
        logger.warning("vector_precedents: embedding query failed: {}", e)
        qv = []

    try:
        q = (
            db_session.query(TnvedEntryEmbedding, TnvedEntry)
            .join(TnvedEntry, TnvedEntry.id == TnvedEntryEmbedding.tnved_entry_id)
            .filter(TnvedEntryEmbedding.embedding.isnot(None))
            .filter(TnvedEntry.source_revision == "precedent_embeddings_v1")
        )
        candidates = q.order_by(TnvedEntry.id.desc()).limit(1200).all()
        if not candidates:
            return []
    except Exception as e:
        logger.warning("vector_precedents: candidate query failed: {}", e)
        return []

    scored: list[tuple[float, float, int, TnvedEntry, str, str, str]] = []
    for emb_row, ent in candidates:
        rv = _safe_embedding(emb_row.embedding)
        s = 0.0
        if qv and rv:
            s = max(0.0, float(_cosine_similarity(qv, rv)))

        desc = str(ent.description or "")
        src, real_hs, frag = _parse_precedent_embedding_row(desc)
        if src not in SEMANTIC_EMBEDDING_ALLOWED_SOURCES:
            continue

        # Fallback-режим: если embedding недоступен, используем keyword similarity.
        if not qv:
            row_text = f"{src} {real_hs} {frag}".lower()
            kw_hits = sum(1 for t in terms if t in row_text) if terms else 0
            s = (kw_hits / max(1, min(8, len(terms)))) if terms else 0.0

        hs = real_hs or re.sub(r"\D", "", str(ent.parent_hs or ""))[:10]
        bucket = _semantic_bucket(hs, rank_prefix)
        score_adj = s * _semantic_weight(bucket)
        if score_adj > 0:
            scored.append((score_adj, s, bucket, ent, src, real_hs, frag))

    if not scored:
        return []
    if rank_prefix:
        best_bucket = min(x[2] for x in scored)
        scored = [x for x in scored if x[2] == best_bucket]
    scored = [x for x in scored if x[0] >= RAG_SEMANTIC_MIN_SCORE]
    if not scored:
        return []
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [(adj, ent, src, real_hs, frag) for adj, _raw, _bucket, ent, src, real_hs, frag in scored[: max(1, max_results)]]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def query_customs_case_law_matches(
    db_session: Session,
    hs_code_prefix: str,
    product_text: str,
    *,
    max_results: int = 4,
    query_embedding: list[float] | None = None,
) -> list[CustomsCaseLaw]:
    """
    Возвращает релевантные кейсы из ``customs_case_law``.

    Базовый режим: keyword matching + приоритет префикса HS.
    Продвинутый режим (подготовка): при передаче ``query_embedding`` добавляет cosine-сходство
    по полю ``customs_case_law.embedding``.
    """
    prefix = _normalize_hs_prefix(hs_code_prefix)
    terms = _tokenize_keywords(product_text)
    scored: list[tuple[float, CustomsCaseLaw]] = []
    candidate_limit = 220
    min_score = 0.12

    try:
        q = db_session.query(CustomsCaseLaw)
        if prefix:
            q = q.filter(
                or_(
                    CustomsCaseLaw.hs_code_prefix.like(f"{prefix}%"),
                    CustomsCaseLaw.recommended_hs_code.like(f"{prefix}%"),
                )
            )
        candidates = q.order_by(CustomsCaseLaw.id.desc()).limit(candidate_limit).all()

        if not candidates:
            candidates = db_session.query(CustomsCaseLaw).order_by(CustomsCaseLaw.id.desc()).limit(candidate_limit).all()

        qv = query_embedding or []
        for row in candidates:
            row_text = " ".join(
                [
                    row.title or "",
                    row.product_scope or "",
                    row.keywords or "",
                    row.reasoning_summary or "",
                    row.decision_summary or "",
                    row.legal_basis or "",
                ]
            ).lower()
            if not row_text:
                continue

            kw_hits = sum(1 for t in terms if t in row_text) if terms else 0
            kw_score = (kw_hits / max(1, min(len(terms), 8))) if terms else 0.0

            prefix_bonus = 0.0
            row_pref = _normalize_hs_prefix(row.hs_code_prefix or row.recommended_hs_code or "")
            if prefix and row_pref and (row_pref.startswith(prefix) or prefix.startswith(row_pref)):
                prefix_bonus = 0.2

            sem_score = 0.0
            rv = _safe_embedding(row.embedding)
            if qv and rv:
                sem_score = max(0.0, _cosine_similarity(qv, rv))

            score = (0.65 * kw_score) + (0.25 * sem_score) + prefix_bonus
            if score >= min_score:
                setattr(row, "_case_law_match_score", score)
                scored.append((score, row))
    except Exception as e:
        logger.warning("query_customs_case_law_matches failed: {}", e)
        return []

    scored.sort(key=lambda x: x[0], reverse=True)
    return [row for _, row in scored[: max(1, max_results)]]


# ---------------------------------------------------------------------------
# EXACT-MATCH ПРЕЦЕДЕНТЫ (feedback loop / ПКР / IFCG).
#
# Задача: перед обращением к LLM проверить, нет ли в БД точно (или почти точно)
# такого же товара с подтверждённым кодом ТН ВЭД. Если есть — вынести ОТДЕЛЬНЫЙ
# блок в начало RAG, который системный промпт трактует как «ОБЯЗАН использовать
# этот код».
#
# Источники:
#   1) declaration_examples с source IN ('user_approved','expert_verified') —
#      подтверждения, сохранённые через feedback-эндпоинт пользователями/декларантами.
#   2) classification_decisions (ПКР ФТС / target_entity / product_name) — ПКР-прецеденты.
#   3) declaration_examples (ifcg и пр.) — как fallback.
# ---------------------------------------------------------------------------

_USER_APPROVED_SOURCES: tuple[str, ...] = ("user_approved", "expert_verified", "manual_override")
_EXACT_MATCH_MIN_RATIO = 0.62
_EXACT_MATCH_AUTO_USE_RATIO = 0.86


def _normalize_product_text(raw: str) -> str:
    """Очистка для fuzzy-сравнения: нижний регистр, без пунктуации и лишних пробелов."""
    s = (raw or "").strip().lower()
    s = re.sub(r"[^\w\s\-]+", " ", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _text_ratio(a: str, b: str) -> float:
    """Гибрид SequenceMatcher и token-recall.

    SequenceMatcher сравнивает полные строки и занижает score, когда запрос короткий,
    а эталон — длинный (с примечаниями). Добавляем token-based recall: доля уникальных
    токенов запроса, встречающихся в эталоне. Итог — максимум из двух метрик
    (partial_ratio тоже подмешиваем через best-window).
    """
    na, nb = _normalize_product_text(a), _normalize_product_text(b)
    if not na or not nb:
        return 0.0
    base = float(SequenceMatcher(None, na, nb).ratio())

    # partial-ratio: сравниваем короткую строку с окном той же длины в длинной.
    short, long_ = (na, nb) if len(na) <= len(nb) else (nb, na)
    partial = 0.0
    if short and long_ and len(short) <= len(long_):
        step = max(1, len(short) // 4)
        best = 0.0
        for start in range(0, max(1, len(long_) - len(short) + 1), step):
            window = long_[start : start + len(short)]
            if not window:
                continue
            r = float(SequenceMatcher(None, short, window).ratio())
            if r > best:
                best = r
        partial = best

    # Token recall: какая доля уникальных токенов запроса встречается в эталоне.
    tokens_a = {t for t in na.split() if len(t) >= 3}
    token_recall = 0.0
    if tokens_a:
        hits = sum(1 for t in tokens_a if t in nb)
        token_recall = hits / len(tokens_a)

    return max(base, partial, token_recall * 0.95)


def find_exact_precedent_matches(
    db_session: Session,
    product_text: str,
    *,
    hs_code_prefix: str | None = None,
    top_k: int = 2,
) -> list[dict[str, object]]:
    """Поиск прецедентов c подтверждённым кодом ТН ВЭД, максимально близких к тексту товара.

    Возвращает список элементов ``{"source", "hs_code", "score", "title", "snippet", "auto_use"}``,
    отсортированных по убыванию score. ``auto_use=True`` означает, что LLM должна взять этот код.
    """
    query_norm = _normalize_product_text(product_text)
    if len(query_norm) < 6:
        return []

    tokens = [t for t in query_norm.split() if len(t) >= 3][:6]
    pattern_pool = [f"%{tok}%" for tok in tokens]
    like_filters = []
    for like in pattern_pool:
        like_filters.append(DeclarationExample.description.ilike(like))

    scored: list[tuple[float, dict[str, object]]] = []
    seen_keys: set[tuple[str, str]] = set()

    # --- 1. declaration_examples с source='user_approved' (feedback loop, высший приоритет)
    try:
        base_q = db_session.query(DeclarationExample).filter(
            DeclarationExample.source.in_(_USER_APPROVED_SOURCES)
        )
        if like_filters:
            base_q = base_q.filter(or_(*like_filters))
        rows = base_q.order_by(DeclarationExample.id.desc()).limit(40).all()
        for row in rows:
            hs = re.sub(r"\D", "", str(row.hs_code or ""))[:10]
            if not hs:
                continue
            ratio = _text_ratio(product_text, row.description or "")
            if ratio < _EXACT_MATCH_MIN_RATIO:
                continue
            key = (hs, (row.description or "")[:120])
            if key in seen_keys:
                continue
            seen_keys.add(key)
            # бонус для user-approved: это эталон, усиливаем score чтобы перебивать ПКР
            adj = min(1.0, ratio + 0.05)
            scored.append(
                (
                    adj,
                    {
                        "source": "user_approved",
                        "hs_code": hs,
                        "score": round(adj, 3),
                        "title": (row.description or "")[:180],
                        "snippet": (row.description or "")[:500],
                        "auto_use": adj >= _EXACT_MATCH_AUTO_USE_RATIO,
                    },
                )
            )
    except Exception as e:
        logger.warning("find_exact_precedent_matches: user_approved lookup: {}", e)

    # --- 2. classification_decisions (ПКР ФТС)
    try:
        q = db_session.query(ClassificationDecision)
        pref = _normalize_hs_prefix(hs_code_prefix or "")
        like_filters_pkr = []
        for tok in tokens:
            like_filters_pkr.append(ClassificationDecision.product_name.ilike(f"%{tok}%"))
            like_filters_pkr.append(ClassificationDecision.target_entity.ilike(f"%{tok}%"))
            like_filters_pkr.append(ClassificationDecision.description.ilike(f"%{tok}%"))
        if like_filters_pkr:
            q = q.filter(or_(*like_filters_pkr))
        if pref:
            q = q.filter(ClassificationDecision.hs_code.like(f"{pref[:4]}%"))
        rows_pkr = q.order_by(ClassificationDecision.id.desc()).limit(40).all()
        for row in rows_pkr:
            hs = re.sub(r"\D", "", str(row.hs_code or ""))[:10]
            if not hs:
                continue
            subject = (row.target_entity or row.product_name or "").strip()
            ratio = max(
                _text_ratio(product_text, subject),
                _text_ratio(product_text, row.description or ""),
            )
            if ratio < _EXACT_MATCH_MIN_RATIO:
                continue
            key = (hs, subject[:120])
            if key in seen_keys:
                continue
            seen_keys.add(key)
            scored.append(
                (
                    ratio,
                    {
                        "source": "pkr",
                        "hs_code": hs,
                        "score": round(ratio, 3),
                        "title": f"ПКР № {row.decision_number or '—'}: {subject[:180] or '—'}",
                        "snippet": (row.description or "")[:500],
                        "auto_use": ratio >= _EXACT_MATCH_AUTO_USE_RATIO,
                    },
                )
            )
    except Exception as e:
        logger.warning("find_exact_precedent_matches: classification_decisions: {}", e)

    # --- 3. declaration_examples (ifcg и пр.) — только если ещё ничего не нашли
    if not scored:
        try:
            q = db_session.query(DeclarationExample).filter(
                ~DeclarationExample.source.in_(_USER_APPROVED_SOURCES)
            )
            if like_filters:
                q = q.filter(or_(*like_filters))
            if hs_code_prefix:
                pref = _normalize_hs_prefix(hs_code_prefix)
                if pref:
                    q = q.filter(DeclarationExample.hs_code.like(f"{pref[:4]}%"))
            for row in q.order_by(DeclarationExample.id.desc()).limit(30).all():
                hs = re.sub(r"\D", "", str(row.hs_code or ""))[:10]
                if not hs:
                    continue
                ratio = _text_ratio(product_text, row.description or "")
                if ratio < _EXACT_MATCH_MIN_RATIO:
                    continue
                key = (hs, (row.description or "")[:120])
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                scored.append(
                    (
                        ratio * 0.95,  # fallback источник, немного занижаем
                        {
                            "source": "declaration_example",
                            "hs_code": hs,
                            "score": round(ratio * 0.95, 3),
                            "title": (row.description or "")[:180],
                            "snippet": (row.description or "")[:500],
                            "auto_use": ratio >= _EXACT_MATCH_AUTO_USE_RATIO,
                        },
                    )
                )
        except Exception as e:
            logger.warning("find_exact_precedent_matches: declaration_examples: {}", e)

    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored[: max(1, int(top_k))]]


def build_rag_context(db_session: Session, hs_code_prefix: str, product_text: str) -> str:
    """
    Собирает текст для системного промпта из нескольких источников:

    - ``classification_decisions``: префикс кода ТН ВЭД и/или совпадение текста с описанием/названием;
    - ``tnved_entry_embeddings``: векторно релевантные кейсы из regulatory_ai_extracts,
      declaration_examples и classification_decisions;
    - ``customs_case_law``: судебная практика, разъяснения ЕЭК и пояснения к ТН ВЭД (по префиксу + keyword score);
    - ``preliminary_decisions``: решения по классификации (ifcg), по префиксу ``hs_code``;
    - ``declaration_examples``: примеры графы 31 (ifcg), по префиксу кода; при наличии текста товара —
      сначала релевантные по ``ILIKE``, затем добор случайными до 5 строк;
    - ``non_tariff_measures``: строки, у которых ``commodity_code`` начинается с префикса;
    - ``regulatory_ai_extracts``: выжимки, где ``hs_code_norm`` начинается с того же префикса
      (поля ``affected_codes`` в схеме нет — используется ``hs_code_norm``).
    """
    prefix = _normalize_hs_prefix(hs_code_prefix)
    blob = (product_text or "").strip()

    lines: list[str] = ["=== ОФИЦИАЛЬНАЯ БАЗА ЗНАНИЙ ===", ""]

    # --- [ЭТАЛОННЫЙ ПРЕЦЕДЕНТ (EXACT MATCH)] — высший приоритет для LLM ---
    exact_matches: list[dict[str, object]] = []
    try:
        exact_matches = find_exact_precedent_matches(
            db_session,
            blob,
            hs_code_prefix=prefix,
            top_k=2,
        )
    except Exception as e:
        logger.warning("build_rag_context: exact precedent lookup failed: {}", e)

    lines.append("[ЭТАЛОННЫЙ ПРЕЦЕДЕНТ (EXACT MATCH) — ВЫСШИЙ ПРИОРИТЕТ]:")
    if not exact_matches:
        lines.append("- (точное совпадение по товару не найдено; применяй ОПИ 1-6 по остальным разделам)")
    else:
        for m in exact_matches:
            src = str(m.get("source") or "precedent").upper()
            score = m.get("score") or 0.0
            hs = str(m.get("hs_code") or "—")
            title = str(m.get("title") or "—").replace("\n", " ")[:220]
            auto = "AUTO_USE=TRUE" if bool(m.get("auto_use")) else "AUTO_USE=FALSE"
            lines.append(
                f"- [{src}] КОД={hs} | score={float(score):.3f} | {auto} | {title}"
            )
        lines.append(
            "  -> ИНСТРУКЦИЯ: если AUTO_USE=TRUE и товар из инвойса смысл-в-смысл совпадает с прецедентом, "
            "ты ОБЯЗАН использовать этот код ТН ВЭД в suggested_hs_code и сослаться на прецедент в opi_reasoning_steps."
        )
    lines.append("")

    # --- [ПРЕЦЕДЕНТЫ] ---
    prec_lines: list[ClassificationDecision] = []
    seen_prec: set[int] = set()
    try:
        if prefix:
            for row in (
                db_session.query(ClassificationDecision)
                .filter(ClassificationDecision.hs_code.like(f"{prefix}%"))
                .order_by(ClassificationDecision.id.desc())
                .limit(3)
                .all()
            ):
                if row.id not in seen_prec:
                    seen_prec.add(row.id)
                    prec_lines.append(row)
        if len(prec_lines) < 3 and len(blob) >= 3:
            pat = f"%{blob[:80]}%"
            q = db_session.query(ClassificationDecision).filter(
                or_(
                    ClassificationDecision.product_name.ilike(pat),
                    ClassificationDecision.description.ilike(pat),
                    ClassificationDecision.target_entity.ilike(pat),
                )
            )
            if seen_prec:
                q = q.filter(ClassificationDecision.id.notin_(seen_prec))
            for row in q.order_by(ClassificationDecision.id.desc()).limit(3 - len(prec_lines)).all():
                if row.id not in seen_prec:
                    seen_prec.add(row.id)
                    prec_lines.append(row)
    except Exception as e:
        logger.warning("build_rag_context: classification_decisions: {}", e)

    lines.append("[ПРЕЦЕДЕНТЫ]:")
    if not prec_lines:
        lines.append("- (нет записей classification_decisions по префиксу или тексту товара)")
    else:
        for p in prec_lines[:3]:
            hs = re.sub(r"\D", "", str(p.hs_code or ""))[:10]
            pname = (p.product_name or "").strip().replace("\n", " ")[:220]
            desc = (p.description or "").strip().replace("\n", " ")[:360]
            t_ent = (p.target_entity or "").strip().replace("\n", " ")[:160]
            tail = f" Цель классификации: {t_ent}" if t_ent else ""
            lines.append(
                f"- № {p.decision_number or '—'} | код {hs or '—'} | {pname or '—'}{tail}. "
                f"Описание: {desc or '—'}"
            )
    lines.append("")

    # --- [ВЕКТОРНЫЕ ПРЕЦЕДЕНТЫ] ---
    vector_lines: list[str] = []
    try:
        for score, ent, src, real_hs, frag in _vector_precedent_matches(
            db_session,
            hs_code_prefix=prefix,
            product_text=blob,
            max_results=5,
        ):
            hs = (real_hs or "").strip()[:10] or "—"
            title = (ent.title or "").strip().replace("\n", " ")[:180] or "—"
            txt = (frag or "").strip().replace("\n", " ")[:380]
            vector_lines.append(
                f"- [{src}] код {hs} | score={score:.3f} | {title}. Фрагмент: {txt or '—'}"
            )
    except Exception as e:
        logger.warning("build_rag_context: vector precedent search: {}", e)

    lines.append("[ВЕКТОРНЫЕ ПРЕЦЕДЕНТЫ (SEMANTIC SEARCH)]:")
    if not vector_lines:
        lines.append("- (векторные совпадения не найдены или индекс не построен)")
    else:
        lines.extend(vector_lines)
    lines.append("")

    # --- [ПРЕЦЕДЕНТЫ ЕЭК/СУДОВ/ПОЯСНЕНИЙ] ---
    case_law_lines: list[str] = []
    try:
        matched_cases = query_customs_case_law_matches(
            db_session,
            hs_code_prefix=prefix,
            product_text=blob,
            max_results=4,
        )
        source_labels = {
            "court": "СУД",
            "eec": "ЕЭК",
            "explanatory_note": "ПОЯСНЕНИЕ",
            "admin_guidance": "РАЗЪЯСНЕНИЕ",
        }
        for c in matched_cases:
            src = source_labels.get((c.source_type or "").strip().lower(), (c.source_type or "ИСТОЧНИК").upper())
            hs = (c.recommended_hs_code or "").strip()[:10] or "—"
            title = (c.title or "").strip().replace("\n", " ")[:180] or "—"
            opi = (c.opi_applied or "").strip()
            score = float(getattr(c, "_case_law_match_score", 0.0) or 0.0)
            reason = (c.reasoning_summary or "").strip().replace("\n", " ")[:340]
            decision = (c.decision_summary or "").strip().replace("\n", " ")[:220]
            extra = f" | ОПИ: {opi}" if opi else ""
            score_tail = f" | score={score:.2f}" if score > 0 else ""
            case_law_lines.append(
                f"- [{src}] № {c.case_number or '—'} | код {hs}{extra}{score_tail} | {title}. "
                f"Логика: {reason or '—'}. Вывод: {decision or '—'}"
            )
    except Exception as e:
        logger.warning("build_rag_context: customs_case_law: {}", e)

    lines.append("[ПРЕЦЕДЕНТЫ И РАЗЪЯСНЕНИЯ (СУДЫ/ЕЭК/ПОЯСНЕНИЯ ТН ВЭД)]:")
    if not case_law_lines:
        lines.append("- (нет релевантных кейсов customs_case_law)")
    else:
        lines.extend(case_law_lines)
    lines.append("")

    # --- [ОФИЦИАЛЬНЫЕ ПРЕДВАРИТЕЛЬНЫЕ РЕШЕНИЯ] (выше примеров декларирования) ---
    prelim_lines: list[str] = []
    try:
        if prefix:
            base_pre = db_session.query(PreliminaryDecision).filter(
                PreliminaryDecision.hs_code.like(f"{prefix}%")
            )
            picked_pre: list[PreliminaryDecision] = []
            seen_pre: set[int] = set()
            if len(blob) >= 4:
                pat = f"%{blob[:72]}%"
                for row in (
                    base_pre.filter(PreliminaryDecision.description.ilike(pat))
                    .order_by(func.random())
                    .limit(5)
                    .all()
                ):
                    if row.id not in seen_pre:
                        seen_pre.add(row.id)
                        picked_pre.append(row)
            need_pre = max(0, 5 - len(picked_pre))
            if need_pre:
                q_pre = base_pre
                if seen_pre:
                    q_pre = q_pre.filter(PreliminaryDecision.id.notin_(seen_pre))
                for row in q_pre.order_by(func.random()).limit(need_pre).all():
                    picked_pre.append(row)
                    if len(picked_pre) >= 5:
                        break
            for pr in picked_pre[:5]:
                d = (pr.description or "").strip().replace("\n", " ")[:900]
                prelim_lines.append(f"- Код: {pr.hs_code} | Описание: {d}")
    except Exception as e:
        logger.warning("build_rag_context: preliminary_decisions: {}", e)

    lines.append("[ОФИЦИАЛЬНЫЕ ПРЕДВАРИТЕЛЬНЫЕ РЕШЕНИЯ ТАМОЖНИ (ВЫСШИЙ ПРИОРИТЕТ)]:")
    if not prelim_lines:
        lines.append("- (нет записей preliminary_decisions по префиксу)")
    else:
        lines.extend(prelim_lines)
    lines.append("")

    # --- [ПРИМЕРЫ ИЗ ПРАКТИКИ] ---
    practice_lines: list[str] = []
    try:
        if prefix:
            base_q = db_session.query(DeclarationExample).filter(DeclarationExample.hs_code.like(f"{prefix}%"))
            picked: list[DeclarationExample] = []
            seen_ids: set[int] = set()
            if len(blob) >= 4:
                pat = f"%{blob[:72]}%"
                for row in (
                    base_q.filter(DeclarationExample.description.ilike(pat))
                    .order_by(func.random())
                    .limit(5)
                    .all()
                ):
                    if row.id not in seen_ids:
                        seen_ids.add(row.id)
                        picked.append(row)
            need = max(0, 5 - len(picked))
            if need:
                q2 = base_q
                if seen_ids:
                    q2 = q2.filter(DeclarationExample.id.notin_(seen_ids))
                for row in q2.order_by(func.random()).limit(need).all():
                    picked.append(row)
                    if len(picked) >= 5:
                        break
            for ex in picked[:5]:
                d = (ex.description or "").strip().replace("\n", " ")[:900]
                practice_lines.append(f"- Код: {ex.hs_code} | Описание: {d}")
    except Exception as e:
        logger.warning("build_rag_context: declaration_examples: {}", e)

    lines.append("[ПРИМЕРЫ ИЗ ПРАКТИКИ (Реальные декларации)]:")
    if not practice_lines:
        lines.append("- (нет записей declaration_examples по префиксу)")
    else:
        lines.extend(practice_lines)
    lines.append("")

    # --- [НЕТАРИФНЫЕ МЕРЫ] ---
    meas_lines: list[str] = []
    try:
        if prefix:
            raw = (
                db_session.query(NonTariffMeasure)
                .filter(NonTariffMeasure.commodity_code.like(f"{prefix}%"))
                .order_by(NonTariffMeasure.id.asc())
                .limit(50)
                .all()
            )
            seen_m: set[tuple[str, str]] = set()
            for m in raw:
                key = ((m.measure_type or "").strip().lower(), (m.regulatory_act or "").strip()[:200])
                if key in seen_m or not (m.regulatory_act or "").strip():
                    continue
                seen_m.add(key)
                act = (m.regulatory_act or "").strip()[:260]
                doc = (m.document_required or "").strip()[:140]
                des = (m.description or "").strip().replace("\n", " ")[:200]
                mt = (m.measure_type or "").strip()
                extra = f" | {doc}" if doc else ""
                des_part = f" — {des}" if des else ""
                meas_lines.append(f"- [{mt}] {act}{extra}{des_part}")
                if len(meas_lines) >= 6:
                    break
    except Exception as e:
        logger.warning("build_rag_context: non_tariff_measures: {}", e)

    lines.append("[НЕТАРИФНЫЕ МЕРЫ]:")
    if not meas_lines:
        lines.append("- (нет выборки non_tariff_measures по префиксу кода)")
    else:
        lines.extend(meas_lines)
    lines.append("")

    # --- [НОРМАТИВНЫЕ АКТЫ (Law.TKS)] — по hs_code_norm ---
    law_lines: list[str] = []
    try:
        if prefix:
            q = (
                db_session.query(RegulatoryAiExtract)
                .filter(RegulatoryAiExtract.hs_code_norm.like(f"{prefix}%"))
                .order_by(RegulatoryAiExtract.updated_at.desc())
                .limit(18)
            )
            for r in q.all():
                ex = (r.source_excerpt or "").strip().replace("\n", " ")[:500]
                law_lines.append(
                    f"- [{r.measure_type}] код {r.hs_code_norm} | {r.document_name[:200]} | {ex or '—'}"
                )
    except Exception as e:
        logger.warning("build_rag_context: regulatory_ai_extracts: {}", e)

    lines.append("[НОРМАТИВНЫЕ АКТЫ (Law.TKS)]:")
    if not law_lines:
        lines.append("- (нет выборки regulatory_ai_extracts по префиксу hs_code_norm)")
    else:
        lines.extend(law_lines)

    out = "\n".join(lines).strip()
    out = _truncate_block(out, MAX_RAG_CONTEXT_CHARS)
    logger.debug(
        "build_rag_context: prefix={!r}, product_len={}, out_len={}",
        prefix,
        len(blob),
        len(out),
    )
    return out
