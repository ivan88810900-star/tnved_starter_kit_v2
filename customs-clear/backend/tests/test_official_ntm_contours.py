from __future__ import annotations

from app.services.normative_requirements_block import build_normative_requirements_block
from app.services.official_ntm_contours import (
    DECISION_30_SECTION_216_RANGES,
    DECISION_30_SECTION_219_RANGES,
    DECISION_30_SECTIONS,
    DECISION_30_UNIQUE_RANGES,
    DECISION_299_SGR_RANGES,
    OFFICIAL_NTM_FAMILIES,
    evaluate_official_ntm_contours,
    is_official_ntm_advisory_enabled,
    should_apply_official_ntm_advisory,
)


def _requirements(hs_code: str, description: str) -> list[dict]:
    return evaluate_official_ntm_contours(hs_code, description)["requirements"]


def test_decision_30_official_range_contour_has_93_unique_ranges() -> None:
    assert len(DECISION_30_SECTION_216_RANGES) == 20
    assert len(DECISION_30_SECTION_219_RANGES) == 113
    assert len(DECISION_30_UNIQUE_RANGES) == 93


def test_all_measure_families_are_always_returned() -> None:
    result = evaluate_official_ntm_contours("6110209100", "джемпер хлопчатобумажный")
    assert len(OFFICIAL_NTM_FAMILIES) == 9
    assert len(result["measure_families"]) == 9
    assert all(row["status"] == "not_detected" for row in result["measure_families"])
    assert "всеобъемлющий экспортный контроль" in result["disclaimer"]


def test_all_current_decision_30_sections_are_indexed_and_filterable() -> None:
    assert len(DECISION_30_SECTIONS) == 30
    assert {row["section"] for row in DECISION_30_SECTIONS} == {
        "1.1", "1.2", "1.3", "1.4", "1.6", "1.7", "1.8", "1.9", "1.12",
        "2.1", "2.2", "2.3", "2.4", "2.6", "2.7", "2.8", "2.9", "2.10",
        "2.11", "2.12", "2.13", "2.14", "2.16", "2.17", "2.19", "2.20",
        "2.21", "2.22", "2.23", "2.30",
    }


def test_dangerous_waste_requires_name_and_carries_direction() -> None:
    generic = _requirements("3825300000", "товар химической промышленности")
    waste_generic = next(row for row in generic if row.get("section") == "1.2")
    assert waste_generic["applicability"] == "needs_clarification"
    assert waste_generic["direction"] == "import"

    explicit = _requirements("3825300000", "опасные клинические отходы")
    waste_explicit = next(row for row in explicit if row.get("section") == "1.2")
    assert waste_explicit["applicability"] == "needs_clarification"
    assert waste_explicit["used_for_missing_check"] is False


def test_generic_ferrous_scrap_is_never_a_definite_prohibition() -> None:
    rows = _requirements("7204100000", "лом черных металлов")
    waste_rows = [row for row in rows if row.get("section") in {"1.2", "2.3"}]
    assert waste_rows
    assert all(row["applicability"] == "needs_clarification" for row in waste_rows)


def test_medicine_section_is_advisory_even_when_confirmed() -> None:
    row = next(
        row for row in _requirements("3004900000", "лекарственное средство")
        if row.get("section") == "2.14"
    )
    assert row["permit_type"] == "РУ"
    assert row["applicability"] == "needs_clarification"
    assert row["used_for_missing_check"] is False


def test_cultural_value_export_direction() -> None:
    row = next(
        row for row in _requirements("9701100000", "старинная картина культурная ценность")
        if row.get("section") == "2.20"
    )
    assert row["direction"] == "export"
    assert row["applicability"] == "needs_clarification"


def test_radio_code_without_characteristics_never_becomes_definite() -> None:
    rows = _requirements("8517620009", "сетевое устройство")
    radio = next(row for row in rows if row["family"] == "radio_frequency")
    assert radio["applicability"] == "needs_clarification"
    assert radio["used_for_missing_check"] is False


def test_radio_characteristic_remains_needs_clarification() -> None:
    rows = _requirements("8517620009", "маршрутизатор Wi-Fi с радиопередатчиком")
    radio = next(row for row in rows if row["family"] == "radio_frequency")
    assert radio["applicability"] == "needs_clarification"
    assert radio["used_for_missing_check"] is False


def test_embedded_radio_is_candidate_regardless_of_finished_good_hs_code() -> None:
    rows = _requirements("9403609009", "шкаф со встроенным Bluetooth радиомодулем")
    radio = next(row for row in rows if row["family"] == "radio_frequency")
    assert radio["section"] == "2.16"
    assert radio["hs_prefix"] is None
    assert radio["applicability"] == "needs_clarification"
    assert radio["used_for_missing_check"] is False


