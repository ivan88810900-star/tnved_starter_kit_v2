from __future__ import annotations

from copy import deepcopy

import pytest

from app.services.official_ntm_exact_health import (
    CURATED_EXACT_HEALTH_ALLOWLIST,
    DECISION_157_URL,
    DECISION_299_URL,
    DECISION_317_URL,
    DECISION_318_URL,
    OFFICIAL_NTM_EXACT_HEALTH_SOURCE_KIND,
    evaluate_exact_health_measures,
    evaluate_official_ntm_exact_health,
)


def _import_facts(**overrides: object) -> dict[str, object]:
    facts: dict[str, object] = {
        "direction": "import",
        "origin_country": "CN",
        "destination_country": "RU",
    }
    facts.update(overrides)
    return facts


def _one(hs_code: str, description: str, facts: dict[str, object]) -> dict:
    rows = evaluate_exact_health_measures(hs_code, description, facts)
    assert len(rows) == 1
    return rows[0]


def test_public_allowlist_contains_only_enumerated_ten_digit_codes() -> None:
    assert len(CURATED_EXACT_HEALTH_ALLOWLIST) == 8
    assert {row["family"] for row in CURATED_EXACT_HEALTH_ALLOWLIST} == {
        "sanitary_registration",
        "veterinary_control",
        "phytosanitary_control",
    }
    for rule in CURATED_EXACT_HEALTH_ALLOWLIST:
        assert rule["exact_hs_codes"]
        assert all(
            len(code) == 10 and code.isdigit() for code in rule["exact_hs_codes"]
        )


def test_unknown_or_prefix_only_code_never_gets_a_false_negative_or_definite() -> None:
    assert evaluate_exact_health_measures("8517620009", "маршрутизатор", {}) == []
    assert (
        evaluate_exact_health_measures("380894", "дезинфицирующее средство", {}) == []
    )
    assert evaluate_exact_health_measures("3808919000", "инсектицид", {}) == []


def test_rows_have_stable_integration_shape_and_never_enter_missing_check() -> None:
    row = _one("9503007500", "Кукла пластиковая", {})
    assert row == {
        **row,
        "source": OFFICIAL_NTM_EXACT_HEALTH_SOURCE_KIND,
        "source_kind": OFFICIAL_NTM_EXACT_HEALTH_SOURCE_KIND,
        "family": "sanitary_registration",
        "permit_type": "СГР",
        "applicability": "definite",
        "outcome": "excluded",
        "matched_hs_scope": "9503007500",
        "hs_scope_mode": "exact",
        "missing_facts": [],
        "used_for_missing_check": False,
        "eligible_for_curated_enforcement": False,
    }
    assert row["source_url"] == DECISION_299_URL
    assert row["source_revision"]
    assert row["exclusion_reason"]


def test_adult_cosmetics_excludes_only_child_cosmetics_rule() -> None:
    row = _one(
        "3304990000",
        "Косметический крем для взрослых",
        _import_facts(intended_use="adult cosmetics"),
    )
    assert row["outcome"] == "excluded"
    assert row["applicability"] == "definite"
    assert "детской косметики" in row["exclusion_reason"]
    assert "другие" in row["reason"]


def test_child_cosmetics_requires_structured_facts_before_definite() -> None:
    incomplete = _one("3304990000", "Детский крем для лица", {})
    assert incomplete["applicability"] == "needs_clarification"
    assert incomplete["outcome"] == "pending_facts"
    assert {
        "direction",
        "destination_country",
        "intended_use:children",
        "composition_or_cas_numbers",
        "first_import",
    }.issubset(incomplete["missing_facts"])

    definite = _one(
        "3304990000",
        "Детский крем для лица",
        _import_facts(
            intended_use="для детей",
            composition="вода, глицерин",
            first_import=True,
        ),
    )
    assert definite["applicability"] == "definite"
    assert definite["outcome"] == "required"
    assert definite["eligible_for_curated_enforcement"] is True
    assert definite["used_for_missing_check"] is False


def test_infant_food_exact_rule_can_be_definite_with_full_facts() -> None:
    row = _one(
        "1901100000",
        "Молочная смесь, детское питание",
        _import_facts(
            intended_use="питание для младенцев",
            composition="молочный белок, витамины",
            first_import=False,
        ),
    )
    assert row["applicability"] == "definite"
    assert row["outcome"] == "required"
    assert row["permit_type"] == "СГР"


