"""Independent scope regressions using newly hashed, explicitly mutated HTML.

Only the retained base HTML is an original. Every mutation is a synthetic test
document and the linked PDF is the clearly synthetic body from ``mixed``.
Claims and exact locators are regenerated against each changed HTML document so
source-scope failures cannot be explained by stale offsets or stale digests.
"""
from copy import deepcopy
import json

from bs4 import BeautifulSoup
import pytest

from app.services import ett_metadata_binding as binding
from app.services.ett_manifest import validate_manifest
from tests.test_ett_metadata_binding import (
    make_reference, mixed, references, replace_html, source_fixture,
)


def _primary_group(soup):
    return next(group for group in soup.select(".DocDetail_Files_Group")
                if group.select_one(".DocDetail_Files_Title").get_text(strip=True) == "Документ")


def _descriptive_anchor(group):
    return next(anchor for anchor in group.find_all("a")
                if anchor.get_text(strip=True).startswith("Решение"))


def _publication_row(soup):
    return next(row for row in soup.select(".DocDetail_Info .DocDetail_Row")
                if row.select_one("._title").get_text(strip=True) == "Дата опубликования")


def _rebind(mixed, soup):
    data, store, _ = mixed
    raw = soup.encode(formatter="minimal")
    pdf_sha = references(data)[0]["pdf_binding"]["artifact_sha256"]
    replace_html(data, store, raw)
    for collection in ("codes", "rate_rules"):
        claimed = make_reference(raw)
        claimed["pdf_binding"]["artifact_sha256"] = pdf_sha
        data[collection][0]["effective_evidence"][-1] = claimed
    validate_manifest(data)
    return raw


def _report(mixed):
    data, store, _ = mixed
    return binding.verify_manifest_source_metadata(data, store)


@pytest.mark.parametrize("scope,reason", [
    ("footer", "ambiguous_or_missing_primary_document_group"),
    ("appendix", "ambiguous_or_missing_primary_document_group"),
    ("nested_document", "primary_anchor_identity_mismatch"),
    ("ownerless_metadata", "metadata_has_no_own_document_scope"),
])
def test_attributable_anchor_outside_the_metadata_owners_primary_group_fails(mixed, scope, reason):
    soup = BeautifulSoup(mixed[2], "html.parser")
    group = _primary_group(soup)
    if scope == "footer":
        footer = soup.new_tag("footer")
        footer.append(group.extract())
        soup.body.append(footer)
    elif scope == "appendix":
        group.select_one(".DocDetail_Files_Title").string = "Приложения"
    elif scope == "nested_document":
        nested = soup.new_tag("div", attrs={"class": "DocDetail"})
        group.wrap(nested)
    else:
        soup.body.append(soup.select_one(".DocDetail_Info").extract())
    _rebind(mixed, soup)
    report = _report(mixed)
    assert report["metadata_verified"] is False
    assert report["references_verified"] == 0
    assert report["references_failed"] == 2
    assert {issue["reason"] for issue in report["issues"]} == {reason}


@pytest.mark.parametrize("variation,reason", [
    ("conflicting_identity", "primary_anchor_identity_mismatch"),
    ("second_pdf_url", "ambiguous_primary_pdf_target"),
    ("unsupported_identity", "unsupported_descriptive_primary_anchor"),
])
def test_a_matching_anchor_cannot_hide_another_conflicting_primary_anchor(mixed, variation, reason):
    soup = BeautifulSoup(mixed[2], "html.parser")
    group = _primary_group(soup)
    duplicate = deepcopy(_descriptive_anchor(group))
    if variation == "conflicting_identity":
        duplicate.string = "Решение Коллегии №67 от 19 апреля 2022 г"
    elif variation == "second_pdf_url":
        duplicate["href"] = duplicate["href"].replace("_doc.pdf", "_other_doc.pdf")
    else:
        duplicate.string = "Решение Коллегии без идентифицирующих реквизитов"
    group.append(duplicate)
    _rebind(mixed, soup)
    report = _report(mixed)
    assert report["references_verified"] == 0
    assert report["references_failed"] == 2
    assert {issue["reason"] for issue in report["issues"]} == {reason}


