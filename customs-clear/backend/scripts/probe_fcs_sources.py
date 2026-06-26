#!/usr/bin/env python3
"""Проба доступности официальных источников предварительных решений по классификации.

Фиксирует фактическое состояние источников ПКР/предрешений ФТС и ЕЭК, чтобы
не строить парсер на неработающем/неверном источнике. Результаты проверены
вручную 2026-06 и закреплены этим скриптом как воспроизводимый артефакт.

Ключевая находка: ``customs.gov.ru/folder/519`` — раздел **таможенной
статистики** (экспорт/импорт по товарам), а НЕ реестр предрешений. Реальные
предрешения публикуются за JS/анти-бот барьерами (см. verdict ниже).

Запуск из ``customs-clear/backend``::

  PYTHONPATH=. python3 scripts/probe_fcs_sources.py
  PYTHONPATH=. python3 scripts/probe_fcs_sources.py --json
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field

try:
    import httpx
except Exception:  # pragma: no cover - httpx есть в зависимостях проекта
    httpx = None  # type: ignore


@dataclass(frozen=True)
class SourceCandidate:
    code: str
    url: str
    note: str
    # Ожидаемый характер источника: usable_html | js_rendered | antibot | wrong_section | unknown
    expected_kind: str = "unknown"


# Кандидаты-источники предрешений/классификационных решений (проверены вручную).
FCS_SOURCE_CANDIDATES: tuple[SourceCandidate, ...] = (
    SourceCandidate(
        code="customs_folder_519",
        url="https://customs.gov.ru/folder/519",
        note="Указан в задаче, но это раздел ТАМОЖЕННОЙ СТАТИСТИКИ, не предрешения.",
        expected_kind="wrong_section",
    ),
    SourceCandidate(
        code="customs_document",
        url="https://customs.gov.ru/document",
        note="Прежний FCS_OFFICIAL_URL — отдаёт 404.",
        expected_kind="unknown",
    ),
    SourceCandidate(
        code="customs_root",
        url="https://customs.gov.ru/",
        note="Корень портала ФТС (доступен).",
        expected_kind="usable_html",
    ),
    SourceCandidate(
        code="tks_predecision",
        url="https://www.tks.ru/db/tnved/predecision/",
        note="Реестр ПКР на TKS: результаты рендерятся клиентским JS (HTTP-ответ без таблицы).",
        expected_kind="js_rendered",
    ),
    SourceCandidate(
        code="alta_clasres",
        url="https://www.alta.ru/clasres/",
        note="Реестр КР на Alta: анти-бот (403) при программном доступе.",
        expected_kind="antibot",
    ),
)


def classify_status(status_code: int | None, expected_kind: str) -> str:
    """Чистая (тестируемая) логика вердикта по HTTP-статусу и ожидаемому виду источника."""
    if status_code is None:
        return "unreachable"
    if status_code in (403, 429):
        return "antibot"
    if status_code == 404:
        return "not_found"
    if 200 <= status_code < 300:
        if expected_kind == "wrong_section":
            return "reachable_but_wrong_section"
        if expected_kind == "js_rendered":
            return "reachable_but_js_rendered"
        return "reachable"
    if status_code >= 500:
        return "server_error"
    return "other"


def _probe_one(c: SourceCandidate, *, timeout: float) -> dict:
    status: int | None = None
    error = ""
    if httpx is not None:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "ru-RU,ru;q=0.9",
        }
        try:
            with httpx.Client(follow_redirects=True, timeout=timeout) as client:
                r = client.get(c.url, headers=headers)
                status = int(r.status_code)
        except Exception as exc:  # network/timeout
            error = f"{type(exc).__name__}: {exc}"
    else:
        error = "httpx недоступен"
    verdict = classify_status(status, c.expected_kind)
    return {
        "code": c.code,
        "url": c.url,
        "status_code": status,
        "verdict": verdict,
        "expected_kind": c.expected_kind,
        "note": c.note,
        "error": error,
    }


def probe(*, timeout: float = 15.0) -> dict:
    results = [_probe_one(c, timeout=timeout) for c in FCS_SOURCE_CANDIDATES]
    usable = [r for r in results if r["verdict"] == "reachable"]
    return {
        "status": "OK",
        "results": results,
        "summary": {
            "total": len(results),
            "directly_usable_html": len(usable),
            "blocked_or_wrong": len(results) - len(usable),
        },
        "conclusion": (
            "Нет HTTP-доступного источника реальных предрешений ФТС: folder/519 — "
            "статистика; customs.gov.ru/document — 404; TKS — клиентский JS; "
            "Alta — анти-бот (403). Реальный live-ingest требует Playwright+сессию "
            "(см. sync_tks_predecisions.py) либо официального open-data фида. "
            "До этого источник истины — fixture с честной маркировкой (FCS-/fcs_official)."
        ),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Проба доступности источников предрешений ФТС/ЕЭК")
    ap.add_argument("--json", action="store_true", help="Вывести JSON")
    ap.add_argument("--timeout", type=float, default=15.0)
    args = ap.parse_args()
    result = probe(timeout=args.timeout)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    for r in result["results"]:
        print(f"{str(r['status_code']):>4}  {r['verdict']:<28}  {r['url']}")
        print(f"      {r['note']}")
    print("\n" + result["conclusion"])


if __name__ == "__main__":
    main()
