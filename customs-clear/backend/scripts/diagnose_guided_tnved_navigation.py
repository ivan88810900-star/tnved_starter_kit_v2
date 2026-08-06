#!/usr/bin/env python3
"""Read-only acceptance для Canonical-backed guided TN VED.

Отчёт содержит только агрегаты: 10-значные товарные коды, названия товаров и
тексты смысловых групп в JSON не записываются.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
from collections import Counter
from collections.abc import Callable, Sequence
from pathlib import Path
from time import perf_counter
from typing import Any

# Должно быть выставлено до импорта app.db.
os.environ.setdefault("CUSTOMSCLEAR_READ_ONLY", "1")

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db import SessionLocal  # noqa: E402
from app.services.guided_tnved_navigation import (  # noqa: E402
    GuidedTnvedNavigationService,
)
from app.services.tree_engine import (  # noqa: E402
    CanonicalModel,
    NodeType,
    get_canonical_model,
)

DEFAULT_HEADINGS = ("0302", "0303", "0304", "2204", "5208", "8517")


def _fixed_codes(raw: str) -> tuple[str, ...]:
    """Compact source-level allowlist used only by aggregate golden checks."""

    return tuple(raw.split())


_0304_GROUP_SPECS = (
    (
        "филе прочей рыбы, свежее или охлажденное",
        _fixed_codes(
            """
            0304410000 0304420000 0304421000 0304425000 0304429000
            0304430000 0304440000 0304441000 0304443000 0304449000
            0304450000 0304460000 0304470000 0304480000 0304490000
            0304491010 0304491080 0304495000 0304498000
            """
        ),
        _fixed_codes(
            """
            0304410000 0304421000 0304425000 0304429000 0304430000
            0304441000 0304443000 0304449000 0304450000 0304460000
            0304470000 0304480000 0304491010 0304491080 0304495000
            0304498000
            """
        ),
    ),
    (
        "прочее, свежее или охлажденное",
        _fixed_codes(
            """
            0304510000 0304520000 0304530000 0304540000 0304550000
            0304560000 0304570000 0304590000 0304592000 0304595000
            0304598000
            """
        ),
        _fixed_codes(
            """
            0304510000 0304520000 0304530000 0304540000 0304550000
            0304560000 0304570000 0304592000 0304595000 0304598000
            """
        ),
    ),
    (
        (
            "филе мороженое рыбы семейств Bregmacerotidae, "
            "Euclichthyidae, Gadidae, Macrouridae, Melanonidae, "
            "Merlucciidae, Moridae и Muraenolepididae"
        ),
        _fixed_codes(
            """
            0304710000 0304711000 0304719000 0304720000 0304730000
            0304740000 0304741100 0304741500 0304741900 0304749000
            0304750000 0304790000 0304791000 0304793000 0304795000
            0304798000 0304799000
            """
        ),
        _fixed_codes(
            """
            0304711000 0304719000 0304720000 0304730000 0304741100
            0304741500 0304741900 0304749000 0304750000 0304791000
            0304793000 0304795000 0304798000 0304799000
            """
        ),
    ),
    (
        "филе прочей рыбы, мороженое",
        _fixed_codes(
            """
            0304810000 0304820000 0304821000 0304825000 0304829000
            0304830000 0304831000 0304833000 0304835000 0304839000
            0304840000 0304850000 0304860000 0304870000 0304880000
            0304881000 0304882000 0304885000 0304889000 0304890000
            0304891010 0304891080 0304892100 0304892900 0304893000
            0304894100 0304894900 0304896000 0304898000
            """
        ),
        _fixed_codes(
            """
            0304810000 0304821000 0304825000 0304829000 0304831000
            0304833000 0304835000 0304839000 0304840000 0304850000
            0304860000 0304870000 0304881000 0304882000 0304885000
            0304889000 0304891010 0304891080 0304892100 0304892900
            0304893000 0304894100 0304894900 0304896000 0304898000
            """
        ),
    ),
    (
        "прочее, мороженое",
        _fixed_codes(
            """
            0304910000 0304920000 0304930000 0304932000 0304938000
            0304940000 0304941000 0304949000 0304950000 0304951000
            0304952100 0304952500 0304952900 0304953000 0304954000
            0304955000 0304956000 0304959000 0304960000 0304961000
            0304969000 0304970000 0304971000 0304979000 0304990000
            0304991100 0304992200 0304992300 0304992900 0304995500
            0304996100 0304996500 0304999800
            """
        ),
        _fixed_codes(
            """
            0304910000 0304920000 0304932000 0304938000 0304941000
            0304949000 0304951000 0304952100 0304952500 0304952900
            0304953000 0304954000 0304955000 0304956000 0304959000
            0304961000 0304969000 0304971000 0304979000 0304991100
            0304992200 0304992300 0304992900 0304995500 0304996100
            0304996500 0304999800
            """
        ),
    ),
)

_0304_DIRECT_LEAVES = _fixed_codes(
    """
    0304310000 0304320000 0304330000 0304390000
    0304610000 0304620000 0304630000 0304690000
    """
)
_0304_DIRECT_03046_LEAVES = _fixed_codes(
    "0304610000 0304620000 0304630000 0304690000"
)

_PDO_2204_TITLE = (
    "вина с защищенным наименованием по происхождению"
)
_PGI_2204_TITLE = "вина с защищенным географическим указанием"
_PDO_2204_SLICE = (
    "2204211100",
    "2204211200",
    "2204211300",
    "2204211700",
    "2204211800",
    "2204211900",
    "2204212200",
    "2204212300",
    "2204212400",
    "2204212600",
    "2204212700",
    "2204212800",
    "2204213200",
    "2204213400",
    "2204213600",
    "2204213700",
    "2204213800",
    "2204214200",
    "2204214300",
    "2204214400",
    "2204214600",
    "2204214700",
    "2204214800",
    "2204216200",
    "2204216600",
    "2204216700",
    "2204216800",
    "2204216900",
    "2204217100",
    "2204217400",
    "2204217600",
    "2204217700",
    "2204217800",
)


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


def _hierarchy_checks(
    heading: str,
    choices: list[dict],
    *,
    integrity: dict[str, Any] | None = None,
) -> dict[str, bool]:
    """Проверки целевой структуры без записи названий/кодов в отчёт."""

    def through_code_branches(node: dict) -> list[dict]:
        """Expose only children hidden by transparent canonical code branches."""

        visible: list[dict] = []
        for child in node.get("children") or []:
            if child.get("role") == "code_branch":
                visible.extend(through_code_branches(child))
            else:
                visible.append(child)
        return visible

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
            for node in through_code_branches(tuna)
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
    if heading == "0304":
        root_groups = [
            node
            for node in choices
            if node.get("role") == "semantic_choice"
            and node.get("kind") == "classification_group"
        ]
        expected_titles = [
            _normalise_title(title)
            for title, _codes, _leaves in _0304_GROUP_SPECS
        ]
        actual_titles = [
            _normalise_title(node.get("title") or "") for node in root_groups
        ]

        def subtree_occurrences(
            node: dict,
            *,
            leaves_only: bool,
        ) -> list[str]:
            occurrences: list[str] = []

            def collect(current: dict) -> None:
                code = current.get("code")
                if code and (
                    not leaves_only
                    or current.get("role") == "declarable_code"
                ):
                    occurrences.append(str(code))
                for child in current.get("children") or []:
                    collect(child)

            collect(node)
            return occurrences

        scope_code_sets_exact = len(root_groups) == len(_0304_GROUP_SPECS)
        scope_leaf_sets_exact = scope_code_sets_exact
        scope_counts_exact = scope_code_sets_exact
        if scope_code_sets_exact:
            for node, (_title, expected_codes, expected_leaves) in zip(
                root_groups,
                _0304_GROUP_SPECS,
                strict=True,
            ):
                code_occurrences = subtree_occurrences(
                    node,
                    leaves_only=False,
                )
                leaf_occurrences = subtree_occurrences(
                    node,
                    leaves_only=True,
                )
                scope_code_sets_exact = scope_code_sets_exact and (
                    tuple(code_occurrences) == expected_codes
                    and len(set(code_occurrences)) == len(code_occurrences)
                )
                scope_leaf_sets_exact = scope_leaf_sets_exact and (
                    tuple(leaf_occurrences) == expected_leaves
                    and len(set(leaf_occurrences)) == len(leaf_occurrences)
                )
                scope_counts_exact = scope_counts_exact and (
                    len(code_occurrences) == len(expected_codes)
                    and len(leaf_occurrences) == len(expected_leaves)
                )

        direct_root = [
            node
            for node in choices
            if node.get("role") != "semantic_choice" and node.get("code")
        ]
        direct_root_codes = [str(node["code"]) for node in direct_root]
        direct_03046 = [
            node
            for node in direct_root
            if str(node.get("code") or "").startswith("03046")
        ]
        metrics = _choice_metrics(choices)
        integrity = integrity or {}
        integrity_matches = not integrity or bool(
            integrity.get("complete")
            and integrity.get("expected_real_codes") == 117
            and integrity.get("reachable_real_codes") == 117
            and integrity.get("canonical_bound_codes") == 117
            and integrity.get("source_code_nodes") == 117
            and integrity.get("reachable_source_code_nodes") == 117
            and integrity.get("canonical_declarable_leaves") == 100
            and integrity.get("declarable_leaf_codes") == 100
            and integrity.get("canonical_coverage") == 1.0
            and integrity.get("fake_codes") == 0
            and not integrity.get("critical_issues")
        )
        return {
            "five_ordered_top_groups": actual_titles == expected_titles,
            "top_groups_are_codeless": (
                len(root_groups) == 5
                and all(node.get("code") is None for node in root_groups)
            ),
            "scoped_code_sets_exact": scope_code_sets_exact,
            "scoped_leaf_sets_exact": scope_leaf_sets_exact,
            "scoped_counts_exact": scope_counts_exact,
            "direct_03046_four_leaves_outside_groups": (
                tuple(str(node.get("code")) for node in direct_03046)
                == _0304_DIRECT_03046_LEAVES
                and len(direct_03046) == 4
                and all(
                    node.get("role") == "declarable_code"
                    and not node.get("children")
                    for node in direct_03046
                )
            ),
            "root_step_13_choices_8_direct_codes": (
                metrics["root_choices"] == 13
                and metrics["root_direct_code_choices"] == 8
                and tuple(direct_root_codes) == _0304_DIRECT_LEAVES
                and len(direct_root_codes) == len(_0304_DIRECT_LEAVES)
            ),
            "max_step_13_choices_9_direct_codes": (
                metrics["max_step_choices"] == 13
                and metrics["max_step_direct_code_choices"] == 9
            ),
            "semantic_leaf_coverage_92_of_100": (
                metrics["semantic_covered_leaves"] == 92
                and metrics["serialized_unique_declarable_leaves"] == 100
            ),
            "canonical_integrity_117_codes_100_leaves": integrity_matches,
        }
    if heading == "5208":
        parents = ("неотбеленные", "отбеленные", "окрашенные")

        def has_plain_weave(node: dict) -> bool:
            return any(
                child.get("kind") == "classification_subgroup"
                and _normalise_title(child.get("title") or "")
                == "полотняного переплетения"
                for child in through_code_branches(node)
            )

        return {
            "plain_weave_nested_by_finish": all(
                parent in top
                and has_plain_weave(top[parent])
                for parent in parents
            )
        }
    if heading == "2204":
        all_nodes: list[dict] = []

        def collect_nodes(nodes: list[dict]) -> None:
            for node in nodes:
                all_nodes.append(node)
                collect_nodes(list(node.get("children") or []))

        def subtree_codes(node: dict) -> tuple[str, ...]:
            codes: list[str] = []

            def collect_codes(current: dict) -> None:
                if current.get("code"):
                    codes.append(str(current["code"]))
                for child in current.get("children") or []:
                    collect_codes(child)

            collect_codes(node)
            return tuple(codes)

        collect_nodes(choices)
        parent_candidates = [
            node for node in all_nodes if node.get("code") == "2204210000"
        ]
        parent = parent_candidates[0] if len(parent_candidates) == 1 else None
        parent_children = list(parent.get("children") or []) if parent else []
        pdo_candidates = [
            node
            for node in parent_children
            if node.get("role") == "semantic_choice"
            and _normalise_title(node.get("title") or "")
            == _normalise_title(_PDO_2204_TITLE)
        ]
        pdo = pdo_candidates[0] if len(pdo_candidates) == 1 else None
        pdo_codes = subtree_codes(pdo) if pdo is not None else ()
        pdo_leaf_roles = bool(pdo) and all(
            node.get("role") == "declarable_code"
            for node in all_nodes
            if node.get("code") in set(_PDO_2204_SLICE)
        )
        pgi_candidates = [
            node
            for node in parent_children
            if node.get("role") == "semantic_choice"
            and _normalise_title(node.get("title") or "")
            == _normalise_title(_PGI_2204_TITLE)
        ]
        pgi = pgi_candidates[0] if len(pgi_candidates) == 1 else None
        pgi_codes = subtree_codes(pgi) if pgi is not None else ()
        pgi_boundary = bool(
            pdo is not None
            and pgi is not None
            and parent_children.index(pdo) < parent_children.index(pgi)
            and "2204217900" in pgi_codes
            and not set(_PDO_2204_SLICE).intersection(pgi_codes)
        )
        return {
            "pdo_official_group_present": pdo is not None,
            "pdo_group_is_codeless": bool(pdo) and pdo.get("code") is None,
            "pdo_exact_33_leaf_slice": (
                pdo_codes == _PDO_2204_SLICE and pdo_leaf_roles
            ),
            "pdo_parent_step_18_choices": len(parent_children) == 18,
            "pdo_parent_step_14_direct_codes": (
                _unsplit_code_count(parent) == 14 if parent is not None else False
            ),
            "pdo_step_33_choices": (
                len(pdo.get("children") or []) == 33 if pdo is not None else False
            ),
            "pdo_step_33_direct_codes": (
                _unsplit_code_count(pdo) == 33 if pdo is not None else False
            ),
            "pgi_boundary_after_pdo_slice": pgi_boundary,
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


def _discover_headings(model: CanonicalModel) -> list[str]:
    """Вернуть все реальные 4-значные heading из одного Canonical snapshot."""

    headings: set[str] = set()
    for node in model.roots:
        code = "".join(ch for ch in (node.code or "") if ch.isdigit())
        if node.node_type == NodeType.HEADING and len(code) == 4:
            headings.add(code)
    return sorted(headings)


def _choice_metrics(choices: list[dict]) -> dict[str, int]:
    """Посчитать UX-нагрузку без сохранения названий или товарных кодов."""

    all_code_occurrences: list[str] = []
    all_leaf_occurrences: list[str] = []
    semantic_leaves: set[str] = set()
    semantic_choice_count = 0
    max_step_choices = len(choices)
    max_step_direct_codes = sum(
        bool(node.get("code")) and node.get("role") != "semantic_choice"
        for node in choices
    )

    def walk(nodes: list[dict], *, under_semantic_choice: bool) -> None:
        nonlocal semantic_choice_count, max_step_choices, max_step_direct_codes
        max_step_choices = max(max_step_choices, len(nodes))
        max_step_direct_codes = max(
            max_step_direct_codes,
            sum(
                bool(node.get("code"))
                and node.get("role") != "semantic_choice"
                for node in nodes
            ),
        )
        for node in nodes:
            is_semantic = node.get("role") == "semantic_choice"
            semantic_choice_count += int(is_semantic)
            inside_semantic = under_semantic_choice or is_semantic
            code = node.get("code")
            if code:
                normalized = str(code)
                all_code_occurrences.append(normalized)
                if node.get("role") == "declarable_code":
                    all_leaf_occurrences.append(normalized)
                    if inside_semantic:
                        semantic_leaves.add(normalized)
            walk(
                list(node.get("children") or []),
                under_semantic_choice=inside_semantic,
            )

    walk(choices, under_semantic_choice=False)
    unique_codes = set(all_code_occurrences)
    return {
        "root_choices": len(choices),
        "root_semantic_choices": sum(
            node.get("role") == "semantic_choice" for node in choices
        ),
        "root_direct_code_choices": sum(
            bool(node.get("code")) and node.get("role") != "semantic_choice"
            for node in choices
        ),
        "semantic_choices": semantic_choice_count,
        "semantic_covered_leaves": len(semantic_leaves),
        "serialized_unique_codes": len(unique_codes),
        "serialized_unique_declarable_leaves": len(set(all_leaf_occurrences)),
        "duplicate_code_occurrences": len(all_code_occurrences) - len(unique_codes),
        "max_step_choices": max_step_choices,
        "max_step_direct_code_choices": max_step_direct_codes,
    }


def _row_from_result(
    heading: str,
    result: dict[str, Any],
    *,
    elapsed_ms: float,
) -> dict[str, Any]:
    integrity = result.get("integrity") or {}
    choices = list(result.get("choices") or [])
    hierarchy_checks = _hierarchy_checks(
        heading,
        choices,
        integrity=integrity,
    )
    return {
        "heading": heading,
        "status": result.get("status"),
        "reason": result.get("reason"),
        "choice_count": len(choices),
        "expected_real_codes": integrity.get("expected_real_codes"),
        "reachable_real_codes": integrity.get("reachable_real_codes"),
        "canonical_bound_codes": integrity.get("canonical_bound_codes"),
        "source_code_nodes": integrity.get("source_code_nodes"),
        "reachable_source_code_nodes": integrity.get(
            "reachable_source_code_nodes"
        ),
        "canonical_declarable_leaves": integrity.get(
            "canonical_declarable_leaves"
        ),
        "declarable_leaf_codes": integrity.get("declarable_leaf_codes"),
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
        "_snapshot_id": (result.get("engine") or {}).get("snapshot_id"),
        "_latency_ms": max(0.0, elapsed_ms),
        "_quality": _choice_metrics(choices),
    }


def _collect_rows(
    headings: Sequence[str],
    *,
    model: CanonicalModel | None,
    session_factory: Callable[[], Any] | None = None,
    service_factory: Callable[..., Any] | None = None,
    clock: Callable[[], float] | None = None,
) -> list[dict[str, Any]]:
    """Выполнить все heading на одной заранее загруженной CanonicalModel."""

    session_factory = session_factory or SessionLocal
    service_factory = service_factory or GuidedTnvedNavigationService
    clock = clock or perf_counter
    service = service_factory(model_loader=lambda: model)

    rows: list[dict] = []
    with session_factory() as db:
        for heading in headings:
            started = clock()
            result = service.build(db, heading)
            rows.append(
                _row_from_result(
                    heading,
                    result,
                    elapsed_ms=(clock() - started) * 1000.0,
                )
            )
    return rows


def _row_is_strictly_complete(row: dict[str, Any]) -> bool:
    expected = row.get("expected_real_codes")
    return bool(
        row.get("status") == "OK"
        and row.get("complete")
        and row.get("canonical_coverage") == 1.0
        and row.get("fake_codes") == 0
        and not row.get("critical_issues")
        and row.get("hierarchy_ok")
        and isinstance(expected, int)
        and row.get("reachable_real_codes") == expected
        and row.get("canonical_bound_codes") == expected
        and row.get("source_code_nodes") == expected
        and row.get("reachable_source_code_nodes") == expected
        and row.get("declarable_leaf_codes")
        == row.get("canonical_declarable_leaves")
        and (row.get("_quality") or {}).get("duplicate_code_occurrences") == 0
    )


def _public_row(row: dict[str, Any]) -> dict[str, Any]:
    """Убрать внутренние census-поля из совместимого golden-heading отчёта."""

    return {key: value for key, value in row.items() if not key.startswith("_")}


def run(headings: list[str]) -> dict:
    """Совместимый строгий gate для явно перечисленных heading."""

    model = get_canonical_model()
    rows = _collect_rows(headings, model=model)
    snapshot_ids = {
        str(row["_snapshot_id"])
        for row in rows
        if row.get("_snapshot_id")
    }

    ok = all(_row_is_strictly_complete(row) for row in rows)
    return {
        "format": "guided-tnved-acceptance-v2",
        "read_only": True,
        "headings": [_public_row(row) for row in rows],
        "snapshot_count": len(snapshot_ids),
        "ok": ok,
    }


def _number_summary(values: Sequence[int | float]) -> dict[str, int | float | None]:
    """Детерминированные nearest-rank percentiles для baseline census."""

    if not values:
        return {
            "count": 0,
            "min": None,
            "p50": None,
            "p90": None,
            "p95": None,
            "p99": None,
            "max": None,
        }
    ordered = sorted(values)
    integral = all(isinstance(value, int) and not isinstance(value, bool) for value in ordered)

    def clean(value: int | float) -> int | float:
        return int(value) if integral else round(float(value), 3)

    def percentile(value: int) -> int | float:
        index = max(0, math.ceil((value / 100) * len(ordered)) - 1)
        return clean(ordered[index])

    return {
        "count": len(ordered),
        "min": clean(ordered[0]),
        "p50": percentile(50),
        "p90": percentile(90),
        "p95": percentile(95),
        "p99": percentile(99),
        "max": clean(ordered[-1]),
    }


def _sum_int(rows: Sequence[dict[str, Any]], key: str) -> int:
    return sum(
        int(row[key])
        for row in rows
        if isinstance(row.get(key), int) and not isinstance(row.get(key), bool)
    )


def _aggregate_catalog(
    headings: Sequence[str],
    rows: Sequence[dict[str, Any]],
    *,
    snapshot_id: str,
    model_node_count: int,
    model_load_ms: float,
) -> dict[str, Any]:
    """Собрать aggregate-only отчёт; per-heading остаются только problem codes."""

    heading_set = set(headings)
    row_by_heading = {str(row["heading"]): row for row in rows}
    observed_snapshots = {
        str(row["_snapshot_id"])
        for row in rows
        if row.get("_snapshot_id")
    }

    def codes_where(predicate: Callable[[dict[str, Any]], bool]) -> list[str]:
        return sorted(
            heading
            for heading, row in row_by_heading.items()
            if predicate(row)
        )

    degraded = codes_where(lambda row: row.get("status") != "OK")
    incomplete = codes_where(lambda row: not row.get("complete"))
    reachability = codes_where(
        lambda row: row.get("reachable_real_codes")
        != row.get("expected_real_codes")
    )
    canonical_binding = codes_where(
        lambda row: row.get("canonical_bound_codes")
        != row.get("expected_real_codes")
        or row.get("canonical_coverage") != 1.0
    )
    source_code_count_mismatch = codes_where(
        lambda row: row.get("source_code_nodes")
        != row.get("expected_real_codes")
        or row.get("reachable_source_code_nodes")
        != row.get("expected_real_codes")
    )
    declarable_leaf_mismatch = codes_where(
        lambda row: row.get("declarable_leaf_codes")
        != row.get("canonical_declarable_leaves")
        or (row.get("_quality") or {}).get(
            "serialized_unique_declarable_leaves"
        )
        != row.get("canonical_declarable_leaves")
    )
    fake_codes = codes_where(lambda row: row.get("fake_codes") not in (0, None))
    duplicate_codes = codes_where(
        lambda row: (row.get("_quality") or {}).get(
            "duplicate_code_occurrences", 0
        )
        > 0
        or "duplicate_code" in set(row.get("critical_issues") or [])
    )
    critical = codes_where(lambda row: bool(row.get("critical_issues")))
    leaf_role_mismatch = codes_where(
        lambda row: "leaf_role_mismatch" in set(row.get("critical_issues") or [])
    )
    childless_nonleaf = codes_where(
        lambda row: "nonleaf_without_reachable_children"
        in set(row.get("critical_issues") or [])
    )
    canonical_parent_mismatch = codes_where(
        lambda row: "canonical_parent_mismatch"
        in set(row.get("critical_issues") or [])
    )
    snapshot_mismatch = codes_where(
        lambda row: row.get("_snapshot_id") != snapshot_id
    )
    missing_rows = sorted(heading_set - set(row_by_heading))

    golden_failed = sorted(
        heading
        for heading in DEFAULT_HEADINGS
        if heading not in row_by_heading
        or not _row_is_strictly_complete(row_by_heading[heading])
    )
    critical_issue_counts: Counter[str] = Counter()
    for row in rows:
        critical_issue_counts.update(set(row.get("critical_issues") or []))

    expected_total = _sum_int(rows, "expected_real_codes")
    reachable_total = _sum_int(rows, "reachable_real_codes")
    bound_total = _sum_int(rows, "canonical_bound_codes")
    source_code_total = _sum_int(rows, "source_code_nodes")
    reachable_source_code_total = _sum_int(rows, "reachable_source_code_nodes")
    canonical_leaf_total = _sum_int(rows, "canonical_declarable_leaves")
    declarable_leaf_total = _sum_int(rows, "declarable_leaf_codes")
    semantic_covered_total = sum(
        int((row.get("_quality") or {}).get("semantic_covered_leaves", 0))
        for row in rows
    )
    headings_with_semantic_choices = sum(
        int((row.get("_quality") or {}).get("semantic_choices", 0) > 0)
        for row in rows
    )
    processed_count = len(row_by_heading)
    snapshot_consistent = bool(rows) and observed_snapshots == {snapshot_id}

    correctness_ok = bool(headings) and all(
        (
            not degraded,
            not incomplete,
            not reachability,
            not canonical_binding,
            not source_code_count_mismatch,
            not declarable_leaf_mismatch,
            not fake_codes,
            not duplicate_codes,
            not critical,
            not snapshot_mismatch,
            not missing_rows,
            processed_count == len(heading_set),
            snapshot_consistent,
        )
    )
    golden_ok = not golden_failed

    def metric_values(key: str) -> list[int]:
        return [
            int((row.get("_quality") or {}).get(key, 0))
            for row in rows
        ]

    def maximum_by_heading(
        value_getter: Callable[[dict[str, Any]], int | float],
    ) -> dict[str, Any]:
        values = [
            (str(row["heading"]), value_getter(row))
            for row in rows
        ]
        if not values:
            return {"value": None, "headings": []}
        maximum = max(value for _, value in values)
        public_value: int | float = (
            maximum
            if isinstance(maximum, int) and not isinstance(maximum, bool)
            else round(float(maximum), 3)
        )
        return {
            "value": public_value,
            "headings": sorted(
                heading for heading, value in values if value == maximum
            ),
        }

    zero_root_choices = codes_where(
        lambda row: (row.get("_quality") or {}).get("root_choices", 0) == 0
    )
    no_semantic_choices = codes_where(
        lambda row: (row.get("_quality") or {}).get("semantic_choices", 0) == 0
    )

    return {
        "format": "guided-tnved-catalog-census-v1",
        "read_only": True,
        "mode": "all_headings",
        "catalog": {
            "discovered_headings": len(heading_set),
            "processed_headings": processed_count,
            "canonical_nodes": model_node_count,
            "snapshot_id": snapshot_id,
            "snapshot_count": len(observed_snapshots),
            "snapshot_consistent": snapshot_consistent,
        },
        "correctness": {
            "status_ok_headings": processed_count - len(degraded),
            "degraded_headings": len(degraded),
            "complete_headings": processed_count - len(incomplete),
            "expected_real_codes": expected_total,
            "reachable_real_codes": reachable_total,
            "canonical_bound_codes": bound_total,
            "source_code_nodes": source_code_total,
            "reachable_source_code_nodes": reachable_source_code_total,
            "canonical_declarable_leaves": canonical_leaf_total,
            "declarable_leaf_codes": declarable_leaf_total,
            "weighted_canonical_coverage": (
                round(bound_total / expected_total, 6)
                if expected_total
                else None
            ),
            "fake_codes": _sum_int(rows, "fake_codes"),
            "duplicate_code_occurrences": sum(
                int(
                    (row.get("_quality") or {}).get(
                        "duplicate_code_occurrences", 0
                    )
                )
                for row in rows
            ),
            "duplicate_code_issue_headings": sum(
                "duplicate_code" in set(row.get("critical_issues") or [])
                for row in rows
            ),
            "critical_issue_headings": len(critical),
            "critical_issue_counts": dict(sorted(critical_issue_counts.items())),
            "ok": correctness_ok,
        },
        "quality_census": {
            "semantic_choice_coverage": {
                "headings_with_choices": headings_with_semantic_choices,
                "heading_ratio": (
                    round(headings_with_semantic_choices / processed_count, 6)
                    if processed_count
                    else None
                ),
                "declarable_leaves_under_choices": semantic_covered_total,
                "declarable_leaf_ratio": (
                    round(semantic_covered_total / declarable_leaf_total, 6)
                    if declarable_leaf_total
                    else None
                ),
            },
            "counts": {
                "root_choices": _number_summary(metric_values("root_choices")),
                "root_semantic_choices": _number_summary(
                    metric_values("root_semantic_choices")
                ),
                "root_direct_code_choices": _number_summary(
                    metric_values("root_direct_code_choices")
                ),
                "max_step_choices": _number_summary(
                    metric_values("max_step_choices")
                ),
                "max_step_direct_code_choices": _number_summary(
                    metric_values("max_step_direct_code_choices")
                ),
                "semantic_groups": _number_summary(
                    [int(row.get("semantic_groups") or 0) for row in rows]
                ),
                "semantic_max_depth": _number_summary(
                    [int(row.get("semantic_max_depth") or 0) for row in rows]
                ),
            },
            "diagnostic_totals": {
                "nesting_fallbacks": _sum_int(rows, "nesting_fallbacks"),
                "rejected_unsafe_groups": _sum_int(
                    rows, "rejected_unsafe_groups"
                ),
                "pruned_empty_groups": _sum_int(rows, "pruned_empty_groups"),
            },
            "latency_ms": {
                "canonical_model_load": round(max(0.0, model_load_ms), 3),
                "per_heading_build": _number_summary(
                    [float(row.get("_latency_ms") or 0.0) for row in rows]
                ),
            },
            "baseline_only": True,
            "usability_thresholds_applied": False,
        },
        "quality_outliers": {
            "zero_root_choices": zero_root_choices,
            "no_semantic_choices": no_semantic_choices,
            "maxima": {
                "root_choices": maximum_by_heading(
                    lambda row: int(
                        (row.get("_quality") or {}).get("root_choices", 0)
                    )
                ),
                "max_step_choices": maximum_by_heading(
                    lambda row: int(
                        (row.get("_quality") or {}).get("max_step_choices", 0)
                    )
                ),
                "max_step_direct_code_choices": maximum_by_heading(
                    lambda row: int(
                        (row.get("_quality") or {}).get(
                            "max_step_direct_code_choices", 0
                        )
                    )
                ),
                "latency_ms": maximum_by_heading(
                    lambda row: float(row.get("_latency_ms") or 0.0)
                ),
            },
            "affects_ok": False,
        },
        "golden_assertions": {
            "required": len(DEFAULT_HEADINGS),
            "passed": len(DEFAULT_HEADINGS) - len(golden_failed),
            "failed_headings": golden_failed,
            "ok": golden_ok,
        },
        "problematic_headings": {
            "missing_result": missing_rows,
            "degraded": degraded,
            "incomplete": incomplete,
            "reachability": reachability,
            "canonical_binding": canonical_binding,
            "source_code_count_mismatch": source_code_count_mismatch,
            "declarable_leaf_mismatch": declarable_leaf_mismatch,
            "fake_codes": fake_codes,
            "duplicate_codes": duplicate_codes,
            "critical_issues": critical,
            "leaf_role_mismatch": leaf_role_mismatch,
            "nonleaf_without_reachable_children": childless_nonleaf,
            "canonical_parent_mismatch": canonical_parent_mismatch,
            "snapshot_mismatch": snapshot_mismatch,
            "golden_assertions": golden_failed,
        },
        "ok": correctness_ok and golden_ok,
    }


def run_all_headings(
    *,
    model_loader: Callable[[], CanonicalModel | None] | None = None,
    session_factory: Callable[[], Any] | None = None,
    service_factory: Callable[..., Any] | None = None,
    clock: Callable[[], float] | None = None,
) -> dict[str, Any]:
    """Whole-catalog census с одной загрузкой/сборкой CanonicalModel."""

    model_loader = model_loader or get_canonical_model
    clock = clock or perf_counter
    started = clock()
    model = model_loader()
    model_load_ms = (clock() - started) * 1000.0
    if model is None:
        return {
            "format": "guided-tnved-catalog-census-v1",
            "read_only": True,
            "mode": "all_headings",
            "error": "canonical_model_unavailable",
            "catalog": {
                "discovered_headings": 0,
                "processed_headings": 0,
                "canonical_nodes": 0,
                "snapshot_count": 0,
                "snapshot_consistent": False,
            },
            "problematic_headings": {},
            "ok": False,
        }

    headings = _discover_headings(model)
    rows = _collect_rows(
        headings,
        model=model,
        session_factory=session_factory,
        service_factory=service_factory,
        clock=clock,
    )
    return _aggregate_catalog(
        headings,
        rows,
        snapshot_id=model.snapshot_id,
        model_node_count=len(model),
        model_load_ms=model_load_ms,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only guided TN VED acceptance (aggregate-only report)."
    )
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument(
        "--headings",
        type=_parse_headings,
        help=(
            "Comma-separated 4-digit headings "
            "(default: 0302,0303,0304,2204,5208,8517)."
        ),
    )
    selection.add_argument(
        "--all-headings",
        action="store_true",
        help=(
            "Discover every 4-digit heading from one CanonicalModel snapshot "
            "and emit an aggregate-only census."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional JSON report path.",
    )
    parser.add_argument(
        "--require-complete",
        action="store_true",
        help=(
            "Exit 1 unless every heading passes correctness and the six "
            "golden assertions; census quality metrics do not set thresholds."
        ),
    )
    args = parser.parse_args(argv)

    report = (
        run_all_headings()
        if args.all_headings
        else run(list(args.headings or DEFAULT_HEADINGS))
    )
    if args.output:
        _write_atomic(args.output.resolve(), report)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if args.require_complete and not report["ok"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
