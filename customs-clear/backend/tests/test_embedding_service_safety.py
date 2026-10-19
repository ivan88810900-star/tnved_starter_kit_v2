from __future__ import annotations

import math
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.embedding_service import (
    cosine_sim,
    embed_texts_openai,
    semantic_search_tnved,
)


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def join(self, *_args, **_kwargs):
        return self

    def filter(self, *_args, **_kwargs):
        return self

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, rows):
        self._rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def query(self, *_args):
        return _FakeQuery(self._rows)


def _row(*, model: str, dim: int, vector, hs_code: str):
    embedding = SimpleNamespace(
        embedding_model=model,
        embedding_dim=dim,
        embedding=vector,
    )
    entry = SimpleNamespace(
        hs_code=hs_code,
        title=f"Товар {hs_code}",
        level=10,
    )
    return embedding, entry


class SemanticSearchSafetyTests(unittest.TestCase):
    @staticmethod
    def _provider_client(vector):
        response = SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"data": [{"index": 0, "embedding": vector}]},
        )
        client = MagicMock()
        client.__enter__.return_value = client
        client.post.return_value = response
        return client

    def test_provider_parser_rejects_coercible_and_overflowing_coordinates(self) -> None:
        invalid_vectors = ([True, False], ["1", "0"], [10**10000, 0])
        for vector in invalid_vectors:
            with self.subTest(vector_type=type(vector[0]).__name__):
                with (
                    patch("app.services.embedding_service._openai_key", return_value="test-key"),
                    patch(
                        "app.services.embedding_service.httpx.Client",
                        return_value=self._provider_client(vector),
                    ),
                ):
                    self.assertEqual(embed_texts_openai(["товар"]), [[]])

    def test_semantic_search_rejects_invalid_provider_json_before_database(self) -> None:
        invalid_vectors = ([True, False], ["1", "0"], [10**10000, 0])
        for vector in invalid_vectors:
            with self.subTest(vector_type=type(vector[0]).__name__):
                with (
                    patch("app.services.embedding_service._openai_key", return_value="test-key"),
                    patch(
                        "app.services.embedding_service.httpx.Client",
                        return_value=self._provider_client(vector),
                    ),
                    patch(
                        "app.services.embedding_service.SessionLocal",
                        side_effect=AssertionError("database must not be queried"),
                    ),
                ):
                    self.assertEqual(semantic_search_tnved("описание товара"), [])

    def test_cosine_similarity_rejects_non_finite_values(self) -> None:
        self.assertEqual(cosine_sim([1.0, 0.0], [math.nan, 1.0]), 0.0)
        self.assertEqual(cosine_sim([1.0, math.inf], [1.0, 0.0]), 0.0)

    def test_search_uses_only_same_model_dimension_and_finite_vectors(self) -> None:
        rows = [
            _row(model="model-a", dim=2, vector=[1.0, 0.0], hs_code="0101000000"),
            _row(model="model-b", dim=2, vector=[1.0, 0.0], hs_code="0202000000"),
            _row(model="model-a", dim=3, vector=[1.0, 0.0, 0.0], hs_code="0303000000"),
            _row(model="model-a", dim=2, vector=[math.nan, 0.0], hs_code="0404000000"),
            _row(model="model-a", dim=2, vector=["bad", 0.0], hs_code="0505000000"),
        ]

        with (
            patch("app.services.embedding_service._embedding_model", return_value="model-a"),
            patch("app.services.embedding_service.embed_texts_openai", return_value=[[1.0, 0.0]]),
            patch("app.services.embedding_service.SessionLocal", return_value=_FakeSession(rows)),
        ):
            results = semantic_search_tnved("описание товара")

        self.assertEqual([item["hs_code"] for item in results], ["0101000000"])
        self.assertEqual(results[0]["embedding_model"], "model-a")
        self.assertEqual(results[0]["score"], 1.0)

    def test_search_omits_non_positive_candidates_and_ranks_positive_matches(self) -> None:
        rows = [
            _row(model="model-a", dim=2, vector=[0.8, 0.6], hs_code="0101000000"),
            _row(model="model-a", dim=2, vector=[1.0, 1.0], hs_code="0202000000"),
            _row(model="model-a", dim=2, vector=[0.0, 1.0], hs_code="0303000000"),
            _row(model="model-a", dim=2, vector=[-1.0, 0.0], hs_code="0404000000"),
        ]

        with (
            patch("app.services.embedding_service._embedding_model", return_value="model-a"),
            patch("app.services.embedding_service.embed_texts_openai", return_value=[[1.0, 0.0]]),
            patch("app.services.embedding_service.SessionLocal", return_value=_FakeSession(rows)),
        ):
            results = semantic_search_tnved("описание товара")

        self.assertEqual(
            [(item["hs_code"], item["score"]) for item in results],
            [("0101000000", 0.8), ("0202000000", 0.707107)],
        )

    def test_search_does_not_rank_zero_or_overflowing_stored_norms(self) -> None:
        rows = [
            _row(model="model-a", dim=2, vector=[0.0, 0.0], hs_code="0101000000"),
            _row(
                model="model-a",
                dim=2,
                vector=[1.7e308, 1.7e308],
                hs_code="0202000000",
            ),
        ]

        with (
            patch("app.services.embedding_service._embedding_model", return_value="model-a"),
            patch("app.services.embedding_service.embed_texts_openai", return_value=[[1.0, 0.0]]),
            patch("app.services.embedding_service.SessionLocal", return_value=_FakeSession(rows)),
        ):
            self.assertEqual(semantic_search_tnved("описание товара"), [])

    def test_search_rejects_coercible_and_overflowing_stored_coordinates(self) -> None:
        rows = [
            _row(model="model-a", dim=2, vector=["1", "0"], hs_code="0101000000"),
            _row(model="model-a", dim=2, vector=[True, False], hs_code="0202000000"),
            _row(model="model-a", dim=2, vector=[10**10000, 0], hs_code="0303000000"),
        ]

        with (
            patch("app.services.embedding_service._embedding_model", return_value="model-a"),
            patch("app.services.embedding_service.embed_texts_openai", return_value=[[1, 0.0]]),
            patch("app.services.embedding_service.SessionLocal", return_value=_FakeSession(rows)),
        ):
            self.assertEqual(semantic_search_tnved("описание товара"), [])

    def test_search_accepts_plain_integer_and_float_coordinates(self) -> None:
        rows = [
            _row(model="model-a", dim=2, vector=[1, 0.0], hs_code="0101000000")
        ]

        with (
            patch("app.services.embedding_service._embedding_model", return_value="model-a"),
            patch("app.services.embedding_service.embed_texts_openai", return_value=[[1.0, 0]]),
            patch("app.services.embedding_service.SessionLocal", return_value=_FakeSession(rows)),
        ):
            results = semantic_search_tnved("описание товара")

        self.assertEqual([item["hs_code"] for item in results], ["0101000000"])
        self.assertEqual(results[0]["score"], 1.0)

    def test_search_scores_large_finite_vectors_without_overflowing_to_zero(self) -> None:
        rows = [
            _row(
                model="model-a",
                dim=2,
                vector=[1.0e308, 0.0],
                hs_code="0101000000",
            )
        ]

        with (
            patch("app.services.embedding_service._embedding_model", return_value="model-a"),
            patch(
                "app.services.embedding_service.embed_texts_openai",
                return_value=[[1.0e308, 0.0]],
            ),
            patch("app.services.embedding_service.SessionLocal", return_value=_FakeSession(rows)),
        ):
            results = semantic_search_tnved("описание товара")

        self.assertEqual([item["hs_code"] for item in results], ["0101000000"])
        self.assertEqual(results[0]["score"], 1.0)

    def test_search_fails_closed_on_invalid_query_embedding(self) -> None:
        for vectors in (
            [],
            [[math.inf, 0.0]],
            [["bad", 0.0]],
            [["1", "0"]],
            [[True, False]],
            [[10**10000, 0]],
            [[0.0, 0.0]],
            [[1.7e308, 1.7e308]],
            [[1.0], [2.0]],
        ):
            with self.subTest(vectors=vectors):
                with patch(
                    "app.services.embedding_service.embed_texts_openai",
                    return_value=vectors,
                ):
                    self.assertEqual(semantic_search_tnved("описание товара"), [])


if __name__ == "__main__":
    unittest.main()
