"""Evidence-first assistant: deterministic fallback, citations, and LLM guardrails."""

from __future__ import annotations

import json
import unittest
from unittest.mock import AsyncMock, patch

from app.services.assistant_chat import run_assistant_chat
from app.services.claude_service import analyze_copilot_bundle
from app.services.grounded_assistant import (
    build_chat_grounding_bundle,
    render_chat_grounded_answer,
)
from app.services.normative_store import SEED_TNVED


def _chat_bundle() -> dict:
    return {
        "question": "Какие документы, платежи и риски?",
        "resolved_hs_code": "8516108008",
        "hs_source": "calculator_context",
        "product_name": "Электрический чайник",
        "country": "CN",
        "tnved": {
            "hs_code": "8516108008",
            "title": "Электрические водонагреватели",
            "description": "",
            "citation_ids": ["S1"],
        },
        "payment": {
            "total_payable": 25_000,
            "customs_value_rub": 100_000,
            "duty_rate_pct": 5,
            "vat_rate_pct": 22,
            "duty_rub": 5_000,
            "vat_rub": 23_100,
            "customs_fee_rub": 1_067,
            "citation_ids": ["S2"],
        },
        "requirements": {
            "required_documents": [
                {
                    "permit_type": "ДС",
                    "tr_ts": "004/2011",
                    "applicability": "definite",
                    "citation_id": "S3",
                }
            ],
            "unconfirmed_documents": [{"permit_type": "ДС", "citation_id": "S3"}],
            "advisory_requirements": [
                {
                    "permit_type": "СГР",
                    "applicability": "needs_clarification",
                    "citation_id": "S3",
                }
            ],
        },
        "risk": {
            "overall_severity": "manual_review_required",
            "coverage_complete": False,
            "signals": [],
            "screening_scope": [
                {"code": "counterparty", "label": "Контрагент", "status": "not_checked"}
            ],
            "source_coverage": [{"citation_id": "S4"}],
        },
        "search_candidates": [],
        "search": {},
        "canonical_anchor": {
            "stable_id": "node-abc",
            "snapshot_id": "snapshot-1",
            "code": "8516108008",
            "node_type": "commodity",
        },
        "coverage": "grounded",
        "facts_used": ["tnved", "payments", "requirements", "risk"],
        "citations": [
            {"id": "S1", "source_id": "eec_ett", "title": "ЕТТ ЕАЭС", "kind": "official"},
            {"id": "S2", "source_id": "calculator_snapshot", "title": "Расчёт", "kind": "calculation"},
            {"id": "S3", "source_id": "official_rules", "title": "ТР ТС", "kind": "official"},
            {"id": "S4", "source_id": "ofac_sdn_list", "title": "OFAC", "kind": "local_registry"},
        ],
        "limitations": ["Санкционный скрининг имеет неполное покрытие."],
    }


