"""Накопительная выборка regulatory_documents по HS (merge + get_regulatory)."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services.hs_matching import normalize_hs_code
from app.services.regulatory_layer import (
    get_regulatory_documents_for_hs,
    merge_regulatory_document_mapping_rows,
)


def _doc(
    doc_id: str,
    *,
    doc_date: date | None = None,
    agency: str = "A",
    doc_type: str = "t",
    doc_number: str = "1",
    title: str = "T",
    summary: str = "",
    source_url: str = "https://example.invalid/x",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=doc_id,
        agency=agency,
        doc_type=doc_type,
        doc_number=doc_number,
        doc_date=doc_date,
        title=title,
        summary=summary,
        source_url=source_url,
    )


def _map(
    hs_prefix: str,
    *,
    confidence: float = 0.9,
    approved: bool = False,
    relevance: str = "direct",
    note: str | None = None,
    scope: str = "import",
) -> SimpleNamespace:
    return SimpleNamespace(
        hs_prefix=hs_prefix,
        confidence=confidence,
        approved=approved,
        relevance=relevance,
        note=note,
        scope=scope,
    )


class TestMergeRegulatoryDocumentMappingRows:
    def test_two_docs_different_prefixes_both_returned(self) -> None:
        d85 = _doc("d85")
        d8517 = _doc("d8517")
        pairs = [(_map("85"), d85), (_map("8517"), d8517)]
        out = merge_regulatory_document_mapping_rows(pairs, max_results=10)
        assert {x["doc_id"] for x in out} == {"d85", "d8517"}

    def test_sort_specificity_desc(self) -> None:
        d1, d2, d3 = _doc("a"), _doc("b"), _doc("c")
        pairs = [
            (_map("85"), d1),
            (_map("851762"), d2),
            (_map("8517"), d3),
        ]
        out = merge_regulatory_document_mapping_rows(pairs, max_results=10)
        assert [x["matched_prefix"] for x in out] == ["851762", "8517", "85"]

    def test_same_doc_two_mappings_keeps_most_specific_prefix(self) -> None:
        d = _doc("same")
        pairs = [(_map("85"), d), (_map("8517"), d)]
        out = merge_regulatory_document_mapping_rows(pairs, max_results=10)
        assert len(out) == 1
        assert out[0]["doc_id"] == "same"
        assert out[0]["matched_prefix"] == "8517"

    def test_same_specificity_tiebreaker_confidence(self) -> None:
        d = _doc("x")
        pairs = [(_map("8517", confidence=0.5), d), (_map("8517", confidence=0.95), d)]
        out = merge_regulatory_document_mapping_rows(pairs, max_results=10)
        assert out[0]["confidence"] == 0.95

    def test_max_results(self) -> None:
        pairs = [(_map("85"), _doc(f"id{i}")) for i in range(5)]
        out = merge_regulatory_document_mapping_rows(pairs, max_results=2)
        assert len(out) == 2


class TestGetRegulatoryDocumentsForHsMocked:
    """Пять вызовов .all() по порядку префиксов для 8517620000."""

    def test_accumulates_across_prefix_levels(self) -> None:
        d85 = _doc("d85")
        d8517 = _doc("d8517")
        # 5 префикса: 10,8,6,4,2 — пустые первые три, затем 8517, затем 85
        seq: list[list[tuple[SimpleNamespace, SimpleNamespace]]] = [
            [],
            [],
            [],
            [(_map("8517"), d8517)],
            [(_map("85"), d85)],
        ]

        inv = {"i": 0}

        def all_side_effect() -> list:
            i = inv["i"]
            inv["i"] += 1
            return seq[i] if i < len(seq) else []

        chain = MagicMock()
        chain.join.return_value = chain
        chain.filter.return_value = chain
        chain.order_by.return_value = chain
        chain.limit.return_value = chain
        chain.all.side_effect = all_side_effect

        fake_db = MagicMock()
        fake_db.query.return_value = chain

        class CM:
            def __enter__(self) -> MagicMock:
                return fake_db

            def __exit__(self, *args: object) -> None:
                return None

        mock_sm = MagicMock(return_value=CM())

        with patch("app.services.regulatory_layer.SessionLocal", mock_sm):
            out = get_regulatory_documents_for_hs("8517620000", max_results=10)

        assert len(out) == 2
        assert out[0]["matched_prefix"] == "8517"
        assert out[1]["matched_prefix"] == "85"
        assert inv["i"] == 5

    def test_spaced_vs_plain_same_merge_path(self) -> None:
        d = _doc("one")
        pairs_plain = [(_map("8517"), d)]
        pairs_spaced = [(_map("8517"), d)]
        a = merge_regulatory_document_mapping_rows(pairs_plain, max_results=10)
        b = merge_regulatory_document_mapping_rows(pairs_spaced, max_results=10)
        assert a == b
        assert normalize_hs_code("85 17 62 00 00") == normalize_hs_code("8517620000")
