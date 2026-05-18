"""Черновик данных для декларации: ТН ВЭД, графа 31, вес/количество/места, документы, особенности."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from loguru import logger

from .claude_service import enrich_declaration_draft_lines
from .document_intel import match_invoice_lines_to_hs
from .non_tariff_rules import find_rules_for_code
from .normative_store import extract_tr_ts_act_codes, find_tnved_entry, lookup_tr_ts_acts_by_codes


def _digits_hs(code: str) -> str:
    return re.sub(r"\D", "", (code or ""))[:10]


def _best_hs_from_candidates(candidates: List[Dict[str, Any]]) -> tuple[str, str]:
    """Возвращает (hs_code, источник_подсказки)."""
    for c in candidates:
        hc = _digits_hs(str(c.get("hs_code") or ""))
        if len(hc) >= 4:
            return hc.ljust(10, "0")[:10], str(c.get("match_reason") or c.get("source") or "справочник")
    return "", ""


def _graf31_without_llm(commercial_desc: str, hs_code: str, tnved_title: str) -> str:
    """Базовый текст графы 31 без ИИ."""
    parts: List[str] = []
    t = (tnved_title or "").strip()
    if t:
        parts.append(t)
    d = (commercial_desc or "").strip()
    if d and d not in t:
        short = d.replace("\n", " ")[:220]
        if short:
            parts.append(f"(коммерческое обозначение: {short})")
    if not parts and d:
        return d.replace("\n", " ")[:500]
    return "; ".join(parts)[:512]


def _aggregate_rules(hs_code: str) -> Dict[str, Any]:
    rules = find_rules_for_code(hs_code) if hs_code else []
    permits: set[str] = set()
    tr_ts: set[str] = set()
    names: List[str] = []
    pec: List[str] = []
    for r in rules:
        names.append(str(r.get("name") or ""))
        for p in r.get("required_permits") or []:
            if isinstance(p, str) and p.strip():
                permits.add(p.strip().upper())
        for t in r.get("tr_ts") or []:
            if isinstance(t, str) and t.strip():
                tr_ts.add(t.strip())
        ed = (r.get("tr_ts_edition") or "").strip()
        if ed:
            pec.append(ed[:200])
        ex = (r.get("exception_note") or "").strip()
        if ex:
            pec.append(f"Оговорка: {ex[:280]}")
    codes = extract_tr_ts_act_codes(tr_ts)
    registry_cards = lookup_tr_ts_acts_by_codes(codes)
    return {
        "rule_names": [n for n in names if n][:6],
        "permit_types": sorted(permits),
        "tr_ts_labels": sorted(tr_ts),
        "tr_ts_registry": registry_cards,
        "peculiarities_rules": pec[:5],
    }


def _normalize_line(
    row: Dict[str, Any],
    pack_row: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Объединяет инвойс и упаковку по индексу."""
    q = float(row.get("quantity") or 0)
    wg = float(row.get("weight_gross") or 0)
    wn = float(row.get("weight_net") or 0)
    pkg = float(row.get("packages") or row.get("places") or 0)
    if pack_row:
        if wg <= 0:
            wg = float(pack_row.get("weight_gross") or 0)
        if wn <= 0:
            wn = float(pack_row.get("weight_net") or 0)
        if pkg <= 0:
            pkg = float(pack_row.get("packages") or pack_row.get("places") or 0)
        if q <= 0:
            q = float(pack_row.get("quantity") or 0)
    return {
        "line": int(row.get("line") or 0),
        "description": str(row.get("description") or "").strip(),
        "quantity": q,
        "unit": str(row.get("unit") or "").strip(),
        "weight_gross_kg": wg,
        "weight_net_kg": wn,
        "places_or_packages": pkg,
    }


