#!/usr/bin/env python3
"""
Еженедельная проверка trade remedies (антидемпинг / СЗМ / компенсационные).

Сравнивает локальные bundle-файлы и БД с доступностью официального портала ЕЭК.
При обнаружении расхождений или устаревших данных создаёт GitHub issue с label
``data-update``. **Не** добавляет меры в БД автоматически.

Usage:
    cd customs-clear/backend
    python3 -m scripts.sync_trade_remedies [--check-only] [--create-issue]

    --check-only    Только отчёт, без создания issue
    --create-issue  Создать issue при наличии предупреждений (нужен gh CLI)
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_ROOT / "data" / "raw_normative"
DB_PATH = BACKEND_ROOT / "customs.db"

REMEDIES_PORTAL_URL = "https://remedies.eaeunion.org/dimd/ru"
DOCS_SEARCH_URL = "https://docs.eaeunion.org/Pages/SearchDocumentsPage.aspx"

BUNDLE_FILES = {
    "anti_dumping": DATA_DIR / "eec_anti_dumping.json",
    "special_safeguard": DATA_DIR / "eec_special_safeguard.json",
    "countervailing": DATA_DIR / "eec_countervailing.json",
}

# Ожидаемые ключевые меры (аудит 2026-06-23) — для smoke-проверки полноты bundle.
EXPECTED_AD_ACTS: tuple[str, ...] = (
    "Решение Коллегии ЕЭК № 97 от 14.10.2025",
    "Решение Коллегии ЕЭК № 96 от 14.10.2025",
    "Решение Коллегии ЕЭК № 62 от 25.05.2026 (продление № 115)",
    "Решение Коллегии ЕЭК № 12 от 09.02.2021; продлено № 4 от 20.01.2026",
)

MAX_BUNDLE_AGE_DAYS = 7


def _http_status(url: str, *, timeout: int = 30) -> tuple[int | None, str]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "CustomsClear/1.0 sync-trade-remedies"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return int(resp.status), "ok"
    except Exception as exc:
        return None, str(exc)


def _load_bundle(path: Path) -> dict | None:
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _bundle_revision_age_days(revision: str) -> int | None:
    parts = revision.split(":")
    if len(parts) < 2:
        return None
    try:
        rev_date = datetime.strptime(parts[-1], "%Y-%m-%d")
    except ValueError:
        return None
    return (datetime.now() - rev_date).days


def _count_db_measures() -> dict[str, int]:
    if not DB_PATH.exists():
        return {}
    conn = sqlite3.connect(DB_PATH)
    try:
        rows = conn.execute(
            """
            SELECT measure_type, COUNT(*)
            FROM special_duties
            GROUP BY measure_type
            """
        ).fetchall()
        return {str(mt): int(cnt) for mt, cnt in rows}
    finally:
        conn.close()


def analyze() -> dict[str, list[str]]:
    findings: dict[str, list[str]] = {"warnings": [], "info": []}

    status, detail = _http_status(REMEDIES_PORTAL_URL)
    if status == 200:
        findings["info"].append(f"Портал remedies.eaeunion.org доступен (HTTP {status})")
    else:
        findings["warnings"].append(
            f"Портал remedies.eaeunion.org недоступен ({status or 'error'}: {detail})"
        )
        docs_status, docs_detail = _http_status(DOCS_SEARCH_URL)
        if docs_status == 200:
            findings["info"].append(f"Fallback docs.eaeunion.org доступен (HTTP {docs_status})")
        else:
            findings["warnings"].append(
                f"Fallback docs.eaeunion.org недоступен ({docs_status or 'error'}: {docs_detail})"
            )

    for domain, path in BUNDLE_FILES.items():
        bundle = _load_bundle(path)
        if not bundle:
            findings["warnings"].append(f"{domain}: bundle отсутствует ({path})")
            continue

        rev = str(bundle.get("revision") or "")
        age = _bundle_revision_age_days(rev)
        if age is None:
            findings["warnings"].append(f"{domain}: неразборная revision ({rev})")
        elif age > MAX_BUNDLE_AGE_DAYS:
            findings["warnings"].append(
                f"{domain}: revision устарела на {age} дн. ({rev}); требуется ручная сверка с ЕЭК"
            )
        else:
            findings["info"].append(f"{domain}: revision {rev} ({age} дн.)")

        official_url = str(bundle.get("official_url") or "")
        if REMEDIES_PORTAL_URL not in official_url:
            findings["warnings"].append(
                f"{domain}: official_url не указывает на remedies.eaeunion.org ({official_url})"
            )

        measures = bundle.get("measures") or []
        findings["info"].append(f"{domain}: {len(measures)} мер в bundle")

        if domain == "anti_dumping":
            acts = {str(m.get("regulatory_act") or "") for m in measures}
            for expected in EXPECTED_AD_ACTS:
                if expected not in acts:
                    findings["warnings"].append(
                        f"anti_dumping: отсутствует ожидаемая мера в bundle: {expected}"
                    )

    db_counts = _count_db_measures()
    if db_counts:
        summary = ", ".join(f"{k}={v}" for k, v in sorted(db_counts.items()))
        findings["info"].append(f"special_duties в БД: {summary}")
    else:
        findings["warnings"].append("special_duties: БД недоступна или таблица пуста")

    return findings


def create_github_issue(findings: dict[str, list[str]]) -> None:
    warnings = findings.get("warnings") or []
    if not warnings:
        print("Нет предупреждений — issue не создаётся")
        return

    body_lines = [
        "## Trade remedies — требуется обновление данных",
        "",
        "Скрипт `sync_trade_remedies.py` обнаружил расхождения. **Авто-импорт не выполнялся.**",
        "",
        "### Предупреждения",
        "",
    ]
    for w in warnings:
        body_lines.append(f"- ⚠️ {w}")

    body_lines.extend(["", "### Информация", ""])
    for item in findings.get("info") or []:
        body_lines.append(f"- {item}")

    body_lines.extend(
        [
            "",
            "### Рекомендуемые действия",
            f"1. Сверить меры на {REMEDIES_PORTAL_URL}",
            "2. Обновить `data/raw_normative/eec_*.json` вручную после проверки",
            "3. Запустить `python3 -m scripts.anti_dumping_ingestion apply` (после review PR)",
            "4. Обновить Alembic/миграцию при изменении схемы",
            "",
            "🤖 Generated by sync_trade_remedies.py",
        ]
    )

    result = subprocess.run(
        [
            "gh",
            "issue",
            "create",
            "--title",
            "[data-update] Trade remedies: требуется сверка с ЕЭК",
            "--label",
            "data-update",
            "--body",
            "\n".join(body_lines),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        print(f"Создан issue: {result.stdout.strip()}")
    else:
        print(f"Не удалось создать issue: {result.stderr.strip()}")


def main() -> int:
    check_only = "--check-only" in sys.argv
    create_issue = "--create-issue" in sys.argv

    print("=" * 60)
    print("Sync Trade Remedies (weekly check)")
    print(f"Дата: {datetime.now().date().isoformat()}")
    print("=" * 60)

    findings = analyze()
    warnings = findings.get("warnings") or []
    info = findings.get("info") or []

    if warnings:
        print(f"\n⚠️  {len(warnings)} предупреждений:")
        for w in warnings:
            print(f"  - {w}")
    else:
        print("\n✅ Предупреждений нет")

    print(f"\nℹ️  {len(info)} информационных записей:")
    for item in info:
        print(f"  - {item}")

    if create_issue and not check_only:
        print("\nСоздание GitHub issue…")
        create_github_issue(findings)
    elif create_issue:
        print("\n--check-only: issue не создаётся")

    print("\n" + "=" * 60)
    return 1 if warnings else 0


if __name__ == "__main__":
    sys.exit(main())