def test_crypto_code_requires_crypto_characteristic() -> None:
    generic = _requirements("8471300000", "портативный компьютер")
    crypto_generic = next(row for row in generic if row["family"] == "cryptography")
    assert crypto_generic["applicability"] == "needs_clarification"

    explicit = _requirements("8471300000", "портативный компьютер с AES шифрованием")
    crypto_explicit = next(row for row in explicit if row["family"] == "cryptography")
    assert crypto_explicit["applicability"] == "needs_clarification"


def test_380894_is_excluded_from_decision_30_section_2_2() -> None:
    rows = _requirements("3808941000", "дезинфицирующее средство, пестицид")
    assert not any(row.get("section") == "2.2" for row in rows)


def test_corrected_decision_30_ranges_and_conditions_are_advisory() -> None:
    cases = (
        ("2910000000", "запрещенный пестицид", "1.4", "import"),
        ("0308000000", "дикий вид водного животного", "2.6", "export"),
        ("7103100001", "необработанный нефрит", "2.11", "export"),
        ("8518000000", "миниатюрное скрытое устройство прослушивания", "2.17", "both"),
        ("2914000000", "лабораторный эталон для исследований", "2.30", "import"),
    )
    for code, description, section, direction in cases:
        row = next(row for row in _requirements(code, description) if row.get("section") == section)
        assert row["direction"] == direction
        assert row["applicability"] == "needs_clarification"

    assert not any(row.get("section") == "2.6" for row in _requirements("0602000000", "дикорастущее растение"))
    assert not any(row.get("section") == "2.11" for row in _requirements("2601000000", "железная руда"))
    assert not any(row.get("section") == "2.17" for row in _requirements("8528000000", "миниатюрный монитор"))


def test_geological_information_candidate_does_not_depend_on_carrier_code() -> None:
    row = next(
        row for row in _requirements("2517100000", "керн и геологическая информация о месторождении")
        if row.get("section") == "2.23"
    )
    assert row["hs_prefix"] is None
    assert row["applicability"] == "needs_clarification"


def test_sgr_complete_table_candidate_is_advisory() -> None:
    assert len(DECISION_299_SGR_RANGES) >= 90
    row = next(
        row for row in _requirements("2919000000", "эфир фосфорной кислоты")
        if row["family"] == "sanitary_registration"
    )
    assert row["permit_type"] == "СГР"
    assert row["direction"] == "import"
    assert row["applicability"] == "needs_clarification"
    assert row["used_for_missing_check"] is False
    assert "Комиссии Таможенного союза №299" in row["note"]


def test_sgr_current_missing_ranges_are_candidates() -> None:
    cases = (
        ("4812000000", "фильтровальный блок для контакта с пищевой продукцией"),
        ("7412200000", "медный фитинг для системы питьевого водоснабжения"),
    )
    for code, description in cases:
        row = next(
            row for row in _requirements(code, description)
            if row["family"] == "sanitary_registration"
        )
        assert row["permit_type"] == "СГР"
        assert row["applicability"] == "needs_clarification"
        assert row["used_for_missing_check"] is False


def test_veterinary_current_candidate_and_stale_prefix_negatives() -> None:
    row = next(
        row for row in _requirements("0309000000", "мука и гранулы из рыбы")
        if row["family"] == "veterinary_control"
    )
    assert row["permit_type"] == "ВЕТКОНТРОЛЬ"
    assert row["direction"] == "import_or_transit"
    assert row["applicability"] == "needs_clarification"
    assert row["used_for_missing_check"] is False
    assert "Комиссии Таможенного союза №317" in row["note"]

    for code in ("0508000000", "2305000000", "5104000000"):
        assert not any(
            candidate["family"] == "veterinary_control"
            for candidate in _requirements(code, "товар без ветеринарного назначения")
        )


def test_veterinary_conditional_rows_require_product_purpose() -> None:
    assert any(
        row["family"] == "veterinary_control"
        for row in _requirements("1001990000", "пшеница фуражная для корма животных")
    )
    assert not any(
        row["family"] == "veterinary_control"
        for row in _requirements("1001990000", "пшеница продовольственная")
    )


def test_phytosanitary_high_risk_is_fss_advisory() -> None:
    row = next(
        row for row in _requirements("0712901100", "семена сахарной кукурузы")
        if row["family"] == "phytosanitary_control"
    )
    assert row["risk_level"] == "high"
    assert row["permit_type"] == "ФСС"
    assert row["direction"] == "import_or_transit"
    assert row["certificate_required"] is True
    assert row["applicability"] == "needs_clarification"
    assert row["used_for_missing_check"] is False


def test_phytosanitary_low_risk_does_not_claim_fss() -> None:
    row = next(
        row for row in _requirements("0901210000", "кофе жареный в потребительской упаковке")
        if row["family"] == "phytosanitary_control"
    )
    assert row["risk_level"] == "low"
    assert row["permit_type"] != "ФСС"
    assert row["direction"] == "import_or_transit"
    assert row["certificate_required"] is False
    assert row["applicability"] == "needs_clarification"


