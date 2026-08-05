"""Контракт пользовательского умного маршрута по ТН ВЭД."""

from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.api import tnved_catalog
from app.services.guided_tnved_navigation import GuidedTnvedNavigationService
from app.services.semantic_navigation import (
    SemanticNavigationBuilder,
    SemanticNavigationTree,
    SemanticNode,
    SemanticNodeType,
)
from app.services.tree_engine import (
    CanonicalModel,
    CommodityNode,
    HeadingNode,
    ParsedCommodityRecord,
    TreeBuilder,
    TreeParser,
    assign_stable_ids,
    compute_snapshot_id,
)


def _canonical_model(*, include_second_leaf: bool = True) -> CanonicalModel:
    root = HeadingNode(title="Рыба свежая или охлажденная", code="0302")
    first = CommodityNode(
        title="Форель",
        code="0302110000",
        level=10,
        metadata={"is_leaf": True},
    )
    root.add_child(first)
    if include_second_leaf:
        second = CommodityNode(
            title="Лосось",
            code="0302130000",
            level=10,
            metadata={"is_leaf": True},
        )
        root.add_child(second)
    roots = [root]
    assign_stable_ids(roots)
    snapshot_id = compute_snapshot_id(roots)
    source_records = [
        ParsedCommodityRecord(
            code10="0302",
            description="Рыба свежая или охлажденная",
            raw_description="Рыба свежая или охлажденная",
            import_duty="",
        ),
        ParsedCommodityRecord(
            code10="0302110000",
            description="– Форель",
            raw_description="– Форель",
            import_duty="",
        ),
    ]
    if include_second_leaf:
        source_records.append(
            ParsedCommodityRecord(
                code10="0302130000",
                description="– Лосось",
                raw_description="– Лосось",
                import_duty="",
            )
        )
    return CanonicalModel.from_roots(
        roots,
        snapshot_id=snapshot_id,
        source_records=source_records,
    )


def _semantic_tree() -> SemanticNavigationTree:
    root = SemanticNode(
        node_type=SemanticNodeType.HEADING,
        title="Рыба свежая или охлажденная",
        code="0302",
    )
    group = root.add_child(
        SemanticNode(
            node_type=SemanticNodeType.CLASSIFICATION_GROUP,
            title="лососевые",
            metadata={"confidence": "high"},
        )
    )
    group.add_child(
        SemanticNode(
            node_type=SemanticNodeType.LEAF,
            title="Форель",
            code="0302110000",
        )
    )
    root.add_child(
        SemanticNode(
            node_type=SemanticNodeType.CLASSIFICATION_GROUP,
            title="пустая хвостовая группа",
            metadata={"confidence": "medium"},
        )
    )
    group.add_child(
        SemanticNode(
            node_type=SemanticNodeType.LEAF,
            title="Лосось",
            code="0302130000",
        )
    )
    return SemanticNavigationTree(
        heading="0302",
        root=root,
        expected_real_codes=frozenset(
            {"0302", "0302110000", "0302130000"}
        ),
    )


def _nested_semantic_tree() -> SemanticNavigationTree:
    tree = _semantic_tree()
    group = tree.root.children[0]
    second_leaf = group.children.pop()
    subgroup = group.add_child(
        SemanticNode(
            node_type=SemanticNodeType.CLASSIFICATION_SUBGROUP,
            title="лосось тихоокеанский",
            metadata={"confidence": "medium"},
        )
    )
    subgroup.add_child(second_leaf)
    return tree


class _Builder:
    def build_heading_from_records(
        self,
        heading,
        records,
    ) -> SemanticNavigationTree:  # noqa: ANN001
        if heading != "0302":
            raise AssertionError(f"unexpected heading: {heading}")
        if not records:
            raise AssertionError("expected Canonical source records")
        return _semantic_tree()


class _NestedBuilder:
    def build_heading_from_records(
        self,
        heading,
        records,
    ) -> SemanticNavigationTree:  # noqa: ANN001
        if heading != "0302":
            raise AssertionError(f"unexpected heading: {heading}")
        if not records:
            raise AssertionError("expected Canonical source records")
        return _nested_semantic_tree()


