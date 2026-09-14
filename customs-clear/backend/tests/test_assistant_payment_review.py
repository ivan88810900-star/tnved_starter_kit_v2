"""The assistant must not convert preliminary payment estimates into final sums."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from app.api.assistant import AssistantChatRequest
from app.services import assistant_chat, assistant_orchestrator, claude_service, grounded_assistant


def _context():
    return {
        "hs_code": "8517130000",
        "total_payable": 342,
        "duty_rub": 100,
        "vat_rub": 242,
        "payment_status": "REVIEW_REQUIRED",
        "amounts_provisional": True,
        "tariff_preference": {
            "applied": False, "status": "needs_review",
            "reason": "Страна сама по себе не подтверждает применимость преференции.",
        },
    }


def _chat_bundle(context):
    collector = grounded_assistant._CitationCollector()
    payment = grounded_assistant._payment_snapshot(context, collector)
    return {
        "question": "Какие платежи и итог?", "resolved_hs_code": "8517130000",
        "payment": payment, "tnved": {}, "facts_used": ["payments"],
        "citations": collector.items, "coverage": "grounded", "limitations": [],
    }


def test_assistant_request_and_snapshot_keep_provisional_context():
    req = AssistantChatRequest.model_validate({"message": "Какие платежи?", "context": _context()})
    context = req.resolved_context().model_dump()
    bundle = _chat_bundle(context)
    assert bundle["payment"]["status"] == "REVIEW_REQUIRED"
    assert bundle["payment"]["amounts_provisional"] is True
    assert bundle["payment"]["tariff_preference"]["applied"] is False
    assert bundle["citations"][0]["status"] == "REVIEW_REQUIRED"
    answer, _ = grounded_assistant.render_chat_grounded_answer(bundle)
    assert "Предварительный итог" in answer
    assert "итог к уплате не подтверждён" in answer
    assert "Страна сама по себе" in answer


@pytest.mark.parametrize("evidence", [
    {"payment_status": "REVIEW_REQUIRED"},
    {"amounts_provisional": True},
    {"tariff_preference": {"status": "needs_review"}},
    {"payment_data_quality": {"amounts_provisional": True}},
    {"payment_review_reason": "Ставка пошлины не подтверждена источником."},
])
def test_pending_evidence_is_not_lost_when_other_flags_missing(evidence):
    bundle = _chat_bundle({"total_payable": 342, **evidence})
    assert bundle["payment"]["amounts_provisional"] is True
    assert bundle["citations"][0]["status"] == "REVIEW_REQUIRED"


def test_legacy_snapshot_is_not_marked_verified():
    bundle = _chat_bundle({"total_payable": 342})
    assert bundle["payment"]["amounts_provisional"] is None
    assert bundle["payment"]["status"] is None
    assert bundle["payment"]["tariff_preference"] is None


def test_unknown_rate_reason_survives_assistant_without_false_preference_claim():
    reason = "Ставка пошлины не подтверждена источником."
    context = AssistantChatRequest.model_validate({
        "message": "Какие платежи?",
        "context": {
            "hs_code": "8517130000", "total_payable": 242,
            "payment_status": "REVIEW_REQUIRED", "amounts_provisional": True,
            "payment_review_reason": reason,
            "payment_review_reasons": ["duty_source_missing"],
        },
    }).resolved_context().model_dump()
    bundle = _chat_bundle(context)
    assert bundle["payment"]["payment_review_reason"] == reason
    assert bundle["payment"]["payment_review_reasons"] == ["duty_source_missing"]
    answer, _ = grounded_assistant.render_chat_grounded_answer(bundle)
    assert reason in answer
    assert "Предварительный итог" in answer
    assert "преференц" not in answer.lower()


def test_generic_review_reason_survives_copilot_projection():
    reason = "Ставка НДС не подтверждена источником."
    slim = assistant_orchestrator.bundle_for_llm({
        "effective_hs_code": "8517130000",
        "payment": {
            "status": "REVIEW_REQUIRED", "amounts_provisional": True,
            "payment_review_reason": reason,
            "payment_review_reasons": ["vat_source_missing"],
            "breakdown": {"duty": 100, "vat": 242, "total_payable": 342},
        },
    })
    assert slim["payment_summary"]["payment_review_reasons"] == ["vat_source_missing"]
    result = grounded_assistant.build_copilot_deterministic_summary(slim)
    assert reason in result["payment_comment"]
    assert "преференц" not in result["payment_comment"].lower()


def test_provisional_chat_cannot_lose_caveat_in_optional_rewrite(monkeypatch):
    bundle = _chat_bundle(_context())
    monkeypatch.setattr(assistant_chat, "build_chat_grounding_bundle", AsyncMock(return_value=bundle))
    monkeypatch.setattr(assistant_chat, "llm_provider_chain", lambda: [("test", "unused")])
    ask = AsyncMock(return_value={"text": '{"answer":"Оплатите 342 руб. [S1]","citation_ids":["S1"]}'})
    monkeypatch.setattr(assistant_chat, "_ask_llm", ask)
    result = asyncio.run(assistant_chat.run_assistant_chat(
        message="Какие платежи?", history=[], current_context=_context()
    ))
    ask.assert_not_awaited()
    assert result["grounding"]["mode"] == "deterministic"
    assert "Предварительный итог" in result["answer"]
    assert "итог к уплате не подтверждён" in result["answer"]


@pytest.mark.parametrize("batch", [False, True])
def test_copilot_keeps_review_status_from_pipeline_to_wording(monkeypatch, batch):
    context = _context()
    slim = assistant_orchestrator.bundle_for_llm({
        "effective_hs_code": "8517130000",
        "payment": {
            "status": context["payment_status"],
            "amounts_provisional": context["amounts_provisional"],
            "tariff_preference": context["tariff_preference"],
            "breakdown": {"duty": 100, "vat": 242, "total_payable": 342},
        },
    })
    assert slim["payment_summary"]["amounts_provisional"] is True
    ask = AsyncMock()
    monkeypatch.setattr(claude_service, "_ask_llm", ask)
    monkeypatch.setattr(claude_service, "_choose_provider", lambda: ("test", "unused"))
    result = asyncio.run(claude_service.analyze_copilot_bundle({"positions": [slim]} if batch else slim))
    ask.assert_not_awaited()
    assert result["grounding"]["mode"] == "deterministic"
    assert "предварительный итог" in result["payment_comment"]
    assert "итог к уплате не подтверждён" in result["payment_comment"]
    assert any("Страна сама по себе" in risk for risk in result["risks"])
