"""Полный offline-аудит `/children`: legacy vs CanonicalModel.

Обе проекции строятся ровно один раз. Затем индексируются первые (pre-order)
вхождения кодов — так же, как runtime ``_find_node_in_tree`` — и сравниваются
прямые потомки с полным structural+content fingerprint.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from time import perf_counter
from typing import Any

from sqlalchemy.orm import Session

from ...models.tnved import Commodity
from ..tnved_tree import (
    build_tree,
    collect_chapter_notes,
    digits,
    exclude_obsolete_reserved,
    node_level,
)
from .builder import TreeBuilder
from .models import TreeParseResult
from .parser import TreeParser
from .serializer import TreeSerializer
from .shadow import compare_children

MIN_GATE2_COMMODITIES = 10_000


@dataclass(frozen=True)
class CanonicalChildrenAuditExample:
    code: str
    reason: str
    legacy_count: int
    canonical_count: int


@dataclass(frozen=True)
class CanonicalChildrenAuditReport:
    prefix: str
    commodity_count: int
    chapter_paths: int
    node_paths: int
    checked: int
    matches: int
    mismatches: int
    unresolved: int
    duration_ms: float
    examples: tuple[CanonicalChildrenAuditExample, ...] = ()

    @property
    def ok(self) -> bool:
        return self.commodity_count > 0 and self.mismatches == 0 and self.unresolved == 0

    @property
    def gate2_ok(self) -> bool:
        """True только для полного обхода достаточно наполненной БД."""
        return (
            not self.prefix
            and self.commodity_count >= MIN_GATE2_COMMODITIES
            and self.ok
        )

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["ok"] = self.ok
        payload["gate2_ok"] = self.gate2_ok
        payload["minimum_gate2_commodities"] = MIN_GATE2_COMMODITIES
        return payload


def _index_first_by_code(roots: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Pre-order index с setdefault повторяет first-match runtime resolver."""
    index: dict[str, dict[str, Any]] = {}
    stack = list(reversed(roots))
    while stack:
        node = stack.pop()
        code = digits(node.get("code") or "")
        if code:
            index.setdefault(code, node)
        stack.extend(reversed(node.get("children") or []))
    return index


def _chapter_children(roots: list[dict[str, Any]], chapter: str) -> list[dict[str, Any]]:
    return [node for node in roots if digits(node.get("code") or "").startswith(chapter)]


def audit_canonical_children(
    db: Session,
    *,
    max_examples: int = 20,
    prefix: str = "",
) -> CanonicalChildrenAuditReport:
    """Сравнить все DB-backed `/children` пути за один полный build.

    Root и Roman-section остаются table-backed при обоих значениях feature flag;
    их идентичность проверяется API-тестом, а не дублируется здесь.
    """
    started = perf_counter()
    # Parser opens the SQLite read snapshot before either projection is built.
    parsed = TreeParser().parse(db)
    prefix_digits = digits(prefix)
    query = exclude_obsolete_reserved(db.query(Commodity).order_by(Commodity.code.asc()))
    if prefix_digits:
        query = query.filter(Commodity.code.like(f"{prefix_digits}%"))
    rows = query.limit(2_000_000).all()
    commodity_count = len(rows)
    chapter_notes = collect_chapter_notes(db)

    legacy_roots = build_tree(rows, chapter_notes)
    if prefix_digits:
        parsed = TreeParseResult(
            commodities=[
                record
                for record in parsed.commodities
                if record.code10.startswith(prefix_digits)
            ],
            chapter_notes=parsed.chapter_notes,
            db_codes=frozenset(
                code for code in parsed.db_codes if code.startswith(prefix_digits)
            ),
            leaf_flags={
                code: is_leaf
                for code, is_leaf in parsed.leaf_flags.items()
                if code.startswith(prefix_digits)
            },
        )
    model = TreeBuilder().build_model(parsed)
    canonical_roots = TreeSerializer().serialize_roots(list(model.roots))

    legacy_index = _index_first_by_code(legacy_roots)
    canonical_index = _index_first_by_code(canonical_roots)
    headings_with_deeper_records = {
        code[:4]
        for record in parsed.commodities
        if len(code := digits(record.code10)) == 10 and node_level(code) > 4
    }
    required_terminal_l4_codes = {
        code
        for code, is_leaf in parsed.leaf_flags.items()
        if (
            is_leaf
            and len(digits(code)) == 10
            and node_level(digits(code)) == 4
            and digits(code)[:4] not in headings_with_deeper_records
        )
    }
    chapter_codes = sorted(
        {
            code[:2]
            for code in (
                list(legacy_index.keys()) + list(canonical_index.keys())
            )
            if len(code) >= 4
        }
    )
    # Comparing only the union of produced nodes can be falsely green when
    # both projections omit the same source-backed terminal L4 leaf. Parser
    # leaf evidence is an independent reachability requirement for those
    # exact XXXX000000 codes.
    node_codes = sorted(
        set(legacy_index) | set(canonical_index) | required_terminal_l4_codes
    )

    matches = 0
    mismatches = 0
    unresolved = 0
    examples: list[CanonicalChildrenAuditExample] = []

    def add_example(code: str, reason: str, legacy_count: int, canonical_count: int) -> None:
        if len(examples) < max(0, max_examples):
            examples.append(
                CanonicalChildrenAuditExample(
                    code=code,
                    reason=reason,
                    legacy_count=legacy_count,
                    canonical_count=canonical_count,
                )
            )

    for chapter in chapter_codes:
        legacy_children = _chapter_children(legacy_roots, chapter)
        canonical_children = _chapter_children(canonical_roots, chapter)
        result = compare_children(chapter, legacy_children, canonical_children)
        if result.match:
            matches += 1
        else:
            mismatches += 1
            add_example(
                chapter,
                result.reason,
                result.legacy_count,
                result.canonical_count,
            )

    for code in node_codes:
        legacy_node = legacy_index.get(code)
        canonical_node = canonical_index.get(code)
        if legacy_node is None or canonical_node is None:
            unresolved += 1
            mismatches += 1
            reason = "legacy_unresolved" if legacy_node is None else "canonical_unresolved"
            add_example(
                code,
                reason,
                len((legacy_node or {}).get("children") or []),
                len((canonical_node or {}).get("children") or []),
            )
            continue
        result = compare_children(
            code,
            legacy_node.get("children") or [],
            canonical_node.get("children") or [],
        )
        if result.match:
            matches += 1
        else:
            mismatches += 1
            add_example(
                code,
                result.reason,
                result.legacy_count,
                result.canonical_count,
            )

    duration_ms = (perf_counter() - started) * 1000
    checked = len(chapter_codes) + len(node_codes)
    return CanonicalChildrenAuditReport(
        prefix=prefix_digits,
        commodity_count=commodity_count,
        chapter_paths=len(chapter_codes),
        node_paths=len(node_codes),
        checked=checked,
        matches=matches,
        mismatches=mismatches,
        unresolved=unresolved,
        duration_ms=round(duration_ms, 3),
        examples=tuple(examples),
    )
