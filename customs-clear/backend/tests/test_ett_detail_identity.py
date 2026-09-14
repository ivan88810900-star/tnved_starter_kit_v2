"""Independent proof must survive original source replay and explicit conflicts."""
from dataclasses import asdict
import hashlib
from html import escape
import json
from pathlib import Path

import pytest

from app.services.ett_detail_identity import ETTDetailIdentityError, corroborate_detail_identity
from app.services.ett_legal_search import parse_legal_search
from tests.test_ett_legal_search import CATEGORY, page as search_page, row as search_row

FIXTURES = Path(__file__).parent / "fixtures/ett_legal_portal"
STEM = "collegium_42_metadata_run_34255440473"
DETAIL = "https://docs.eaeunion.org/documents/399/6485/"
SEARCH = "https://docs.eaeunion.org/documents/search/?q=42"
PDF = "/upload/iblock/f50/46fwofvvh6dw34qku7vyou54j81p9zml/err_17032022_42_doc.pdf"
LABEL = "Решение Коллегии №42 от 15 марта 2022 г"
EXPECTED = {"issuing_body": "collegium", "adoption_date": "2022-03-15", "number": "42"}


def anchor(label=LABEL, href=PDF, extra=""):
    return f'<a href="{escape(href)}" {extra}>{escape(label)}</a>'


def detail(*, fragment=None, anchors=None, outside="", primary_extra=""):
    if fragment is None:
        fragment = (FIXTURES / (STEM + ".fragment.html")).read_bytes().decode()
    if anchors is None:
        anchors = anchor("Рус") + anchor() + anchor("Скачать")
    return ('<html><head><title>Fixture</title></head><body><div class="Header_Bottom__Title">Правовой портал</div>'
            '<div class="Box_Title">Информация о документе</div><div class="DocDetail">' + fragment +
            '<div class="DocDetail_Files"><div class="DocDetail_Files_Group"><div class="DocDetail_Files_Title">Документ</div>' +
            anchors + primary_extra + '</div></div></div>' + outside + '</body></html>').encode()


def search(*, label="Решение Коллеги ЕЭК №42", adopted="15.03.2022", category=None, document="6485"):
    rows = search_row(number="42", document=document, label=label, adopted=adopted,
                      category=category or CATEGORY.replace("2026", "2022"))
    rows = rows.replace("/documents/463/", "/documents/399/")
    return search_page(rows, query="42", pagination=False)


def run(raw=None, *, search_raw=None, proof=None, page_url=DETAIL, expected=None):
    raw = detail() if raw is None else raw
    search_raw = search() if search_raw is None else search_raw
    evidence = asdict(parse_legal_search(search_raw, SEARCH).documents[0].evidence) if proof is None else proof
    return corroborate_detail_identity(raw, page_url, EXPECTED if expected is None else expected,
                                       search_raw=search_raw, search_page_url=SEARCH, search_row_evidence=evidence)


def test_original_42_metadata_fragment_and_independent_label_corroborate_without_typo_repair():
    fragment = (FIXTURES / (STEM + ".fragment.html")).read_bytes()
    metadata = json.loads((FIXTURES / (STEM + ".metadata.json")).read_bytes())
    assert hashlib.sha256(fragment).hexdigest() == metadata["fragment_sha256"]
    raw = detail(anchors=metadata["descriptive_pdf_anchor"]["raw_html"])
    result = run(raw)
    assert result["source_sha256"] == hashlib.sha256(raw).hexdigest()
    assert result["corroborated_metadata_identity"] == EXPECTED
    assert result["candidate_pdf_url"] == "https://docs.eaeunion.org" + PDF
    assert result["original_short_title"] == "Решение Коллеги ЕЭК №42"
    assert result["strict_detail_title_status"] == result["strict_search_title_status"] == "unresolved_original_spelling"
    assert result["original_search_identity_status"] == "unresolved_decision_identity"
    assert result["original_short_title_modified"] is result["original_search_classification_modified"] is False
    assert result["primary_pdf_body_identity_verified"] is result["effective_dates_verified"] is result["production_ready"] is False
    assert run(raw) == result


def test_same_pdf_repeated_links_are_retained_and_only_descriptive_anchor_corroborates():
    result = run()
    assert len(result["observed_primary_group_pdf_references"]) == 3
    assert result["qualifying_reference_indices_zero_based"] == [1]
    assert len({a["locator"] for a in result["observed_primary_group_pdf_references"]}) == 3
    assert result["metadata_evidence"]["fields"]["publication_date"]["observed_iso_date"] == "2022-03-17"
    assert result["corroborated_metadata_identity"]["adoption_date"] == "2022-03-15"


@pytest.mark.parametrize("field", ["locator", "text", "text_sha256"])
def test_caller_edited_search_row_evidence_is_rejected(field):
    raw = search()
    proof = asdict(parse_legal_search(raw, SEARCH).documents[0].evidence)
    proof[field] += "modified"
    with pytest.raises(ETTDetailIdentityError, match="does_not_replay"):
        run(search_raw=raw, proof=proof)


def test_valid_search_row_from_another_document_cannot_authorize_detail_page():
    with pytest.raises(ETTDetailIdentityError, match="does_not_replay"):
        run(search_raw=search(document="9999"))


@pytest.mark.parametrize("label", ["Решение Совета ЕЭК №42", "Решение Коллегии ЕЭК №43",
                                    "Решение Совета ЕЭК №42 с уточнением", "Протокол №42", "Распоряжение Коллегии ЕЭК №42"])
def test_search_title_conflict_or_unsupported_document_kind_cannot_be_overridden(label):
    with pytest.raises(ETTDetailIdentityError):
        run(search_raw=search(label=label))


