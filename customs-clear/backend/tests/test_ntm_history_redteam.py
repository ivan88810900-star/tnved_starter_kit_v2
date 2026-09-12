"""Independent historical corruption and applicability checks for legacy NTM."""
from datetime import date

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.ntm_v2 import NtmApplicabilityRuleV2, NtmMeasureV2
from app.services import ntm_v2_legacy_measures_import as reader
from app.services import ntm_v2_legacy_measures_enforcement as enforcement


@pytest.fixture
def database():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[NtmMeasureV2.__table__, NtmApplicabilityRuleV2.__table__])
    factory = sessionmaker(bind=engine)
    with factory() as db:
        measure = NtmMeasureV2(
            measure_kind="vet", permit_type="ВС", title="Synthetic conditional source text",
            source_kind="legacy_non_tariff_measures", source_ref="independent:unreviewed",
            import_key="independent:measure", status="active",
            valid_from=date(2020, 1, 1), valid_to=date(2030, 12, 31),
        )
        db.add(measure)
        db.flush()
        db.add(NtmApplicabilityRuleV2(
            measure_id=measure.id, direction="export", country_iso="CN",
            hs_scope_mode="exact", hs_code="8517130000",
            source_kind="legacy_non_tariff_measures", source_ref="independent:unreviewed",
            rule_import_key="independent:rule", applicability="definite",
            requires_manual_review=False, valid_from=date(2022, 1, 1), valid_to=date(2028, 12, 31),
            description_match_json={
                "legal_review_verified": True, "manifest_sha256": "b" * 64,
                "legacy_payload": {"measure_type": "vet_control",
                    "description": "Only raw materials; processed goods explicitly excluded"},
            },
        ))
        db.commit()
    yield factory
    engine.dispose()


def snapshot(factory):
    with factory() as db:
        return {
            model.__tablename__: [tuple(row) for row in db.execute(select(model.__table__))]
            for model in (NtmMeasureV2, NtmApplicabilityRuleV2)
        }


@pytest.mark.parametrize("code,at,country,direction,expected", [
    ("8517130000", date(2025, 6, 1), "CN", "export", 1),
    ("8517130001", date(2025, 6, 1), "CN", "export", 0),
    ("8517", date(2025, 6, 1), "CN", "export", 0),
    ("8517130000", date(2021, 12, 31), "CN", "export", 0),
    ("8517130000", date(2022, 1, 1), "CN", "export", 1),
    ("8517130000", date(2028, 12, 31), "CN", "export", 1),
    ("8517130000", date(2029, 1, 1), "CN", "export", 0),
    ("8517130000", date(2025, 6, 1), "RU", "export", 0),
    ("8517130000", date(2025, 6, 1), "CN", "import", 0),
    ("8517130000", date(2025, 6, 1), None, "export", 1),
])
def test_history_country_direction_and_leaf_scope_cannot_create_document_obligation(
        database, code, at, country, direction, expected):
    before = snapshot(database)
    with database() as db:
        rows = reader.get_v2_legacy_measures_broker_rows(
            code, "Processed excluded goods", session=db, as_of=at, country=country, direction=direction)
    assert len(rows) == expected
    for row in rows:
        assert row["as_of"] == at.isoformat()
        assert row["stored_applicability"] == "definite"
        assert row["applicability"] == "needs_clarification"
        assert row["requires_manual_review"] is True
        assert row["used_for_missing_check"] is False
        assert row["legal_review_verified"] is False
        assert enforcement.classify_v2_measure_for_enforcement(row, []) == "manual_review"
    assert reader.merge_v2_legacy_measures_into_broker([], rows) == []
    assert snapshot(database) == before


def test_corrupt_persisted_json_is_unavailable_instead_of_empty_legal_result(database):
    with database() as db:
        db.execute(text("UPDATE ntm_applicability_rules_v2 SET description_match_json='broken-json'"))
        db.commit()
        rows = reader.get_v2_legacy_measures_broker_rows(
            "8517130000", "Processed goods", session=db,
            as_of=date(2025, 6, 1), country="CN", direction="export")
    assert len(rows) == 1
    assert rows[0]["source_data_status"] == "unavailable"
    assert rows[0]["permit_type"] == ""
    assert rows[0]["used_for_missing_check"] is False
    assert rows[0]["requires_manual_review"] is True


def test_stored_exclusion_and_mutually_inconsistent_dates_never_grant(database):
    with database() as db:
        rule = db.query(NtmApplicabilityRuleV2).one()
        rule.excluded_hs_json = ["8517"]
        db.commit()
        assert reader.get_v2_legacy_measures_broker_rows(
            "8517130000", session=db, as_of=date(2025, 6, 1), country="CN", direction="export") == []
        rule.excluded_hs_json = []
        rule.valid_from = date(2028, 1, 1)
        rule.valid_to = date(2022, 1, 1)
        db.commit()
        rows = reader.get_v2_legacy_measures_broker_rows(
            "8517130000", session=db, as_of=date(2025, 6, 1), country="CN", direction="export")
    assert len(rows) == 1
    assert "effective_dates_unverified" in rows[0]["context_review_reasons"]
    assert rows[0]["used_for_missing_check"] is False
    assert rows[0]["legal_review_verified"] is False
