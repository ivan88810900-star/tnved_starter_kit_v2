"""Synthetic HTML layout tests; these are not a retained official acquisition."""
from dataclasses import FrozenInstanceError
import hashlib

import pytest

from app.services.ett_index import (
    ETTIndexError, INDEX_URL, MAX_INDEX_BYTES, parse_index, validate_source_url,
)
from app.services.ett_manifest import EXPECTED_CHAPTERS
from tests.ett_index_fixtures import synthetic_index_html as index_html


def change(old: str, new: str) -> bytes:
    return index_html().decode().replace(old, new).encode()


def test_complete_topology_and_all_visible_scope_document_references():
    raw = index_html()
    result = parse_index(raw)
    assert result.source_url == INDEX_URL
    assert result.source_sha256 == hashlib.sha256(raw).hexdigest()
    assert result.size_bytes == len(raw)
    assert tuple(r.chapter for r in result.chapters) == EXPECTED_CHAPTERS
    assert len(result.documents) == 100
    assert result.chapters[0].url == INDEX_URL + "ru.2022/published-01-opaque.pdf"
    assert result.chapters[0].text == "Описание 01"
    assert result.chapters[0].locator.startswith("html:a:")
    assert result.chapters[0].href == "ru.2022/published-01-opaque.pdf"
    assert "%20" in result.nomenclature_notes.url
    assert result.tariff_notes.url.endswith("_24.08.2026.pdf")
    assert result.additional_documents[-1].url.endswith("_08.02.2024.pdf")
    assert result.additional_documents[-1].text == ""
    assert len(result.amendment_links) == 1
    assert result.amendment_links[0].role == "amendment_reference"
    assert "11.08.2026 № 102" in result.declaration_text
    assert result.declaration_sha256 == hashlib.sha256(result.declaration_text.encode()).hexdigest()
    assert result.amendment_inventory_complete is False
    assert not hasattr(result, "valid_from")
    assert "Unrelated footer" not in result.declaration_text


def test_discovery_and_nested_references_are_immutable():
    result = parse_index(index_html())
    with pytest.raises(FrozenInstanceError):
        result.amendment_inventory_complete = True
    with pytest.raises(FrozenInstanceError):
        result.chapters[0].url = "https://example.com/"


@pytest.mark.parametrize("chapter", ["01", "76", "78", "97"])
def test_missing_chapter_is_not_padded_or_guessed(chapter):
    with pytest.raises(ETTIndexError, match="exactly chapters"):
        parse_index(index_html(omit=chapter))


@pytest.mark.parametrize("label", ["77", "00", "98", "001", "1", "０１", "01 / 02"])
def test_invalid_reserved_and_ambiguous_chapter_labels(label):
    with pytest.raises(ETTIndexError, match="chapter label"):
        parse_index(change("Группа&nbsp;01", "Группа " + label))


def test_duplicate_chapter_even_identical_is_rejected():
    with pytest.raises(ETTIndexError, match="duplicated"):
        parse_index(index_html(extra='<table><tr><td>Группа 01</td><td><a href="ru.2022/published-01-opaque.pdf">Duplicate</a></td></tr></table>'))


def test_conflicting_and_multiple_chapter_links_fail_closed():
    with pytest.raises(ETTIndexError, match="ambiguous"):
        parse_index(change("Описание 01</a>", 'Описание 01</a><a href="other.pdf">Other</a>'))
    with pytest.raises(ETTIndexError, match="share one"):
        parse_index(change("published-02-opaque.pdf", "published-01-opaque.pdf"))


@pytest.mark.parametrize("change_text", ["nomenclature", "tariff"])
def test_notes_selected_by_unique_visible_label_not_date_or_filename(change_text):
    old = "Примечания к единой Товарной" if change_text == "nomenclature" else "Примечания к Единому таможенному"
    with pytest.raises(ETTIndexError, match="note link"):
        parse_index(change(old, "Missing note label"))
    # Giving the blank older reference the current title must be ambiguous.
    with pytest.raises(ETTIndexError, match="note link"):
        parse_index(change("&#8203;&#8203;</a>", "Примечания к Единому таможенному тарифу Евразийского экономического союза</a>"))


def test_empty_editorial_extra_cells_are_allowed_but_data_cells_are_not():
    assert len(parse_index(change("Описание 01</a></td>", "Описание 01</a></td><td>&#8203;</td>")).chapters) == 96
    with pytest.raises(ETTIndexError, match="ambiguous"):
        parse_index(change("Описание 01</a></td>", "Описание 01</a></td><td>Unexpected data</td>"))


@pytest.mark.parametrize("raw", [b"", b"<html><body>challenge</body></html>", b"\xff", b"x" * (MAX_INDEX_BYTES + 1)])
def test_non_index_non_utf8_and_oversize_body_rejected(raw):
    with pytest.raises(ETTIndexError):
        parse_index(raw)


