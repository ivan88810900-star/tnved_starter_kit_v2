"""Lexical duty cells; historical PDF examples are not a current legal edition."""
from decimal import Decimal, localcontext
from pathlib import Path

import pytest

from app.services.ett_duty_cells import MAX_CELL_CHARACTERS, parse_duty_cell
from app.services.ett_manifest import ETTDuty
from app.services.ett_pdf_evidence import extract_pdf_evidence


@pytest.mark.parametrize("raw,expected", [
    ("0", "0"), ("5", "5"), ("12,5", "12.5"), ("6,5", "6.5"),
    ("0,000000000001", "0.000000000001"), (" 12,50 \n", "12.50"),
    ("100", "100"), ("150", "150"),
])
def test_complete_bare_percentage_requires_confirmed_header(raw, expected):
    result = parse_duty_cell(raw, percent_header_confirmed=True)
    assert result["status"] == "parsed"
    assert result["duty"] == {"kind": "ad_valorem", "ad_valorem_percent": expected}
    assert result["raw_text"] == raw
    assert parse_duty_cell(raw, percent_header_confirmed=False)["unparsed_reason"] == "percent_header_unconfirmed"


@pytest.mark.parametrize("raw", ["5%", "5 %", "5\u00a0%", "5\u202f%", "5\n%"])
def test_explicit_percent_retains_its_lexical_unit_without_inferring_a_header(raw):
    result = parse_duty_cell(raw, percent_header_confirmed=False)
    assert result["status"] == "parsed"
    assert result["duty"]["ad_valorem_percent"] == "5"


@pytest.mark.parametrize("raw,amount,currency,unit,quantity", [
    ("1,75 евро за 1 кг", "1.75", "EUR", "kg", "1"),
    ("0,38 евро за 1 м2", "0.38", "EUR", "m2", "1"),
    ("0,38 евро за 1 м²", "0.38", "EUR", "m2", "1"),
    ("1,25 евро за 1 пару", "1.25", "EUR", "pair", "1"),
    ("1,5 евро за 1 л", "1.5", "EUR", "litre", "1"),
    ("2 евро за 1000 шт", "2", "EUR", "unit", "1000"),
    ("250 долларов США за 1000 кг", "250", "USD", "kg", "1000"),
    ("203 доллара США за 1000 кг", "203", "USD", "kg", "1000"),
    ("171 доллар США за 1000 кг", "171", "USD", "kg", "1000"),
    ("0,015 евро за 1 кг", "0.015", "EUR", "kg", "1"),
    ("0 евро за 1 кг", "0", "EUR", "kg", "1"),
    ("10 евро за 1 т", "10", "EUR", "tonne", "1"),
    ("1 евро за 100 г", "1", "EUR", "g", "100"),
    ("1 евро за 1 м3", "1", "EUR", "m3", "1"),
    ("1 евро за 1 м³", "1", "EUR", "m3", "1"),
    ("1 евро за 1 м", "1", "EUR", "m", "1"),
    ("1 евро за 1 кВт·ч", "1", "EUR", "kwh", "1"),
])
def test_supported_specific_units_and_currency_quantities(raw, amount, currency, unit, quantity):
    result = parse_duty_cell(raw, percent_header_confirmed=False)
    assert result["status"] == "parsed"
    assert result["duty"] == {"kind": "specific", "specific_amount": amount, "currency": currency, "unit": unit, "unit_quantity": quantity}
    ETTDuty.model_validate(result["duty"])


@pytest.mark.parametrize("raw,kind,percent,amount", [
    ("10, но не менее 0,02 евро за 1 кг", "combined_max", "10", "0.02"),
    ("12,5, но не менее 0,2 евро за 1 кг", "combined_max", "12.5", "0.2"),
    ("10 плюс 0,1 евро за 1 кг", "combined_sum", "10", "0.1"),
    ("4,5 плюс 0,04 евро за 1 кг", "combined_sum", "4.5", "0.04"),
    ("5 % + 0,1 евро за 1 кг", "combined_sum", "5", "0.1"),
    ("5%+0,1 евро за 1 кг", "combined_sum", "5", "0.1"),
    ("10 %, но не менее\n0,02 евро за\n1 кг", "combined_max", "10", "0.02"),
])
def test_only_complete_combined_expressions_parse(raw, kind, percent, amount):
    result = parse_duty_cell(raw, percent_header_confirmed=True)
    assert result["status"] == "parsed"
    assert result["duty"] == {"kind": kind, "ad_valorem_percent": percent, "specific_amount": amount, "currency": "EUR", "unit": "kg", "unit_quantity": "1"}
    if "%" not in raw:
        assert parse_duty_cell(raw, percent_header_confirmed=False)["unparsed_reason"] == "percent_header_unconfirmed"