class GuidedTnvedNavigationTests(unittest.TestCase):
    def test_canonical_source_record_projection_is_immutable(self) -> None:
        model = _canonical_model()

        records = model.source_records_for_heading("0302")

        self.assertIsInstance(records, tuple)
        self.assertEqual(records[0].code, "0302")
        with self.assertRaises(FrozenInstanceError):
            records[0].description = "changed"  # type: ignore[misc]
        with self.assertRaises(TypeError):
            model.source_records_by_heading["0302"] = ()  # type: ignore[index]

    def test_canonical_overlay_is_complete_and_explainable(self) -> None:
        model = _canonical_model()
        service = GuidedTnvedNavigationService(
            builder=_Builder(),
            model_loader=lambda: model,
        )

        result = service.build(object(), "03 02")

        self.assertEqual(result["status"], "OK")
        self.assertEqual(
            result["engine"]["mode"],
            "canonical_semantic_overlay",
        )
        self.assertEqual(result["heading"]["code"], "0302")
        self.assertEqual(result["integrity"]["canonical_coverage"], 1.0)
        self.assertEqual(result["integrity"]["fake_codes"], 0)
        self.assertEqual(result["integrity"]["pruned_empty_groups"], 1)
        self.assertTrue(result["integrity"]["complete"])

        choice = result["choices"][0]
        self.assertEqual(choice["role"], "semantic_choice")
        self.assertIsNone(choice["code"])
        self.assertEqual(choice["result_count"], 2)
        self.assertEqual(
            {child["code"] for child in choice["children"]},
            {"0302110000", "0302130000"},
        )
        self.assertTrue(
            all(child["canonical_anchor"] for child in choice["children"])
        )

    def test_database_update_after_model_build_does_not_change_guided_source(
        self,
    ) -> None:
        engine = create_engine("sqlite+pysqlite:///:memory:")
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "CREATE TABLE tnved_sections ("
                        "id INTEGER PRIMARY KEY, roman_number VARCHAR(16), "
                        "title TEXT, notes TEXT)"
                    )
                )
                connection.execute(
                    text(
                        "CREATE TABLE tnved_chapters ("
                        "id INTEGER PRIMARY KEY, section_id INTEGER, code VARCHAR(16), "
                        "title TEXT, notes TEXT)"
                    )
                )
                connection.execute(
                    text(
                        "CREATE TABLE tnved_commodities ("
                        "id INTEGER PRIMARY KEY, chapter_id INTEGER, code VARCHAR(32), "
                        "description TEXT, unit VARCHAR(64), import_duty TEXT, "
                        "supp_unit VARCHAR(16), weight_coeff FLOAT)"
                    )
                )
                connection.execute(
                    text(
                        "CREATE TABLE hs_rates ("
                        "id INTEGER PRIMARY KEY, hs_code VARCHAR(10))"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO tnved_sections "
                        "(id, roman_number, title, notes) "
                        "VALUES (1, 'I', 'Test section', '')"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO tnved_chapters "
                        "(id, section_id, code, title, notes) "
                        "VALUES (1, 1, '03', 'Fish', '')"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO tnved_commodities "
                        "(id, chapter_id, code, description, unit, import_duty, "
                        "supp_unit, weight_coeff) VALUES "
                        "(1, 1, '0302', 'Рыба свежая или охлажденная', '', '', '', 0), "
                        "(2, 1, '0302110000', '– Форель', '', '', '', 0), "
                        "(3, 1, '0302130000', '– Лосось', '', '', '', 0)"
                    )
                )

            with Session(engine) as db:
                parsed = TreeParser().parse(db)
            model = TreeBuilder().build_model(parsed)
            snapshot_id = model.snapshot_id

            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE tnved_commodities "
                        "SET description='MUTATED AFTER SNAPSHOT' "
                        "WHERE code='0302110000'"
                    )
                )

            service = GuidedTnvedNavigationService(
                builder=SemanticNavigationBuilder(),
                model_loader=lambda: model,
            )
            with Session(engine) as db:
                result = service.build(db, "0302")
                changed = db.execute(
                    text(
                        "SELECT description FROM tnved_commodities "
                        "WHERE code='0302110000'"
                    )
                ).scalar_one()

            self.assertEqual(changed, "MUTATED AFTER SNAPSHOT")
            self.assertEqual(result["status"], "OK")
            self.assertEqual(result["engine"]["snapshot_id"], snapshot_id)

            def find_choice(items, code):  # noqa: ANN001
                for item in items:
                    if item.get("code") == code:
                        return item
                    found = find_choice(item.get("children") or [], code)
                    if found is not None:
                        return found
                return None

            choice = find_choice(result["choices"], "0302110000")
            self.assertIsNotNone(choice)
            self.assertEqual(choice["title"], "Форель")
            self.assertNotEqual(choice["title"], "MUTATED AFTER SNAPSHOT")
        finally:
            engine.dispose()

    def test_ids_are_stable_and_real_codes_use_canonical_ids(self) -> None:
        model = _canonical_model()
        service = GuidedTnvedNavigationService(
            builder=_Builder(),
            model_loader=lambda: model,
        )

        first = service.build(object(), "0302")
        second = service.build(object(), "0302")

        first_group = first["choices"][0]
        second_group = second["choices"][0]
        self.assertEqual(first_group["id"], second_group["id"])
        self.assertTrue(first_group["id"].startswith("guide-"))
        for child in first_group["children"]:
            canonical = model.get_by_code(child["code"])
            self.assertIsNotNone(canonical)
            self.assertEqual(child["id"], canonical.stable_id)

    def test_nested_semantic_choice_is_serialized_as_an_extra_question(self) -> None:
        model = _canonical_model()
        service = GuidedTnvedNavigationService(
            builder=_NestedBuilder(),
            model_loader=lambda: model,
        )

        result = service.build(object(), "0302")

        self.assertEqual(result["status"], "OK")
        group = result["choices"][0]
        subgroup = next(
            child
            for child in group["children"]
            if child["kind"] == "classification_subgroup"
        )
        self.assertEqual(subgroup["role"], "semantic_choice")
        self.assertEqual(subgroup["result_count"], 1)
        self.assertEqual(subgroup["children"][0]["code"], "0302130000")
        self.assertEqual(result["integrity"]["semantic_groups"], 2)
        self.assertEqual(result["integrity"]["semantic_subgroups"], 1)
        self.assertEqual(result["integrity"]["semantic_max_depth"], 2)
        self.assertEqual(result["integrity"]["nesting_fallbacks"], 0)

    def test_missing_canonical_binding_never_returns_partial_choices(self) -> None:
        model = _canonical_model(include_second_leaf=False)
        service = GuidedTnvedNavigationService(
            builder=_Builder(),
            model_loader=lambda: model,
        )

        result = service.build(object(), "0302")

        self.assertEqual(result["status"], "DEGRADED")
        self.assertEqual(result["reason"], "integrity_gate_failed")
        self.assertEqual(result["choices"], [])
        self.assertIn(
            "canonical_binding_missing",
            result["integrity"]["critical_issues"],
        )
        self.assertEqual(
            result["fallback"]["href"],
            "/api/v1/tnved/children/0302",
        )

    def test_unavailable_canonical_model_falls_back_without_exception(self) -> None:
        service = GuidedTnvedNavigationService(
            builder=_Builder(),
            model_loader=lambda: None,
        )

        result = service.build(object(), "0302")

        self.assertEqual(result["status"], "DEGRADED")
        self.assertEqual(result["reason"], "canonical_model_unavailable")
        self.assertEqual(result["choices"], [])

    def test_model_without_source_records_falls_back_without_database_read(self) -> None:
        root = HeadingNode(title="Рыба", code="0302")
        assign_stable_ids([root])
        model = CanonicalModel.from_roots([root])
        service = GuidedTnvedNavigationService(
            builder=_Builder(),
            model_loader=lambda: model,
        )

        result = service.build(object(), "0302")

        self.assertEqual(result["status"], "DEGRADED")
        self.assertEqual(result["reason"], "canonical_source_records_unavailable")
        self.assertEqual(result["choices"], [])
        self.assertEqual(result["engine"]["snapshot_id"], model.snapshot_id)

    def test_requires_one_four_digit_heading(self) -> None:
        service = GuidedTnvedNavigationService(
            builder=_Builder(),
            model_loader=lambda: _canonical_model(),
        )
        with self.assertRaisesRegex(ValueError, "exactly 4 digits"):
            service.build(object(), "302")

    def test_api_route_is_registered_before_generic_code_route(self) -> None:
        app = FastAPI()
        app.include_router(tnved_catalog.router, prefix="/api/v1/tnved")

        def fake_db():
            yield object()

        app.dependency_overrides[tnved_catalog.get_db] = fake_db
        expected = {
            "status": "OK",
            "heading": {"code": "0302"},
            "choices": [],
        }
        with (
            patch.object(
                tnved_catalog,
                "build_guided_tnved_navigation",
                return_value=expected,
            ),
            TestClient(app) as client,
        ):
            response = client.get("/api/v1/tnved/guided/0302")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected)

    def test_api_rejects_invalid_heading_as_bad_request(self) -> None:
        app = FastAPI()
        app.include_router(tnved_catalog.router, prefix="/api/v1/tnved")

        def fake_db():
            yield object()

        app.dependency_overrides[tnved_catalog.get_db] = fake_db
        with (
            patch.object(
                tnved_catalog,
                "build_guided_tnved_navigation",
                side_effect=ValueError("heading must contain exactly 4 digits"),
            ),
            TestClient(app) as client,
        ):
            response = client.get("/api/v1/tnved/guided/302")

        self.assertEqual(response.status_code, 400)
        self.assertIn("exactly 4 digits", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