def test_phytosanitary_removed_broad_prefixes_are_negative() -> None:
    for code, description in (
        ("0710800000", "овощи замороженные"),
        ("0811100000", "клубника замороженная"),
    ):
        assert not any(
            row["family"] == "phytosanitary_control"
            for row in _requirements(code, description)
        )


def test_dual_use_candidate_is_export_only_and_never_enforced() -> None:
    row = next(
        row for row in _requirements("8517620009", "сетевое оборудование")
        if row["family"] == "export_control_dual_use"
    )
    assert row["permit_type"] == "ЛЗ/разрешение ФСТЭК"
    assert row["direction"] == "export"
    assert row["applicability"] == "needs_clarification"
    assert row["used_for_missing_check"] is False


def test_adult_ceramic_tableware_pp2425_declaration() -> None:
    rows = _requirements("6912002300", "керамическая столовая тарелка для взрослых")
    row = next(row for row in rows if row["permit_type"] == "ДС" and row.get("tr_ts") is None)
    assert row["permit_type"] == "ДС"
    assert row["applicability"] == "needs_clarification"
    assert "2425" in row["note"]
    assert "ГОСТ" in row["note"]
    assert row["used_for_missing_check"] is False


def test_generic_tableware_needs_characteristics() -> None:
    row = next(
        row for row in _requirements("6912002300", "керамическая столовая тарелка")
        if row["rule_name"].startswith("Посуда и столовые приборы")
    )
    assert row["applicability"] == "needs_clarification"


def test_child_tableware_routes_to_tr_ts_007_without_false_form() -> None:
    row = next(
        row for row in _requirements("6912002300", "керамическая тарелка для детей")
        if row["rule_name"] == "Посуда и столовые приборы для детей"
    )
    assert row["tr_ts"] == "007/2011"
    assert row["permit_type"] == "ДС/СГР"
    assert row["applicability"] == "needs_clarification"


def test_grain_has_official_015_advisory_without_enforcement() -> None:
    row = next(
        row for row in _requirements("1001990000", "пшеница зерно")
        if row.get("tr_ts") == "015/2011"
    )
    assert row["applicability"] == "needs_clarification"
    assert row["used_for_missing_check"] is False


def test_civil_defence_rule_needs_characteristic_confirmation() -> None:
    row = next(
        row for row in _requirements("9020000000", "дыхательный аппарат")
        if row.get("tr_ts") == "050/2021"
    )
    assert row["applicability"] == "needs_clarification"


def test_poultry_051_is_description_qualified_and_advisory() -> None:
    row = next(
        row for row in _requirements("0207140000", "части тушек кур")
        if row.get("tr_ts") == "051/2021"
    )
    assert row["applicability"] == "needs_clarification"
    assert row["used_for_missing_check"] is False


def test_lpg_and_metro_use_description_qualified_advisory_rules() -> None:
    lpg = next(
        row for row in _requirements("2711129400", "сжиженный пропан для топлива")
        if row.get("tr_ts") == "036/2016"
    )
    metro = next(
        row for row in _requirements("8605000000", "вагон метрополитена")
        if row.get("tr_ts") == "052/2021"
    )
    assert lpg["applicability"] == "needs_clarification"
    assert metro["applicability"] == "needs_clarification"
    assert lpg["used_for_missing_check"] is False
    assert metro["used_for_missing_check"] is False


def test_decorative_ceramic_is_not_mistaken_for_tableware() -> None:
    assert not any(
        row["rule_name"].startswith("Посуда и столовые приборы")
        for row in _requirements("6913900000", "декоративная керамическая статуэтка")
    )


def test_advisory_rollout_is_on_by_default_with_explicit_kill_switch(monkeypatch) -> None:
    monkeypatch.delenv("NTM_V2_OFFICIAL_FULL_ADVISORY_ENABLED", raising=False)
    assert is_official_ntm_advisory_enabled() is True
    assert should_apply_official_ntm_advisory() is True
    monkeypatch.setenv("NTM_V2_OFFICIAL_FULL_ADVISORY_ENABLED", "false")
    assert is_official_ntm_advisory_enabled() is False
    assert should_apply_official_ntm_advisory() is False
    assert should_apply_official_ntm_advisory(True) is True
    assert should_apply_official_ntm_advisory(False) is False


def test_normative_block_carries_family_matrix() -> None:
    evaluated = evaluate_official_ntm_contours("6912002300", "керамическая тарелка")
    block = build_normative_requirements_block({
        "status": "WARNING",
        "required_permits": [],
        "missing_permit_types": [],
        "advisory_requirements": evaluated["requirements"],
        "measure_families": evaluated["measure_families"],
        "measure_families_disclaimer": evaluated["disclaimer"],
    })
    assert len(block["measure_families"]) == 9
    assert block["measure_families_disclaimer"]
