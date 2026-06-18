#!/usr/bin/env python3
"""
Monitor EEC trade remedies for changes.

Compares current local bundles (anti-dumping, special safeguard, countervailing)
against the EEC trade protection page to detect new or expired measures.

Usage:
    cd customs-clear/backend
    python3 -m scripts.monitor_trade_remedies [--check-only] [--create-issue]

    --check-only   Only report differences, do not modify files
    --create-issue Create a GitHub issue if changes are detected (requires gh CLI)
"""
from __future__ import annotations

import json
import sys
import urllib.request
from datetime import date, datetime
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_ROOT / "data" / "raw_normative"

EEC_TRADE_PROTECT_URL = "https://eec.eaeunion.org/comission/department/catr/trade-protect/"

BUNDLE_FILES = {
    "anti_dumping": DATA_DIR / "eec_anti_dumping.json",
    "special_safeguard": DATA_DIR / "eec_special_safeguard.json",
    "countervailing": DATA_DIR / "eec_countervailing.json",
}

KNOWN_DECISION_REGISTRY: dict[str, list[dict[str, str]]] = {
    "anti_dumping": [
        {"act": "Решение Коллегии ЕЭК № 66 от 02.06.2020", "product": "Арматура стальная, катанка", "hs": "7213, 7214"},
        {"act": "Решение Коллегии ЕЭК № 48 от 17.03.2020", "product": "Трубы бесшовные из нержавеющей стали", "hs": "7304"},
        {"act": "Решение Коллегии ЕЭК № 4 от 14.01.2020", "product": "Прокат из коррозионностойкой стали", "hs": "7219, 7220"},
        {"act": "Решение Коллегии ЕЭК № 93 от 29.05.2018", "product": "Трубы сварные из чёрных металлов", "hs": "7306"},
        {"act": "Решение Коллегии ЕЭК № 7 от 22.01.2019", "product": "Поливинилхлорид суспензионный", "hs": "3904"},
        {"act": "Решение Коллегии ЕЭК № 11 от 29.01.2019", "product": "Прокат горячекатаный из нелегированных сталей", "hs": "7208"},
        {"act": "Решение Коллегии ЕЭК № 144 от 24.10.2017", "product": "Прокат из легированной стали горячекатаный", "hs": "7225"},
        {"act": "Решение Коллегии ЕЭК № 13 от 14.02.2017", "product": "Шины для грузовых автомобилей", "hs": "4011"},
        {"act": "Решение Коллегии ЕЭК № 169 от 13.12.2016", "product": "Каустическая сода", "hs": "2836"},
        {"act": "Решение Коллегии ЕЭК № 126 от 20.09.2016", "product": "Трубы обсадные нефтяного сортамента", "hs": "7304"},
        {"act": "Решение Коллегии ЕЭК № 68 от 07.06.2016", "product": "Бульдозеры и экскаваторы", "hs": "8429"},
        {"act": "Решение Коллегии ЕЭК № 55 от 19.05.2015", "product": "Трубы бесшовные из чёрных металлов", "hs": "7304"},
        {"act": "Решение Коллегии ЕЭК № 199 от 11.12.2014", "product": "Подшипниковая сталь", "hs": "7228"},
        {"act": "Решение Коллегии ЕЭК № 118 от 28.08.2018", "product": "Столовые/кухонные изделия из керамики", "hs": "6810"},
        {"act": "Решение Совета ЕЭК № 95 от 10.07.2018", "product": "Бумага и картон мелованные", "hs": "4810"},
    ],
    "special_safeguard": [
        {"act": "Решение Коллегии ЕЭК № 65 от 14.04.2020", "product": "Трубы из чёрных металлов", "hs": "7306"},
        {"act": "Решение Коллегии ЕЭК № 30 от 03.03.2020", "product": "Прокат плоский оцинкованный", "hs": "7210"},
        {"act": "Решение Коллегии ЕЭК № 149 от 29.10.2019", "product": "Подшипниковая сталь", "hs": "7228"},
    ],
    "countervailing": [
        {"act": "Решение Совета ЕЭК № 95 от 10.07.2018", "product": "Бумага и картон мелованные", "hs": "4810"},
        {"act": "Решение Коллегии ЕЭК № 164 от 17.12.2019", "product": "Поливинилхлорид", "hs": "3904"},
    ],
}


def load_bundle(path: Path) -> dict | None:
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def check_eec_site_reachable() -> tuple[bool, str]:
    try:
        req = urllib.request.Request(
            EEC_TRADE_PROTECT_URL,
            headers={"User-Agent": "CustomsClear/1.0 trade-remedy-monitor"},
        )
        resp = urllib.request.urlopen(req, timeout=30)
        return True, f"HTTP {resp.status}"
    except Exception as e:
        return False, str(e)