@pytest.mark.parametrize("old,new", [
    ("</html>", ""), ("</table>", ""), ("</td>", ""),
    ('<meta charset="utf-8">', '<base href="https://example.com/">'),
    ("<!doctype html>", '<!DOCTYPE html [<!ENTITY x SYSTEM "file:///etc/passwd">]>'),
    ("Описание 01", "Описание\x00 01"),
    ('href="ru.2022/published-01-opaque.pdf"', 'href="ru.2022/published-01-opaque.pdf" href="other.pdf"'),
    ("<h1>", '<h1 hidden>'),
    ("<tr><td><p>Группа&nbsp;01", '<tr style="display: none"><td><p>Группа&nbsp;01'),
])
def test_malformed_hidden_or_ambiguous_document_is_rejected(old, new):
    with pytest.raises(ETTIndexError):
        parse_index(change(old, new))


@pytest.mark.parametrize("replacement", ["", "в неизвестной редакции", "в редакции"])
def test_revision_inventory_is_not_fabricated(replacement):
    with pytest.raises(ETTIndexError, match="revision declaration"):
        parse_index(change("в ред.", replacement))


@pytest.mark.parametrize("url", [
    "http://eec.eaeunion.org/upload/files/catr/ett/a.pdf",
    "https://eec.eaeunion.org:443/upload/files/catr/ett/a.pdf",
    "https://user@eec.eaeunion.org/upload/files/catr/ett/a.pdf",
    "https://eec.eaeunion.org.evil.test/upload/files/catr/ett/a.pdf",
    "https://eec.eaeunion.org/upload/files/catr/ett/a.pdf?download=1",
    "https://eec.eaeunion.org/upload/files/catr/ett/a.pdf#x",
    "https://eec.eaeunion.org/upload/files/catr/ett/../a.pdf",
    "https://eec.eaeunion.org/upload/files/catr/ett/%2e%2e/a.pdf",
    "https://eec.eaeunion.org/upload/files/catr/ett/a%2Fb.pdf",
    "https://eec.eaeunion.org/upload/files/catr/ett/a%5Cb.pdf",
    "https://eec.eaeunion.org/upload/files/catr/ett/a%252f.pdf",
    "https://eec.eaeunion.org/upload/files/catr/ett/a%00.pdf",
    "https://eec.eaeunion.org/upload/files/catr/ett/a%0A.pdf",
    "https://eec.eaeunion.org/upload/files/catr/ett/a%3fquery.pdf",
    "https://eec.eaeunion.org/upload/files/catr/ett/a%.pdf",
    "https://eec.eaeunion.org/upload/files/catr/ett/a%ff.pdf",
    "https://eec.eaeunion.org//upload/files/catr/ett/a.pdf",
    "https://eec.eaeunion.org/irrelevant.pdf",
    "https://docs.eaeunion.org/admin/",
    "https://docs.eaeunion.org/",
    "file:///tmp/a.pdf",
])
def test_unsafe_absolute_source_urls(url):
    with pytest.raises(ETTIndexError):
        validate_source_url(url, allow_portal=True)


@pytest.mark.parametrize("href", ["../a.pdf", "https://evil.test/a.pdf", "//evil.test/a.pdf", "a.pdf?x=1", "a.pdf#x", "a\nb.pdf", "a\\b.pdf", "a%2Fb.pdf", "a%252f.pdf", "a.txt"])
def test_unsafe_or_non_pdf_chapter_href(href):
    with pytest.raises(ETTIndexError):
        parse_index(change("ru.2022/published-01-opaque.pdf", href))


def test_allowed_official_document_paths_and_exact_target_identity():
    for url in [INDEX_URL + "ru.2022/chapter.pdf", "https://eec.eaeunion.org/upload/files/catr/ett/chapter.pdf"]:
        assert validate_source_url(url) == url
    for url in ["https://docs.eaeunion.org/docs/ru-ru/01232481/err_28042022_66", "https://docs.eaeunion.org/documents/399/6620/"]:
        assert validate_source_url(url, allow_portal=True) == url
        with pytest.raises(ETTIndexError):
            validate_source_url(url)


def test_all_additional_scope_pdfs_are_retained_without_currentness_claim():
    result = parse_index(index_html(extra='<a href="ru.2022/new-opaque.pdf">Unexpected additional source</a>'))
    assert result.additional_documents[-1].url.endswith("new-opaque.pdf")
    assert result.additional_documents[-1].role == "supplemental_pdf"
    assert result.amendment_inventory_complete is False


def test_nonofficial_extra_pdf_is_not_silently_omitted():
    with pytest.raises(ETTIndexError, match="official HTTPS"):
        parse_index(index_html(extra='<a href="https://example.com/extra.pdf">Unexpected source</a>'))


def test_deep_html_cannot_trigger_unbounded_ancestor_walks():
    with pytest.raises(ETTIndexError, match="nesting"):
        parse_index(index_html(extra="<div>" * 300 + "text" + "</div>" * 300))


def test_balanced_but_incorrect_required_tag_order_is_rejected():
    with pytest.raises(ETTIndexError, match="improperly nested"):
        parse_index(change("Описание 01</a></td>", "Описание 01</td></a>"))
