#!/usr/bin/env python3
"""
Проверка publication.pravo.gov.ru на новые постановления по ставкам РОП.
При обнаружении — создаёт GitHub issue (если задан GITHUB_TOKEN).

Запуск: PYTHONPATH=. python3 scripts/check_rop_rates_update.py
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

PRAVO_SEARCH = "http://publication.pravo.gov.ru/api/Documents?numberDoc=1041&yearDoc=2024"
LOCAL_RATES = _ROOT / "data" / "rop_rates_2024.json"
TIMEOUT = 20


def _fetch(url: str) -> str | None:
    try:
        req = Request(url, headers={"User-Agent": "tnved-rop-check/1.0"})
        with urlopen(req, timeout=TIMEOUT) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except (URLError, TimeoutError, OSError):
        return None


def _local_legal_ref() -> str:
    if not LOCAL_RATES.is_file():
        return ""
    doc = json.loads(LOCAL_RATES.read_text(encoding="utf-8"))
    return str(doc.get("legal_ref") or "")


def _create_issue(title: str, body: str) -> bool:
    token = os.getenv("GITHUB_TOKEN", "").strip()
    repo = os.getenv("GITHUB_REPOSITORY", "").strip()
    if not token or not repo:
        print("SKIP issue: GITHUB_TOKEN or GITHUB_REPOSITORY not set")
        return False
    try:
        subprocess.run(
            [
                "gh", "issue", "create",
                "--repo", repo,
                "--title", title,
                "--body", body,
                "--label", "data-refresh",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"WARN: gh issue create failed: {exc}")
        return False


def main() -> int:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    local_ref = _local_legal_ref()
    api_body = _fetch(PRAVO_SEARCH)
    stale_hint = False
    details: list[str] = [f"Checked at: {now}", f"Local legal_ref: {local_ref or '(missing JSON)'}"]

    if api_body:
        details.append("pravo.gov.ru API: reachable")
        if re.search(r"1041|экологическ", api_body, flags=re.IGNORECASE):
            details.append("Document 1041 reference found in API response")
        else:
            stale_hint = True
            details.append("WARNING: expected PP 1041 markers not found — manual review needed")
    else:
        stale_hint = True
        details.append("pravo.gov.ru API: unreachable")

    # Ежегодное напоминание: ставки индексируются, Минприроды готовит предложения к 1 сентября
    month = datetime.now().month
    if month == 12:
        stale_hint = True
        details.append("December check: verify upcoming ROP rate indexation for next calendar year")

    print("\n".join(details))

    if stale_hint:
        title = "ROP rates: scheduled check — review official PP updates"
        body = "\n".join([
            "## ROP rates freshness check",
            "",
            *details,
            "",
            "Action: compare publication.pravo.gov.ru PP 1041 (and successors) with",
            "`customs-clear/backend/data/rop_rates_2024.json`, then run:",
            "",
            "```bash",
            "cd customs-clear/backend",
            "PYTHONPATH=. python3 scripts/build_rop_rates_json.py",
            "PYTHONPATH=. python3 scripts/import_rop_rates.py",
            "```",
        ])
        if _create_issue(title, body):
            print("Created GitHub issue")
        return 1
    print("OK: no update action required")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
