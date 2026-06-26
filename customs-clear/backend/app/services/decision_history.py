"""История решений по классификации (JSONL) — основа для обратной связи и подсказок ИИ."""
from __future__ import annotations

import difflib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from collections import Counter
from typing import Any, Dict, List, Tuple

from loguru import logger

_PATH = Path(os.getenv("DECISIONS_LOG_PATH", "data/user_decisions.jsonl"))
_MAX_READ_LINES = int(os.getenv("DECISIONS_LOG_MAX_READ", "5000"))
_SIMILAR_LIMIT = int(os.getenv("DECISIONS_SIMILAR_LIMIT", "6"))
_SIMILAR_MIN_SCORE = float(os.getenv("DECISIONS_SIMILAR_MIN_SCORE", "0.18"))
_CLIENT_BOOST_MULT = float(os.getenv("DECISIONS_CLIENT_BOOST_MULT", "1.28"))


def _norm_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower().strip())


def _tokens(s: str) -> set[str]:
    return {w for w in re.findall(r"[\w\d]+", s.lower(), flags=re.UNICODE) if len(w) >= 2}


def client_score_multiplier(row_client_id: str | None, prefer_client_id: str | None) -> float:
    """Усиление релевантности записей того же клиента (как в X-Client-Id)."""
    if not prefer_client_id or not row_client_id:
        return 1.0
    if (row_client_id or "").strip() == (prefer_client_id or "").strip():
        return max(1.0, min(_CLIENT_BOOST_MULT, 2.0))
    return 1.0


def similarity_score(query: str, description: str) -> float:
    """Гибрид: SequenceMatcher + Jaccard по токенам."""
    q, d = _norm_text(query), _norm_text(description)
    if not q or not d:
        return 0.0
    r1 = difflib.SequenceMatcher(None, q, d).ratio()
    qt, dt = _tokens(q), _tokens(d)
    if not qt or not dt:
        jac = 0.0
    else:
        inter = len(qt & dt)
        union = len(qt | dt) or 1
        jac = inter / union
    return 0.42 * r1 + 0.58 * jac


def _iter_tail_jsonl() -> List[Dict[str, Any]]:
    if not _PATH.is_file():
        return []
    try:
        lines = _PATH.read_text(encoding="utf-8", errors="ignore").splitlines()
        tail = lines[-_MAX_READ_LINES:] if len(lines) > _MAX_READ_LINES else lines
        out: List[Dict[str, Any]] = []
        for line in tail:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out
    except OSError as e:
        logger.warning(f"decision_history read: {e}")
        return []


