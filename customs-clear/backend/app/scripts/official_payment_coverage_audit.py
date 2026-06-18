"""Runnable read-only official payment coverage audit report (issue #55)."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from app.services.official_payment_coverage_audit import run_official_payment_coverage_audit

STABLE_REPORT_TOP_LEVEL_KEYS: frozenset[str] = frozenset(
    {
        "status",
        "generated_at",
        "db_mutated",
        "domains",
        "summary",
        "trade_remedies_aggregate",
        "notes",
    }
)

STABLE_DOMAIN_AUDIT_KEYS: frozenset[str] = frozenset(
    {
        "domain",
        "domain_key",
        "expected_official_source",
        "configured_official_source",
        "local_bundle_present",
        "local_bundle_path",
        "source_revision",
        "source_url",
        "row_count",
        "official_row_count",
        "legacy_row_count",
        "parsed_rows",
        "missing_source",
        "parser_failed",
        "manual_review_required",
        "source_present_but_not_applied",
        "stale_source_status",
        "unsafe_revision",
        "unsafe_url",
        "partial_rows",
        "domain_unsupported",
        "coverage_status",
        "known_gaps",
        "recommended_next_action",
        "backfill_situation",
        "backfill_notes",
        "countervailing_source_url",
        "countervailing_synced_at",
    }
)

STABLE_SUMMARY_KEYS: frozenset[str] = frozenset(
    {
        "domain_count",
        "by_coverage_status",
        "by_recommended_next_action",
    }
)


def build_report() -> dict[str, Any]:
    """Собрать детерминированный read-only отчёт аудита."""
    return run_official_payment_coverage_audit()


def dump_report_json(report: dict[str, Any]) -> str:
    """Сериализовать отчёт в стабильный JSON для CI/admin UI."""
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run read-only official payment coverage audit against the current DB "
            "and print an actionable backfill plan as JSON."
        )
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON report (default output format).",
    )
    parser.parse_args(argv)

    report = build_report()
    print(dump_report_json(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
