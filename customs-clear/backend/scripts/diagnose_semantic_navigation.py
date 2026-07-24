#!/usr/bin/env python3
"""Диагностика Semantic Navigation v1 (read-only, экспериментальный слой).

Для набора heading'ов строит semantic-tree, прогоняет валидатор и печатает:
найденные группы, число реальных кодов под каждой группой, коды без группы,
глубину, title-collision по разным родителям и controlled-nesting fallback.
Не меняет данные и не трогает production API.
"""

from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.db import SessionLocal  # noqa: E402
from app.models.tnved import Commodity  # noqa: E402
from app.services.normative_store import init_db  # noqa: E402
from app.services.semantic_navigation import (  # noqa: E402
    SemanticNavigationBuilder,
    SemanticNavigationSerializer,
    SemanticNavigationValidator,
    SemanticNode,
    SemanticNodeType,
)
from app.services.tnved_tree.data_access import exclude_obsolete_reserved  # noqa: E402
from app.services.tnved_tree.helpers import digits  # noqa: E402

HEADINGS = ["0302", "0303", "5208", "8517"]


def _db_codes_for_heading(db, heading4: str) -> set[str]:
    rows = exclude_obsolete_reserved(
        db.query(Commodity.code).filter(Commodity.code.like(f"{heading4}%"))
    ).all()
    out: set[str] = set()
    for (code,) in rows:
        d = digits(code)
        if not d:
            continue
        out.add(d.zfill(4) if len(d) <= 4 else d.zfill(10)[:10])
    return out


def _count_real_codes(node: SemanticNode) -> int:
    n = 1 if node.carries_real_code and node.code else 0
    for ch in node.children:
        n += _count_real_codes(ch)
    return n


def _count_unsplit_real_codes(node: SemanticNode) -> int:
    """Коды в узле без захода в дочерние semantic-группы."""

    n = 1 if node.carries_real_code and node.code else 0
    for ch in node.children:
        if ch.node_type in (
            SemanticNodeType.CLASSIFICATION_GROUP,
            SemanticNodeType.CLASSIFICATION_SUBGROUP,
        ):
            continue
        n += _count_unsplit_real_codes(ch)
    return n


def _report_groups(node: SemanticNode, indent: int = 0) -> None:
    for ch in node.children:
        if ch.node_type in (
            SemanticNodeType.CLASSIFICATION_GROUP,
            SemanticNodeType.CLASSIFICATION_SUBGROUP,
        ):
            real = _count_real_codes(ch)
            unsplit = _count_unsplit_real_codes(ch)
            prefix = "  " * indent
            kind = "group" if ch.node_type == SemanticNodeType.CLASSIFICATION_GROUP else "subgroup"
            nested_by = ch.metadata.get("nested_by")
            hint = f", nested_by={nested_by}" if nested_by else ""
            print(
                f"{prefix}  • [{kind}] {ch.title!r}: "
                f"{real} реальных кодов, unsplit={unsplit}{hint}"
            )
            _report_groups(ch, indent + 1)
        else:
            _report_groups(ch, indent)


def _duplicate_titles_by_parent(tree) -> dict[str, list[str]]:
    by_title: dict[str, set[str]] = {}
    nodes = tree.nodes_by_id()
    for group in tree.group_nodes():
        parent = nodes.get(group.parent_id or "")
        parent_label = (
            f"{parent.node_type.value}:{parent.title}" if parent is not None else "<root>"
        )
        by_title.setdefault(group.title.strip().casefold(), set()).add(parent_label)
    return {
        title: sorted(parents)
        for title, parents in by_title.items()
        if len(parents) > 1
    }


def main() -> int:
    init_db()
    builder = SemanticNavigationBuilder()
    validator = SemanticNavigationValidator()
    serializer = SemanticNavigationSerializer()

    exit_code = 0
    with SessionLocal() as db:
        for heading in HEADINGS:
            print("=" * 72)
            print(f"HEADING {heading}")
            print("=" * 72)

            db_codes = _db_codes_for_heading(db, heading)
            tree = builder.build_heading(db, heading)
            result = validator.validate(tree, db_codes=frozenset(db_codes))

            groups = tree.group_nodes()
            subgroups = [
                group
                for group in groups
                if group.node_type == SemanticNodeType.CLASSIFICATION_SUBGROUP
            ]
            real_in_tree = sorted(set(tree.real_codes_in_tree()))
            print(f"Реальных кодов в БД (incl. heading, excl. pad): {len(tree.expected_real_codes)}")
            print(f"Реальных кодов в дереве: {len(real_in_tree)}")
            print(f"Accepted groups: {len(groups)}")
            print(
                f"Nested subgroups: {len(subgroups)}; "
                f"max semantic node depth: "
                f"{max((group.depth for group in groups), default=0)}"
            )
            if groups:
                _report_groups(tree.root)
            else:
                print("  (не найдено)")

            collisions = _duplicate_titles_by_parent(tree)
            print(f"Duplicate titles under different parents: {len(collisions)}")
            for title, parents in sorted(collisions.items()):
                print(f"  ↳ {title!r}: {' | '.join(parents)}")

            print(f"Nesting fallbacks: {len(tree.nesting_fallbacks)}")
            for item in tree.nesting_fallbacks:
                print(
                    f"  ↔ [{item.reason}] {item.title!r} "
                    f"(parent={item.parent_title!r}, "
                    f"codes={item.real_code_count}, source={item.source_code})"
                )

            print(f"Rejected candidates: {len(tree.rejected_candidates)}")
            for title, reason, src in tree.rejected_candidates:
                print(f"  ✗ [{reason}] {title!r} (из {src})")

            print(f"Кодов без группы (ungrouped): {len(tree.ungrouped_codes)}")
            if tree.ungrouped_codes:
                print("  " + ", ".join(tree.ungrouped_codes[:30]))
                if len(tree.ungrouped_codes) > 30:
                    print(f"  ... ещё {len(tree.ungrouped_codes) - 30}")

            if result.issues:
                print(f"Validation issues: {len(result.issues)} "
                      f"(critical: {len(result.critical_issues)})")
                for issue in result.issues[:20]:
                    print(f"  [{issue.severity}] {issue.code}: {issue.message}")
                if result.has_critical:
                    exit_code = 1
            else:
                print("Validation issues: нет")

            # компактный фрагмент дерева для наглядности (0302)
            if heading == "0302":
                print("\nФрагмент semantic-tree (0302):")
                text = serializer.to_text(tree).splitlines()
                for line in text[:25]:
                    print("  " + line)
                if len(text) > 25:
                    print(f"  ... ещё {len(text) - 25} строк")
            print()

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