@pytest.mark.parametrize("raw,footnotes", [
    ("5 63С)", ["63C"]), ("0 63 С)", ["63C"]), ("5%63С)", ["63C"]),
    ("5 63C)", ["63C"]), ("5 63С) 67 C)", ["63C", "67C"]),
    ("5 63С) 63С)", ["63C"]), ("  0  9 \nС) \n", ["9C"]),
    ("0,12 евро за 1 кг63С)", ["63C"]),
    ("0,61 евро за 1 кг67С)", ["67C"]),
    ("10, но не менее 0,02 евро за 1 кг63С)", ["63C"]),
])
def test_unambiguous_footnotes_preserve_original_spans_without_legal_resolution(raw, footnotes):
    result = parse_duty_cell(raw, percent_header_confirmed=True)
    assert result["status"] == "parsed"
    assert result["footnote_ids"] == footnotes
    for marker in result["footnote_markers"]:
        assert raw[marker["start"]:marker["end"]] == marker["raw_text"]
    assert result["legal_interpretation_verified"] is False
    assert result["can_promote"] is False
    assert result["unparsed_reason"] is None


@pytest.mark.parametrize("raw", [
    "563С)", "09С)", "1063С)", "6,563С)", "83С)", "5,563С)",
    "7,55С)", "6,52С)", "563C)", "15, либо 12,5, но не менее 0,1 евро за 1 кг",
    "0,38 евро за 1 м263С)", "0,38 евро за 1 м363С)",
    "10, но не менее", "10 плюс", "250 долларов", "203 доллара США",
    "1 евро за 1 см3", "0,4 евро за 1 л 100% спирта",
    "5 с 1 января", "5 до 31.12.2026", "5 или 10", "5 / 10", "5; 10",
    "5 10", "5,", "5, но не более 1 евро за 1 кг", "5 63С) кроме сахара",
    "5 1)", "5 (63С)", "5 0С)", "5 063С)", "5 63А)",
    "5 63с)", "5 63С) 1)", "5 НДС 22", "Описание: 735 кВт 5", "мощность 5",
    "5.5", "1.000", "1 000", "01", "00", "00,1", "-5", "+5", "1e2", "NaN", "Infinity",
    "5％", "５", "٥", "5\u200b", "\u202e5", "5\x00", "5\x0b", "5\u20095",
    "5 евро за 0 кг", "1 евро за кг", "1 евро / кг", "1 EUR за 1 кг",
    "1 евро за 1 kg", "5,0000000000001", "1" * 25, "5% 63С) 2",
])
def test_no_partial_number_or_unsupported_qualifier_becomes_a_duty(raw):
    result = parse_duty_cell(raw, percent_header_confirmed=True)
    assert result["status"] == "unresolved"
    assert result["duty"] is None
    assert result["unparsed_reason"]
    assert result["can_promote"] is False


@pytest.mark.parametrize("raw", ["", " \t\n", "\u00a0\u202f", "5" * (MAX_CELL_CHARACTERS + 1)])
def test_empty_and_oversized_cells_never_default_to_zero(raw):
    assert parse_duty_cell(raw, percent_header_confirmed=True)["duty"] is None


@pytest.mark.parametrize("raw,header", [(None, True), (5, True), (b"5", True), ("5", 1), ("5", "true"), ("5", None)])
def test_public_input_contract_is_strict(raw, header):
    with pytest.raises(ValueError):
        parse_duty_cell(raw, percent_header_confirmed=header)


def test_exact_decimals_do_not_depend_on_process_arithmetic_precision():
    with localcontext() as context:
        context.prec = 3
        result = parse_duty_cell("123456789012345678901234,123456789012", percent_header_confirmed=True)
    assert Decimal(result["duty"]["ad_valorem_percent"]) == Decimal("123456789012345678901234.123456789012")


def test_raw_historical_pdf_fused_superscript_is_not_a_numeric_rate():
    corpus = Path(__file__).resolve().parents[3] / "backend/app/services/source_sync/data"
    paths = list(corpus.glob("ru.01_*.pdf"))
    assert len(paths) == 1
    report = extract_pdf_evidence(paths[0].read_bytes(), artifact_id="chapter-01", chapter="01")
    candidate = next(c for p in report["pages"] for c in p["candidates"] if c["code"] == "0106410001")
    assert candidate["rate_fragment"] == "563С)"
    result = parse_duty_cell(candidate["rate_fragment"], percent_header_confirmed=True)
    assert result["status"] == "unresolved"
    assert result["duty"] is None
    assert result["footnote_ids"] == []


