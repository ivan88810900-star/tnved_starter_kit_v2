"""Historical legacy metadata is not legal applicability or a source review."""
from datetime import date, datetime

import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.ntm_v2 import NtmApplicabilityRuleV2, NtmMeasureV2
from app.services import ntm_v2_legacy_measures_import as service
from app.services import ntm_v2_legacy_measures_enforcement as enforcement

REF = date(2026, 9, 12)


@pytest.fixture
def database():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[NtmMeasureV2.__table__, NtmApplicabilityRuleV2.__table__])
    yield sessionmaker(bind=engine)
    engine.dispose()


def seed(factory, *, code="1234567890", kind="vet", measure_changes=None, **rule_changes):
    with factory() as db:
        index = db.query(NtmMeasureV2).count()
        measure_data = dict(measure_kind=kind, permit_type="ВС" if kind == "vet" else "ФСС",
                            title="Unreviewed conditional fixture", tr_ts_act_code="", status="active",
                            source_kind=service.MEASURES_SOURCE_KIND, source_ref="fixture:legacy",
                            import_key=f"fixture:{index}")
        measure_data.update(measure_changes or {})
        measure = NtmMeasureV2(**measure_data)
        db.add(measure)
        db.flush()
        data = dict(measure_id=measure.id, direction="import", hs_scope_mode="exact", hs_code=code,
                    description_match_json={"legacy_payload": {
                        "measure_type": "vet_control" if kind == "vet" else "phyto_control",
                        "description": "Only raw goods; processed products excluded", "commodity_code": code}},
                    applicability="definite", requires_manual_review=False,
                    source_kind=service.MEASURES_SOURCE_KIND, source_ref="fixture:legacy",
                    rule_import_key=f"fixture:{index}")
        data.update(rule_changes)
        rule = NtmApplicabilityRuleV2(**data)
        db.add(rule)
        db.commit()
        return rule.id


def read(factory, code="1234567890", **kwargs):
    with factory() as db:
        return service.get_v2_legacy_measures_broker_rows(
            code, "Processed excluded product", session=db, as_of=kwargs.pop("as_of", REF), **kwargs)


def test_persisted_definite_and_forged_approval_never_override_read_review(database):
    seed(database, description_match_json={"legal_review_verified": True, "approved": True,
                                          "manifest_sha256": "a" * 64})
    with database() as db:
        before = [tuple(row) for row in db.execute(select(NtmApplicabilityRuleV2.__table__))]
    rows = read(database)
    assert len(rows) == 1
    row = rows[0]
    assert row["stored_applicability"] == "definite" and row["stored_requires_manual_review"] is False
    assert row["applicability"] == "needs_clarification" and row["requires_manual_review"] is True
    assert row["used_for_missing_check"] is False and row["legal_review_verified"] is False
    assert enforcement.classify_v2_measure_for_enforcement(row, []) == "manual_review"
    assert service.merge_v2_legacy_measures_into_broker([], rows) == []
    with database() as db:
        assert before == [tuple(row) for row in db.execute(select(NtmApplicabilityRuleV2.__table__))]


def test_exact_leaf_never_matches_sibling_or_parent_query(database):
    seed(database)
    assert read(database, "1234567899") == []
    assert read(database, "1234") == []
    assert len(read(database)) == 1


def test_specific_match_does_not_hide_distinct_broader_candidate(database):
    seed(database)
    seed(database, code="1234", kind="phyto", hs_scope_mode="prefix")
    rows = read(database)
    assert [row["matched_prefix"] for row in rows] == ["1234567890", "1234"]
    assert {row["measure_kind"] for row in rows} == {"vet", "phyto"}
    assert all(row["requires_manual_review"] for row in rows)


@pytest.mark.parametrize("at,expected", [(date(2020, 1, 1), 1), (date(2020, 1, 2), 1),
                                         (date(2019, 12, 31), 0), (date(2020, 1, 3), 0)])
@pytest.mark.parametrize("on_measure", [False, True])
def test_explicit_historical_date_and_inclusive_stored_bounds(database, at, expected, on_measure):
    bounds = {"valid_from": date(2020, 1, 1), "valid_to": date(2020, 1, 2)}
    seed(database, measure_changes=bounds if on_measure else {}, **({} if on_measure else bounds))
    rows = read(database, as_of=at)
    assert len(rows) == expected
    assert all(row["as_of"] == at.isoformat() and not row["used_for_missing_check"] for row in rows)