def test_active_disinfectant_is_definite_but_legacy_3808990000_is_not() -> None:
    facts = _import_facts(
        intended_use="бытовая дезинфекция",
        composition="этанол 70%",
        disinfectant_use=True,
        veterinary_use=False,
        first_import=True,
    )
    active = _one("3808948000", "Дезинфицирующее средство", facts)
    assert active["applicability"] == "definite"
    assert active["outcome"] == "required"

    legacy = _one("3808990000", "Дезинфицирующее средство", facts)
    assert legacy["applicability"] == "needs_clarification"
    assert "active_tnved_code:380894xxxx" in legacy["missing_facts"]
    assert legacy["eligible_for_curated_enforcement"] is False


def test_veterinary_disinfectant_is_excluded_only_from_sanitary_rule() -> None:
    row = _one(
        "3808948000",
        "Дезинфицирующее средство для ветеринарии",
        _import_facts(disinfectant_use=True, veterinary_use=True),
    )
    assert row["outcome"] == "excluded"
    assert "ветеринарное назначение" in row["exclusion_reason"]


def test_live_purebred_horse_exact_veterinary_control() -> None:
    row = _one(
        "0101210000",
        "Живая чистопородная племенная лошадь",
        _import_facts(
            animal_origin=True,
            processing_method="live",
            intended_use="breeding",
        ),
    )
    assert row["family"] == "veterinary_control"
    assert row["applicability"] == "definite"
    assert row["outcome"] == "control_required"
    assert row["permit_type"] == "ВЕТКОНТРОЛЬ"
    assert row["source_url"] == DECISION_317_URL
    assert "вид ветеринарного документа" in row["reason"]


def test_current_fish_meal_subcode_is_definite_legacy_0309000000_is_not() -> None:
    facts = _import_facts(
        animal_origin=True,
        composition="100% рыба",
        processing_method="сушение и измельчение",
    )
    active = _one("0309100000", "Мука из рыбы", facts)
    assert active["applicability"] == "definite"
    assert active["outcome"] == "control_required"

    legacy = _one("0309000000", "Мука и гранулы из рыбы", facts)
    assert legacy["applicability"] == "needs_clarification"
    assert "active_tnved_code:0309xxxxxxxx" in legacy["missing_facts"]


def test_veterinary_transit_is_never_excluded_as_non_import() -> None:
    row = _one(
        "0309100000",
        "Мука из рыбы",
        {
            "direction": "transit",
            "origin_country": "CN",
            "destination_country": "DE",
            "animal_origin": True,
            "composition": "100% рыба",
            "processing_method": "сушение и измельчение",
        },
    )

    assert row["applicability"] == "needs_clarification"
    assert row["outcome"] == "pending_facts"
    assert row["eligible_for_curated_enforcement"] is False
    assert row["missing_facts"] == ["transit_route_and_control_documents"]


@pytest.mark.parametrize("code", ["0508000000", "2305000000", "5104000000"])
def test_stale_veterinary_prefix_golden_negatives_are_explicit(code: str) -> None:
    row = _one(code, "товар без ветеринарного назначения", {})
    assert row["applicability"] == "definite"
    assert row["outcome"] == "excluded"
    assert row["eligible_for_curated_enforcement"] is False
    assert "устаревшему широкому префиксу" in row["exclusion_reason"]


def test_conditional_feed_wheat_requires_code_name_and_feed_facts() -> None:
    incomplete = _one(
        "1001990000",
        "Пшеница фуражная для корма животных",
        _import_facts(feed_use=True, intended_use="animal feed"),
    )
    assert incomplete["applicability"] == "needs_clarification"
    assert "processing_method" in incomplete["missing_facts"]

    definite = _one(
        "1001990000",
        "Пшеница фуражная для корма животных",
        _import_facts(
            feed_use=True,
            intended_use="animal feed",
            processing_method="очищенная, необработанная",
        ),
    )
    assert definite["applicability"] == "definite"
    assert definite["outcome"] == "control_required"

    food = _one(
        "1001990000",
        "Пшеница продовольственная",
        _import_facts(feed_use=False, intended_use="food for people"),
    )
    assert food["outcome"] == "excluded"
    assert "некормовое назначение" in food["exclusion_reason"]


def test_high_risk_sowing_corn_requires_fss_only_with_full_exact_facts() -> None:
    incomplete = _one("0712901100", "Семена сахарной кукурузы", {})
    assert incomplete["applicability"] == "needs_clarification"
    assert incomplete["outcome"] == "pending_facts"
    assert "phytosanitary_risk_tier:high" in incomplete["missing_facts"]
    assert "packaging" in incomplete["missing_facts"]

    definite = _one(
        "0712901100",
        "Кукуруза сахарная гибридная для посева",
        _import_facts(
            intended_use="для посева",
            processing_method="семена сушеные, необработанные",
            packaging="коммерческая партия в мешках",
            phytosanitary_risk_tier="high",
        ),
    )
    assert definite["family"] == "phytosanitary_control"
    assert definite["applicability"] == "definite"
    assert definite["outcome"] == "certificate_required"
    assert definite["certificate_required"] is True
    assert definite["risk_level"] == "high"
    assert definite["source_url"] == DECISION_318_URL
    assert definite["requirements_source_url"] == DECISION_157_URL