class GroundingBundleTests(unittest.IsolatedAsyncioTestCase):
    async def test_bundle_reuses_server_facts_and_separates_advisory(self) -> None:
        nt_result = {
            "status": "WARNING",
            "normative_block": {
                "status": "WARNING",
                "required_documents": [
                    {
                        "permit_type": "ДС",
                        "tr_ts": "004/2011",
                        "source": "tr_ts_catalog",
                        "source_label": "ТР ТС каталог",
                        "applicability": "definite",
                    }
                ],
                "missing_documents": [{"permit_type": "ДС", "source": "tr_ts_catalog"}],
                "advisory_requirements": [
                    {
                        "permit_type": "СГР",
                        "source": "official_sgr_registry",
                        "source_label": "Решение ЕЭК №299",
                        "applicability": "needs_clarification",
                    }
                ],
            },
            "risk_block": {
                "status": "MANUAL_REVIEW",
                "overall_severity": "manual_review_required",
                "coverage_complete": False,
                "signals": [],
                "source_coverage": [
                    {
                        "source_id": "ofac_sdn_list",
                        "title": "OFAC SDN",
                        "coverage_status": "missing",
                        "manual_review_required": True,
                    }
                ],
                "screening_scope": [
                    {"code": "hs_code", "label": "Код", "status": "checked", "value": "8516108008"}
                ],
            },
        }
        with (
            patch(
                "app.services.grounded_assistant.get_tnved_context_for_hs",
                return_value={
                    "title": "Электрические водонагреватели",
                    "description": "",
                    "breadcrumb": [],
                    "notes": [],
                    "official_ett_url": "https://eec.example/ett",
                    "source_revision": "official-test",
                },
            ),
            patch(
                "app.services.grounded_assistant.canonical_anchor_for_hs",
                return_value={
                    "stable_id": "node-1",
                    "snapshot_id": "snap-1",
                    "code": "8516108008",
                    "node_type": "commodity",
                },
            ),
            patch(
                "app.services.grounded_assistant.check_position_non_tariff",
                new=AsyncMock(return_value=nt_result),
            ),
        ):
            bundle = await build_chat_grounding_bundle(
                message="Какие документы?",
                history=[],
                current_context={
                    "hs_code": "8516108008",
                    "product_name": "Чайник",
                    "origin_country": "CN",
                    "total_payable": 25_000,
                    "payment_data_quality": {"confidence": "high"},
                },
            )

        self.assertEqual(bundle["resolved_hs_code"], "8516108008")
        self.assertEqual(bundle["coverage"], "grounded")
        self.assertEqual(bundle["requirements"]["required_documents"][0]["applicability"], "definite")
        self.assertEqual(
            bundle["requirements"]["advisory_requirements"][0]["applicability"],
            "needs_clarification",
        )
        self.assertFalse(bundle["risk"]["coverage_complete"])
        self.assertTrue(bundle["citations"])

    def test_seed_does_not_label_850940_as_kettle(self) -> None:
        row = next(item for item in SEED_TNVED if item["hs_code"] == "8509400000")
        self.assertNotIn("чайник", row["title"].lower())
        self.assertIn("измельчител", row["title"].lower())

    async def test_chat_search_removes_question_words_before_typo_recovery(self) -> None:
        with (
            patch(
                "app.services.grounded_assistant.search_commodities_smart",
                return_value={
                    "results": [
                        {
                            "code": "8517130000",
                            "description": "Смартфоны",
                            "match_reason": "typo_correction",
                        }
                    ],
                    "strategy": "hybrid_fts_typo",
                    "effective_query": "смартфон",
                    "corrected_query": "смартфон",
                },
            ) as search,
            patch(
                "app.services.grounded_assistant.canonical_anchors_for_hs_codes",
                return_value={},
            ),
        ):
            bundle = await build_chat_grounding_bundle(
                message="Подбери код ТН ВЭД для смартфн",
                history=[],
                current_context=None,
            )
        search.assert_called_once_with("смартфн", limit=5)
        self.assertEqual(bundle["search"]["corrected_query"], "смартфон")
        self.assertEqual(bundle["search_candidates"][0]["match_reason"], "typo_correction")


class DeterministicAnswerTests(unittest.TestCase):
    def test_answer_has_inline_sources_and_conservative_risk_language(self) -> None:
        answer, suggestions = render_chat_grounded_answer(_chat_bundle())
        self.assertIn("[S1]", answer)
        self.assertIn("[S2]", answer)
        self.assertIn("не означает «риска нет»", answer)
        self.assertIn("не считается обязательным", answer)
        self.assertTrue(suggestions)


class AssistantChatGuardrailTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_key_returns_useful_server_answer(self) -> None:
        with (
            patch(
                "app.services.assistant_chat.build_chat_grounding_bundle",
                new=AsyncMock(return_value=_chat_bundle()),
            ),
            patch("app.services.assistant_chat.llm_provider_chain", return_value=[]),
        ):
            result = await run_assistant_chat(
                message="Какие документы и платежи?",
                history=[],
                current_context={"hs_code": "8516108008"},
            )
        self.assertEqual(result["grounding"]["mode"], "deterministic")
        self.assertFalse(result["grounding"]["llm_configured"])
        self.assertIn("### Платежи", result["answer"])
        self.assertNotIn("ключ", result["answer"].lower())

    async def test_configured_llm_must_return_known_inline_citation(self) -> None:
        response = json.dumps(
            {
                "answer": "По серверному расчёту итог составляет 25 000 ₽. [S2]",
                "citation_ids": ["S2"],
            },
            ensure_ascii=False,
        )
        with (
            patch(
                "app.services.assistant_chat.build_chat_grounding_bundle",
                new=AsyncMock(return_value=_chat_bundle()),
            ),
            patch("app.services.assistant_chat.llm_provider_chain", return_value=[("anthropic", "test")]),
            patch(
                "app.services.assistant_chat._ask_llm",
                new=AsyncMock(return_value={"provider": "anthropic", "text": response}),
            ),
        ):
            result = await run_assistant_chat(
                message="Сколько платить?",
                history=[],
                current_context={"hs_code": "8516108008"},
            )
        self.assertEqual(result["grounding"]["mode"], "llm_grounded")
        self.assertEqual(result["grounding"]["provider"], "anthropic")
        self.assertIn("[S2]", result["answer"])

    async def test_unknown_llm_citation_falls_back_to_deterministic(self) -> None:
        response = json.dumps(
            {"answer": "Выдуманный факт. [S999]", "citation_ids": ["S999"]},
            ensure_ascii=False,
        )
        with (
            patch(
                "app.services.assistant_chat.build_chat_grounding_bundle",
                new=AsyncMock(return_value=_chat_bundle()),
            ),
            patch("app.services.assistant_chat.llm_provider_chain", return_value=[("gemini", "test")]),
            patch(
                "app.services.assistant_chat._ask_llm",
                new=AsyncMock(return_value={"provider": "gemini", "text": response}),
            ),
        ):
            result = await run_assistant_chat(
                message="Что делать?",
                history=[],
                current_context={"hs_code": "8516108008"},
            )
        self.assertEqual(result["grounding"]["mode"], "deterministic")
        self.assertNotIn("S999", result["answer"])
        self.assertTrue(
            any("не прошёл проверку" in item for item in result["grounding"]["limitations"])
        )

    async def test_unknown_declared_citation_falls_back_even_when_inline_id_is_valid(self) -> None:
        response = json.dumps(
            {
                "answer": "По серверному расчёту итог составляет 25 000 ₽. [S2]",
                "citation_ids": ["S2", "S999"],
            },
            ensure_ascii=False,
        )
        with (
            patch(
                "app.services.assistant_chat.build_chat_grounding_bundle",
                new=AsyncMock(return_value=_chat_bundle()),
            ),
            patch("app.services.assistant_chat.llm_provider_chain", return_value=[("gemini", "test")]),
            patch(
                "app.services.assistant_chat._ask_llm",
                new=AsyncMock(return_value={"provider": "gemini", "text": response}),
            ),
        ):
            result = await run_assistant_chat(
                message="Сколько платить?",
                history=[],
                current_context={"hs_code": "8516108008"},
            )
        self.assertEqual(result["grounding"]["mode"], "deterministic")
        self.assertNotIn("S999", result["answer"])


class CopilotGroundingTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _context() -> dict:
        return {
            "effective_hs_code": "8516108008",
            "description": "Электрический чайник",
            "tnved_from_db": {
                "title": "Электрические водонагреватели",
                "official_ett_url": "https://eec.example/ett",
                "source_revision": "official-test",
            },
            "payment_summary": {
                "duty": 5_000,
                "vat": 23_100,
                "total_payable": 29_167,
                "data_quality": {"confidence": "high", "antidumping_status": "none"},
            },
            "normative_requirements": {
                "required_documents": [
                    {
                        "permit_type": "ДС",
                        "source": "tr_ts_catalog",
                        "source_label": "ТР ТС каталог",
                        "applicability": "definite",
                    }
                ],
                "missing_documents": [{"permit_type": "ДС"}],
                "advisory_requirements": [],
            },
            "risk_summary": {
                "overall_severity": "manual_review_required",
                "coverage_complete": False,
            },
        }

    async def test_copilot_without_key_is_still_a_full_summary(self) -> None:
        with patch("app.services.claude_service._choose_provider", return_value=("none", None)):
            result = await analyze_copilot_bundle(self._context())
        self.assertEqual(result["grounding"]["mode"], "deterministic")
        self.assertTrue(result["citations"])
        self.assertIn("29167", result["payment_comment"].replace(" ", ""))
        self.assertTrue(result["next_steps"])
        self.assertNotIn("Ключ ИИ", result.get("note", ""))

    async def test_copilot_reports_only_fact_blocks_that_were_present(self) -> None:
        context = self._context()
        context.pop("payment_summary")
        with patch("app.services.claude_service._choose_provider", return_value=("none", None)):
            result = await analyze_copilot_bundle(context)
        self.assertNotIn("payments", result["grounding"]["facts_used"])
        self.assertIn("tnved", result["grounding"]["facts_used"])

    async def test_malformed_copilot_llm_response_does_not_expose_raw_text(self) -> None:
        with (
            patch("app.services.claude_service._choose_provider", return_value=("anthropic", "test")),
            patch(
                "app.services.claude_service._ask_llm",
                new=AsyncMock(return_value={"provider": "anthropic", "text": "not-json-secret"}),
            ),
        ):
            result = await analyze_copilot_bundle(self._context())
        self.assertEqual(result["grounding"]["mode"], "deterministic")
        self.assertNotIn("raw", result)
        self.assertNotIn("not-json-secret", json.dumps(result, ensure_ascii=False))

    async def test_copilot_rejects_unknown_declared_citation(self) -> None:
        response = json.dumps(
            {
                "summary": "Рабочий код требует проверки характеристик. [S1]",
                "citation_ids": ["S1", "S999"],
            },
            ensure_ascii=False,
        )
        with (
            patch("app.services.claude_service._choose_provider", return_value=("anthropic", "test")),
            patch(
                "app.services.claude_service._ask_llm",
                new=AsyncMock(return_value={"provider": "anthropic", "text": response}),
            ),
        ):
            result = await analyze_copilot_bundle(self._context())
        self.assertEqual(result["grounding"]["mode"], "deterministic")
        self.assertNotIn("S999", json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
