#!/usr/bin/env python3
"""Собирает справочные коды всех шести контрольных списков РФ.

Официальные publication.pravo.gov.ru URL сохраняются как source of truth. Для
воспроизводимого извлечения кодов используется HTML-зеркало Alta: берутся только
ссылки с классом ``ordw-tnved`` из действующей редакции, а не произвольные числа
или коды из вложенных блоков ``content-old`` с предыдущими редакциями.
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.request
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = BACKEND_ROOT / "data" / "official_export_control_rules.seed.json"

SOURCES = (
    (1284, "Химическое оружие", "https://publication.pravo.gov.ru/Document/View/0001202207190026"),
    (1285, "Ядерные материалы и оборудование", "https://publication.pravo.gov.ru/Document/View/0001202207190029"),
    (1286, "Двойное назначение в ядерных целях", "https://publication.pravo.gov.ru/Document/View/0001202207190018"),
    (1287, "Микроорганизмы, токсины и оборудование", "https://publication.pravo.gov.ru/Document/View/0001202207190030"),
    (1288, "Ракетное оружие", "https://publication.pravo.gov.ru/Document/View/0001202207190036"),
    (1299, "Двойное назначение для вооружений и военной техники", "https://publication.pravo.gov.ru/Document/View/0001202207220041"),
)

# Alta сохраняет source-faithful ссылки всех действующих строк списков. При этом
# отдельные строки ПП РФ №1299 всё ещё содержат прежние 10-значные коды, уже
# заменённые ПП РФ №698 и отсутствующие в текущей редакции ЕТН ВЭД ЕАЭС. Сырые
# ссылки остаются в source_lists для аудита источника, а этот версионированный
# слой запрещает использовать отменённые точные коды как runtime-кандидаты.
RETIRED_EXACT_CODES = {
    "schema_version": "1",
    "catalog_revision": "ett:2026-06-18",
    "effective_from": "2026-06-04",
    "basis": "Постановление Правительства РФ от 04.06.2026 №698",
    "basis_url": "https://publication.pravo.gov.ru/document/0001202606040049",
    "codes": (
        {"hs_code": "3910000002", "replacement_code": "3910000006"},
        {"hs_code": "3910000008", "replacement_code": "3910000009"},
    ),
}


class _TnvedLinkParser(HTMLParser):
    _VOID_ELEMENTS = frozenset({
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    })

    def __init__(self) -> None:
        super().__init__()
        self.in_tnved_link = False
        self.codes: set[str] = set()
        self._content_old_ancestors = 0
        self._open_tags: list[tuple[str, bool, bool]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        classes = str(values.get("class") or "").split()
        starts_old_block = "content-old" in classes
        if starts_old_block:
            self._content_old_ancestors += 1
        starts_tnved_link = (
            tag == "a"
            and "ordw-tnved" in classes
            and self._content_old_ancestors == 0
        )
        if tag not in self._VOID_ELEMENTS:
            self._open_tags.append((tag, starts_old_block, starts_tnved_link))
        self.in_tnved_link = any(row[2] for row in self._open_tags)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self._open_tags) - 1, -1, -1):
            if self._open_tags[index][0] != tag:
                continue
            popped = self._open_tags[index:]
            del self._open_tags[index:]
            self._content_old_ancestors -= sum(row[1] for row in popped)
            break
        self.in_tnved_link = any(row[2] for row in self._open_tags)

    def handle_data(self, data: str) -> None:
        if not self.in_tnved_link:
            return
        code = re.sub(r"\D", "", data)
        if 4 <= len(code) <= 10:
            self.codes.add(code)


def _download(url: str, timeout: float) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "Tariff-NTM-dataset-builder/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def build_dataset(timeout: float = 60.0) -> dict[str, object]:
    source_lists: list[dict[str, object]] = []
    union: set[str] = set()
    for number, title, official_url in SOURCES:
        mirror_url = f"https://www.alta.ru/tamdoc/22ps{number}/"
        parser = _TnvedLinkParser()
        parser.feed(_download(mirror_url, timeout))
        codes = sorted(parser.codes, key=lambda value: (len(value), value))
        if not codes:
            raise RuntimeError(f"no TN VED links extracted for PP RF {number}")
        union.update(codes)
        source_lists.append({
            "number": number,
            "title": title,
            "official_url": official_url,
            "extraction_reference_url": mirror_url,
            "hs_candidates": codes,
        })
    return {
        "schema_version": "2",
        "dataset_id": "rf_export_control_all_lists_hs_candidates",
        "legal_source": "ПП РФ №1284–1288 и №1299 — шесть списков экспортного контроля",
        "source_url": SOURCES[-1][2],
        "current_revision_note": (
            "HS-коды являются справочными; решают наименование, назначение и технические параметры. "
            "Перед сделкой проверяется актуальная редакция каждого официального списка."
        ),
        "applicability": "needs_clarification",
        "direction": "export",
        "permit_type": "ЛЗ/разрешение ФСТЭК",
        "extracted_at": date.today().isoformat(),
        "retired_exact_codes": {
            **RETIRED_EXACT_CODES,
            "codes": [dict(row) for row in RETIRED_EXACT_CODES["codes"]],
        },
        "source_lists": source_lists,
        "hs_candidates": sorted(union, key=lambda value: (len(value), value)),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--check", action="store_true", help="Compare remote extraction with committed dataset")
    args = parser.parse_args()
    payload = build_dataset(args.timeout)
    raw_candidate_count = len(payload["hs_candidates"])
    retired_exact_code_count = len(payload["retired_exact_codes"]["codes"])
    summary = {
        "output": str(args.output),
        "source_lists": len(payload["source_lists"]),
        "hs_candidates": raw_candidate_count,
        "raw_hs_candidates": raw_candidate_count,
        "effective_hs_candidates": raw_candidate_count - retired_exact_code_count,
        "retired_exact_codes": retired_exact_code_count,
        "source_counts": {
            str(row["number"]): len(row["hs_candidates"])
            for row in payload["source_lists"]
        },
    }
    if args.check:
        if not args.output.is_file():
            summary.update({"ok": False, "error": "committed dataset not found"})
            print(json.dumps(summary, ensure_ascii=False))
            return 1
        committed = json.loads(args.output.read_text(encoding="utf-8"))
        committed.pop("extracted_at", None)
        candidate = dict(payload)
        candidate.pop("extracted_at", None)
        summary["ok"] = committed == candidate
        if not summary["ok"]:
            summary["error"] = "remote extraction differs from committed dataset"
        print(json.dumps(summary, ensure_ascii=False))
        return 0 if summary["ok"] else 1
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary["ok"] = True
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
