#!/usr/bin/env python3
"""Сборка data/declaration_documents_chapters.json из официальных контуров.

Источники (только из seed_regulatory_documents.py, без выдуманных документов):
- Решения ЕЭК №317, №318, №157, №299, №30
- Технические регламенты ТР ТС / ТР ЕАЭС (TR_TS_DOCS)

Примечание: «Решение ЕЭК №172 от 16.10.2018» о перечне документов ДТ в реестре ЕЭС
отсутствует; №172/2022 — о предварительных решениях по классификации.
Общие документы — ТК ЕАЭС ст.108 (см. UNIVERSAL в seed_declaration_documents.py).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from scripts.seed_regulatory_documents import EEC_DECISIONS, TR_TS_DOCS  # noqa: E402

TARGET_CHAPTERS = frozenset(
    {"07", "15", "17", "27", "28", "29", "39", "44", "48", "52", "55", "70", "72", "73"}
)

OUTPUT = BACKEND_ROOT / "data" / "declaration_documents_chapters.json"


def _chapter_of(hs: str) -> str:
    hs = (hs or "").strip()
    return hs[:2].zfill(2) if hs else ""


def _in_target(hs: str) -> bool:
    return _chapter_of(hs) in TARGET_CHAPTERS


def _eec_chapter_docs() -> list[dict]:
    rows: list[dict] = []
    templates = {
        "317": {
            "type": "vet_cert",
            "name": "Ветеринарный сертификат (ветеринарно-санитарный контроль)",
            "mandatory": True,
            "cat": "conformity",
            "legal": "Решение КТС от 18.06.2010 №317; ТК ЕАЭС ст.108 п.1 пп.9",
        },
        "318": {
            "type": "phyto_cert",
            "name": "Фитосанитарный сертификат (карантин растений)",
            "mandatory": True,
            "cat": "conformity",
            "legal": "Решение КТС от 18.06.2010 №318; ТК ЕАЭС ст.108 п.1 пп.9",
        },
        "157": {
            "type": "phyto_cert",
            "name": "Фитосанитарный сертификат (единый перечень подкарантинной продукции)",
            "mandatory": True,
            "cat": "conformity",
            "legal": "Решение КТС от 18.11.2011 №157; ТК ЕАЭС ст.108",
            "cond": "Для продукции из единого перечня подкарантинной продукции",
        },
        "299": {
            "type": "SGR",
            "name": "Свидетельство о государственной регистрации (СГР)",
            "mandatory": True,
            "cat": "conformity",
            "legal": "Решение КТС от 28.06.2010 №299; ТК ЕАЭС ст.108 п.1 пп.9",
            "cond": "Для продукции, подлежащей санитарным мерам ЕАЭС (перечень Решения №299)",
        },
        "30": {
            "type": "import_license",
            "name": "Лицензия / разрешение на ввоз (лицензируемая продукция)",
            "mandatory": False,
            "cat": "special",
            "legal": "Решение КТС от 27.01.2012 №30; ТК ЕАЭС ст.108 п.1 пп.9",
            "cond": "Для товаров, включённых в перечень лицензируемого импорта",
        },
    }

    for dec in EEC_DECISIONS:
        num = str(dec.get("num", ""))
        tpl = templates.get(num)
        if not tpl:
            continue
        hs_keys: set[str] = set()
        for ch in dec.get("hs_chapters") or []:
            chs = str(ch).zfill(2)
            if _in_target(chs):
                hs_keys.add(chs)
        for pref in dec.get("hs_prefixes") or []:
            pref = str(pref).strip()
            if _in_target(pref):
                hs_keys.add(pref)
        for hs in sorted(hs_keys):
            rows.append(
                {
                    "hs": hs,
                    "type": tpl["type"],
                    "name": tpl["name"],
                    "mandatory": tpl["mandatory"],
                    "cat": tpl["cat"],
                    "legal": tpl["legal"],
                    **({"cond": tpl["cond"]} if tpl.get("cond") else {}),
                    "source": f"EEC-{num}",
                }
            )
    return rows


def _tr_ts_chapter_docs() -> list[dict]:
    rows: list[dict] = []
    for tr in TR_TS_DOCS:
        code = str(tr.get("code", ""))
        title = str(tr.get("title", ""))
        form = str(tr.get("form", "ДС"))
        legal = f"ТР ТС {code} «{title}»; ТК ЕАЭС ст.108 п.1 пп.9"
        templates: list[dict] = []
        if "СС" in form:
            templates.append(
                {
                    "type": "cert_conform",
                    "name": f"Сертификат соответствия (ТР ТС {code})",
                    "cond": "Если форма оценки соответствия — сертификация (СС)",
                }
            )
        if "ДС" in form:
            templates.append(
                {
                    "type": "decl_conform",
                    "name": f"Декларация о соответствии (ТР ТС {code})",
                    "cond": "Если форма оценки соответствия — декларирование (ДС)",
                }
            )
        for hs_raw in tr.get("hs") or []:
            hs = str(hs_raw).strip()
            if len(hs) <= 2:
                hs = hs.zfill(2)
            if not _in_target(hs):
                continue
            for tpl in templates:
                rows.append(
                    {
                        "hs": hs,
                        "type": tpl["type"],
                        "name": tpl["name"],
                        "mandatory": True,
                        "cat": "conformity",
                        "legal": legal,
                        "cond": tpl["cond"],
                        "source": f"TR-TS-{code}",
                    }
                )
    seen: set[tuple[str, str, str]] = set()
    out: list[dict] = []
    for r in rows:
        key = (r["hs"], r["type"], r["name"])
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def build() -> dict:
    specific = _eec_chapter_docs() + _tr_ts_chapter_docs()
    covered = sorted({_chapter_of(r["hs"]) for r in specific})
    missing = sorted(TARGET_CHAPTERS - set(covered))
    return {
        "meta": {
            "sources": [
                "ТК ЕАЭС ст.108 (общие документы — UNIVERSAL seed)",
                "Решения ЕЭК №317, №318, №157, №299, №30",
                "Технические регламенты ТР ТС/ЕАЭС (TR_TS_DOCS)",
            ],
            "note": (
                "Решение ЕЭК №172 от 16.10.2018 о перечне документов ДТ в официальном реестре "
                "не найдено; записи только при явной привязке TR ТС / решений ЕЭК "
                "(префикс ТН ВЭД или глава из hs_chapters)."
            ),
            "target_chapters": sorted(TARGET_CHAPTERS),
            "covered_chapters": covered,
            "chapters_without_specific_source": missing,
        },
        "specific": specific,
    }


def main() -> int:
    payload = build()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {OUTPUT} — {len(payload['specific'])} chapter-specific rows")
    print(f"Covered: {payload['meta']['covered_chapters']}")
    print(f"No specific official binding: {payload['meta']['chapters_without_specific_source']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
