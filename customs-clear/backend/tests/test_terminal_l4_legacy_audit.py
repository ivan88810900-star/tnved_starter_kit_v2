"""Terminal XXXX000000 behavior in the legacy tree and Gate audit."""

from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.services.tnved_tree.build_tree import build_tree
from app.services.tree_engine.audit import audit_canonical_children
from app.services.tree_engine.models import ParsedCommodityRecord, TreeParseResult


def _row(code: str, description: str, import_duty: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        code=code,
        description=description,
        import_duty=import_duty,
    )


def _record(code: str, description: str) -> ParsedCommodityRecord:
    return ParsedCommodityRecord(
        code10=code,
        description=description,
        raw_description=description,
        import_duty="",
    )


class _Query:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def order_by(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN201
        return self

    def filter(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN201
        return self

    def limit(self, value: int):  # noqa: ANN201
        return self

    def all(self) -> list[object]:
        return list(self._rows)


class _Db:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def query(self, *args, **kwargs) -> _Query:  # noqa: ANN002, ANN003
        return _Query(self._rows)


def _tree(include_terminal_leaf: bool) -> list[dict]:
    children = []
    if include_terminal_leaf:
        children.append(
            {
                "code": "0409000000",
                "display_code": "0409000000",
                "name": "Мед натуральный",
                "import_duty": "15%",
                "notes": "",
                "is_leaf": True,
                "is_codeless": False,
                "is_group": False,
                "children": [],
            }
        )
    return [
        {
            "code": "0409",
            "display_code": "0409",
            "name": "Мед натуральный",
            "import_duty": "",
            "notes": "",
            "is_leaf": False,
            "is_codeless": False,
            "is_group": True,
            "children": children,
        }
    ]


class LegacyTerminalL4Tests(unittest.TestCase):
    def test_exact_only_pad_keeps_heading_wrapper_and_real_leaf(self) -> None:
        full_title = (
            "Инструменты из двух или более товарных позиций 8202 – 8205, "
            "в наборах, предназначенных для розничной продажи"
        )
        with patch(
            "app.services.normative_store.is_leaf_hs_code",
            return_value=True,
        ) as is_leaf:
            roots = build_tree(
                [_row("8206000000", full_title, "3")],
                {},
            )

        self.assertEqual(len(roots), 1)
        heading = roots[0]
        self.assertEqual(heading["code"], "8206")
        self.assertEqual(heading["name"], full_title)
        self.assertFalse(heading["is_leaf"])
        self.assertTrue(heading["is_group"])
        self.assertEqual(len(heading["children"]), 1)

        leaf = heading["children"][0]
        self.assertEqual(leaf["code"], "8206000000")
        self.assertEqual(leaf["display_code"], "8206000000")
        self.assertEqual(leaf["name"], full_title)
        self.assertEqual(leaf["import_duty"], "3%")
        self.assertTrue(leaf["is_leaf"])
        self.assertFalse(leaf["is_codeless"])
        self.assertFalse(leaf["is_group"])
        self.assertEqual(leaf["children"], [])
        is_leaf.assert_called_once_with("8206000000")

    def test_nonexact_only_pad_remains_heading_metadata(self) -> None:
        with patch(
            "app.services.normative_store.is_leaf_hs_code",
            return_value=False,
        ) as is_leaf:
            roots = build_tree(
                [_row("0503000000", "Товарная позиция 0503000000", "0")],
                {},
            )

        self.assertEqual(roots[0]["code"], "0503")
        self.assertEqual(roots[0]["children"], [])
        is_leaf.assert_called_once_with("0503000000")

    def test_pad_with_deeper_code_is_not_materialized(self) -> None:
        def classify(code: str) -> bool:
            return code == "9401100001"

        with patch(
            "app.services.normative_store.is_leaf_hs_code",
            side_effect=classify,
        ) as is_leaf:
            roots = build_tree(
                [
                    _row("9401000000", "Сиденья"),
                    _row("9401100001", "– сиденье самолета", "10"),
                ],
                {},
            )

        child_codes = [child["code"] for child in roots[0]["children"]]
        self.assertEqual(child_codes, ["9401100001"])
        self.assertNotIn("9401000000", [call.args[0] for call in is_leaf.call_args_list])


class TerminalL4GateAuditTests(unittest.TestCase):
    def _audit(self, *, include_terminal_leaf: bool):
        parsed = TreeParseResult(
            commodities=[_record("0409000000", "Мед натуральный")],
            chapter_notes={},
            db_codes=frozenset({"0409000000"}),
            leaf_flags={"0409000000": True},
        )
        roots = _tree(include_terminal_leaf)
        model = SimpleNamespace(roots=[])
        db = _Db([_row("0409000000", "Мед натуральный", "15")])

        with (
            patch("app.services.tree_engine.audit.TreeParser.parse", return_value=parsed),
            patch("app.services.tree_engine.audit.exclude_obsolete_reserved", side_effect=lambda q: q),
            patch("app.services.tree_engine.audit.collect_chapter_notes", return_value={}),
            patch("app.services.tree_engine.audit.build_tree", return_value=roots),
            patch("app.services.tree_engine.audit.TreeBuilder.build_model", return_value=model),
            patch("app.services.tree_engine.audit.TreeSerializer.serialize_roots", return_value=roots),
        ):
            return audit_canonical_children(db)  # type: ignore[arg-type]

    def test_gate_detects_terminal_l4_missing_from_both_projections(self) -> None:
        report = self._audit(include_terminal_leaf=False)

        self.assertFalse(report.ok)
        self.assertEqual(report.node_paths, 2)
        self.assertEqual(report.checked, 3)
        self.assertEqual(report.matches, 2)
        self.assertEqual(report.mismatches, 1)
        self.assertEqual(report.unresolved, 1)
        self.assertEqual(report.examples[0].code, "0409000000")

    def test_gate_passes_when_terminal_l4_is_reachable_in_both(self) -> None:
        report = self._audit(include_terminal_leaf=True)

        self.assertTrue(report.ok)
        self.assertEqual(report.node_paths, 2)
        self.assertEqual(report.checked, 3)
        self.assertEqual(report.matches, 3)
        self.assertEqual(report.mismatches, 0)
        self.assertEqual(report.unresolved, 0)

    def test_exact_l4_with_deeper_record_is_not_required_as_leaf(self) -> None:
        parsed = TreeParseResult(
            commodities=[
                _record("2206000000", "Fermented drinks"),
                _record("2206001000", "Deeper group"),
            ],
            chapter_notes={},
            db_codes=frozenset({"2206000000", "2206001000"}),
            # Exact-rate evidence alone is insufficient when descendants exist.
            leaf_flags={"2206000000": True},
        )
        child = {
            "code": "2206001000",
            "display_code": "2206001000",
            "name": "Deeper group",
            "import_duty": "",
            "notes": "",
            "is_leaf": True,
            "is_codeless": False,
            "is_group": False,
            "children": [],
        }
        roots = [
            {
                "code": "2206",
                "display_code": "2206",
                "name": "Fermented drinks",
                "import_duty": "",
                "notes": "",
                "is_leaf": False,
                "is_codeless": False,
                "is_group": True,
                "children": [child],
            }
        ]
        model = SimpleNamespace(roots=[])
        db = _Db(
            [
                _row("2206000000", "Fermented drinks"),
                _row("2206001000", "Deeper group"),
            ]
        )

        with (
            patch("app.services.tree_engine.audit.TreeParser.parse", return_value=parsed),
            patch("app.services.tree_engine.audit.exclude_obsolete_reserved", side_effect=lambda q: q),
            patch("app.services.tree_engine.audit.collect_chapter_notes", return_value={}),
            patch("app.services.tree_engine.audit.build_tree", return_value=roots),
            patch("app.services.tree_engine.audit.TreeBuilder.build_model", return_value=model),
            patch("app.services.tree_engine.audit.TreeSerializer.serialize_roots", return_value=roots),
        ):
            report = audit_canonical_children(db)  # type: ignore[arg-type]

        self.assertTrue(report.ok)
        self.assertEqual(report.node_paths, 2)
        self.assertEqual(report.mismatches, 0)
        self.assertEqual(report.unresolved, 0)


if __name__ == "__main__":
    unittest.main()
