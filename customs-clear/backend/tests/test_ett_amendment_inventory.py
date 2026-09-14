"""Source-bound amendment enumeration, without effective-date interpretation."""
from collections import Counter
from dataclasses import FrozenInstanceError
from datetime import date
import hashlib
from pathlib import Path

import pytest

from app.services.ett_amendment_inventory import (
    ETTAmendmentInventoryError, parse_amendment_inventory,
)
from tests.ett_index_fixtures import synthetic_index_html

CURRENT = Path(__file__).parent / "fixtures/ett_index/eec_run_34235767121.html"
CURRENT_SHA = "75991416897e2764afc58f20c72dcaff49753b564f8504c383414028a0633072"
COLLEGIUM = "решений Коллегии Евразийской экономической комиссии"
COUNCIL = "решений Совета Евразийской экономической комиссии"


def changed(old: str, new: str) -> bytes:
    assert old in synthetic_index_html().decode()
    return synthetic_index_html().decode().replace(old, new).encode()


def test_synthetic_inventory_separates_founding_and_retains_only_observed_links():
    result = parse_amendment_inventory(synthetic_index_html())
    assert result.named_count == 3
    assert result.linked_count == 1
    assert result.missing_link_count == 2
    assert result.founding_act.issuing_body == "council"
    assert result.founding_act.adoption_date == date(2021, 9, 14)
    assert result.founding_act.number == "80"
    assert result.founding_act.direct_references == ()
    assert [(r.issuing_body, r.adoption_date, r.number) for r in result.amendments] == [
        ("collegium", date(2022, 4, 19), "66"),
        ("collegium", date(2026, 8, 11), "102"),
        ("council", date(2026, 7, 9), "76"),
    ]
    assert result.amendments[0].direct_references[0].url == "https://docs.eaeunion.org/docs/ru-ru/01232481/err_28042022_66"
    assert result.amendments[1].direct_references == ()
    assert result.legal_inventory_complete is result.act_bodies_verified is result.effective_dates_resolved is False
    assert not hasattr(result.amendments[0], "effective_date")


def test_original_current_index_enumerates_all_105_named_acts():
    raw = CURRENT.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == CURRENT_SHA
    result = parse_amendment_inventory(raw)
    assert result.source_sha256 == CURRENT_SHA
    assert result.declaration_sha256 == "005e8d2b7748f06cf5e2dfba9c5b61d4a446854ec634198162d42929a06a8218"
    assert result.named_count == len(result.amendments) == 105
    assert (result.linked_count, result.missing_link_count) == (2, 103)
    assert Counter(r.issuing_body for r in result.amendments) == {"collegium": 61, "council": 44}
    assert len({(r.issuing_body, r.adoption_date, r.number) for r in result.amendments}) == 105
    assert [(r.issuing_body, r.adoption_date, r.number) for r in result.amendments if r.direct_references] == [
        ("collegium", date(2022, 4, 19), "66"), ("council", date(2022, 4, 15), "76"),
    ]
    assert [(r.adoption_date, r.number) for r in result.amendments[-2:]] == [
        (date(2026, 7, 1), "69"), (date(2026, 7, 9), "76"),
    ]
    assert result.legal_inventory_complete is False


@pytest.mark.parametrize("raw", [synthetic_index_html(), CURRENT.read_bytes()])
def test_every_quote_and_inherited_authority_is_bound_to_exact_declaration_characters(raw):
    result = parse_amendment_inventory(raw)
    assert result.source_sha256 == hashlib.sha256(raw).hexdigest()
    assert result.size_bytes == len(raw)
    assert hashlib.sha256(result.declaration_text.encode()).hexdigest() == result.declaration_sha256
    for act in (result.founding_act,) + result.amendments:
        for quote in (act.evidence, act.authority_evidence):
            assert result.declaration_text[quote.start:quote.end] == quote.raw_text
            assert hashlib.sha256(quote.raw_text.encode()).hexdigest() == quote.raw_text_sha256
        expected = "Коллегии" if act.issuing_body == "collegium" else "Совета"
        assert expected in act.authority_evidence.raw_text


def test_immutable_results_cannot_mutate_completeness_or_nested_act_metadata():
    result = parse_amendment_inventory(synthetic_index_html())
    with pytest.raises(FrozenInstanceError):
        result.legal_inventory_complete = True
    with pytest.raises(FrozenInstanceError):
        result.amendments[0].adoption_date = date(2022, 5, 8)
    with pytest.raises(FrozenInstanceError):
        result.amendments[0].evidence.start = 0


@pytest.mark.parametrize("separator", [", ", " ", "\n\t", "&nbsp;"])
def test_explicit_next_act_does_not_require_comma(separator):
    raw = changed("от 11.08.2026 № 102,", f"от 11.08.2026 № 102{separator}от 12.08.2026 № 103,")
    result = parse_amendment_inventory(raw)
    assert result.named_count == 4
    assert result.amendments[2].number == "103"


@pytest.mark.parametrize("old,new", [
    ("11.08.2026", "31.02.2026"), ("11.08.2026", "29.02.2025"),
    ("11.08.2026", "00.08.2026"), ("11.08.2026", "11.13.2026"),
    ("11.08.2026", "11.08.0000"), ("14 сентября 2021", "31 сентября 2021"),
    ("14 сентября 2021", "14 сентября 0000"),
    ("11.08.2026", "11.8.2026"), ("11.08.2026", "１１.０８.２０２６"),
    ("№ 102", "№ 0"), ("№ 102", "№ 0102"), ("№ 102", "№ 102abc"),
    ("№ 102", "№ 1000000"), ("№ 102", "№ 102/1"),
    ("№ 80</p>", "№ 80abc</p>"), ("№ 80</p>", "№ 80/1</p>"),
])
def test_invalid_or_unsupported_dates_and_numbers_are_not_normalized_into_acts(old, new):
    with pytest.raises(ETTAmendmentInventoryError):
        parse_amendment_inventory(changed(old, new))