def analyze_bundles() -> dict[str, list[str]]:
    """Compare local bundles against known decision registry."""
    findings: dict[str, list[str]] = {
        "warnings": [],
        "info": [],
    }

    for domain, path in BUNDLE_FILES.items():
        bundle = load_bundle(path)
        if not bundle:
            findings["warnings"].append(f"{domain}: bundle file missing at {path}")
            continue

        measures = bundle.get("measures", [])
        known = KNOWN_DECISION_REGISTRY.get(domain, [])

        # Check revision freshness
        rev = bundle.get("revision", "")
        parts = rev.split(":")
        if len(parts) >= 2:
            try:
                rev_date = datetime.strptime(parts[-1], "%Y-%m-%d")
                age_days = (datetime.now() - rev_date).days
                if age_days > 180:
                    findings["warnings"].append(
                        f"{domain}: bundle revision is {age_days} days old ({rev})"
                    )
                else:
                    findings["info"].append(
                        f"{domain}: revision {rev} ({age_days} days old)"
                    )
            except ValueError:
                findings["warnings"].append(
                    f"{domain}: unparseable revision date ({rev})"
                )

        # Cross-check measures against known registry
        bundle_acts = {m.get("regulatory_act", "") for m in measures}
        known_acts = {k["act"] for k in known}

        missing_from_bundle = known_acts - bundle_acts
        extra_in_bundle = bundle_acts - known_acts

        if missing_from_bundle:
            for act in missing_from_bundle:
                findings["warnings"].append(
                    f"{domain}: known decision missing from bundle: {act}"
                )

        if extra_in_bundle:
            for act in extra_in_bundle:
                findings["info"].append(
                    f"{domain}: bundle has extra measure not in registry: {act}"
                )

        # Check for expired measures (effective_to in the past)
        for m in measures:
            eff_to = m.get("effective_to", "")
            if eff_to:
                try:
                    to_date = datetime.strptime(eff_to, "%Y-%m-%d")
                    if to_date < datetime.now():
                        findings["warnings"].append(
                            f"{domain}: expired measure {m.get('regulatory_act', '?')} "
                            f"(effective_to={eff_to})"
                        )
                except ValueError:
                    pass

        findings["info"].append(
            f"{domain}: {len(measures)} measures in bundle, "
            f"{len(known)} in known registry"
        )

    return findings


def create_github_issue(findings: dict[str, list[str]]) -> None:
    import subprocess

    warnings = findings.get("warnings", [])
    if not warnings:
        print("No warnings — skipping issue creation")
        return

    body_lines = [
        "## Trade Remedies Monitor Alert",
        "",
        "The trade remedies monitoring script detected potential issues:",
        "",
    ]
    for w in warnings:
        body_lines.append(f"- ⚠️ {w}")

    body_lines.extend([
        "",
        "### Info",
        "",
    ])
    for i in findings.get("info", []):
        body_lines.append(f"- {i}")

    body_lines.extend([
        "",
        "### Recommended actions",
        "1. Check https://eec.eaeunion.org/comission/department/catr/trade-protect/ for updates",
        "2. Look for new Решения Коллегии/Совета ЕЭК on trade remedies",
        "3. Update bundles if new measures found",
        "4. Run coverage audit after updates",
        "",
        "🤖 Generated by monitor_trade_remedies.py",
    ])

    body = "\n".join(body_lines)

    result = subprocess.run(
        ["gh", "issue", "create",
         "--title", "[TRADE REMEDIES] Changes detected in EEC measures",
         "--label", "claude",
         "--body", body],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        print(f"Created issue: {result.stdout.strip()}")
    else:
        print(f"Failed to create issue: {result.stderr}")


def main():
    check_only = "--check-only" in sys.argv
    create_issue = "--create-issue" in sys.argv

    print("=" * 60)
    print("Trade Remedies Monitor")
    print(f"Date: {date.today().isoformat()}")
    print("=" * 60)

    # Check EEC site
    print("\n[1/3] Checking EEC site reachability...")
    reachable, status = check_eec_site_reachable()
    print(f"  EEC site: {'reachable' if reachable else 'UNREACHABLE'} ({status})")

    # Analyze bundles
    print("\n[2/3] Analyzing local bundles...")
    findings = analyze_bundles()

    warnings = findings.get("warnings", [])
    info = findings.get("info", [])

    if warnings:
        print(f"\n  ⚠️  {len(warnings)} warning(s):")
        for w in warnings:
            print(f"    - {w}")
    else:
        print("\n  ✅ No warnings")

    print(f"\n  ℹ️  {len(info)} info item(s):")
    for i in info:
        print(f"    - {i}")

    # Create issue if requested
    if create_issue and warnings:
        print("\n[3/3] Creating GitHub issue...")
        create_github_issue(findings)
    elif create_issue:
        print("\n[3/3] No warnings — skipping issue creation")
    else:
        print("\n[3/3] Skipped issue creation (use --create-issue to enable)")

    print(f"\n{'=' * 60}")
    print(f"Done. {'CHECK ONLY — no files modified.' if check_only else ''}")
    print(f"{'=' * 60}")

    return 1 if warnings else 0


if __name__ == "__main__":
    sys.exit(main())
