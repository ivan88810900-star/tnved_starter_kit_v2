"""Контракт пользовательского умного маршрута по ТН ВЭД."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import tnved_catalog
from app.services.guided_tnved_navigation import GuidedTnvedNavigationService
from app.services.semantic_navigation import (
    SemanticNavigationTree,
    SemanticNode,
    SemanticNodeType,
)
from app.services.tree_engine import (
    CanonicalModel,
    CommodityNode,
    HeadingNode,
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
    return CanonicalModel.from_roots(roots, snapshot_id=snapshot_id)


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


class _Builder:
    def build_heading(self, _db, heading: str) -> SemanticNavigationTree:
        if heading != "0302":
            raise AssertionError(f"unexpected heading: {heading}")
        return _semantic_tree()


class GuidedTnvedNavigationTests(unittest.TestCase):
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
