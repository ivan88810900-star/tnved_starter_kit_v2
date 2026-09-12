"""Unknown legacy TR coverage is retained for review, never made mandatory.

All documentary text below is synthetic; these tests establish routing and
enforcement boundaries, not the applicability of any technical regulation.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.ntm_v2 import NtmApplicabilityRuleV2, NtmMeasureV2
from app.models.tnved import Chapter, Commodity, NonTariffMeasure, Section
from app.services.non_tariff_rules import _measure_to_permit_type, find_measures_for_code
from app.services.ntm_noise_classifier import (
    classify_measures, is_measure_noise, tr_ts_scope_requires_review,
)
from app.services.ntm_v2_legacy_measures_import import (
    get_v2_legacy_measures_broker_rows, import_legacy_non_tariff_measures_to_ntm_v2,
    legacy_measure_dict_to_broker_row, merge_v2_legacy_measures_into_broker,
)


@pytest.fixture
def sessions(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[
        Section.__table__, Chapter.__table__, Commodity.__table__,
        NonTariffMeasure.__table__, NtmMeasureV2.__table__,
        NtmApplicabilityRuleV2.__table__,
    ])
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr("app.db.SessionLocal", factory)
    monkeypatch.setattr("app.services.non_tariff_rules.SessionLocal", factory)
    monkeypatch.setattr("app.services.normative_store.SessionLocal", factory)
    yield factory
    engine.dispose()


def seed(factory, code="8517130000", *, text="Декларация о соответствии"):
    with factory() as session:
        section = Section(roman_number="XVI", title="Synthetic")
        session.add(section)
        session.flush()
        chapter = Chapter(section_id=section.id, code=code[:2], title="Synthetic")
        session.add(chapter)
        session.flush()
        session.add(Commodity(chapter_id=chapter.id, code=code, description="Synthetic"))
        session.add(NonTariffMeasure(
            commodity_code=code, measure_type="tr_ts", quality="normal",
            description="Synthetic scope-unresolved source record",
            document_required=text, regulatory_act="ТР ЕАЭС 037/2016",
        ))
        session.commit()


@pytest.mark.parametrize("code", ["8517120000", "8517130000", "8517140000", "8517", "85", "9999999999"])
def test_missing_positive_catalog_match_is_reviewable_not_proven_noise(code):
    assert not is_measure_noise(code, "tr_ts")
    assert tr_ts_scope_requires_review(code, "tr_ts")
    noise, retained = classify_measures([(1, code, "tr_ts")])
    assert noise == [] and retained == [1]


@pytest.mark.parametrize("text", [
    "Декларация о соответствии", "Сертификат соответствия", "Ветеринарный сертификат",
])
def test_documentary_keywords_cannot_resolve_unknown_tr_scope(text):
    assert _measure_to_permit_type("tr_ts", text, "8517130000") is None


def test_supported_catalog_and_other_measure_types_keep_existing_handling():
    assert not tr_ts_scope_requires_review("8471300000", "tr_ts")
    assert _measure_to_permit_type("tr_ts", "Декларация о соответствии", "8471300000") == "ДС"
    assert not tr_ts_scope_requires_review("0201100000", "vet_control")
    assert _measure_to_permit_type("vet_control", "Ветеринарный сертификат", "0201100000") == "ВС"


def test_import_preserves_raw_source_but_requires_review_and_is_idempotent(sessions):
    seed(sessions)
    with sessions() as session:
        first = import_legacy_non_tariff_measures_to_ntm_v2(session)
        second = import_legacy_non_tariff_measures_to_ntm_v2(session)
        rule = session.scalars(select(NtmApplicabilityRuleV2)).one()
        measure = session.scalars(select(NtmMeasureV2)).one()
        source = session.scalars(select(NonTariffMeasure)).one()
        assert first["measures_created"] == 1 and second["measures_created"] == 0
        assert rule.applicability == "needs_clarification" and rule.requires_manual_review
        assert measure.permit_type == ""
        assert source.quality == "normal"
        assert rule.description_match_json["legacy_payload"]["document_required"] == "Декларация о соответствии"
        assert session.query(NtmApplicabilityRuleV2).count() == 1


def test_previously_imported_definite_row_is_safe_before_and_after_reimport(sessions):
    seed(sessions)
    with sessions() as session:
        import_legacy_non_tariff_measures_to_ntm_v2(session)
        rule = session.scalars(select(NtmApplicabilityRuleV2)).one()
        measure = session.scalars(select(NtmMeasureV2)).one()
        rule.applicability, rule.requires_manual_review = "definite", False
        measure.permit_type = "ДС"
        payload = dict(rule.description_match_json)
        payload["legacy_payload"] = {**payload["legacy_payload"], "permit_type": "ДС"}
        rule.description_match_json = payload
        session.commit()

        before = get_v2_legacy_measures_broker_rows("8517130000", session=session)
        assert len(before) == 1 and before[0]["permit_type"] == ""
        assert before[0]["applicability"] == "needs_clarification"
        assert before[0]["requires_manual_review"]
        assert merge_v2_legacy_measures_into_broker([], before) == []
        # Read-only guard did not mutate the old persisted classification.
        session.expire_all()
        assert rule.applicability == "definite" and measure.permit_type == "ДС"
        import_legacy_non_tariff_measures_to_ntm_v2(session)
        assert rule.applicability == "needs_clarification" and rule.requires_manual_review
        assert measure.permit_type == ""


def test_known_catalog_retains_permit_hint_without_approving_legacy_scope(sessions):
    seed(sessions, "8471300000")
    with sessions() as session:
        import_legacy_non_tariff_measures_to_ntm_v2(session)
        rule = session.scalars(select(NtmApplicabilityRuleV2)).one()
        measure = session.scalars(select(NtmMeasureV2)).one()
        assert rule.applicability == "needs_clarification" and rule.requires_manual_review
        assert measure.permit_type == "ДС"


def test_legacy_lookup_clears_mandatory_permit_and_retains_review_details(sessions):
    seed(sessions)
    rows = find_measures_for_code("8517130000")
    assert len(rows) == 1
    assert rows[0]["permit_type"] is None
    assert rows[0]["applicability"] == "needs_clarification"
    assert rows[0]["requires_manual_review"] and not rows[0]["used_for_missing_check"]
    assert rows[0]["document_required"] == "Декларация о соответствии"


def test_broker_row_conversion_and_merge_do_not_lose_review_gate():
    row = legacy_measure_dict_to_broker_row({
        "measure_type": "tr_ts", "commodity_code": "8517130000",
        "permit_type": "ДС", "tr_ts_code": "037/2016",
    })
    assert row["permit_type"] == "" and row["requires_manual_review"]
    assert row["applicability"] == "needs_clarification"
    assert merge_v2_legacy_measures_into_broker([], [row]) == []
    assert merge_v2_legacy_measures_into_broker([], [{
        "permit_type": "ДС", "tr_ts": "037/2016", "applicability": "needs_clarification",
    }]) == []


@pytest.fixture
def isolated_position(monkeypatch):
    from app.services import non_tariff_service as service
    monkeypatch.setattr(service, "get_full_ntm_requirements", lambda *args: [])
    monkeypatch.setattr(service, "find_rules_for_code", lambda *args: [])
    monkeypatch.setattr(service, "find_measures_by_description", lambda *args: [])
    monkeypatch.setattr(service, "get_sensitive_override", lambda *args: None)
    monkeypatch.setattr(service, "find_normative_notes_for_hs", lambda *args: [])
    monkeypatch.setattr(service, "get_regulatory_documents_for_hs", lambda *args, **kwargs: [])
    monkeypatch.setattr(service, "lookup_tr_ts_acts_by_codes", lambda *args: [])
    monkeypatch.setattr(service, "_data_freshness", lambda: {})
    monkeypatch.setattr(service, "build_sanctions_risk_block", lambda **kwargs: SimpleNamespace(model_dump=lambda: {}))
    return service


@pytest.mark.parametrize("enforcement", [False, True])
def test_unknown_tr_is_visible_only_as_advisory_even_with_measures_enforcement(sessions, isolated_position, enforcement):
    seed(sessions)
    with sessions() as session:
        import_legacy_non_tariff_measures_to_ntm_v2(session)
    result = asyncio.run(isolated_position.check_position_non_tariff(
        hs_code="8517130000", description="", country="CN", permits=[],
        skip_registry_verify=True, measures_enforcement_enabled=enforcement,
        rules_enforcement_enabled=False, official_sgr_advisory_enabled=False,
        official_ntm_advisory_enabled=False, official_curated_enforcement_enabled=False,
        include_effective_requirements_debug=True,
    ))
    assert result["status"] == "WARNING"
    assert result["required_permits"] == result["required_permit_types"] == result["missing_permit_types"] == []
    assert len(result["advisory_requirements"]) == 1
    advisory = result["advisory_requirements"][0]
    assert advisory["source"] == "legacy_non_tariff_measures"
    assert advisory["applicability"] == "needs_clarification"
    assert advisory["requires_manual_review"] and not advisory["used_for_missing_check"]
    assert result["rule_sources"][0]["required_permits"] == []
    assert result["rule_sources"][0]["applicability"] == "needs_clarification"
    assert result["normative_block"]["required_documents"] == []
    assert result["normative_block"]["advisory_requirements"][0]["applicability"] == "needs_clarification"
    assert result["effective_requirements_debug"]["used_for_missing_check"] == []


def test_unknown_tr_trigger_cannot_enter_broker_from_caller_supplied_permit():
    from app.services.non_tariff_service import _build_broker_required_permits
    assert _build_broker_required_permits("8517130000", [], [{
        "measure_type": "tr_ts", "commodity_code": "8517130000",
        "permit_type": "ДС", "tr_ts_code": "037/2016", "source_level": "trigger",
    }], None) == []


@pytest.mark.parametrize("source_level,expected_source", [
    ("trigger", "legacy_description_trigger"), ("ai_enriched", "ai_extracted"),
])
def test_unresolved_advisory_preserves_description_and_ai_origin(sessions, isolated_position, monkeypatch, source_level, expected_source):
    row = {
        "measure_type": "tr_ts", "commodity_code": "8517130000", "permit_type": "ДС",
        "tr_ts_code": "037/2016", "source_level": source_level,
    }
    async def enrich(**kwargs):
        return [row] if source_level == "ai_enriched" else []
    monkeypatch.setattr(isolated_position, "enrich_measures_by_description", enrich)
    monkeypatch.setattr(isolated_position, "find_measures_by_description",
                        lambda *args: [row] if source_level == "trigger" else [])
    result = asyncio.run(isolated_position.check_position_non_tariff(
        hs_code="8517130000", description="Synthetic description", country="CN", permits=[],
        skip_registry_verify=True, measures_enforcement_enabled=False,
        rules_enforcement_enabled=False, official_sgr_advisory_enabled=False,
        official_ntm_advisory_enabled=False, official_curated_enforcement_enabled=False,
    ))
    assert result["status"] == "WARNING" and result["required_permit_types"] == []
    assert result["missing_permit_types"] == []
    assert result["advisory_requirements"][0]["source"] == expected_source
    assert result["advisory_requirements"][0]["applicability"] == "needs_clarification"
