"""Self-contained tests for the whole-catalog Guided TN VED census."""

from __future__ import annotations

import io
import json
import re
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from app.services.tree_engine import NodeType
from scripts import diagnose_guided_tnved_navigation as diagnostic


class _FakeModel:
    def __init__(self, codes: list[str], *, snapshot_id: str = "snap-test") -> None:
        self.roots = tuple(
            SimpleNamespace(code=code, node_type=NodeType.HEADING)
            for code in codes
        )
        self.snapshot_id = snapshot_id

    def __len__(self) -> int:
        return len(self.roots) * 10


class _FakeSession:
    def __enter__(self) -> object:
        return object()

    def __exit__(self, *_args: object) -> None:
        return None


def _semantic(title: str, *children: dict) -> dict:
    return {
        "role": "semantic_choice",
        "kind": "classification_group",
        "title": title,
        "code": None,
        "children": list(children),
    }


def _subgroup(title: str, code: str) -> dict:
    return {
        "role": "semantic_choice",
        "kind": "classification_subgroup",
        "title": title,
        "code": None,
        "children": [_code(code)],
    }


def _code(code: str) -> dict:
    return {
        "role": "declarable_code",
        "kind": "leaf",
        "title": "not exported",
        "code": code,
        "children": [],
    }


def _branch(code: str, *children: dict) -> dict:
    return {
        "role": "code_branch",
        "kind": "classification_group",
        "title": "not exported",
        "code": code,
        "children": list(children),
    }


def _golden_choices() -> dict[str, list[dict]]:
    return {
        "0302": [
            _semantic("лососевые", _code("0302110000")),
            _semantic("камбалообразные", _code("0302210000")),
            _semantic("тунец", _code("0302310000")),
        ],
        "0303": [
            _semantic(
                "тунец",
                _subgroup("тунец синий", "0303410000"),
                _subgroup(
                    "тунец тихоокеанский голубой",
                    "0303420000",
                ),
            )
        ],
        "5208": [
            _semantic(
                finish,
                _subgroup("полотняного переплетения", code),
            )
            for finish, code in (
                ("неотбеленные", "5208111000"),
                ("отбеленные", "5208211000"),
                ("окрашенные", "5208310000"),
            )
        ],
        "2204": [
            _branch(
                "2204210000",
                _semantic("вино", _code("2204210600")),
                _semantic(
                    diagnostic._PDO_2204_TITLE,
                    *(
                        _code(code)
                        for code in diagnostic._PDO_2204_SLICE
                    ),
                ),
                _semantic(
                    diagnostic._PGI_2204_TITLE,
                    _code("2204217900"),
                ),
                *(
                    _code(code)
                    for code in (
                        "2204218000",
                        "2204218100",
                        "2204218200",
                        "2204218300",
                        "2204218400",
                    )
                ),
                _semantic("более 15 об.%", _code("2204218500")),
                *(
                    _code(code)
                    for code in (
                        "2204219000",
                        "2204219100",
                        "2204219200",
                        "2204219300",
                        "2204219400",
                        "2204219500",
                        "2204219600",
                        "2204219700",
                        "2204219800",
                    )
                ),
            )
        ],
        "8517": [_code("8517130000")],
    }


def _ok_result(
    heading: str,
    choices: list[dict],
    *,
    snapshot_id: str = "snap-test",
) -> dict:
    def iter_nodes(nodes: list[dict]):
        for node in nodes:
            yield node
            yield from iter_nodes(node.get("children") or [])

    nodes = list(iter_nodes(choices))
    code_count = sum(bool(node.get("code")) for node in nodes)
    leaf_count = sum(node.get("role") == "declarable_code" for node in nodes)
    semantic_count = sum(node.get("role") == "semantic_choice" for node in nodes)
    subgroup_count = sum(
        node.get("kind") == "classification_subgroup" for node in nodes
    )
    return {
        "status": "OK",
        "engine": {"snapshot_id": snapshot_id},
        "choices": choices,
        "integrity": {
            "complete": True,
            "expected_real_codes": code_count,
            "reachable_real_codes": code_count,
            "canonical_bound_codes": code_count,
            "source_code_nodes": code_count,
            "reachable_source_code_nodes": code_count,
            "canonical_declarable_leaves": leaf_count,
            "declarable_leaf_codes": leaf_count,
            "canonical_coverage": 1.0,
            "fake_codes": 0,
            "critical_issues": [],
            "semantic_groups": semantic_count,
            "semantic_subgroups": subgroup_count,
            "semantic_max_depth": 2 if subgroup_count else int(semantic_count > 0),
            "nesting_fallbacks": 1 if heading == "0303" else 0,
            "rejected_unsafe_groups": 2 if heading == "8517" else 0,
            "pruned_empty_groups": 1 if heading == "0302" else 0,
        },
    }


def test_discovery_uses_only_unique_four_digit_canonical_headings() -> None:
    model = _FakeModel(["8517", "03 02", "0302", "5208"])
    model.roots += (
        SimpleNamespace(code="0302110000", node_type=NodeType.COMMODITY),
        SimpleNamespace(code="bad", node_type=NodeType.HEADING),
    )

    assert diagnostic._discover_headings(model) == ["0302", "5208", "8517"]


def test_2204_golden_assertions_reject_a_partial_pdo_slice() -> None:
    choices = _golden_choices()["2204"]

    assert all(diagnostic._hierarchy_checks("2204", choices).values())
    choices[0]["children"][1]["children"].pop()
    checks = diagnostic._hierarchy_checks("2204", choices)
    assert checks["pdo_official_group_present"] is True
    assert checks["pdo_exact_33_leaf_slice"] is False
    assert checks["pdo_step_33_choices"] is False