async def build_declaration_draft(
    invoice: Dict[str, Any],
    packing: Optional[Dict[str, Any]] = None,
    *,
    use_llm: bool = True,
    prefer_client_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Собирает черновик строк декларации и сводку."""
    items: List[Dict[str, Any]] = list(invoice.get("items") or [])
    raw_text = (invoice.get("raw_text") or "").strip()
    pack_items: List[Dict[str, Any]] = list((packing or {}).get("items") or [])

    if not items and raw_text:
        items = [
            {
                "line": 1,
                "description": raw_text[:4000],
                "quantity": 0.0,
                "unit": "",
                "weight_gross": float((invoice.get("summary") or {}).get("gross_weight_total") or 0),
                "weight_net": float((invoice.get("summary") or {}).get("net_weight_total") or 0),
                "packages": float((invoice.get("summary") or {}).get("packages") or 0),
            }
        ]

    inv_summary = invoice.get("summary") or {}
    pack_summary = (packing or {}).get("summary") or {}
    total_places = float(inv_summary.get("packages") or inv_summary.get("lines_count") or 0)
    if total_places <= 0:
        total_places = float(pack_summary.get("packages") or 0)

    lines_for_llm: List[Dict[str, Any]] = []
    normalized: List[Dict[str, Any]] = []
    for i, row in enumerate(items):
        pk = pack_items[i] if i < len(pack_items) else None
        norm = _normalize_line(row, pk)
        normalized.append(norm)
        lines_for_llm.append(
            {
                "line": norm["line"] or i + 1,
                "description": norm["description"][:1200],
                "quantity": norm["quantity"],
                "unit": norm["unit"],
                "weight_gross_kg": norm["weight_gross_kg"],
            }
        )

    llm_by_line: Dict[int, Dict[str, Any]] = {}
    if use_llm and lines_for_llm:
        try:
            enriched = await enrich_declaration_draft_lines(
                lines_for_llm[:20],
                prefer_client_id=prefer_client_id,
            )
            if enriched:
                for e in enriched:
                    ln = int(e.get("line") or 0)
                    if ln:
                        llm_by_line[ln] = e
        except Exception as ex:
            logger.warning(f"ИИ-обогащение черновика ДТ: {ex}")

    declaration_lines: List[Dict[str, Any]] = []
    for i, norm in enumerate(normalized):
        line_no = norm["line"] or i + 1
        desc = norm["description"]
        matched = match_invoice_lines_to_hs(
            [{"description": desc, "index": line_no}],
            limit_per_line=6,
        )
        cands = (matched[0] or {}).get("candidates") or []
        hs_heur, hs_src = _best_hs_from_candidates(cands)

        le = llm_by_line.get(line_no) or {}
        hs_llm = _digits_hs(str(le.get("hs_code") or ""))
        if len(hs_llm) == 10:
            hs_final = hs_llm
            hs_source = "ии"
        elif len(hs_heur) >= 4:
            hs_final = hs_heur
            hs_source = "справочник" if not le else "ии+справочник"
        else:
            hs_final = hs_llm if len(hs_llm) >= 4 else hs_heur
            hs_source = "ии" if len(hs_llm) >= 4 else ("справочник" if hs_heur else "")

        ent = find_tnved_entry(hs_final) if hs_final else None
        tnved_title = (ent.title if ent else "") or ""

        graf31 = (le.get("graf31_ru") or "").strip()
        if not graf31:
            graf31 = _graf31_without_llm(desc, hs_final, tnved_title)

        agg = _aggregate_rules(hs_final)
        permit_llm = le.get("permit_types")
        if isinstance(permit_llm, list) and permit_llm:
            permits = sorted({str(x).strip().upper() for x in permit_llm if str(x).strip()})
        else:
            permits = agg["permit_types"]

        tr_ts_llm = le.get("tr_ts_short")
        if isinstance(tr_ts_llm, list) and tr_ts_llm:
            tr_ts_disp = [str(x) for x in tr_ts_llm if x]
        elif isinstance(tr_ts_llm, str) and tr_ts_llm.strip():
            tr_ts_disp = [tr_ts_llm.strip()]
        else:
            tr_ts_disp = agg["tr_ts_labels"]

        pec: List[str] = []
        p_llm = (le.get("peculiarities") or "").strip()
        if p_llm:
            pec.append(p_llm)
        pec.extend(agg["peculiarities_rules"])

        declaration_lines.append(
            {
                "line": line_no,
                "commercial_description": desc,
                "hs_code": hs_final,
                "hs_code_source": hs_source,
                "tnved_title_ru": tnved_title,
                "graf31_ru": graf31,
                "quantity": norm["quantity"],
                "unit": norm["unit"],
                "weight_gross_kg": norm["weight_gross_kg"],
                "weight_net_kg": norm["weight_net_kg"],
                "places_or_packages": norm["places_or_packages"],
                "permit_types": permits,
                "tr_ts": tr_ts_disp,
                "tr_ts_registry": agg["tr_ts_registry"],
                "applied_rule_names": agg["rule_names"],
                "peculiarities": pec[:6],
                "hs_candidates": cands[:5],
            }
        )

    total_qty = sum(r["quantity"] for r in declaration_lines)
    total_gross = sum(r["weight_gross_kg"] for r in declaration_lines)
    total_places_sum = sum(r["places_or_packages"] for r in declaration_lines)
    if total_places_sum <= 0 and total_places > 0:
        total_places_sum = total_places

    return {
        "status": "OK",
        "document_focus": "declaration_draft",
        "summary": {
            "lines_count": len(declaration_lines),
            "total_quantity": total_qty,
            "total_gross_weight_kg": round(total_gross, 4),
            "total_places_or_packages": total_places_sum,
            "invoice_number": invoice.get("invoice_number"),
        },
        "declaration_lines": declaration_lines,
        "disclaimer": (
            "Черновик для работы декларанта: коды ТН ВЭД и формулировки графы 31 могут быть уточнены классификатором "
            "и таможней. Обязательные документы и ТР ТС проверяйте по актуальным правилам и договору."
        ),
    }
