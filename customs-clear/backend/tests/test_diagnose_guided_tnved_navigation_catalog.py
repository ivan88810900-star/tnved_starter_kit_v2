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


def _subgroup_many(title: str, *codes: str) -> dict:
    return {
        "role": "semantic_choice",
        "kind": "classification_subgroup",
        "title": title,
        "code": None,
        "children": [_code(code) for code in codes],
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
    group_0304_titles = [
        title for title, _codes, _leaves in diagnostic._0304_GROUP_SPECS
    ]
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
        "0304": [
            _code("0304310000"),
            _code("0304320000"),
            _code("0304330000"),
            _code("0304390000"),
            _semantic(
                group_0304_titles[0],
                _code("0304410000"),
                _branch(
                    "0304420000",
                    _code("0304421000"),
                    _code("0304425000"),
                    _code("0304429000"),
                ),
                _code("0304430000"),
                _branch(
                    "0304440000",
                    _code("0304441000"),
                    _code("0304443000"),
                    _code("0304449000"),
                ),
                _code("0304450000"),
                _code("0304460000"),
                _code("0304470000"),
                _code("0304480000"),
                _branch(
                    "0304490000",
                    _code("0304491010"),
                    _code("0304491080"),
                    _code("0304495000"),
                    _code("0304498000"),
                ),
            ),
            _semantic(
                group_0304_titles[1],
                _code("0304510000"),
                _code("0304520000"),
                _code("0304530000"),
                _code("0304540000"),
                _code("0304550000"),
                _code("0304560000"),
                _code("0304570000"),
                _branch(
                    "0304590000",
                    _code("0304592000"),
                    _code("0304595000"),
                    _code("0304598000"),
                ),
            ),
            _code("0304610000"),
            _code("0304620000"),
            _code("0304630000"),
            _code("0304690000"),
            _semantic(
                group_0304_titles[2],
                _branch(
                    "0304710000",
                    _code("0304711000"),
                    _code("0304719000"),
                ),
                _code("0304720000"),
                _code("0304730000"),
                _branch(
                    "0304740000",
                    _code("0304741100"),
                    _code("0304741500"),
                    _code("0304741900"),
                    _code("0304749000"),
                ),
                _code("0304750000"),
                _branch(
                    "0304790000",
                    _code("0304791000"),
                    _code("0304793000"),
                    _code("0304795000"),
                    _code("0304798000"),
                    _code("0304799000"),
                ),
            ),
            _semantic(
                group_0304_titles[3],
                _code("0304810000"),
                _branch(
                    "0304820000",
                    _code("0304821000"),
                    _code("0304825000"),
                    _code("0304829000"),
                ),
                _branch(
                    "0304830000",
                    _code("0304831000"),
                    _code("0304833000"),
                    _code("0304835000"),
                    _code("0304839000"),
                ),
                _code("0304840000"),
                _code("0304850000"),
                _code("0304860000"),
                _code("0304870000"),
                _branch(
                    "0304880000",
                    _code("0304881000"),
                    _code("0304882000"),
                    _code("0304885000"),
                    _code("0304889000"),
                ),
                _branch(
                    "0304890000",
                    _code("0304891010"),
                    _code("0304891080"),
                    _code("0304892100"),
                    _code("0304892900"),
                    _code("0304893000"),
                    _code("0304894100"),
                    _code("0304894900"),
                    _code("0304896000"),
                    _code("0304898000"),
                ),
            ),
            _semantic(
                group_0304_titles[4],
                _code("0304910000"),
                _code("0304920000"),
                _branch(
                    "0304930000",
                    _code("0304932000"),
                    _code("0304938000"),
                ),
                _branch(
                    "0304940000",
                    _code("0304941000"),
                    _code("0304949000"),
                ),
                _branch(
                    "0304950000",
                    _code("0304951000"),
                    _code("0304952100"),
                    _code("0304952500"),
                    _code("0304952900"),
                    _code("0304953000"),
                    _code("0304954000"),
                    _code("0304955000"),
                    _code("0304956000"),
                    _code("0304959000"),
                ),
                _branch(
                    "0304960000",
                    _code("0304961000"),
                    _code("0304969000"),
                ),
                _branch(
                    "0304970000",
                    _code("0304971000"),
                    _code("0304979000"),
                ),
                _branch(
                    "0304990000",
                    _code("0304991100"),
                    _code("0304992200"),
                    _code("0304992300"),
                    _code("0304992900"),
                    _code("0304995500"),
                    _code("0304996100"),
                    _code("0304996500"),
                    _code("0304999800"),
                ),
            ),
        ],
        "0406": [
            _branch(
                "0406100000",
                _semantic(
                    "сыр первый",
                    _code("0406101000"),
                    _code("0406102000"),
                ),
                _code("0406109000"),
            ),
            _branch(
                "0406200000",
                _semantic(
                    "сыр второй",
                    _code("0406201000"),
                    _code("0406202000"),
                ),
                _code("0406209000"),
            ),
            _branch(
                "0406300000",
                _branch(
                    "0406301000",
                    _code("0406301100"),
                    _code("0406301200"),
                    _code("0406301900"),
                ),
                _code("0406309000"),
            ),
            _branch(
                "0406400000",
                _branch(
                    "0406401000",
                    _code("0406401100"),
                    _code("0406401200"),
                    _code("0406401900"),
                ),
                _code("0406408000"),
                _code("0406409000"),
            ),
            _branch(
                "0406900000",
                *(
                    _code(code)
                    for code in (
                        "0406900100",
                        "0406900200",
                        "0406900300",
                        "0406900400",
                        "0406900500",
                        "0406900600",
                        "0406900700",
                        "0406900800",
                        "0406900900",
                        "0406901200",
                        "0406901300",
                        "0406901500",
                        "0406901700",
                        "0406901800",
                        "0406901900",
                    )
                ),
                _semantic(
                    diagnostic._0406_TOP_TITLE,
                    _subgroup_many(
                        diagnostic._0406_LOW_TITLE,
                        "0406906100",
                        "0406906300",
                        "0406906900",
                    ),
                    _subgroup_many(
                        diagnostic._0406_MIDDLE_TITLE,
                        "0406907300",
                        "0406907400",
                        "0406907500",
                        "0406907600",
                        "0406907800",
                        "0406907900",
                        "0406908100",
                        "0406908200",
                        "0406908400",
                        "0406908500",
                        "0406908600",
                        "0406908900",
                        "0406909200",
                    ),
                    _code("0406909300"),
                ),
            ),
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
                        for code in diagnostic._PDO_2204_PRE_OTHER_SLICE
                    ),
                    _subgroup_many(
                        diagnostic._PDO_2204_OTHER_TITLE,
                        *diagnostic._PDO_2204_OTHER_SLICE,
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
            ),
            _branch(
                diagnostic._BULK_2204_PARENT_CODE,
                *(
                    _code(code)
                    for code in (
                        "2204221000",
                        "2204221100",
                        "2204221200",
                        "2204221300",
                        "2204221700",
                        "2204221800",
                    )
                ),
                _semantic(
                    diagnostic._BULK_2204_OTHER_TITLE,
                    *(
                        _code(code)
                        for code in diagnostic._BULK_2204_OTHER_SLICE
                    ),
                ),
                _semantic(
                    diagnostic._PGI_2204_TITLE,
                    _code("2204227900"),
                ),
                *(
                    _code(code)
                    for code in (
                        "2204228000",
                        "2204228100",
                        "2204228200",
                        "2204228300",
                        "2204228400",
                        "2204228500",
                        "2204228600",
                        "2204228700",
                        "2204228800",
                        "2204228900",
                        "2204229000",
                        "2204229100",
                        "2204229200",
                        "2204229300",
                        "2204229400",
                        "2204229500",
                        "2204229600",
                        "2204229700",
                        "2204229800",
                    )
                ),
            ),
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


def test_0304_golden_assertions_require_exact_ordered_scopes() -> None:
    choices = _golden_choices()["0304"]

    assert all(diagnostic._hierarchy_checks("0304", choices).values())

    first_group = choices[4]
    first_group["children"][0], first_group["children"][1] = (
        first_group["children"][1],
        first_group["children"][0],
    )
    checks = diagnostic._hierarchy_checks("0304", choices)

    assert checks["five_ordered_top_groups"] is True
    assert checks["scoped_code_sets_exact"] is False
    assert checks["scoped_leaf_sets_exact"] is False


def test_0304_golden_assertions_keep_03046_direct_and_groups_ordered() -> None:
    choices = _golden_choices()["0304"]
    choices[4], choices[5] = choices[5], choices[4]

    checks = diagnostic._hierarchy_checks("0304", choices)

    assert checks["five_ordered_top_groups"] is False
    assert checks["root_step_13_choices_8_direct_codes"] is True

    choices = _golden_choices()["0304"]
    direct_03046 = choices.pop(6)
    choices[4]["children"].append(direct_03046)
    checks = diagnostic._hierarchy_checks("0304", choices)

    assert checks["direct_03046_four_leaves_outside_groups"] is False
    assert checks["root_step_13_choices_8_direct_codes"] is False


def test_2204_golden_assertions_reject_a_partial_pdo_slice() -> None:
    choices = _golden_choices()["2204"]

    assert all(diagnostic._hierarchy_checks("2204", choices).values())
    choices[0]["children"][1]["children"].pop()
    checks = diagnostic._hierarchy_checks("2204", choices)
    assert checks["pdo_official_group_present"] is True
    assert checks["pdo_exact_33_leaf_slice"] is False
    assert checks["pdo_step_18_choices"] is False


def test_2204_golden_assertions_require_pdo_before_pgi_under_same_parent() -> None:
    choices = _golden_choices()["2204"]
    parent_children = choices[0]["children"]
    parent_children[1], parent_children[2] = parent_children[2], parent_children[1]

    checks = diagnostic._hierarchy_checks("2204", choices)

    assert checks["pdo_exact_33_leaf_slice"] is True
    assert checks["pgi_boundary_after_pdo_slice"] is False


def test_2204_golden_assertions_require_exact_pdo_other_subgroup() -> None:
    choices = _golden_choices()["2204"]
    pdo_other = choices[0]["children"][1]["children"][-1]
    pdo_other["children"].pop()

    checks = diagnostic._hierarchy_checks("2204", choices)

    assert checks["pdo_other_subgroup_present"] is True
    assert checks["pdo_other_exact_16_leaf_slice"] is False
    assert checks["pdo_other_step_16_choices"] is False
    assert checks["pdo_exact_33_leaf_slice"] is False


def test_2204_golden_assertions_require_exact_220422_other_group() -> None:
    choices = _golden_choices()["2204"]
    bulk_other = choices[1]["children"][6]
    bulk_other["children"].pop()

    checks = diagnostic._hierarchy_checks("2204", choices)

    assert checks["bulk_220422_other_group_present"] is True
    assert checks["bulk_220422_other_exact_7_leaf_slice"] is False
    assert checks["bulk_220422_other_step_7_choices"] is False


def test_0406_golden_assertions_require_exact_moisture_scope() -> None:
    choices = _golden_choices()["0406"]

    assert all(diagnostic._hierarchy_checks("0406", choices).values())
    moisture = choices[-1]["children"][-1]
    moisture["children"][1]["children"].pop()
    checks = diagnostic._hierarchy_checks("0406", choices)

    assert checks["moisture_group_present_under_040690"] is True
    assert checks["semantic_leaf_coverage_21_of_47"] is False


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
    assert report["catalog"]["discovered_headings"] == 7
    assert report["catalog"]["snapshot_count"] == 1
    assert report["correctness"]["expected_real_codes"] == 265
    assert report["correctness"]["source_code_nodes"] == 265
    assert report["correctness"]["canonical_declarable_leaves"] == 239
    assert report["correctness"]["duplicate_code_occurrences"] == 0
    assert report["golden_assertions"]["failed_headings"] == []
    assert report["quality_census"]["diagnostic_totals"] == {
        "nesting_fallbacks": 1,
        "rejected_unsafe_groups": 2,
        "pruned_empty_groups": 1,
    }
    assert report["quality_census"]["semantic_choice_coverage"] == {
        "headings_with_choices": 6,
        "heading_ratio": 0.857143,
        "declarable_leaves_under_choices": 165,
        "declarable_leaf_ratio": 0.690377,
    }
    root_choices = report["quality_census"]["counts"]["root_choices"]
    assert root_choices["p50"] == 3
    assert root_choices["max"] == 13
    assert report["quality_census"]["latency_ms"]["per_heading_build"]["p95"] == 1.0
    assert report["quality_census"]["usability_thresholds_applied"] is False
    assert report["quality_outliers"]["zero_root_choices"] == []
    assert report["quality_outliers"]["no_semantic_choices"] == ["8517"]
    assert report["quality_outliers"]["maxima"]["root_choices"] == {
        "value": 13,
        "headings": ["0304"],
    }
    assert report["quality_outliers"]["affects_ok"] is False
    assert "headings" not in report
    assert all(not codes for codes in report["problematic_headings"].values())
    serialized = json.dumps(report, ensure_ascii=False)
    assert "not exported" not in serialized
    assert "лососевые" not in serialized
    assert diagnostic._PDO_2204_TITLE not in serialized
    assert diagnostic._PGI_2204_TITLE not in serialized
    assert diagnostic._0304_GROUP_SPECS[0][0] not in serialized
    assert diagnostic._0406_TOP_TITLE not in serialized
    assert "0302110000" not in serialized
    assert "0304410000" not in serialized
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
