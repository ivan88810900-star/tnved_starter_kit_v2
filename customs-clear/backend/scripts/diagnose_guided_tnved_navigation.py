#!/usr/bin/env python3
"""Read-only acceptance для Canonical-backed guided TN VED.

Отчёт содержит только агрегаты: 10-значные товарные коды, названия товаров и
тексты смысловых групп в JSON не записываются.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

# Должно быть выставлено до импорта app.db.
os.environ.setdefault("CUSTOMSCLEAR_READ_ONLY", "1")

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db import SessionLocal  # noqa: E402
from app.services.guided_tnved_navigation import (  # noqa: E402
    build_guided_tnved_navigation,
)

DEFAULT_HEADINGS = ("0302", "0303", "5208", "8517")


def _normalise_title(raw: str) -> str:
    return " ".join((raw or "").casefold().split())


def _unsplit_code_count(node: dict) -> int:
    """Число прямых кодовых вариантов до следующего пользовательского шага.

    Глубокие canonical-потомки уже свёрнуты внутри собственного варианта и не
    должны искусственно завышать нагрузку первого экрана. Их полнота отдельно
    контролируется expected/reachable/canonical coverage.
    """

    return sum(
        1
        for child in node.get("children") or []
        if child.get("role") != "semantic_choice" and child.get("code")
    )


def _hierarchy_checks(heading: str, choices: list[dict]) -> dict[str, bool]:
    """Проверки целевой структуры без записи названий/кодов в отчёт."""

    top = {_normalise_title(node.get("title") or ""): node for node in choices}
    if heading == "0302":
        return {
            "required_top_groups": {
                "лососевые",
                "камбалообразные",
                "тунец",
            }.issubset(top)
        }
    if heading == "0303":
        tuna = top.get("тунец")
        if tuna is None:
            return {
                "tuna_parent_present": False,
                "tuna_unsplit_span_lt_20": False,
                "tuna_species_nested": False,
            }
        subgroups = {
            _normalise_title(node.get("title") or "")
            for node in tuna.get("children") or []
            if node.get("kind") == "classification_subgroup"
        }
        return {
            "tuna_parent_present": True,
            "tuna_unsplit_span_lt_20": _unsplit_code_count(tuna) < 20,
            "tuna_species_nested": {
                "тунец синий",
                "тунец тихоокеанский голубой",
            }.issubset(subgroups),
        }
    if heading == "5208":
        parents = ("неотбеленные", "отбеленные", "окрашенные")
        return {
            "plain_weave_nested_by_finish": all(
                parent in top
                and any(
                    child.get("kind") == "classification_subgroup"
                    and _normalise_title(child.get("title") or "")
                    == "полотняного переплетения"
                    for child in top[parent].get("children") or []
                )
                for parent in parents
            )
        }
    if heading == "8517":
        accepted_titles: set[str] = set()

        def collect(nodes: list[dict]) -> None:
            for node in nodes:
                if node.get("role") == "semantic_choice":
                    accepted_titles.add(_normalise_title(node.get("title") or ""))
                collect(node.get("children") or [])

        collect(choices)
        return {
            "technical_ranges_not_accepted": not accepted_titles.intersection(
                {"10 ггц", "1610 нм"}
            )
        }
    return {}


def _parse_headings(raw: str) -> list[str]:
    headings: list[str] = []
    for item in (raw or "").split(","):
        heading = "".join(ch for ch in item if ch.isdigit())
        if len(heading) != 4:
            raise argparse.ArgumentTypeError(
                f"heading {item!r} must contain exactly 4 digits"
            )
        if heading not in headings:
            headings.append(heading)
    if not headings:
        raise argparse.ArgumentTypeError("at least one heading is required")
    return headings


def _write_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def run(headings: list[str]) -> dict:
    rows: list[dict] = []
    snapshot_ids: set[str] = set()
    with SessionLocal() as db:
        for heading in headings:
            result = build_guided_tnved_navigation(db, heading)
            integrity = result.get("integrity") or {}
            snapshot_id = (result.get("engine") or {}).get("snapshot_id")
            if snapshot_id:
                snapshot_ids.add(str(snapshot_id))
            choices = list(result.get("choices") or [])
            hierarchy_checks = _hierarchy_checks(heading, choices)
            rows.append(
                {
                    "heading": heading,
                    "status": result.get("status"),
                    "reason": result.get("reason"),
                    "choice_count": len(choices),
                    "expected_real_codes": integrity.get("expected_real_codes"),
                    "reachable_real_codes": integrity.get("reachable_real_codes"),
                    "canonical_bound_codes": integrity.get("canonical_bound_codes"),
                    "canonical_coverage": integrity.get("canonical_coverage"),
                    "fake_codes": integrity.get("fake_codes"),
                    "semantic_groups": integrity.get("semantic_groups"),
                    "semantic_subgroups": integrity.get("semantic_subgroups"),
                    "semantic_max_depth": integrity.get("semantic_max_depth"),
                    "nesting_fallbacks": integrity.get("nesting_fallbacks"),
                    "rejected_unsafe_groups": integrity.get("rejected_unsafe_groups"),
                    "pruned_empty_groups": integrity.get("pruned_empty_groups"),
                    "critical_issues": list(integrity.get("critical_issues") or []),
                    "hierarchy_checks": hierarchy_checks,
                    "hierarchy_ok": all(hierarchy_checks.values()),
                    "complete": bool(integrity.get("complete")),
                }
            )

    ok = all(
        row["status"] == "OK"
        and row["complete"]
        and row["canonical_coverage"] == 1.0
        and row["fake_codes"] == 0
        and not row["critical_issues"]
        and row["hierarchy_ok"]
        for row in rows
    )
    return {
        "format": "guided-tnved-acceptance-v2",
        "read_only": True,
        "headings": rows,
        "snapshot_count": len(snapshot_ids),
        "ok": ok,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only guided TN VED acceptance (aggregate-only report)."
    )
    parser.add_argument(
        "--headings",
        type=_parse_headings,
        default=list(DEFAULT_HEADINGS),
        help="Comma-separated 4-digit headings (default: 0302,0303,5208,8517).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional JSON report path.",
    )
    parser.add_argument(
        "--require-complete",
        action="store_true",
        help="Exit 1 unless every heading passes the complete integrity gate.",
    )
    args = parser.parse_args()

    report = run(list(args.headings))
    if args.output:
        _write_atomic(args.output.resolve(), report)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if args.require_complete and not report["ok"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
