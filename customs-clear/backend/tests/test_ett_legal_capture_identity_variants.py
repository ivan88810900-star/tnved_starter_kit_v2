"""Observed title variants preserve authority/date/number checks and source text."""
import hashlib
import json
from pathlib import Path

import pytest

from app.services.ett_legal_attachments import ETTLegalAttachmentError, parse_legal_attachments
from app.services.ett_legal_capture import LegalCaptureError, _page_identity
from tests.test_ett_legal_capture import PAGE1, PDF_PATH, portal

FIXTURES = Path(__file__).parent / "fixtures/ett_legal_portal"
CATEGORY = "Акты Евразийской экономической комиссии – Коллегия Евразийской экономической комиссии – Решения – 2022"
EXPECTED = {"issuing_body": "collegium", "adoption_date": "2022-04-19", "number": "66"}


def variant(*, short=False, space="", category=CATEGORY):
    raw = portal().replace("Решения</div>".encode(), (category + "</div>").encode())
    label = "Решение Коллегии " + ("" if short else "ЕЭК ") + "№" + space + "66"
    return raw.replace("Решение Коллегии ЕЭК № 66".encode(), label.encode())


@pytest.mark.parametrize("number,expected_sha", [
    ("132", "bbd7b6ed45ed96aa1f6f97dc6f46bf877cceaa50fc9d712af1b2d9f4c210defe"),
    ("142", "36f22d9ada001d6500147b4e2fba30d0f87ddd054e8d6afbd4e228fe2a9c5392"),
    ("170", "fd23f4f19af3073d20b8dd2567a1bfa9b4630288ccab5d16d375d806cedefee0"),
])
def test_original_metadata_fragments_reproduce_two_actual_grammar_variants(number, expected_sha):
    stem = f"collegium_{number}_metadata_run_34251758308"
    fragment = (FIXTURES / (stem + ".fragment.html")).read_bytes()
    evidence = json.loads((FIXTURES / (stem + ".metadata.json")).read_bytes())
    assert hashlib.sha256(fragment).hexdigest() == expected_sha == evidence["fragment_sha256"]
    assert len(fragment) == evidence["fragment_size_bytes"] == evidence["source_byte_span"][1] - evidence["source_byte_span"][0]
    # Only the unchanged metadata fragment is original. Surrounding test markup
    # and this attachment URL are synthetic, never acquisition evidence.
    wrapper = '<html><head><title>Fixture</title></head><body><div>Правовой портал</div>'
    raw = (wrapper + '<div>Информация о документе</div>').encode() + fragment
    raw += f'<a href="{PDF_PATH}">Synthetic PDF</a></body></html>'.encode()
    result = _page_identity(raw, evidence["expected_identity"])
    assert result["observed_identity"] == evidence["expected_identity"]
    assert result["metadata_matches_discovery_identity"] is True
    assert result["primary_body_identity_verified"] is False
    attachments = parse_legal_attachments(raw, evidence["source_url"])
    assert attachments.document_identity == result["short_title"]
    assert ("ЕЭК" in attachments.document_identity) == (number == "170")
    assert attachments.semantic_verified is False


@pytest.mark.parametrize("space", ["", " ", "\u00a0", "\n"])
@pytest.mark.parametrize("short", [False, True])
def test_literal_spacing_variants_do_not_change_observed_identity(space, short):
    raw = variant(short=short, space=space)
    assert _page_identity(raw, EXPECTED)["observed_identity"] == EXPECTED
    observed = parse_legal_attachments(raw, PAGE1).document_identity
    assert ("ЕЭК" in observed) is (not short)


@pytest.mark.parametrize("category", ["Решения", CATEGORY.replace("Коллегия", "Совет"), CATEGORY.replace("2022", "2021"),
                                     CATEGORY.replace("Решения", "Распоряжения"), CATEGORY.replace("2022", "год неизвестен")])
def test_abbreviated_title_requires_explicit_matching_eec_authority_and_year(category):
    raw = variant(short=True, category=category)
    with pytest.raises(LegalCaptureError):
        _page_identity(raw, EXPECTED)
    with pytest.raises(ETTLegalAttachmentError):
        parse_legal_attachments(raw, PAGE1)


def test_full_title_cannot_override_an_explicit_contradictory_category():
    with pytest.raises(LegalCaptureError):
        _page_identity(variant(category=CATEGORY.replace("Коллегия", "Совет")), EXPECTED)


@pytest.mark.parametrize("old,new", [("№66", "№67"), ("19.04.2022", "20.04.2022"),
                                     ("Решение Коллегии", "Решение Совета"), ("Коллегии", "Коллеги")])
def test_actual_number_date_or_body_contradictions_remain_rejected(old, new):
    raw = variant().replace(old.encode(), new.encode())
    with pytest.raises(LegalCaptureError):
        _page_identity(raw, EXPECTED)


def test_duplicate_category_cannot_corroborate_an_abbreviated_title():
    raw = variant(short=True)
    extra = '<div class="DocDetail_Row"><div class="DocDetail_Col _title">Вид документа</div><div class="DocDetail_Col _value">' + CATEGORY + '</div></div>'
    raw = raw.replace(b'<div class="DocDetail_Info">', b'<div class="DocDetail_Info">' + extra.encode())
    with pytest.raises(LegalCaptureError):
        _page_identity(raw, EXPECTED)
    with pytest.raises(ETTLegalAttachmentError):
        parse_legal_attachments(raw, PAGE1)


def test_original_42_title_typo_is_preserved_despite_independent_metadata_and_pdf_label():
    from app.services.ett_legal_metadata import parse_legal_metadata
    stem = "collegium_42_metadata_run_34255440473"
    fragment = (FIXTURES / (stem + ".fragment.html")).read_bytes()
    evidence = json.loads((FIXTURES / (stem + ".metadata.json")).read_bytes())
    assert hashlib.sha256(fragment).hexdigest() == evidence["fragment_sha256"] == "c91ca208de95d0166e05a78b0356418a12f7189c20d3f5004831bcc14731c980"
    anchor = evidence["descriptive_pdf_anchor"]["raw_html"]
    assert hashlib.sha256(anchor.encode()).hexdigest() == evidence["descriptive_pdf_anchor"]["raw_html_sha256"]
    raw = ('<html><head><title>Fixture</title></head><body><div class="Header_Bottom__Title">Правовой портал</div>'
           '<div class="Box_Title">Информация о документе</div>').encode() + fragment + anchor.encode() + b'</body></html>'
    metadata = parse_legal_metadata(raw, evidence["source_url"])
    assert metadata["fields"]["short_title"]["observed_text"] == "Решение Коллеги ЕЭК №42"
    assert metadata["fields"]["document_number"]["observed_text"] == "42"
    assert metadata["fields"]["adoption_date"]["observed_iso_date"] == "2022-03-15"
    assert "Коллегия Евразийской экономической комиссии" in metadata["fields"]["document_type"]["observed_text"]
    assert "Решение Коллегии №42 от 15 марта 2022 г" in anchor
    with pytest.raises(LegalCaptureError):
        _page_identity(raw, evidence["expected_index_identity"])
    with pytest.raises(ETTLegalAttachmentError):
        parse_legal_attachments(raw, evidence["source_url"])