@pytest.mark.parametrize("old,new", [("Решение Коллеги ЕЭК №42", "Решение Совета ЕЭК №42"),
                                      ("Решение Коллеги ЕЭК №42", "Решение Коллегии ЕЭК №43"),
                                      ("Решение Коллеги ЕЭК №42", "Протокол №42"),
                                      ("Решение Коллеги ЕЭК №42", "Решение Коллеги ЕЭК №43"),
                                      ("15.03.2022", "16.03.2022"), ("15.03.2022", "31.02.2022"),
                                      ("Коллегия Евразийской", "Совет Евразийской")])
def test_detail_contradictions_and_invalid_dates_remain_rejected(old, new):
    with pytest.raises(ETTDetailIdentityError):
        run(detail().replace(old.encode(), new.encode()))


@pytest.mark.parametrize("category", [CATEGORY.replace("2026", "2021"), "Международные договоры", CATEGORY.replace("Коллегия", "Совет").replace("2026", "2022")])
def test_search_category_or_year_conflict_is_rejected(category):
    with pytest.raises(ETTDetailIdentityError):
        run(search_raw=search(category=category))


def test_missing_adoption_never_uses_publication_or_pdf_filename():
    with pytest.raises(ETTDetailIdentityError):
        run(detail().replace("Дата принятия документа".encode(), "Дата изменения документа".encode()))


@pytest.mark.parametrize("extra", [anchor(LABEL.replace("Коллегии", "Совета")), anchor(LABEL.replace("№42", "№43")),
                                   anchor(LABEL.replace("15 марта", "16 марта")), anchor("Решение неизвестного органа №42")])
def test_conflicting_or_unresolved_descriptive_pdf_label_is_rejected_even_with_one_match(extra):
    with pytest.raises(ETTDetailIdentityError):
        run(detail(anchors=anchor() + extra))


def test_two_independently_matching_pdf_urls_remain_ambiguous():
    with pytest.raises(ETTDetailIdentityError, match="ambiguous_descriptive_pdf_target"):
        run(detail(anchors=anchor() + anchor(href=PDF.replace("_doc.pdf", "_other.pdf"))))


@pytest.mark.parametrize("anchors", [anchor("Рус") + anchor("Скачать"), anchor("err_17032022_42_doc.pdf"), anchor(extra="hidden")])
def test_generic_filename_or_hidden_anchor_cannot_corroborate(anchors):
    with pytest.raises(ETTDetailIdentityError, match="descriptive_pdf_target"):
        run(detail(anchors=anchors))


@pytest.mark.parametrize("scope", ["footer", "nested_document", "appendix"])
def test_another_document_or_unrelated_attachment_scope_cannot_supply_proof(scope):
    if scope == "footer": raw = detail(anchors=anchor("Рус"), outside="<footer>" + anchor() + "</footer>")
    elif scope == "nested_document": raw = detail(anchors=anchor("Рус"), primary_extra='<div class="DocDetail">' + anchor() + '</div>')
    else: raw = detail().replace('>Документ</div>'.encode(), '>Приложения</div>'.encode())
    with pytest.raises(ETTDetailIdentityError):
        run(raw)


def test_duplicate_metadata_or_primary_group_is_rejected():
    extra = '<div class="DocDetail_Row"><div class="DocDetail_Col _title">Номер документа</div><div class="DocDetail_Col _value">42</div></div>'
    with pytest.raises(ETTDetailIdentityError):
        run(detail().replace(b'<div class="DocDetail_Info">', b'<div class="DocDetail_Info">' + extra.encode()))
    extra = '<div class="DocDetail_Files_Group"><div class="DocDetail_Files_Title">Документ</div>' + anchor() + '</div>'
    with pytest.raises(ETTDetailIdentityError):
        run(detail(primary_extra=extra))


def test_extra_caller_verified_flags_are_not_accepted():
    with pytest.raises(ETTDetailIdentityError):
        run(expected={**EXPECTED, "verified": True})
    proof = asdict(parse_legal_search(search(), SEARCH).documents[0].evidence)
    with pytest.raises(ETTDetailIdentityError):
        run(proof={**proof, "verified": True})


@pytest.mark.parametrize("href", ["https://evil.invalid/act.pdf", PDF + "?from=another", "/upload/iblock/abc/../act.pdf"])
def test_unsafe_or_modified_pdf_url_cannot_become_a_capture_candidate(href):
    with pytest.raises(ETTDetailIdentityError):
        run(detail(anchors=anchor(href=href)))


def test_explicit_regular_title_can_agree_without_erasing_search_typo():
    result = run(detail().replace("Решение Коллеги ЕЭК №42".encode(), "Решение Коллегии ЕЭК №42".encode()))
    assert result["strict_detail_title_status"] == "strict_identity_agrees"
    assert result["strict_search_title_status"] == "unresolved_original_spelling"
    assert result["legal_identity_approval"] is False


@pytest.mark.parametrize("raw", [b"", b"not HTML", b"x" * (4 * 1024 * 1024 + 1)])
def test_unbounded_or_non_document_bytes_cannot_supply_corroboration(raw):
    with pytest.raises(ETTDetailIdentityError):
        run(raw)


def test_duplicate_href_or_class_attributes_cannot_change_evidence_after_parsing():
    raw = detail(anchors=anchor()).replace(b'<a href=', b'<a href="https://evil.invalid/body.pdf" href=', 1)
    with pytest.raises(ETTDetailIdentityError):
        run(raw)
    raw = detail().replace(b'class="DocDetail_Info"', b'class="DocDetail_Info" class="Other"')
    with pytest.raises(ETTDetailIdentityError):
        run(raw)


def test_primary_pdf_reference_bound_is_enforced():
    with pytest.raises(ETTDetailIdentityError, match="pdf_anchor_bound"):
        run(detail(anchors=anchor() * 129))
