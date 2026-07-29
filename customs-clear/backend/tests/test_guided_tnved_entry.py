"""Product-description entry into the Canonical-backed Guided route."""

from __future__ import annotations

from unittest.mock import Mock

from app.services.guided_tnved_entry import build_guided_search_routes
from app.services.tree_engine import (
    CanonicalModel,
    CommodityNode,
    HeadingNode,
    assign_stable_ids,
)


def _model() -> CanonicalModel:
    phones = HeadingNode(title="Телефонные аппараты", code="8517")
    phones.add_child(
        CommodityNode(
            title="Смартфоны",
            code="8517130000",
            level=10,
            metadata={"display_code": "8517130000", "is_leaf": True},
        )
    )
    computers = HeadingNode(title="Вычислительные машины", code="8471")
    computers.add_child(
        CommodityNode(
            title="Портативные вычислительные машины",
            code="8471300000",
            level=10,
            metadata={"display_code": "8471300000", "is_leaf": True},
        )
    )
    waste_paper = HeadingNode(
        title="Регенерируемые бумага или картон",
        code="4707",
    )
    assign_stable_ids([phones, computers, waste_paper])
    return CanonicalModel.from_roots([phones, computers, waste_paper])


def test_text_results_are_grouped_into_ranked_canonical_headings() -> None:
    routes = build_guided_search_routes(
        "смартфон для работы",
        [
            {"code": "8517130000", "match_reason": "name_match"},
            {"code": "8517140000", "match_reason": "full_text"},
            {"code": "8471300000", "match_reason": "domain_dictionary"},
        ],
        model_loader=_model,
    )

    assert [route["heading"] for route in routes] == ["8517", "8471"]
    assert routes[0]["candidate_count"] == 2
    assert routes[0]["best_match_reason"] == "name_match"
    assert routes[0]["first_result_rank"] == 1
    assert routes[0]["canonical_anchor"]["code"] == "8517"
    assert routes[0]["guided_href"] == "/api/v1/tnved/guided/8517"
    assert routes[1]["candidate_count"] == 1


def test_numeric_lookup_does_not_add_guided_product_hypotheses() -> None:
    loader = Mock(return_value=_model())

    routes = build_guided_search_routes(
        "8517 13 0000",
        [{"code": "8517130000", "match_reason": "code_prefix"}],
        model_loader=loader,
    )

    assert routes == []
    loader.assert_not_called()


def test_canonical_failure_is_a_soft_miss() -> None:
    routes = build_guided_search_routes(
        "смартфон",
        [{"code": "8517130000", "match_reason": "name_match"}],
        model_loader=lambda: None,
    )

    assert routes == []


def test_route_limit_keeps_the_best_ranked_headings() -> None:
    routes = build_guided_search_routes(
        "товар для работы",
        [
            {"code": "8517130000", "match_reason": "name_match"},
            {"code": "8471300000", "match_reason": "full_text"},
        ],
        limit=1,
        model_loader=_model,
    )

    assert [route["heading"] for route in routes] == ["8517"]


def test_curated_semantic_evidence_outranks_incidental_full_text() -> None:
    routes = build_guided_search_routes(
        "смартфон",
        [
            {"code": "4707301000", "match_reason": "full_text"},
            {"code": "8517130000", "match_reason": "domain_dictionary"},
            {"code": "8517140000", "match_reason": "domain_dictionary"},
        ],
        model_loader=_model,
    )

    assert [route["heading"] for route in routes] == ["8517", "4707"]
    assert routes[0]["candidate_count"] == 2
    assert routes[0]["best_match_reason"] == "domain_dictionary"