def test_phytosanitary_transit_remains_advisory_not_excluded() -> None:
    row = _one(
        "0712901100",
        "Кукуруза сахарная гибридная для посева",
        {
            "direction": "transit",
            "origin_country": "CN",
            "destination_country": "DE",
            "intended_use": "для посева",
            "processing_method": "семена сушеные, необработанные",
            "packaging": "коммерческая партия в мешках",
            "phytosanitary_risk_tier": "high",
        },
    )

    assert row["applicability"] == "needs_clarification"
    assert row["outcome"] == "pending_facts"
    assert row.get("certificate_required") is None
    assert row["missing_facts"] == ["transit_route_and_control_documents"]


def test_low_risk_roasted_coffee_is_exact_no_fss_for_current_subcode() -> None:
    facts = _import_facts(
        processing_method="roasted",
        packaging="consumer package",
        phytosanitary_risk_tier="low",
    )
    row = _one("0901210001", "Кофе жареный в потребительской упаковке", facts)
    assert row["applicability"] == "definite"
    assert row["outcome"] == "excluded"
    assert row["permit_type"] == "ФСС"
    assert row["certificate_required"] is False
    assert row["risk_level"] == "low"
    assert row["eligible_for_curated_enforcement"] is False

    legacy = _one("0901210000", "Кофе жареный в потребительской упаковке", facts)
    assert legacy["applicability"] == "needs_clarification"
    assert "active_tnved_code:090121000x" in legacy["missing_facts"]


def test_frozen_produce_exact_negatives_do_not_use_broad_chapter_prefix() -> None:
    exact = _one(
        "0710801000",
        "Овощи замороженные",
        {"processing_method": "frozen"},
    )
    assert exact["applicability"] == "definite"
    assert exact["outcome"] == "excluded"
    assert exact["certificate_required"] is False

    legacy = _one(
        "0811100000",
        "Клубника замороженная",
        {"processing_method": "frozen"},
    )
    assert legacy["applicability"] == "needs_clarification"
    assert "active_tnved_code:exact_frozen_subposition" in legacy["missing_facts"]


def test_non_import_transaction_is_explicitly_outside_exact_import_rule() -> None:
    row = _one(
        "0712901100",
        "Кукуруза сахарная гибридная для посева",
        {
            "direction": "export",
            "origin_country": "RU",
            "destination_country": "CN",
            "intended_use": "для посева",
            "processing_method": "семена",
            "packaging": "мешки",
            "phytosanitary_risk_tier": "high",
        },
    )
    assert row["applicability"] == "definite"
    assert row["outcome"] == "excluded"
    assert row["certificate_required"] is False
    assert "ввозу" in row["exclusion_reason"]


def test_sgr_remains_import_only_for_transit_direction() -> None:
    row = _one(
        "3304990000",
        "Детский крем для лица",
        {
            "direction": "transit",
            "origin_country": "CN",
            "destination_country": "DE",
            "intended_use": "для детей",
            "composition": "вода, глицерин",
            "first_import": True,
        },
    )

    assert row["applicability"] == "definite"
    assert row["outcome"] == "excluded"
    assert "ввозу" in row["exclusion_reason"]


def test_mapping_flexibility_alias_and_no_input_mutation() -> None:
    facts = _import_facts(
        processing_method=["roasted", "ground"],
        packaging={"kind": "consumer", "weight": "250g"},
        phytosanitary_risk_tier="low",
        extra_application_fact={"ignored": True},
    )
    before = deepcopy(facts)
    rows = evaluate_official_ntm_exact_health(
        "09 01 21 00 01",
        "Roasted coffee",
        facts,
    )
    assert facts == before
    assert rows[0]["applicability"] == "definite"
    assert rows[0]["outcome"] == "excluded"


def test_all_emitted_applicability_values_are_contract_safe() -> None:
    cases = (
        ("9503007500", "Кукла", {}),
        ("3304990000", "Детский крем", {}),
        ("0309000000", "Мука из рыбы", {}),
        ("0712901100", "Кукуруза для посева", {}),
        ("0901210000", "Кофе жареный", {}),
    )
    rows = [
        row
        for code, description, facts in cases
        for row in evaluate_exact_health_measures(code, description, facts)
    ]
    assert rows
    assert {row["applicability"] for row in rows} <= {"definite", "needs_clarification"}
    assert all(row["used_for_missing_check"] is False for row in rows)