def append_decision(event: Dict[str, Any]) -> None:
    """Добавить запись (идемпотентность на стороне клиента не гарантируется)."""
    try:
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        row = dict(event)
        row["ts"] = datetime.now(timezone.utc).isoformat()
        with open(_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    except Exception as e:
        logger.warning(f"decision_history: {e}")


def export_all_decisions() -> List[Dict[str, Any]]:
    """Все записи из хвоста журнала (для выгрузки / обучение)."""
    return list(_iter_tail_jsonl())


def compute_journal_stats() -> Dict[str, Any]:
    """Агрегированная статистика по хвосту журнала (без выгрузки полного текста)."""
    rows = _iter_tail_jsonl()
    hs_c: Counter[str] = Counter()
    src_c: Counter[str] = Counter()
    clients: set[str] = set()
    ts_vals: List[str] = []

    for r in rows:
        conf = re.sub(r"\D", "", str(r.get("confirmed_hs") or ""))[:10]
        if len(conf) >= 4:
            hs_c[conf] += 1
        src_c[str(r.get("source") or "unknown")[:64]] += 1
        cid = str(r.get("client_id") or "").strip()
        if cid:
            clients.add(cid[:128])
        ts = r.get("ts")
        if isinstance(ts, str) and ts.strip():
            ts_vals.append(ts.strip())

    return {
        "journal_path": str(_PATH),
        "file_exists": _PATH.is_file(),
        "records_in_index": len(rows),
        "unique_confirmed_hs_codes": len(hs_c),
        "unique_client_ids": len(clients),
        "first_ts": min(ts_vals) if ts_vals else None,
        "last_ts": max(ts_vals) if ts_vals else None,
        "top_confirmed_hs": [{"hs_code": h, "count": c} for h, c in hs_c.most_common(20)],
        "by_source": [{"source": s, "count": c} for s, c in src_c.most_common(12)],
    }


def read_recent_decisions(limit: int = 30) -> List[Dict[str, Any]]:
    """Последние N записей (для UI / отладки)."""
    lim = max(1, min(limit, 200))
    rows = _iter_tail_jsonl()
    return rows[-lim:] if len(rows) > lim else rows


def find_similar_decisions(
    query: str,
    *,
    limit: int | None = None,
    min_score: float | None = None,
    prefer_client_id: str | None = None,
) -> List[Dict[str, Any]]:
    """
    Похожие прошлые подтверждения по описанию (для UI и контекста ИИ).
    Возвращает список с полями description, suggested_hs, confirmed_hs, ts, similarity (0..1).
    """
    q = (query or "").strip()
    lim = limit if limit is not None else _SIMILAR_LIMIT
    lim = max(1, min(lim, 20))
    thr = min_score if min_score is not None else _SIMILAR_MIN_SCORE
    thr = max(0.05, min(thr, 0.95))

    if len(q) < 3:
        return []

    rows = _iter_tail_jsonl()
    scored: List[Tuple[float, Dict[str, Any]]] = []
    seen: set[tuple[str, str, str]] = set()

    for row in rows:
        desc = str(row.get("description") or "").strip()
        conf = str(row.get("confirmed_hs") or "").strip()
        if not desc and not conf:
            continue
        sc = similarity_score(q, desc) if desc else 0.0
        if conf and conf in q.replace(" ", ""):
            sc = max(sc, 0.25)
        r_client = str(row.get("client_id") or "").strip() or None
        mult = client_score_multiplier(r_client, prefer_client_id)
        sc_rank = float(sc) * mult
        if sc_rank < thr:
            continue
        key = (desc[:120], conf, str(row.get("ts") or ""))
        if key in seen:
            continue
        seen.add(key)
        scored.append(
            (
                sc_rank,
                {
                    "description": desc[:400],
                    "suggested_hs": str(row.get("suggested_hs") or "")[:24],
                    "confirmed_hs": conf[:24],
                    "ts": row.get("ts"),
                    "similarity": round(sc_rank, 3),
                    "similarity_base": round(float(sc), 3),
                    "client_match": mult > 1.0,
                },
            )
        )

    scored.sort(key=lambda x: -x[0])
    return [item for _, item in scored[:lim]]


def similar_decisions_context(
    query: str,
    prefer_client_id: str | None = None,
) -> Dict[str, Any]:
    """Фрагмент для слияния в JSON контекста copilot."""
    if os.getenv("DECISIONS_SIMILAR_ENABLED", "true").lower() not in ("1", "true", "yes"):
        return {"similar_past_decisions": [], "similar_decisions_enabled": False}
    items = find_similar_decisions(query, prefer_client_id=prefer_client_id)
    if not items:
        return {"similar_past_decisions": [], "similar_decisions_enabled": True}
    out: Dict[str, Any] = {
        "similar_past_decisions": items,
        "similar_decisions_enabled": True,
    }
    if prefer_client_id:
        out["decisions_prefer_client_id"] = prefer_client_id[:128]
    return out


def suggest_hs_codes(
    query: str,
    *,
    limit: int = 8,
    min_score: float | None = None,
    prefer_client_id: str | None = None,
) -> List[Dict[str, Any]]:
    """
    Агрегация подтверждённых ТН ВЭД из журнала по похожести описаний (для UI и классификатора).
    Возвращает hs_code, weight (сумма похожестей), count, best_similarity, sample_description.
    """
    q = (query or "").strip()
    lim = max(1, min(limit, 30))
    thr = min_score if min_score is not None else max(0.08, _SIMILAR_MIN_SCORE * 0.85)
    thr = max(0.05, min(thr, 0.9))

    if len(q) < 2:
        return []

    q_digits = re.sub(r"\D", "", q)
    rows = _iter_tail_jsonl()
    by_hs: Dict[str, Dict[str, Any]] = {}

    for row in rows:
        desc = str(row.get("description") or "").strip()
        conf_raw = str(row.get("confirmed_hs") or "").strip()
        conf = re.sub(r"\D", "", conf_raw)[:10]
        if not conf or len(conf) < 4:
            continue
        sc = similarity_score(q, desc) if desc else 0.0
        if q_digits and conf in q_digits:
            sc = max(sc, 0.22)
        r_client = str(row.get("client_id") or "").strip() or None
        mult = client_score_multiplier(r_client, prefer_client_id)
        sc_w = float(sc) * mult
        if sc_w < thr:
            continue
        if conf not in by_hs:
            by_hs[conf] = {
                "score_sum": 0.0,
                "count": 0,
                "max_sim": 0.0,
                "sample": desc[:200] if desc else "",
                "client_hits": 0,
            }
        ag = by_hs[conf]
        ag["score_sum"] += sc_w
        ag["count"] = int(ag["count"]) + 1
        ag["max_sim"] = max(float(ag["max_sim"]), sc_w)
        if mult > 1.0:
            ag["client_hits"] = int(ag.get("client_hits") or 0) + 1
        if len(desc) > len(str(ag.get("sample") or "")):
            ag["sample"] = desc[:200]

    out: List[Dict[str, Any]] = []
    for hs, ag in by_hs.items():
        item = {
            "hs_code": hs,
            "weight": round(float(ag["score_sum"]), 3),
            "count": int(ag["count"]),
            "best_similarity": round(float(ag["max_sim"]), 3),
            "sample_description": str(ag.get("sample") or ""),
        }
        ch = int(ag.get("client_hits") or 0)
        if ch > 0:
            item["client_boosted_rows"] = ch
        out.append(item)
    out.sort(key=lambda x: (-x["weight"], -x["count"], -x["best_similarity"]))
    return out[:lim]


def journal_hints_for_classifier(
    description: str,
    limit: int = 5,
    prefer_client_id: str | None = None,
) -> str:
    """Текстовый блок для user-message LLM-классификатора."""
    if os.getenv("DECISIONS_CLASSIFIER_HINTS", "true").lower() not in ("1", "true", "yes"):
        return ""
    hints = suggest_hs_codes(
        description,
        limit=limit,
        min_score=max(0.1, _SIMILAR_MIN_SCORE * 0.8),
        prefer_client_id=prefer_client_id,
    )
    if not hints:
        return ""
    lines = [
        "Справочно: из журнала подтверждённых решений по похожим описаниям чаще выбирали коды "
        "(не подставляй слепо — сверь с ТН ВЭД и описанием):"
    ]
    for h in hints:
        lines.append(
            f"  — {h['hs_code']}: вес {h['weight']}, срабатываний {h['count']}, "
            f"лучшая похожесть {h['best_similarity']}; пример: {h['sample_description'][:100]}"
        )
    return "\n".join(lines) + "\n\n"