def test_leap_day_is_valid_adoption_date_but_not_an_effective_date():
    result = parse_amendment_inventory(changed("11.08.2026", "29.02.2024"))
    assert result.amendments[1].adoption_date == date(2024, 2, 29)
    assert result.effective_dates_resolved is False


@pytest.mark.parametrize("old,new", [
    ("от 11.08.2026 № 102,", "от 11.08.2026 № 102, от 11.08.2026 № 102,"),
    ("от 11.08.2026 № 102,", "от 19.04.2022 № 66,"),
    ("от 09.07.2026 № 76", "от 14.09.2021 № 80"),
    ("Решением Совета от 14 сентября 2021 г. № 80", "Решением Совета от 14 сентября 2021 г. № 80 Решением Совета от 14 сентября 2021 г. № 80"),
])
def test_duplicate_amendment_and_founding_act_identity_fails(old, new):
    with pytest.raises(ETTAmendmentInventoryError):
        parse_amendment_inventory(changed(old, new))


@pytest.mark.parametrize("old,new", [
    (COLLEGIUM, COUNCIL), (COUNCIL, COLLEGIUM),
    (COUNCIL, COUNCIL + " " + COLLEGIUM),
    (COUNCIL, "решений Суда Евразийского экономического союза"),
    ("от 11.08.2026 № 102,", "Решением Совета от 11.08.2026 № 102,"),
    ("Решением Совета от 14 сентября 2021 г. № 80", "Решением Коллегии от 14 сентября 2021 г. № 80"),
])
def test_missing_mixed_repeated_or_unknown_authorities_fail_closed(old, new):
    with pytest.raises(ETTAmendmentInventoryError):
        parse_amendment_inventory(changed(old, new))


@pytest.mark.parametrize("old,new", [
    ("от 09.07.2026 № 76", ""),
    ("(в ред.", "(в ред. (в ред."),
    ("№ 76)</p>", "№ 76</p>"),
    ("от 11.08.2026 № 102,", "от 11.08.2026 № 102, и иные акты,"),
    ("от 11.08.2026 № 102,", "не действует от 11.08.2026 № 102,"),
    ("от 09.07.2026 № 76", "от 09.07.2026 № 76 в части"),
    ("(в ред. решений", "(в ред. неизвестных решений"),
    ("№ 76)</p>", "№ 76) от 10.07.2026 № 77</p>"),
    ("от 11.08.2026 № 102,", "от 11.08.2026 № 102от 12.08.2026 № 103,"),
])
def test_unknown_residual_missing_list_and_unscoped_acts_are_not_discarded(old, new):
    with pytest.raises(ETTAmendmentInventoryError):
        parse_amendment_inventory(changed(old, new))


def test_link_date_and_number_shared_by_two_authorities_are_ambiguous():
    with pytest.raises(ETTAmendmentInventoryError, match="link identity"):
        parse_amendment_inventory(changed("от 09.07.2026 № 76", "от 19.04.2022 № 66"))


def test_unlinked_same_date_and_number_in_two_authorities_remain_distinct():
    result = parse_amendment_inventory(changed("от 09.07.2026 № 76", "от 11.08.2026 № 102"))
    assert result.amendments[1].adoption_date == result.amendments[2].adoption_date
    assert result.amendments[1].number == result.amendments[2].number
    assert result.amendments[1].issuing_body != result.amendments[2].issuing_body


def test_observed_link_with_unrecognized_label_does_not_infer_identity_from_filename():
    raw = synthetic_index_html(extra='<a href="https://docs.eaeunion.org/documents/1/2/">Decision</a>')
    with pytest.raises(ETTAmendmentInventoryError, match="observed act label"):
        parse_amendment_inventory(raw)


def test_observed_link_not_named_by_declaration_fails():
    raw = synthetic_index_html(extra='<a href="https://docs.eaeunion.org/documents/1/2/">от 01.01.2026 № 900</a>')
    with pytest.raises(ETTAmendmentInventoryError, match="link identity"):
        parse_amendment_inventory(raw)


def test_one_link_cannot_be_reused_for_two_named_acts():
    url = "https://docs.eaeunion.org/docs/ru-ru/01232481/err_28042022_66"
    raw = changed("от 11.08.2026 № 102,", f'<a href="{url}">от 11.08.2026 № 102</a>,')
    with pytest.raises(ETTAmendmentInventoryError, match="different acts"):
        parse_amendment_inventory(raw)


def test_missing_index_component_prevents_partial_inventory():
    with pytest.raises(ETTAmendmentInventoryError, match="valid retained ETT index"):
        parse_amendment_inventory(synthetic_index_html(omit="97"))


@pytest.mark.parametrize("raw", [b"", b"\xff", "<html></html>"])
def test_bad_input(raw):
    with pytest.raises(ETTAmendmentInventoryError):
        parse_amendment_inventory(raw)


def test_named_act_limit_is_independent_of_html_size(monkeypatch):
    monkeypatch.setattr("app.services.ett_amendment_inventory.MAX_NAMED_AMENDMENTS", 2)
    with pytest.raises(ETTAmendmentInventoryError, match="count"):
        parse_amendment_inventory(synthetic_index_html())