def test_2204_golden_assertions_require_pdo_before_pgi_under_same_parent() -> None:
    choices = _golden_choices()["2204"]
    parent_children = choices[0]["children"]
    parent_children[1], parent_children[2] = parent_children[2], parent_children[1]

    checks = diagnostic._hierarchy_checks("2204", choices)

    assert checks["pdo_exact_33_leaf_slice"] is True
    assert checks["pgi_boundary_after_pdo_slice"] is False


def test_all_heading_census_loads_model_once_and_returns_aggregates_only() -> None:
    choices = _golden_choices()
    model = _FakeModel(list(choices))
    loader_calls = 0
    built: list[str] = []

    def load_model() -> _FakeModel:
        nonlocal loader_calls
        loader_calls += 1
        return model

    class FakeService:
        def __init__(self, *, model_loader) -> None:
            assert model_loader() is model

        def build(self, _db: object, heading: str) -> dict:
            built.append(heading)
            return _ok_result(heading, choices[heading])

    tick = 0

    def clock() -> float:
        nonlocal tick
        tick += 1
        return tick / 1000

    report = diagnostic.run_all_headings(
        model_loader=load_model,
        session_factory=_FakeSession,
        service_factory=FakeService,
        clock=clock,
    )

    assert loader_calls == 1
    assert built == sorted(choices)
    assert report["ok"] is True
    assert report["catalog"]["discovered_headings"] == 5
    assert report["catalog"]["snapshot_count"] == 1
    assert report["correctness"]["expected_real_codes"] == 60
    assert report["correctness"]["source_code_nodes"] == 60
    assert report["correctness"]["canonical_declarable_leaves"] == 59
    assert report["correctness"]["duplicate_code_occurrences"] == 0
    assert report["golden_assertions"]["failed_headings"] == []
    assert report["quality_census"]["diagnostic_totals"] == {
        "nesting_fallbacks": 1,
        "rejected_unsafe_groups": 2,
        "pruned_empty_groups": 1,
    }
    assert report["quality_census"]["semantic_choice_coverage"] == {
        "headings_with_choices": 4,
        "heading_ratio": 0.8,
        "declarable_leaves_under_choices": 44,
        "declarable_leaf_ratio": 0.745763,
    }
    root_choices = report["quality_census"]["counts"]["root_choices"]
    assert root_choices["p50"] == 1
    assert root_choices["max"] == 3
    assert report["quality_census"]["latency_ms"]["per_heading_build"]["p95"] == 1.0
    assert report["quality_census"]["usability_thresholds_applied"] is False
    assert report["quality_outliers"]["zero_root_choices"] == []
    assert report["quality_outliers"]["no_semantic_choices"] == ["8517"]
    assert report["quality_outliers"]["maxima"]["root_choices"] == {
        "value": 3,
        "headings": ["0302", "5208"],
    }
    assert report["quality_outliers"]["affects_ok"] is False
    assert "headings" not in report
    assert all(not codes for codes in report["problematic_headings"].values())
    serialized = json.dumps(report, ensure_ascii=False)
    assert "not exported" not in serialized
    assert "лососевые" not in serialized
    assert diagnostic._PDO_2204_TITLE not in serialized
    assert diagnostic._PGI_2204_TITLE not in serialized
    assert "0302110000" not in serialized
    assert re.search(r"(?<!\d)\d{10}(?!\d)", serialized) is None


def test_aggregation_lists_only_problem_heading_codes() -> None:
    choices = _golden_choices()
    rows = [
        diagnostic._row_from_result(
            heading,
            _ok_result(heading, heading_choices),
            elapsed_ms=1.0,
        )
        for heading, heading_choices in choices.items()
    ]
    failed = rows[-1]
    failed.update(
        {
            "status": "DEGRADED",
            "complete": False,
            "critical_issues": ["duplicate_code"],
            "canonical_coverage": None,
        }
    )

    report = diagnostic._aggregate_catalog(
        list(choices),
        rows,
        snapshot_id="snap-test",
        model_node_count=40,
        model_load_ms=2.0,
    )

    assert report["ok"] is False
    assert report["correctness"]["duplicate_code_issue_headings"] == 1
    assert report["problematic_headings"]["degraded"] == ["8517"]
    assert report["problematic_headings"]["duplicate_codes"] == ["8517"]
    assert report["problematic_headings"]["golden_assertions"] == ["8517"]
    assert "headings" not in report
    assert "title" not in json.dumps(report)


def test_cli_all_headings_writes_report_and_enforces_correctness() -> None:
    failed_report = {
        "format": "guided-tnved-catalog-census-v1",
        "read_only": True,
        "mode": "all_headings",
        "problematic_headings": {"degraded": ["8517"]},
        "ok": False,
    }

    with TemporaryDirectory() as directory:
        output = Path(directory) / "census.json"
        stdout = io.StringIO()
        with (
            patch.object(
                diagnostic,
                "run_all_headings",
                return_value=failed_report,
            ) as run_all,
            patch.object(diagnostic, "run") as run_selected,
            redirect_stdout(stdout),
        ):
            exit_code = diagnostic.main(
                [
                    "--all-headings",
                    "--require-complete",
                    "--output",
                    str(output),
                ]
            )

        assert exit_code == 1
        run_all.assert_called_once_with()
        run_selected.assert_not_called()
        assert json.loads(output.read_text(encoding="utf-8")) == failed_report
        assert json.loads(stdout.getvalue()) == failed_report
