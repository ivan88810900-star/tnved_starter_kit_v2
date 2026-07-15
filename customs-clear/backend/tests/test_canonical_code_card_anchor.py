"""Additive Canonical anchor bridge for TN VED search/code-card consumers."""

from __future__ import annotations

import json
from unittest.mock import patch

from app.api.tnved_catalog import search_commodities
from app.schemas.tnved_catalog import TnvedCommodityDetailsResponse
from app.services.tnved_code_card import (
    canonical_anchor_for_hs,
    canonical_anchors_for_hs_codes,
)
from app.services.tree_engine import CanonicalModel, CommodityNode, HeadingNode, assign_stable_ids


def _model() -> CanonicalModel:
    heading = HeadingNode(title="Телефонные аппараты", code="8517")
    leaf = CommodityNode(
        title="Смартфоны",
        code="8517130000",
        level=10,
        metadata={"display_code": "8517130000", "is_leaf": True},
    )
    heading.add_child(leaf)
    assign_stable_ids([heading])
    return CanonicalModel.from_roots([heading])


def test_exact_code_resolves_versioned_anchor() -> None:
    model = _model()
    payload = canonical_anchor_for_hs("8517 13 000 0", model=model)
    assert payload is not None
    assert payload["stable_id"].startswith("node-")
    assert payload["snapshot_id"] == model.snapshot_id
    assert payload["code"] == "8517130000"
    assert payload["node_type"] == "commodity"


def test_batch_uses_one_snapshot_and_ignores_unknown_codes() -> None:
    model = _model()
    with patch("app.services.tnved_code_card.get_canonical_model", return_value=model) as provider:
        payload = canonical_anchors_for_hs_codes(["8517", "8517130000", "9999999999"])
    provider.assert_called_once_with()
    assert set(payload) == {"8517", "8517130000"}
    assert {item["snapshot_id"] for item in payload.values()} == {model.snapshot_id}


def test_provider_failure_is_soft_miss() -> None:
    with patch(
        "app.services.tnved_code_card.get_canonical_model",
        side_effect=RuntimeError("database unavailable"),
    ):
        assert canonical_anchor_for_hs("8517130000") is None
        assert canonical_anchors_for_hs_codes(["8517130000"]) == {}


def test_detail_schema_accepts_optional_anchor_without_requiring_it() -> None:
    legacy = TnvedCommodityDetailsResponse(code="8517130000")
    assert legacy.canonical_anchor is None

    anchored = TnvedCommodityDetailsResponse(
        code="8517130000",
        canonical_anchor={
            "stable_id": "node-0123456789abcdef01234567",
            "snapshot_id": "snap-v2-0123456789abcdef0123456789abcdef",
            "code": "8517130000",
            "node_type": "commodity",
        },
    )
    assert anchored.canonical_anchor is not None
    assert anchored.canonical_anchor.code == "8517130000"


def test_search_response_exposes_anchor_additively() -> None:
    anchor = {
        "stable_id": "node-0123456789abcdef01234567",
        "snapshot_id": "snap-v2-0123456789abcdef0123456789abcdef",
        "code": "8517130000",
        "node_type": "commodity",
    }
    with (
        patch(
            "app.services.tnved_fts.search_commodities_smart",
            return_value={
                "results": [
                    {
                        "code": "8517130000",
                        "description": "Смартфоны",
                        "match_reason": "name_match",
                    }
                ],
                "corrected_query": None,
                "effective_query": "смартфон",
                "strategy": "hybrid_fts",
            },
        ),
        patch("app.services.normative_store.is_leaf_hs_code", return_value=True),
        patch(
            "app.api.tnved_catalog.canonical_anchors_for_hs_codes",
            return_value={"8517130000": anchor},
        ),
    ):
        response = search_commodities(q="смартфон", db=None)  # type: ignore[arg-type]

    payload = json.loads(response.body)
    assert payload["results"][0]["canonical_anchor"] == anchor
    assert payload["results"][0]["code"] == "8517130000"
    assert payload["results"][0]["name"] == "Смартфоны"
    assert payload["results"][0]["match_reason"] == "name_match"
    assert payload["search"]["strategy"] == "hybrid_fts"