def test_known_direction_country_and_explicit_hs_exclusion_constrain_candidates(database):
    seed(database, direction="export", country_iso="CN")
    assert read(database) == []
    assert read(database, direction="export", country="DE") == []
    assert len(read(database, direction="export", country="CN")) == 1
    with database() as db:
        row = db.query(NtmApplicabilityRuleV2).one()
        row.excluded_hs_json = ["1234567890"]
        db.commit()
    assert read(database, direction="export", country="CN") == []


@pytest.mark.parametrize("changes,reason", [
    ({"direction": "unknown"}, "direction_unverified"),
    ({"country_iso": "CN"}, "country_unverified"),
    ({"country_iso": "EU"}, "country_unverified"),
    ({"excluded_hs_json": {"unsupported": ["1234"]}}, "exclusions_unverified"),
    ({"excluded_hs_json": ["1234", False]}, "exclusions_unverified"),
    ({"hs_scope_mode": "unsupported"}, "hs_scope_unverified"),
    ({"valid_from": date(2027, 1, 1), "valid_to": date(2026, 1, 1)}, "effective_dates_unverified"),
])
def test_unknown_or_malformed_constraints_remain_visible_for_clarification(database, changes, reason):
    seed(database, **changes)
    rows = read(database)
    assert len(rows) == 1 and rows[0]["applicability"] == "needs_clarification"
    assert reason in rows[0]["context_review_reasons"]
    assert not rows[0]["used_for_missing_check"]


def test_malformed_persisted_date_returns_unavailable_diagnostic_not_empty_result(database):
    seed(database)
    with database() as db:
        db.execute(text("UPDATE ntm_applicability_rules_v2 SET valid_from='not-a-date'"))
        db.commit()
    rows = read(database)
    assert len(rows) == 1
    assert rows[0]["source_data_status"] == "unavailable"
    assert rows[0]["applicability"] == "needs_clarification" and rows[0]["permit_type"] == ""
    assert "source_metadata_unavailable" in rows[0]["context_review_reasons"]


@pytest.mark.parametrize("invalid", ["2020-01-01", "", False, 0, datetime(2020, 1, 1)])
def test_invalid_explicit_date_rejected_before_opening_session(monkeypatch, invalid):
    monkeypatch.setattr(service.db, "SessionLocal", lambda: pytest.fail("Invalid date opened DB"))
    with pytest.raises(ValueError, match="as_of"):
        service.get_v2_legacy_measures_broker_rows("1234567890", as_of=invalid)


def test_enforcement_adapter_forwards_explicit_context(monkeypatch):
    observed = []

    def candidates(hs, description, **context):
        observed.append(context)
        return []

    monkeypatch.setattr(enforcement, "get_v2_legacy_measures_broker_rows", candidates)
    result, _ = enforcement.apply_v2_measures_enforcement_to_broker(
        [], "1234567890", "fixture", as_of=date(2020, 1, 1), country="CN", direction="export")
    assert result == []
    assert observed == [{"as_of": date(2020, 1, 1), "country": "CN", "direction": "export"}]


def test_forged_raw_rows_cannot_bypass_legacy_merge():
    baseline = [{"permit_type": "РУ", "tr_ts": None}]
    forged = [{"source_kind": service.MEASURES_SOURCE_KIND, "measure_kind": "vet", "permit_type": "ВС",
               "applicability": "definite", "requires_manual_review": False, "legal_review_verified": True}]
    assert enforcement.classify_v2_measure_for_enforcement(forged[0], []) == "manual_review"
    assert service.merge_v2_legacy_measures_into_broker(baseline, forged) == baseline
    assert baseline == [{"permit_type": "РУ", "tr_ts": None}]


def test_candidate_read_has_one_joined_select_and_no_write_statements(database):
    seed(database)
    seed(database, code="1234", kind="phyto", hs_scope_mode="prefix")
    engine = database.kw["bind"]
    statements = []

    def capture(conn, cursor, statement, *args):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        assert len(read(database)) == 2
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert len(statements) == 1 and statements[0].lstrip().upper().startswith("SELECT")
