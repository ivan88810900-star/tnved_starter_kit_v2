#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db import SessionLocal  # noqa: E402
from app.models.core import FssNotification  # noqa: E402
from app.services.compliance_resolver import (  # noqa: E402
    _check_sanction_risks,
    build_compliance_document_items,
)


def _mk_item_data(description: str, *, brand: str = "", article: str = "") -> dict[str, Any]:
    return {
        "name_ru": description,
        "name": description,
        "usage": description,
        "material": "",
        "brand": brand,
        "manufacturer": "",
        "counterparty": "",
        "article": article,
    }


def _short_docs(docs: list[dict[str, Any]], limit: int = 6) -> str:
    if not docs:
        return "—"
    rows: list[str] = []
    for d in docs[: max(1, int(limit))]:
        doc_type = str(d.get("doc_type") or "—")
        status = str(d.get("compliance_status") or "—")
        title = str(d.get("title") or "—")
        reg = str(d.get("registry_match") or "")
        if reg:
            rows.append(f"{doc_type} [{status}] {title} | registry_match={reg}")
        else:
            rows.append(f"{doc_type} [{status}] {title}")
    if len(docs) > limit:
        rows.append(f"... (+{len(docs) - limit} more)")
    return "\n".join(rows)


def _to_markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    # Простой markdown-рендер без внешних зависимостей.
    safe_headers = [h.replace("\n", " ") for h in headers]
    out = ["| " + " | ".join(safe_headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for r in rows:
        safe = [str(x).replace("\n", "<br>") for x in r]
        out.append("| " + " | ".join(safe) + " |")
    return "\n".join(out)


def _find_fss_status(docs: list[dict[str, Any]]) -> tuple[str, str]:
    # Сначала ищем «основной» документ ФСБ (не AI-warning).
    for d in docs:
        doc_type = str(d.get("doc_type") or "").strip().lower()
        title = str(d.get("title") or "").strip().lower()
        source = str(d.get("source") or "").strip().lower()
        if (doc_type == "нотификация фсб" or title == "нотификация фсб") and source != "ai_keyword_risk":
            return str(d.get("compliance_status") or "—"), str(d.get("registry_match") or "")
    for d in docs:
        doc_type = str(d.get("doc_type") or "").strip().lower()
        title = str(d.get("title") or "").strip().lower()
        if doc_type == "нотификация фсб" or "нотификация фсб" in title:
            return str(d.get("compliance_status") or "—"), str(d.get("registry_match") or "")
    return "NOT_FOUND", ""


def main() -> int:
    cases = [
        ("Смартфон", "8517130000", "Smartphone with WiFi, NFC and encryption", "China"),
        ("Насос", "8413708100", "Centrifugal chemical pump for industrial use", "Germany"),
        ("Игрушки", "9503007000", "Plastic building blocks for children", "Vietnam"),
        ("Реагент", "3822190000", "Laboratory reagent solvent mixture", "USA"),
    ]

    report_rows: list[list[str]] = []
    sanction_rows: list[list[str]] = []

    with SessionLocal() as db:
        # Для кейса №1: берём реальный номер нотификации для проверки REQUIRED -> MATCHED.
        fss_any = db.query(FssNotification).filter(FssNotification.number != "").first()
        fss_number = str(fss_any.number or "").strip() if fss_any else ""

        for name, hs_code, description, country in cases:
            base_item = _mk_item_data(description=description)
            bundle = build_compliance_document_items(hs_code=hs_code, item_data=base_item, country=country, db=db)
            docs = list(bundle.get("documents") or [])
            blocking = bool(bundle.get("blocking_issue"))
            notes_count = sum(1 for d in docs if str(d.get("source") or "") == "normative_notes")
            ai_count = sum(1 for d in docs if str(d.get("source") or "") == "ai_keyword_risk")
            registry_count = sum(1 for d in docs if d.get("registry_match"))

            extra = ""
            # Кейсы санкций (№2, №4): Germany / USA
            if country in {"Germany", "USA"}:
                sanction_docs, sanction_block = _check_sanction_risks(
                    hs_code=hs_code,
                    country=country,
                    item_data=base_item,
                    db=db,
                )
                risk_hits = [d for d in sanction_docs if str(d.get("source") or "") in {"sanction_import_risks", "eu_sanctions_list"}]
                sanction_rows.append(
                    [
                        name,
                        country,
                        "YES" if sanction_docs else "NO",
                        "YES" if sanction_block else "NO",
                        _short_docs(risk_hits, limit=4) if risk_hits else "—",
                    ]
                )
                extra = f"sanction_docs={len(sanction_docs)}, sanction_blocking={sanction_block}"

            # Registry Match Test для кейса №1.
            if name == "Смартфон":
                before_status, before_match = _find_fss_status(docs)
                if fss_number:
                    test_item = _mk_item_data(description=description, article=fss_number)
                    test_bundle = build_compliance_document_items(
                        hs_code=hs_code,
                        item_data=test_item,
                        country=country,
                        db=db,
                    )
                    test_docs = list(test_bundle.get("documents") or [])
                    after_status, after_match = _find_fss_status(test_docs)
                    extra = (
                        f"FSS number used={fss_number}; "
                        f"before={before_status}/{(before_match or '∅')}; "
                        f"after={after_status}/{(after_match or '∅')}"
                    )
                else:
                    extra = "FSS test skipped: no fss_notifications records found"

            report_rows.append(
                [
                    name,
                    hs_code,
                    country,
                    "YES" if blocking else "NO",
                    str(len(docs)),
                    str(notes_count),
                    str(ai_count),
                    str(registry_count),
                    extra or "—",
                    _short_docs(docs, limit=5),
                ]
            )

    print("# Compliance Cases Test Report")
    print("")
    print("## Основные кейсы")
    print(
        _to_markdown_table(
            [
                "Кейс",
                "HS",
                "Country",
                "blocking_issue",
                "Docs",
                "Normative notes",
                "AI warnings",
                "Registry matches",
                "Доп. проверка",
                "Ключевые ComplianceDocumentItem",
            ],
            report_rows,
        )
    )
    print("")
    print("## Санкционные проверки (Germany/USA)")
    if sanction_rows:
        print(
            _to_markdown_table(
                ["Кейс", "Country", "Sanction docs", "Sanction blocking", "Найденные записи (sanction_import_risks / eu_sanctions_list)"],
                sanction_rows,
            )
        )
    else:
        print("Санкционные кейсы не выполнялись.")
    print("")
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

