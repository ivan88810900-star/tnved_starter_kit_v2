"""Secret-safe readiness checks for optional external AI capabilities."""

from __future__ import annotations

import json
from typing import Any

from .assistant_chat import _validated_llm_answer
from .claude_service import _ask_llm, llm_provider_chain
from .embedding_service import (
    _openai_key,
    cosine_sim,
    embed_texts_openai,
    embeddings_stats,
)

_SYNTHETIC_CITATION = "S1"


def _contract_checks() -> dict[str, bool]:
    valid = json.dumps(
        {
            "answer": "Синтетический факт подтверждён. [S1]",
            "citation_ids": [_SYNTHETIC_CITATION],
        },
        ensure_ascii=False,
    )
    invalid = json.dumps(
        {
            "answer": "Неподтверждённый факт. [S2]",
            "citation_ids": ["S2"],
        },
        ensure_ascii=False,
    )
    return {
        "cosine_identity": cosine_sim([1.0, 0.0], [1.0, 0.0]) == 1.0,
        "cosine_dimension_guard": cosine_sim([1.0], [1.0, 0.0]) == 0.0,
        "grounded_llm_accepts_known_citation": (
            _validated_llm_answer(valid, {_SYNTHETIC_CITATION}) is not None
        ),
        "grounded_llm_rejects_unknown_citation": (
            _validated_llm_answer(invalid, {_SYNTHETIC_CITATION}) is None
        ),
    }


async def _live_llm_check() -> dict[str, Any]:
    chain = llm_provider_chain()
    if not chain:
        return {"requested": True, "ok": False, "reason": "llm_not_configured"}
    response = await _ask_llm(
        "Return only JSON. Use exactly citation S1 and no other facts.",
        (
            'Return {"answer":"Synthetic readiness check passed. [S1]",'
            '"citation_ids":["S1"]}. This contains no customer or customs data.'
        ),
    )
    validated = _validated_llm_answer(
        str(response.get("text") or ""),
        {_SYNTHETIC_CITATION},
    )
    return {
        "requested": True,
        "ok": validated is not None,
        "provider": str(response.get("provider") or "none"),
        "response_text_stored": False,
        "reason": None if validated is not None else "grounding_contract_failed",
    }


def _live_embedding_check() -> dict[str, Any]:
    if not _openai_key():
        return {"requested": True, "ok": False, "reason": "embedding_provider_not_configured"}
    vectors = embed_texts_openai(["synthetic product description for readiness check"])
    vector = vectors[0] if vectors else []
    return {
        "requested": True,
        "ok": bool(vector),
        "provider": "openai",
        "dimension": len(vector),
        "vector_stored": False,
        "reason": None if vector else "empty_embedding",
    }


async def build_optional_ai_readiness_report(
    *,
    live_llm: bool = False,
    live_embedding: bool = False,
) -> dict[str, Any]:
    """Build an aggregate report; live checks use synthetic data and never write DB rows."""
    contracts = _contract_checks()
    chain = llm_provider_chain()
    report: dict[str, Any] = {
        "format": "customsclear-optional-ai-readiness-v1",
        "external_calls_requested": bool(live_llm or live_embedding),
        "secrets_in_report": False,
        "contracts": contracts,
        "semantic_search": embeddings_stats(),
        "optional_llm": {
            "configured": bool(chain),
            "provider_order": [provider for provider, _key in chain],
            "deterministic_fallback": True,
            "grounding_validation": True,
        },
        "live_llm": {"requested": False, "ok": None},
        "live_embedding": {"requested": False, "ok": None},
    }
    if live_llm:
        try:
            report["live_llm"] = await _live_llm_check()
        except Exception as exc:
            report["live_llm"] = {
                "requested": True,
                "ok": False,
                "reason": f"provider_error:{type(exc).__name__}",
            }
    if live_embedding:
        try:
            report["live_embedding"] = _live_embedding_check()
        except Exception as exc:
            report["live_embedding"] = {
                "requested": True,
                "ok": False,
                "reason": f"provider_error:{type(exc).__name__}",
            }

    report["ok"] = bool(
        all(contracts.values())
        and (not live_llm or report["live_llm"]["ok"] is True)
        and (not live_embedding or report["live_embedding"]["ok"] is True)
    )
    return report