@pytest.mark.parametrize("raw,kind,amount,percent", [
    ("1 евро за 1 см3 объема двигателя", "specific", "1", None),
    ("3 евро за 1 см³ объема двигателя", "specific", "3", None),
    ("20, но не менее 0,8 евро за 1 см3 объема двигателя", "combined_max", "0.8", "20"),
    ("10, но не менее 0,13 евро за 1 см3\nобъема двигателя", "combined_max", "0.13", "10"),
])
def test_engine_displacement_is_an_explicit_specific_basis(raw, kind, amount, percent):
    result = parse_duty_cell(raw, percent_header_confirmed=True)
    assert result["status"] == "parsed"
    expected = {"kind": kind, "specific_amount": amount, "currency": "EUR", "unit": "engine_displacement_cm3", "unit_quantity": "1"}
    if percent is not None:
        expected["ad_valorem_percent"] = percent
    assert result["duty"] == expected


@pytest.mark.parametrize("amount,unit", [("0,6", "см3"), ("0,79", "см3"), ("0,79", "см³")])
def test_full_lower_of_clause_has_the_precise_capped_max_structure(amount, unit):
    raw = f"15, либо 12,5, но не менее {amount} евро за 1 {unit} объема двигателя, в зависимости от того, какая из исчисленных сумм таможенной пошлины ниже"
    result = parse_duty_cell(raw, percent_header_confirmed=True)
    assert result["duty"] == {"kind": "capped_combined_max", "ad_valorem_cap_percent": "15", "ad_valorem_percent": "12.5", "specific_amount": amount.replace(",", "."), "currency": "EUR", "unit": "engine_displacement_cm3", "unit_quantity": "1"}
    assert result["can_promote"] is False
    assert parse_duty_cell(raw, percent_header_confirmed=False)["unparsed_reason"] == "percent_header_unconfirmed"


@pytest.mark.parametrize("cap_symbol,inner_symbol,expected", [("%", "%", "parsed"), ("%", "", "unresolved"), ("", "%", "unresolved")])
def test_both_percentage_units_must_be_explicit_without_a_confirmed_header(cap_symbol, inner_symbol, expected):
    raw = f"15{cap_symbol}, либо 12,5{inner_symbol}, но не менее 0,6 евро за 1 см3 объема двигателя, в зависимости от того, какая из исчисленных сумм таможенной пошлины ниже"
    assert parse_duty_cell(raw, percent_header_confirmed=False)["status"] == expected


@pytest.mark.parametrize("replacement", [
    ("ниже", "выше"), ("ниже", ""), (", в зависимости от того, какая из исчисленных сумм таможенной пошлины ниже", ""),
    ("либо", "плюс"), ("не менее", "не более"), ("см3 объема двигателя", "м3"),
    ("см3 объема двигателя", "см3 груза"), ("см3 объема двигателя", "кг"),
    ("см3 объема двигателя", "см3"), ("15, либо", "10, либо"),
    ("ниже", "ниже до 31.12.2026"),
])
def test_other_or_incomplete_nested_formulas_are_not_reinterpreted(replacement):
    raw = "15, либо 12,5, но не менее 0,6 евро за 1 см3 объема двигателя, в зависимости от того, какая из исчисленных сумм таможенной пошлины ниже"
    result = parse_duty_cell(raw.replace(*replacement), percent_header_confirmed=True)
    assert result["status"] == "unresolved"
    assert result["duty"] is None


def test_every_historical_engine_cell_is_parsed_after_source_bound_assembly_and_typography():
    from app.services.ett_duty_typography import normalize_duty_typography
    from app.services.ett_table_assembly import assemble_pdf_table
    from collections import Counter

    corpus = Path(__file__).resolve().parents[3] / "backend/app/services/source_sync/data"
    paths = list(corpus.glob("ru.87_*.pdf"))
    assert len(paths) == 1
    report = assemble_pdf_table(paths[0].read_bytes(), artifact_id="chapter-87", chapter="87")
    counts = Counter()
    for record in report["records"]:
        normalized = normalize_duty_typography(record)
        assert normalized["status"] == "normalized"
        result = parse_duty_cell(normalized["normalized_text"], percent_header_confirmed=True)
        assert result["status"] == "parsed", (record["code"], result["unparsed_reason"])
        if result["duty"].get("unit") == "engine_displacement_cm3":
            counts[result["duty"]["kind"]] += 1
    assert counts == {"specific": 54, "combined_max": 71, "capped_combined_max": 6}