def test_repeated_descriptive_links_to_the_same_primary_pdf_remain_individually_attributable(mixed):
    soup = BeautifulSoup(mixed[2], "html.parser")
    group = _primary_group(soup)
    group.append(deepcopy(_descriptive_anchor(group)))
    _rebind(mixed, soup)
    report = _report(mixed)
    assert report["metadata_verified"] is True
    assert report["references_verified"] == 2
    # Three original PDF links plus the additional descriptive link.
    assert report["parsed_sources"][0]["primary_pdf_anchor_count"] == 4
    assert report["linked_pdf_artifacts_verified"] == 1


@pytest.mark.parametrize("conflicting", [False, True])
def test_duplicate_visible_metadata_rows_are_ambiguous_even_if_the_claim_selects_the_first(mixed, conflicting):
    soup = BeautifulSoup(mixed[2], "html.parser")
    row = _publication_row(soup)
    duplicate = deepcopy(row)
    if conflicting:
        duplicate.select_one("._value").string = "01.01.2000"
    row.parent.append(duplicate)
    _rebind(mixed, soup)
    report = _report(mixed)
    assert report["references_verified"] == 0
    assert report["references_failed"] == 2
    assert {issue["reason"] for issue in report["issues"]} == {"duplicate_metadata_label"}


@pytest.mark.parametrize("hidden", ["hidden_attribute", "aria_hidden", "inline_style"])
def test_hidden_conflicting_metadata_cannot_supply_or_override_visible_values(mixed, hidden):
    soup = BeautifulSoup(mixed[2], "html.parser")
    row = _publication_row(soup)
    duplicate = deepcopy(row)
    duplicate.select_one("._value").string = "01.01.2000"
    if hidden == "hidden_attribute":
        duplicate["hidden"] = ""
    elif hidden == "aria_hidden":
        duplicate["aria-hidden"] = "true"
    else:
        duplicate["style"] = "display: none"
    row.parent.append(duplicate)
    _rebind(mixed, soup)
    report = _report(mixed)
    assert report["metadata_verified"] is True
    assert report["references_verified"] == 2
    assert "01.01.2000" not in json.dumps(report)


def test_hidden_only_publication_row_cannot_be_used_as_visible_metadata(mixed):
    # Prepare claims against a source with stable serialized positions, then add
    # an attribute only to that row's opening tag. Its line/column and every
    # descendant's line/column remain unchanged in this multiline fixture.
    soup = BeautifulSoup(mixed[2], "html.parser")
    raw = _rebind(mixed, soup)
    reparsed = BeautifulSoup(raw, "html.parser")
    row = _publication_row(reparsed)
    line = raw.decode().splitlines(keepends=True)[row.sourceline - 1]
    offset = sum(len(value) for value in raw.decode().splitlines(keepends=True)[:row.sourceline - 1]) + row.sourcepos
    source = raw.decode()
    opening_end = source.index(">", offset)
    assert "DocDetail_Row" in line
    changed = (source[:opening_end] + " hidden" + source[opening_end:]).encode()
    replace_html(mixed[0], mixed[1], changed)
    validate_manifest(mixed[0])
    report = _report(mixed)
    assert report["references_verified"] == 0
    assert {issue["reason"] for issue in report["issues"]} == {"metadata_field_missing_or_ambiguous"}


@pytest.mark.parametrize("exception", [ValueError, TypeError, KeyError, IndexError, AttributeError, RecursionError])
def test_unexpected_occurrence_parse_failure_is_sanitized_and_counted(mixed, monkeypatch, exception):
    def fail(*_args, **_kwargs):
        raise exception("PRIVATE_SOURCE_TEXT_OR_PATH")
    monkeypatch.setattr(binding, "_verify_occurrence", fail)
    report = _report(mixed)
    assert report["metadata_verified"] is False
    assert report["references_verified"] == 0
    assert report["references_failed"] == 2
    assert {issue["reason"] for issue in report["issues"]} == {"metadata_occurrence_replay_failed"}
    assert "PRIVATE" not in json.dumps(report)
