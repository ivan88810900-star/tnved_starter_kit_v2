"""Доп. логика по документам: эвристики сопоставления строк и проверка ИНН РФ."""
from __future__ import annotations

import re
from typing import Any, Dict, List

from .normative_store import search_hs_rates_enriched, search_tnved


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def validate_inn_ru(inn: str) -> Dict[str, Any]:
    """Контрольная сумма ИНН юрлица (10) или физлица (12)."""
    raw = (inn or "").strip()
    d = _digits(raw)
    if len(d) not in (10, 12):
        return {
            "valid": False,
            "inn": raw,
            "reason": "ИНН РФ должен содержать 10 (юрлицо) или 12 (физлицо) цифр",
        }

    def _check10(x: str) -> bool:
        coeffs = [2, 4, 10, 3, 5, 9, 4, 6, 8]
        s = sum(int(x[i]) * coeffs[i] for i in range(9)) % 11
        ctrl = 0 if s == 10 else s
        return ctrl == int(x[9])

    def _check12(x: str) -> bool:
        c1 = [7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
        c2 = [3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
        s1 = sum(int(x[i]) * c1[i] for i in range(10)) % 11
        k1 = 0 if s1 == 10 else s1
        if k1 != int(x[10]):
            return False
        s2 = sum(int(x[i]) * c2[i] for i in range(11)) % 11
        k2 = 0 if s2 == 10 else s2
        return k2 == int(x[11])

    ok = _check10(d) if len(d) == 10 else _check12(d)
    return {
        "valid": ok,
        "inn": d,
        "kind": "legal_entity" if len(d) == 10 else "individual",
        "reason": "" if ok else "Не сходится контрольная сумма ИНН",
    }


def validate_counterparty(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Минимальная проверка контрагента: ИНН РФ при country=RU или если задан inn."""
    country = (payload.get("country") or "").strip().upper()
    inn = (payload.get("inn") or "").strip()
    name = (payload.get("name") or "").strip()
    out: Dict[str, Any] = {"status": "OK", "checks": []}
    if inn or country in ("RU", "RUS", "РФ", "RUSSIA"):
        if inn:
            inn_res = validate_inn_ru(inn)
            out["checks"].append({"type": "inn_ru", **inn_res})
            if not inn_res["valid"]:
                out["status"] = "WARNING"
        elif country in ("RU", "RUS", "РФ", "RUSSIA"):
            out["checks"].append(
                {
                    "type": "inn_ru",
                    "valid": False,
                    "skipped": True,
                    "reason": "Для РФ рекомендуется указать ИНН",
                }
            )
    if name and len(name) < 2:
        out["checks"].append({"type": "name", "valid": False, "reason": "Слишком короткое наименование"})
        out["status"] = "WARNING"
    return out


def match_invoice_lines_to_hs(
    lines: List[Dict[str, Any]],
    *,
    limit_per_line: int = 6,
) -> List[Dict[str, Any]]:
    """Подбор кандидатов ТН ВЭД по тексту строки (поиск по коду в тексте + search_tnved)."""
    out: List[Dict[str, Any]] = []
    for i, line in enumerate(lines):
        desc = str(line.get("description") or line.get("text") or "").strip()
        idx = line.get("index", i)
        candidates: List[Dict[str, Any]] = []
        if not desc:
            out.append({"line_index": idx, "description": desc, "candidates": []})
            continue
        m = re.search(r"\d{4,10}", desc)
        if m:
            q = m.group(0)[:10]
            for row in search_hs_rates_enriched(q, limit=limit_per_line):
                candidates.append({**row, "match_reason": "digits_in_line"})
        if len(candidates) < limit_per_line:
            for row in search_tnved(desc[:120], limit=limit_per_line):
                hc = row.get("hs_code") or ""
                if any(c.get("hs_code") == hc for c in candidates):
                    continue
                candidates.append(
                    {
                        "hs_code": hc,
                        "title": row.get("title") or "",
                        "source": "tnved_search",
                        "match_reason": "text_search",
                    }
                )
                if len(candidates) >= limit_per_line:
                    break
        out.append(
            {
                "line_index": idx,
                "description": desc,
                "candidates": candidates[:limit_per_line],
            }
        )
    return out
